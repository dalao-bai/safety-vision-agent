from __future__ import annotations

import argparse
import json
import mimetypes
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .io_utils import load_json, write_json
from .constants import HAZARD_TYPES, OBJECT_TYPES, UNCERTAINTY_REASONS
from .review_records import convert_reviews_to_records
from .review_index import upgrade_review_with_draft


class ReviewServer:
    def __init__(self, args: argparse.Namespace) -> None:
        self.output_dir = Path(args.output_dir)
        self.db_records_dir = Path(args.db_records_dir)
        self.source_type = args.source_type
        self.cwd = Path.cwd().resolve()
        self.draft_dir = self.output_dir / "draft_json"
        self.review_dir = self.output_dir / "review_decisions"
        self.boxed_dir = self.output_dir / "boxed_review"
        # per-file mtime cache: sample_id -> (review_mtime, draft_mtime, entry_dict)
        self._sample_cache: dict[str, tuple[float, float, dict]] = {}
        # directory-level list cache: avoids per-file stat on every /api/list call
        self._list_cache: list[dict[str, Any]] | None = None
        self._list_dir_mtime: float = -1.0
        # rule blocks for the rule selector UI
        _rule_blocks_path = Path(__file__).parent.parent / "知识图谱主文件" / "four_openings_edges_rule_blocks.json"
        self.rules: list = load_json(_rule_blocks_path) if _rule_blocks_path.exists() else []

    def list_samples(self, force_rescan: bool = False) -> list[dict[str, Any]]:
        try:
            dir_mtime = self.review_dir.stat().st_mtime
        except OSError:
            dir_mtime = -1.0

        if not force_rescan and self._list_cache is not None and dir_mtime == self._list_dir_mtime:
            return self._list_cache

        samples = []
        for review_path in sorted(self.review_dir.glob("*.review.json")):
            raw_id = review_path.stem.replace(".review", "")
            draft_path = self.draft_dir / f"{raw_id}.json"
            try:
                review_mtime = review_path.stat().st_mtime
                draft_mtime = draft_path.stat().st_mtime if draft_path.exists() else 0.0
            except OSError:
                review_mtime = draft_mtime = 0.0

            cached = self._sample_cache.get(raw_id)
            if cached and cached[0] == review_mtime and cached[1] == draft_mtime:
                samples.append(cached[2])
                continue

            try:
                review = load_json(review_path)
            except Exception as exc:
                entry: dict[str, Any] = {"sample_id": raw_id, "error": str(exc)}
                self._sample_cache[raw_id] = (review_mtime, draft_mtime, entry)
                samples.append(entry)
                continue
            sample_id = review.get("sample_id") or raw_id
            draft = load_json(draft_path) if draft_path.exists() else {}
            review = upgrade_review_with_draft(review, draft) if draft else review
            entry = self._build_list_entry(sample_id, review, draft)
            self._sample_cache[raw_id] = (review_mtime, draft_mtime, entry)
            samples.append(entry)

        self._list_cache = samples
        self._list_dir_mtime = dir_mtime
        return samples

    def _build_list_entry(self, sample_id: str, review: dict, draft: dict) -> dict[str, Any]:
        decisions: dict[str, int] = {"pending": 0, "accept": 0, "reject": 0, "revise": 0, "other": 0}
        for obj in review.get("objects", []):
            decision = obj.get("decision")
            decisions[decision if decision in decisions else "other"] += 1
        return {
            "sample_id": sample_id,
            "image_path": review.get("image_path") or draft.get("image_path", ""),
            "review_status": review.get("review_status", ""),
            "image_decision": review.get("image_decision", ""),
            "needs_rerun": review.get("needs_rerun") is True,
            "rerun_status": review.get("rerun_status", ""),
            "last_rerun_at": review.get("last_rerun_at", ""),
            "rerun_count": review.get("rerun_count", 0),
            "decisions": decisions,
            "object_count": len(review.get("objects", [])),
        }

    def _patch_list_cache(self, sample_id: str, review: dict) -> None:
        if self._list_cache is None:
            return
        new_entry = self._build_list_entry(sample_id, review, {})
        for i, item in enumerate(self._list_cache):
            if item.get("sample_id") == sample_id:
                self._list_cache[i] = new_entry
                return
        self._list_cache.append(new_entry)

    def get_sample(self, sample_id: str) -> dict[str, Any]:
        review_path = self.review_dir / f"{sample_id}.review.json"
        draft_path = self.draft_dir / f"{sample_id}.json"
        if not review_path.exists():
            raise FileNotFoundError(f"review json not found: {sample_id}")
        review = load_json(review_path)
        draft = load_json(draft_path) if draft_path.exists() else {}
        if draft:
            review = upgrade_review_with_draft(review, draft)
        image_path = Path(review.get("image_path") or draft.get("image_path", ""))
        overlay_path = self.find_overlay(sample_id)
        return {
            "sample_id": sample_id,
            "review": review,
            "draft": draft,
            "image_url": self.file_url(image_path) if image_path else "",
            "overlay_url": self.file_url(overlay_path) if overlay_path else "",
            "review_path": review_path.as_posix(),
            "draft_path": draft_path.as_posix(),
        }

    def save_review(self, sample_id: str, data: dict[str, Any]) -> dict[str, Any]:
        review_path = self.review_dir / f"{sample_id}.review.json"
        if not review_path.exists():
            raise FileNotFoundError(f"review json not found: {sample_id}")
        if data.get("sample_id") != sample_id:
            raise ValueError("review sample_id must match selected sample")
        write_json(review_path, data)
        self._patch_list_cache(sample_id, data)
        # invalidate per-file mtime cache so next full rescan re-reads this file
        self._sample_cache.pop(sample_id, None)
        return {"ok": True, "review_path": review_path.as_posix()}

    def mark_rerun(self, sample_id: str, needs_rerun: bool) -> dict[str, Any]:
        review_path = self.review_dir / f"{sample_id}.review.json"
        draft_path = self.draft_dir / f"{sample_id}.json"
        if not review_path.exists():
            raise FileNotFoundError(f"review json not found: {sample_id}")
        review = load_json(review_path)
        draft = load_json(draft_path) if draft_path.exists() else {}
        if draft:
            review = upgrade_review_with_draft(review, draft)
        review["needs_rerun"] = needs_rerun
        if needs_rerun and not review.get("rerun_note"):
            review["rerun_note"] = ""
        write_json(review_path, review)
        self._patch_list_cache(sample_id, review)
        self._sample_cache.pop(sample_id, None)
        return {"ok": True, "sample_id": sample_id, "needs_rerun": needs_rerun}

    def commit(self, append_to_db: bool) -> dict[str, Any]:
        return convert_reviews_to_records(self.output_dir, append_to_db, self.db_records_dir, self.source_type)

    def find_overlay(self, sample_id: str) -> Path | None:
        for suffix in (".png", ".svg"):
            candidate = self.boxed_dir / f"{sample_id}_review{suffix}"
            if candidate.exists():
                return candidate
        return None

    def file_url(self, path: Path) -> str:
        return "/file?path=" + urllib.parse.quote(path.as_posix())

    def resolve_file_path(self, raw_path: str) -> Path:
        path = Path(urllib.parse.unquote(raw_path))
        candidates = []
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.append(self.cwd / path)
            if path.parts and path.parts[0] == self.cwd.name:
                candidates.append(self.cwd / Path(*path.parts[1:]))
            candidates.append(self.output_dir / path)
            candidates.append(self.output_dir.parent / path)
            candidates.append(self.output_dir.resolve().parent.parent / path)
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.exists() and self.is_allowed_path(resolved):
                return resolved
        raise FileNotFoundError(raw_path)

    def is_allowed_path(self, path: Path) -> bool:
        allowed_roots = [self.cwd, self.output_dir.resolve(), self.output_dir.resolve().parent, self.output_dir.resolve().parent.parent]
        for root in allowed_roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False


def create_handler(app: ReviewServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "AnnotationReviewServer/1.0"

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                self.send_html(REVIEW_HTML)
                return
            if parsed.path == "/api/list":
                force = self.query(parsed).get("force", [""])[0] == "1"
                self.send_json({"samples": app.list_samples(force_rescan=force)})
                return
            if parsed.path == "/api/options":
                self.send_json(
                    {
                        "objects": [{"id": item[0], "name": item[1]} for item in OBJECT_TYPES],
                        "hazards": [{"id": item[0], "name": item[1]} for item in HAZARD_TYPES],
                        "uncertainty_reasons": UNCERTAINTY_REASONS,
                    }
                )
                return
            if parsed.path == "/api/rules":
                by_object: dict = {}
                for r in app.rules:
                    oid = r.get("object_id")
                    if oid:
                        by_object.setdefault(oid, []).append(r)
                self.send_json({"rules_by_object": by_object})
                return
            if parsed.path == "/api/review":
                sample_id = self.query(parsed).get("sample_id", [""])[0]
                try:
                    self.send_json(app.get_sample(sample_id))
                except Exception as exc:
                    self.send_error_json(404, str(exc))
                return
            if parsed.path == "/file":
                raw_path = self.query(parsed).get("path", [""])[0]
                try:
                    self.send_file(app.resolve_file_path(raw_path))
                except Exception as exc:
                    self.send_error_json(404, str(exc))
                return
            self.send_error_json(404, "not found")

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/review":
                sample_id = self.query(parsed).get("sample_id", [""])[0]
                try:
                    self.send_json(app.save_review(sample_id, self.read_json_body()))
                except Exception as exc:
                    self.send_error_json(400, str(exc))
                return
            if parsed.path == "/api/rerun":
                sample_id = self.query(parsed).get("sample_id", [""])[0]
                try:
                    body = self.read_json_body()
                    self.send_json(app.mark_rerun(sample_id, bool(body.get("needs_rerun"))))
                except Exception as exc:
                    self.send_error_json(400, str(exc))
                return
            if parsed.path == "/api/commit":
                try:
                    body = self.read_json_body()
                    self.send_json(app.commit(bool(body.get("append_to_db"))))
                except Exception as exc:
                    self.send_error_json(400, str(exc))
                return
            self.send_error_json(404, "not found")

        def query(self, parsed: urllib.parse.ParseResult) -> dict[str, list[str]]:
            return urllib.parse.parse_qs(parsed.query)

        def read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

        def send_html(self, html_text: str) -> None:
            data = html_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_file(self, path: Path) -> None:
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_error_json(self, status: int, message: str) -> None:
            self.send_json({"error": message}, status=status)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def run_review_server(args: argparse.Namespace) -> int:
    app = ReviewServer(args)
    handler = create_handler(app)
    server = ThreadingHTTPServer((args.review_host, args.review_port), handler)
    host, port = server.server_address
    print(f"review server: http://{host}:{port}", flush=True)
    print(f"output_dir={app.output_dir}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


REVIEW_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>四口五临边审核台</title>
<style>
:root{--bg:#f4f5f2;--panel:#ffffff;--line:#d8ddd2;--text:#17201a;--muted:#687265;--accent:#1e7d5b;--danger:#b43f3f;--warn:#9a6a13;--ink:#111611;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei",Arial,sans-serif;font-size:14px}
button,select,textarea,input{font:inherit}
button{border:1px solid var(--line);background:#fff;color:var(--text);height:34px;padding:0 12px;border-radius:6px;cursor:pointer}
button:hover{border-color:#9fb0a3;background:#f8faf7}
button:focus,select:focus,textarea:focus,input:focus{outline:2px solid rgba(30,125,91,.25);outline-offset:2px}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.danger{background:var(--danger);border-color:var(--danger);color:#fff}
button.active-accept{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:700}
button.active-reject{background:var(--danger);border-color:var(--danger);color:#fff;font-weight:700}
button.active-pending{background:var(--warn);border-color:var(--warn);color:#fff;font-weight:700}
header{height:54px;display:flex;align-items:center;gap:12px;padding:0 16px;background:#fff;border-bottom:1px solid var(--line)}
header h1{font-size:17px;margin:0;font-weight:700}
header .status{margin-left:auto;color:var(--muted)}
.layout{display:grid;grid-template-columns:280px 1fr 320px;height:calc(100vh - 54px);min-height:640px}
aside{border-right:1px solid var(--line);background:#fbfcfa;overflow:auto}
.tools{display:flex;gap:8px;align-items:center;padding:12px;border-bottom:1px solid var(--line);position:sticky;top:0;background:#fbfcfa;z-index:1}
.samples{padding:8px}
.sample{width:100%;height:auto;text-align:left;display:block;padding:10px;border-radius:6px;margin-bottom:6px;background:#fff}
.sample.active{border-color:var(--accent);box-shadow:inset 3px 0 0 var(--accent)}
.sample.s-accept{border-left:3px solid var(--accent)}
.sample.s-reject{border-left:3px solid var(--danger)}
.sample.s-pending{border-left:3px solid var(--warn)}
.sample strong{display:block;font-size:13px;line-height:1.25;word-break:break-all}
.sample span{display:block;color:var(--muted);font-size:12px;margin-top:5px}
main{display:grid;grid-template-rows:auto 1fr;border-right:1px solid var(--line);min-width:0}
.meta{display:flex;gap:10px;align-items:center;padding:10px 14px;border-bottom:1px solid var(--line);background:#fff;min-width:0}
.meta code{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font-size:12px}
.viewer{overflow:auto;padding:14px;display:grid;gap:14px;align-content:start}
.image-wrap{position:relative;width:100%;background:#e8ece5;border:1px solid var(--line);border-radius:6px;overflow:hidden}
.image-wrap img{display:block;width:100%;height:auto;background:#e8ece5}
.box-overlay{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;user-select:none}
.box-overlay rect.box{fill:rgba(30,125,91,.12);stroke:#18a36f;stroke-width:4;vector-effect:non-scaling-stroke}
.box-overlay rect.edit-box{fill:rgba(30,125,91,.06);stroke-dasharray:6 3}
.box-overlay text{font-family:"Microsoft YaHei",Arial,sans-serif;font-size:18px;font-weight:700;paint-order:stroke;stroke:#fff;stroke-width:5;stroke-linejoin:round;fill:#0d6849}
.box-overlay .hazard rect.box{fill:rgba(180,63,63,.14);stroke:#d83d3d}
.box-overlay .hazard text{fill:#b21f1f}
.box-overlay .uncertain rect.box{fill:rgba(154,106,19,.16);stroke:#c98613}
.box-overlay .uncertain text{fill:#8a5a0c}
.info-panel{overflow:auto;background:#fff;display:grid;grid-template-rows:auto 1fr auto;min-width:0}
.info-header{padding:12px 14px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:8px}
.info-header h2{font-size:14px;margin:0;font-weight:700;flex:1}
.objects-section{padding:12px 14px;overflow:auto}
.objects-section h3{font-size:12px;color:var(--muted);margin:0 0 8px;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.obj-card{border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin-bottom:8px;background:#fbfcfa}
.obj-card strong{display:block;font-size:13px;margin-bottom:5px}
.obj-card.hazard{border-left:3px solid var(--danger)}
.obj-card.safe{border-left:3px solid var(--accent)}
.obj-card.uncertain{border-left:3px solid var(--warn)}
.obj-row{display:grid;grid-template-columns:72px 1fr;gap:4px;font-size:12px;margin-top:3px;align-items:start}
.obj-label{color:var(--muted);font-weight:600;white-space:nowrap}
.obj-rule{grid-column:1/-1;color:var(--text);font-size:12px;line-height:1.5;background:#f4f5f2;border-radius:4px;padding:4px 6px;margin-top:4px}
.obj-missing{color:var(--warn)}
.verdict-panel{border-top:1px solid var(--line);padding:16px 14px;display:grid;gap:12px}
.verdict-panel h3{font-size:12px;color:var(--muted);margin:0;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.verdict-btns{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.verdict-btns button{height:42px;font-size:14px;font-weight:600}
.note-field{display:grid;gap:5px}
.note-field label{font-size:12px;color:var(--muted)}
.note-field textarea{width:100%;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--text);padding:7px;min-height:60px;resize:vertical}
.save-row{display:flex;gap:8px;align-items:center}
.save-row button{flex:1;height:38px}
.badge{display:inline-flex;align-items:center;height:22px;padding:0 7px;border-radius:999px;background:#eef3ee;color:#325241;font-size:12px}
.badge.accept{background:#eef3ee;color:var(--accent)}
.badge.reject{background:#fde8e8;color:var(--danger)}
.badge.pending-b{background:#fff4d7;color:var(--warn)}
.badge.warn{background:#fff4d7;color:var(--warn)}
.progress-bar{height:4px;background:var(--line);border-radius:2px;overflow:hidden;margin:0 14px 0}
.progress-fill{height:100%;background:var(--accent);transition:width .3s}
@media(max-width:1100px){.layout{grid-template-columns:240px 1fr;grid-template-rows:55% 45%;height:auto}.info-panel{grid-column:1 / -1;min-height:420px}main{border-right:0}}
</style>
</head>
<body>
<header>
  <h1>四口五临边 · 数据可用性审核</h1>
  <button id="refresh">刷新列表</button>
  <button id="commit">导出可用数据</button>
  <span id="topStatus" class="status"></span>
</header>
<div class="layout">
  <aside>
    <div class="tools">
      <span class="badge" id="countBadge">0 条</span>
      <select id="filter">
        <option value="all">全部</option>
        <option value="pending">待审核</option>
        <option value="accept">可用</option>
        <option value="reject">不可用</option>
      </select>
    </div>
    <div style="padding:8px 12px;border-bottom:1px solid var(--line);position:sticky;top:56px;background:#fbfcfa;z-index:1">
      <input id="searchBox" type="text" placeholder="搜索图片名称…" style="width:100%;border:1px solid var(--line);border-radius:6px;padding:5px 9px;font-size:13px;background:#fff;color:var(--text)">
    </div>
    <div id="progressWrap" style="padding:0 0 8px">
      <div class="progress-bar"><div class="progress-fill" id="progressFill" style="width:0%"></div></div>
      <div style="padding:4px 14px;font-size:12px;color:var(--muted)" id="progressText"></div>
    </div>
    <div id="samples" class="samples"></div>
  </aside>
  <main>
    <div class="meta">
      <span class="badge" id="decisionBadge">未选择</span>
      <code id="pathText"></code>
    </div>
    <div class="viewer">
      <div class="image-wrap">
        <img id="rawImage" alt="">
        <svg id="boxOverlay" class="box-overlay"></svg>
      </div>
    </div>
  </main>
  <section class="info-panel">
    <div class="info-header">
      <h2 id="sampleTitle">—</h2>
    </div>
    <div class="objects-section">
      <h3>AI 标注对象</h3>
      <div id="objectList"></div>
    </div>
    <div class="verdict-panel">
      <h3>整图可用性判断</h3>
      <div class="verdict-btns">
        <button id="btnAccept">可用</button>
        <button id="btnReject">不可用</button>
        <button id="btnPending">待定</button>
      </div>
      <div class="note-field">
        <label>备注（选填）</label>
        <textarea id="reviewNote" placeholder="说明原因，如：标注框偏移、图片模糊、场景不符…"></textarea>
      </div>
      <div class="save-row">
        <button id="btnSave" class="primary">保存并下一张</button>
        <button id="btnSaveOnly">仅保存</button>
      </div>
    </div>
  </section>
</div>
<script>
let samples = [];
let activeId = "";
let currentReview = null;
let currentDecision = "pending";
let rulesByObject = {};
let editingObjects = new Set();
// bbox drag state
let dragState = null; // {objIdx, mode, startSvgX, startSvgY, origBbox, handleIdx?}

const STATUS_OPTIONS = [
  {id: "confirmed_hazard", name: "有隐患"},
  {id: "safe", name: "无隐患"},
  {id: "uncertain", name: "不确定"},
];
const HAZARD_OPTIONS = [
  {id: "missing_protection", name: "防护缺失"},
  {id: "discontinuous_protection", name: "防护不连续/不严密"},
  {id: "temporary_substitute", name: "临时替代防护"},
  {id: "unfixed_or_weak_protection", name: "固定不牢/强度不足"},
  {id: "door_open_or_missing", name: "防护门缺失/未关闭"},
  {id: "access_or_obstruction_issue", name: "通行/障碍异常"},
];

const $ = (id) => document.getElementById(id);

function setStatus(text) { $("topStatus").textContent = text || ""; }

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || r.statusText);
  return d;
}

async function loadList(force = false) {
  const data = await api(force ? "/api/list?force=1" : "/api/list");
  samples = data.samples || [];
  renderSamples();
  updateProgress();
  if (!activeId && samples.length) await loadSample(samples[0].sample_id);
}

function sampleDecision(item) {
  return item.image_decision || "pending";
}

function renderSamples() {
  const filter = $("filter").value;
  const query = ($("searchBox").value || "").trim().toLowerCase();
  const list = $("samples");
  list.innerHTML = "";
  let visible = samples;
  if (filter === "pending") visible = samples.filter((s) => !s.image_decision || s.image_decision === "pending");
  if (filter === "accept") visible = samples.filter((s) => s.image_decision === "accept");
  if (filter === "reject") visible = samples.filter((s) => s.image_decision === "reject");
  if (query) visible = visible.filter((s) => s.sample_id.toLowerCase().includes(query) || (s.image_path || "").toLowerCase().includes(query));
  $("countBadge").textContent = `${visible.length} 条`;
  for (const item of visible) {
    const dec = sampleDecision(item);
    const btn = document.createElement("button");
    btn.className = "sample" + (item.sample_id === activeId ? " active" : "") + ` s-${dec}`;
    const decLabel = dec === "accept" ? "✓ 可用" : dec === "reject" ? "✗ 不可用" : "· 待定";
    btn.innerHTML = `<strong>${escapeText(item.sample_id)}</strong><span>${decLabel} · ${item.object_count || 0} 个对象</span>`;
    btn.onclick = async () => { await loadSample(item.sample_id); };
    list.appendChild(btn);
  }
}

function updateProgress() {
  const total = samples.length;
  const done = samples.filter((s) => s.image_decision && s.image_decision !== "pending").length;
  const accept = samples.filter((s) => s.image_decision === "accept").length;
  const reject = samples.filter((s) => s.image_decision === "reject").length;
  const pct = total ? Math.round(done / total * 100) : 0;
  $("progressFill").style.width = pct + "%";
  $("progressText").textContent = `已审 ${done}/${total} (${pct}%) · 可用 ${accept} · 不可用 ${reject}`;
}

async function loadSample(sampleId) {
  const data = await api(`/api/review?sample_id=${encodeURIComponent(sampleId)}`);
  activeId = sampleId;
  currentReview = data.review || {};
  if (!Array.isArray(currentReview.objects)) currentReview.objects = [];
  currentDecision = currentReview.image_decision || "pending";
  editingObjects.clear();
  dragState = null;
  $("rawImage").src = data.image_url || "";
  $("pathText").textContent = data.review_path || "";
  $("sampleTitle").textContent = sampleId;
  $("reviewNote").value = currentReview.review_note || "";
  renderDecisionButtons();
  renderObjectList();
  renderOverlay();
  renderSamples();
}

function renderDecisionButtons() {
  $("btnAccept").className = currentDecision === "accept" ? "active-accept" : "";
  $("btnReject").className = currentDecision === "reject" ? "active-reject" : "";
  $("btnPending").className = currentDecision === "pending" ? "active-pending" : "";
  const badge = $("decisionBadge");
  badge.className = "badge" + (currentDecision === "accept" ? " accept" : currentDecision === "reject" ? " reject" : " pending-b");
  badge.textContent = currentDecision === "accept" ? "可用" : currentDecision === "reject" ? "不可用" : "待定";
}

function escapeText(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}

function escapeAttr(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}

function toggleEditObject(i) {
  if (editingObjects.has(i)) { editingObjects.delete(i); } else { editingObjects.add(i); }
  renderObjectList();
  renderOverlay();
}

function deleteObject(i) {
  if (!currentReview || !Array.isArray(currentReview.objects)) return;
  const obj = currentReview.objects[i];
  if (!obj) return;
  const name = obj.object_name || obj.object_id || "该对象";
  if (!confirm(`确定删除「${name}」这个标注对象吗？此操作在保存后生效。`)) return;
  currentReview.objects.splice(i, 1);
  // re-index editing set: drop deleted, shift higher indices down by 1
  const next = new Set();
  editingObjects.forEach(idx => {
    if (idx < i) next.add(idx);
    else if (idx > i) next.add(idx - 1);
  });
  editingObjects = next;
  renderObjectList();
  renderOverlay();
}

function applyStatusChange(idx, newStatus) {
  if (!currentReview || !Array.isArray(currentReview.objects)) return;
  const obj = currentReview.objects[idx];
  if (!obj) return;
  obj.status = newStatus;
  if (newStatus === "safe") {
    obj.hazard_type_id = null;
    obj.hazard_type = null;
    obj.rule_id = null;
    obj.rule = "";
  } else if (newStatus === "uncertain") {
    obj.hazard_type_id = null;
    obj.hazard_type = null;
    obj.rule_id = null;
    obj.rule = "";
  }
  renderObjectList();
}

function applyHazardChange(idx, newHazardId) {
  if (!currentReview || !Array.isArray(currentReview.objects)) return;
  const obj = currentReview.objects[idx];
  if (!obj) return;
  const found = HAZARD_OPTIONS.find(h => h.id === newHazardId);
  obj.hazard_type_id = newHazardId || null;
  obj.hazard_type = found ? found.name : null;
  obj.rule_id = null;
  obj.rule = "";
  renderObjectList();
}

function applyEvidenceChange(idx, value) {
  if (!currentReview || !Array.isArray(currentReview.objects)) return;
  const obj = currentReview.objects[idx];
  if (!obj) return;
  obj.visual_evidence = value;
}

function buildRuleSelector(obj, i) {
  if (obj.status === "safe") return "";
  const oid = obj.object_id;
  const rules = (rulesByObject[oid] || []).filter(r => r.hazard_type_id);
  if (!rules.length) return "";
  const cur = obj.rule_id || "";
  const noRule = !cur;
  const opts = rules.map(r => {
    const sel = r.rule_id === cur ? " selected" : "";
    const snippet = (r.rule_text || "").slice(0, 36);
    const label = `[${r.rule_id}] ${r.hazard_type || ""} — ${snippet}${r.rule_text && r.rule_text.length > 36 ? "…" : ""}`;
    return `<option value="${escapeAttr(r.rule_id)}"${sel}>${escapeText(label)}</option>`;
  }).join("");
  const labelColor = noRule ? "var(--warn)" : "var(--muted)";
  const borderColor = noRule ? "var(--warn)" : "var(--line)";
  return `<div class="obj-row" style="margin-top:6px;align-items:start">
    <span class="obj-label" style="color:${labelColor};padding-top:4px">${noRule ? "⚠ 规则" : "规则"}</span>
    <select class="rule-select" data-obj-index="${i}" style="width:100%;border:1px solid ${borderColor};border-radius:4px;padding:3px 5px;font-size:12px;background:#fff;color:var(--text)">
      <option value="">— 选择规则 —</option>
      ${opts}
    </select>
  </div>`;
}

function applyRuleToObject(idx, ruleId) {
  if (!currentReview || !Array.isArray(currentReview.objects)) return;
  const obj = currentReview.objects[idx];
  if (!obj) return;
  if (!ruleId) {
    obj.rule_id = null;
    obj.rule = "";
  } else {
    const rules = rulesByObject[obj.object_id] || [];
    const rule = rules.find(r => r.rule_id === ruleId);
    if (rule) { obj.rule_id = rule.rule_id; obj.rule = rule.rule_text || ""; }
  }
  renderObjectList();
}

function renderObjectList() {
  const list = $("objectList");
  const objects = currentReview ? currentReview.objects || [] : [];
  if (!objects.length) {
    list.innerHTML = `<p style="color:var(--muted);font-size:12px;margin:0">无标注对象</p>`;
    return;
  }
  list.innerHTML = objects.map((obj, i) => {
    const editing = editingObjects.has(i);
    const cls = obj.status === "confirmed_hazard" ? "hazard" : obj.status === "uncertain" ? "uncertain" : "safe";
    const statusLabel = obj.status === "confirmed_hazard" ? "有隐患" : obj.status === "uncertain" ? "不确定" : "无隐患";

    const statusField = editing
      ? `<div class="obj-row"><span class="obj-label">状态</span>
          <select class="edit-status" data-obj-index="${i}" style="border:1px solid var(--line);border-radius:4px;padding:2px 5px;font-size:12px;background:#fff;color:var(--text)">
            ${STATUS_OPTIONS.map(s => `<option value="${escapeAttr(s.id)}"${s.id === obj.status ? " selected" : ""}>${escapeText(s.name)}</option>`).join("")}
          </select></div>`
      : `<div class="obj-row"><span class="obj-label">状态</span><span>${escapeText(statusLabel)}</span></div>`;

    const showHazard = obj.status === "confirmed_hazard";
    const hazardField = showHazard
      ? (editing
          ? `<div class="obj-row"><span class="obj-label">隐患类型</span>
              <select class="edit-hazard" data-obj-index="${i}" style="border:1px solid var(--line);border-radius:4px;padding:2px 5px;font-size:12px;background:#fff;color:var(--text)">
                <option value="">— 选择 —</option>
                ${HAZARD_OPTIONS.map(h => `<option value="${escapeAttr(h.id)}"${h.id === obj.hazard_type_id ? " selected" : ""}>${escapeText(h.name)}</option>`).join("")}
              </select></div>`
          : (obj.hazard_type ? `<div class="obj-row"><span class="obj-label">隐患类型</span><span>${escapeText(obj.hazard_type)}</span></div>` : ""))
      : "";

    const ruleRow = obj.rule_id ? `<div class="obj-row"><span class="obj-label">规则 ID</span><span>${escapeText(obj.rule_id)}</span></div>` : "";
    const ruleText = obj.rule ? `<div class="obj-rule">${escapeText(obj.rule)}</div>` : "";
    const bboxRow = obj.bbox ? `<div class="obj-row"><span class="obj-label">坐标</span><span class="bbox-display" style="font-family:monospace;font-size:11px">${obj.bbox.join(", ")}</span></div>` : "";
    const ruleSelector = buildRuleSelector(obj, i);
    const evidence = editing
      ? `<div class="obj-row" style="align-items:start"><span class="obj-label" style="padding-top:4px">可见证据</span>
          <textarea class="edit-evidence" data-obj-index="${i}" style="width:100%;border:1px solid var(--line);border-radius:4px;padding:4px 6px;font-size:12px;line-height:1.5;background:#fff;color:var(--text);min-height:60px;resize:vertical">${escapeText(obj.visual_evidence || "")}</textarea></div>`
      : (obj.visual_evidence ? `<div class="obj-row"><span class="obj-label">可见证据</span><span>${escapeText(obj.visual_evidence)}</span></div>` : "");
    const missing = obj.missing_evidence ? `<div class="obj-row obj-missing"><span class="obj-label">缺失证据</span><span>${escapeText(obj.missing_evidence)}</span></div>` : "";
    const uncertain = obj.uncertainty_reason ? `<div class="obj-row"><span class="obj-label">不确定原因</span><span>${escapeText(obj.uncertainty_reason)}</span></div>` : "";
    const editBtn = `<button onclick="toggleEditObject(${i})" style="float:right;height:22px;padding:0 8px;font-size:11px;margin-left:6px;border-radius:4px">${editing ? "收起" : "修改"}</button>`;
    const delBtn = editing ? `<button onclick="deleteObject(${i})" style="float:right;height:22px;padding:0 8px;font-size:11px;margin-left:6px;border-radius:4px;background:var(--danger);border-color:var(--danger);color:#fff">删除</button>` : "";

    return `<div class="obj-card ${cls}" data-obj-index="${i}">
      <strong>${editBtn}${delBtn}${i + 1}. ${escapeText(obj.object_name || obj.object_id || "未命名")}</strong>
      ${statusField}${hazardField}${ruleRow}${ruleText}${ruleSelector}${bboxRow}${evidence}${missing}${uncertain}
    </div>`;
  }).join("");

  list.querySelectorAll("select.rule-select").forEach(sel => {
    sel.addEventListener("change", () => applyRuleToObject(parseInt(sel.dataset.objIndex), sel.value));
  });
  list.querySelectorAll("select.edit-status").forEach(sel => {
    sel.addEventListener("change", () => applyStatusChange(parseInt(sel.dataset.objIndex), sel.value));
  });
  list.querySelectorAll("select.edit-hazard").forEach(sel => {
    sel.addEventListener("change", () => applyHazardChange(parseInt(sel.dataset.objIndex), sel.value));
  });
  list.querySelectorAll("textarea.edit-evidence").forEach(ta => {
    ta.addEventListener("input", () => applyEvidenceChange(parseInt(ta.dataset.objIndex), ta.value));
  });
}

function svgPt(svg, clientX, clientY) {
  const pt = svg.createSVGPoint();
  pt.x = clientX; pt.y = clientY;
  return pt.matrixTransform(svg.getScreenCTM().inverse());
}

function renderOverlay() {
  const svg = $("boxOverlay");
  const image = $("rawImage");
  svg.innerHTML = "";
  if (!currentReview || !image.naturalWidth || !image.naturalHeight) return;
  const W = image.naturalWidth, H = image.naturalHeight;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const hasEditing = editingObjects.size > 0;
  svg.style.pointerEvents = hasEditing ? "all" : "none";
  const HANDLE_R = Math.max(10, Math.min(24, W / 50));

  (currentReview.objects || []).forEach((obj, index) => {
    const bbox = obj.bbox;
    if (!Array.isArray(bbox) || bbox.length !== 4) return;
    const [x1, y1, x2, y2] = bbox.map(Number);
    if (![x1, y1, x2, y2].every(Number.isFinite) || x2 <= x1 || y2 <= y1) return;
    const editing = editingObjects.has(index);
    const cls = obj.status === "confirmed_hazard" ? "hazard" : obj.status === "uncertain" ? "uncertain" : "safe";
    const label = `${index + 1}. ${obj.object_name || obj.object_id || ""}`.trim();
    const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;

    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("class", cls);
    g.setAttribute("data-obj-index", String(index));

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("class", editing ? "box edit-box" : "box");
    rect.setAttribute("x", x1); rect.setAttribute("y", y1);
    rect.setAttribute("width", x2 - x1); rect.setAttribute("height", y2 - y1);
    if (editing) { rect.style.pointerEvents = "all"; rect.style.cursor = "move"; rect.setAttribute("data-handle", "move"); }
    g.appendChild(rect);

    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", Math.max(4, x1 + 6)); text.setAttribute("y", Math.max(22, y1 - 8));
    text.textContent = label;
    g.appendChild(text);

    if (editing) {
      [
        [x1, y1, "nw-resize", "nw"], [cx, y1, "n-resize", "n"], [x2, y1, "ne-resize", "ne"],
        [x2, cy, "e-resize",  "e"],  [x2, y2, "se-resize", "se"], [cx, y2, "s-resize", "s"],
        [x1, y2, "sw-resize", "sw"], [x1, cy, "w-resize",  "w"],
      ].forEach(([hx, hy, cur, hid]) => {
        const h = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        h.setAttribute("x", hx - HANDLE_R / 2); h.setAttribute("y", hy - HANDLE_R / 2);
        h.setAttribute("width", HANDLE_R); h.setAttribute("height", HANDLE_R);
        h.setAttribute("fill", "#fff"); h.setAttribute("stroke", "#18a36f");
        h.setAttribute("stroke-width", "2"); h.setAttribute("rx", "2");
        h.style.pointerEvents = "all"; h.style.cursor = cur;
        h.setAttribute("data-handle", hid); h.setAttribute("data-obj-index", String(index));
        g.appendChild(h);
      });
    }
    svg.appendChild(g);
  });

  svg.onmousedown = (e) => {
    const handle = e.target.getAttribute("data-handle");
    if (!handle) return;
    const rawIdx = e.target.getAttribute("data-obj-index") ?? e.target.closest("g")?.getAttribute("data-obj-index");
    const objIdx = parseInt(rawIdx ?? "-1");
    if (objIdx < 0 || !currentReview) return;
    const obj = currentReview.objects[objIdx];
    if (!obj || !Array.isArray(obj.bbox)) return;
    const pt = svgPt(svg, e.clientX, e.clientY);
    dragState = {objIdx, mode: handle, startX: pt.x, startY: pt.y, origBbox: [...obj.bbox]};
    e.preventDefault();
  };
}

function setDecision(value) {
  currentDecision = value;
  renderDecisionButtons();
}

function nextSample() {
  const currentIndex = samples.findIndex((s) => s.sample_id === activeId);
  // search forward from current position first
  for (let i = currentIndex + 1; i < samples.length; i++) {
    if (!samples[i].image_decision || samples[i].image_decision === "pending") return samples[i].sample_id;
  }
  // wrap around to beginning
  for (let i = 0; i < currentIndex; i++) {
    if (!samples[i].image_decision || samples[i].image_decision === "pending") return samples[i].sample_id;
  }
  // no pending left, just go to the next one
  const next = samples[currentIndex + 1] || samples[0];
  return next ? next.sample_id : null;
}

function patchLocalSample(sampleId, decision, note) {
  const s = samples.find((item) => item.sample_id === sampleId);
  if (s) { s.image_decision = decision; s.review_note = note; }
}

async function saveVerdict(andNext) {
  if (!activeId || !currentReview) return;
  currentReview.image_decision = currentDecision;
  currentReview.review_note = $("reviewNote").value || "";
  currentReview.review_status = "reviewed";
  await api(`/api/review?sample_id=${encodeURIComponent(activeId)}`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(currentReview)
  });
  patchLocalSample(activeId, currentDecision, currentReview.review_note);
  setStatus("已保存");
  updateProgress();
  renderSamples();
  if (andNext) {
    const next = nextSample();
    if (next) await loadSample(next);
  }
}

async function commit() {
  const result = await api("/api/commit", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({append_to_db: false})
  });
  setStatus(`导出完成 · 可用 ${result.accepted || 0} 条`);
}

$("refresh").onclick = () => loadList(true).catch((e) => setStatus(e.message));
$("filter").onchange = renderSamples;
$("searchBox").addEventListener("input", renderSamples);
$("btnAccept").onclick = () => setDecision("accept");
$("btnReject").onclick = () => setDecision("reject");
$("btnPending").onclick = () => setDecision("pending");
$("btnSave").onclick = () => saveVerdict(true).catch((e) => alert(e.message));
$("btnSaveOnly").onclick = () => saveVerdict(false).catch((e) => alert(e.message));
$("commit").onclick = () => commit().catch((e) => alert(e.message));
$("rawImage").addEventListener("load", renderOverlay);
window.addEventListener("resize", renderOverlay);

document.addEventListener("mousemove", (e) => {
  if (!dragState || !currentReview) return;
  const svg = $("boxOverlay");
  const pt = svgPt(svg, e.clientX, e.clientY);
  const dx = pt.x - dragState.startX;
  const dy = pt.y - dragState.startY;
  const [ox1, oy1, ox2, oy2] = dragState.origBbox;
  const obj = currentReview.objects[dragState.objIdx];
  if (!obj) return;
  const W = $("rawImage").naturalWidth, H = $("rawImage").naturalHeight;
  const clamp = (v, lo, hi) => Math.round(Math.max(lo, Math.min(hi, v)));
  const MIN = 10;
  let x1 = ox1, y1 = oy1, x2 = ox2, y2 = oy2;
  const m = dragState.mode;
  if (m === "move") {
    const w = ox2 - ox1, h = oy2 - oy1;
    x1 = clamp(ox1 + dx, 0, W - w); y1 = clamp(oy1 + dy, 0, H - h);
    x2 = x1 + w; y2 = y1 + h;
  } else {
    if (m.includes("w")) x1 = clamp(ox1 + dx, 0, ox2 - MIN);
    if (m.includes("e")) x2 = clamp(ox2 + dx, ox1 + MIN, W);
    if (m.includes("n")) y1 = clamp(oy1 + dy, 0, oy2 - MIN);
    if (m.includes("s")) y2 = clamp(oy2 + dy, oy1 + MIN, H);
  }
  obj.bbox = [x1, y1, x2, y2];
  renderOverlay();
  // update coord display in card without full re-render
  const card = document.querySelector(`.obj-card[data-obj-index="${dragState.objIdx}"]`);
  if (card) {
    const span = card.querySelector(".bbox-display");
    if (span) span.textContent = `${x1}, ${y1}, ${x2}, ${y2}`;
  }
});

document.addEventListener("mouseup", () => { dragState = null; });

async function loadRules() {
  try {
    const data = await api("/api/rules");
    rulesByObject = data.rules_by_object || {};
  } catch (e) {
    // rules unavailable — selector won't appear
  }
}

loadRules().catch(() => {});
loadList().catch((e) => setStatus(e.message));
</script>
</body>
</html>
"""
