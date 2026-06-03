from __future__ import annotations

import argparse
import json
import mimetypes
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .io_utils import load_json, write_json
from .review_records import convert_reviews_to_records


class ReviewServer:
    def __init__(self, args: argparse.Namespace) -> None:
        self.output_dir = Path(args.output_dir)
        self.db_records_dir = Path(args.db_records_dir)
        self.source_type = args.source_type
        self.cwd = Path.cwd().resolve()
        self.draft_dir = self.output_dir / "draft_json"
        self.review_dir = self.output_dir / "review_decisions"
        self.boxed_dir = self.output_dir / "boxed_review"

    def list_samples(self) -> list[dict[str, Any]]:
        samples = []
        for review_path in sorted(self.review_dir.glob("*.review.json")):
            try:
                review = load_json(review_path)
            except Exception as exc:
                samples.append({"sample_id": review_path.stem.replace(".review", ""), "error": str(exc)})
                continue
            sample_id = review.get("sample_id") or review_path.stem.replace(".review", "")
            draft_path = self.draft_dir / f"{sample_id}.json"
            draft = load_json(draft_path) if draft_path.exists() else {}
            decisions = {"pending": 0, "accept": 0, "reject": 0, "revise": 0, "other": 0}
            for obj in review.get("objects", []):
                decision = obj.get("decision")
                decisions[decision if decision in decisions else "other"] += 1
            samples.append(
                {
                    "sample_id": sample_id,
                    "image_path": review.get("image_path") or draft.get("image_path", ""),
                    "review_status": review.get("review_status", ""),
                    "image_decision": review.get("image_decision", ""),
                    "decisions": decisions,
                    "object_count": len(review.get("objects", [])),
                }
            )
        return samples

    def get_sample(self, sample_id: str) -> dict[str, Any]:
        review_path = self.review_dir / f"{sample_id}.review.json"
        draft_path = self.draft_dir / f"{sample_id}.json"
        if not review_path.exists():
            raise FileNotFoundError(f"review json not found: {sample_id}")
        review = load_json(review_path)
        draft = load_json(draft_path) if draft_path.exists() else {}
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
        return {"ok": True, "review_path": review_path.as_posix()}

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
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.exists() and self.is_allowed_path(resolved):
                return resolved
        raise FileNotFoundError(raw_path)

    def is_allowed_path(self, path: Path) -> bool:
        allowed_roots = [self.cwd, self.output_dir.resolve()]
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
                self.send_json({"samples": app.list_samples()})
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
button,select,textarea{font:inherit}
button{border:1px solid var(--line);background:#fff;color:var(--text);height:34px;padding:0 12px;border-radius:6px;cursor:pointer}
button:hover{border-color:#9fb0a3;background:#f8faf7}
button:focus,textarea:focus{outline:2px solid rgba(30,125,91,.25);outline-offset:2px}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.danger{background:var(--danger);border-color:var(--danger);color:#fff}
header{height:54px;display:flex;align-items:center;gap:12px;padding:0 16px;background:#fff;border-bottom:1px solid var(--line)}
header h1{font-size:17px;margin:0;font-weight:700}
header .status{margin-left:auto;color:var(--muted)}
.layout{display:grid;grid-template-columns:280px minmax(420px,1fr) minmax(420px,560px);height:calc(100vh - 54px);min-height:640px}
aside{border-right:1px solid var(--line);background:#fbfcfa;overflow:auto}
.tools{display:flex;gap:8px;align-items:center;padding:12px;border-bottom:1px solid var(--line);position:sticky;top:0;background:#fbfcfa;z-index:1}
.samples{padding:8px}
.sample{width:100%;height:auto;text-align:left;display:block;padding:10px;border-radius:6px;margin-bottom:6px;background:#fff}
.sample.active{border-color:var(--accent);box-shadow:inset 3px 0 0 var(--accent)}
.sample strong{display:block;font-size:13px;line-height:1.25;word-break:break-all}
.sample span{display:block;color:var(--muted);font-size:12px;margin-top:5px}
main{display:grid;grid-template-rows:auto 1fr;border-right:1px solid var(--line);min-width:0}
.meta{display:flex;gap:10px;align-items:center;padding:12px 14px;border-bottom:1px solid var(--line);background:#fff;min-width:0}
.meta code{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted)}
.viewer{overflow:auto;padding:14px;display:grid;gap:14px;align-content:start}
.image-block h2{font-size:13px;margin:0 0 8px;color:var(--muted);font-weight:700}
.image-block img{display:block;width:100%;height:auto;background:#e8ece5;border:1px solid var(--line);border-radius:6px}
.editor{display:grid;grid-template-rows:auto 1fr auto;background:#fff;min-width:0}
.editor-bar{display:flex;gap:8px;align-items:center;padding:12px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.editor textarea{width:100%;height:100%;resize:none;border:0;padding:14px;font-family:Consolas,"Courier New",monospace;font-size:13px;line-height:1.5;color:var(--ink);background:#fff}
.summary{border-top:1px solid var(--line);padding:10px 12px;color:var(--muted);min-height:44px;white-space:pre-wrap}
.badge{display:inline-flex;align-items:center;height:22px;padding:0 7px;border-radius:999px;background:#eef3ee;color:#325241;font-size:12px}
.badge.warn{background:#fff4d7;color:var(--warn)}
.badge.danger{background:#fde8e8;color:var(--danger)}
@media(max-width:1100px){.layout{grid-template-columns:240px 1fr;grid-template-rows:52% 48%;height:auto}.editor{grid-column:1 / -1;min-height:520px}main{border-right:0}}
</style>
</head>
<body>
<header>
  <h1>四口五临边审核台</h1>
  <button id="refresh">刷新</button>
  <button id="commit">生成 accepted_records</button>
  <button id="append" class="danger">导入母数据库</button>
  <span id="topStatus" class="status"></span>
</header>
<div class="layout">
  <aside>
    <div class="tools">
      <span class="badge" id="countBadge">0 条</span>
      <select id="filter">
        <option value="all">全部</option>
        <option value="pending">待审核</option>
        <option value="changed">已处理</option>
      </select>
    </div>
    <div id="samples" class="samples"></div>
  </aside>
  <main>
    <div class="meta">
      <span class="badge" id="decisionBadge">未选择</span>
      <code id="pathText"></code>
    </div>
    <div class="viewer">
      <section class="image-block">
        <h2>原图</h2>
        <img id="rawImage" alt="">
      </section>
      <section class="image-block">
        <h2>草标框</h2>
        <img id="boxedImage" alt="">
      </section>
    </div>
  </main>
  <section class="editor">
    <div class="editor-bar">
      <button id="acceptPending">待定改通过</button>
      <button id="save" class="primary">保存 JSON</button>
      <span class="badge warn" id="dirtyBadge" hidden>未保存</span>
    </div>
    <textarea id="jsonEditor" spellcheck="false"></textarea>
    <div id="summary" class="summary"></div>
  </section>
</div>
<script>
let samples = [];
let activeId = "";
let dirty = false;

const $ = (id) => document.getElementById(id);

function setStatus(text) {
  $("topStatus").textContent = text || "";
}

function setDirty(value) {
  dirty = value;
  $("dirtyBadge").hidden = !value;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

async function loadList() {
  const data = await api("/api/list");
  samples = data.samples || [];
  renderSamples();
  if (!activeId && samples.length) await loadSample(samples[0].sample_id);
}

function renderSamples() {
  const filter = $("filter").value;
  const list = $("samples");
  list.innerHTML = "";
  let visible = samples;
  if (filter === "pending") visible = samples.filter((s) => (s.decisions || {}).pending > 0);
  if (filter === "changed") visible = samples.filter((s) => ((s.decisions || {}).accept + (s.decisions || {}).reject + (s.decisions || {}).revise) > 0);
  $("countBadge").textContent = `${visible.length} 条`;
  for (const item of visible) {
    const button = document.createElement("button");
    button.className = "sample" + (item.sample_id === activeId ? " active" : "");
    const d = item.decisions || {};
    button.innerHTML = `<strong>${item.sample_id}</strong><span>pending ${d.pending || 0} · accept ${d.accept || 0} · reject ${d.reject || 0} · revise ${d.revise || 0}</span>`;
    button.onclick = async () => {
      if (dirty && !confirm("当前 JSON 未保存，继续切换？")) return;
      await loadSample(item.sample_id);
    };
    list.appendChild(button);
  }
}

async function loadSample(sampleId) {
  const data = await api(`/api/review?sample_id=${encodeURIComponent(sampleId)}`);
  activeId = sampleId;
  $("jsonEditor").value = JSON.stringify(data.review, null, 2);
  $("rawImage").src = data.image_url || "";
  $("boxedImage").src = data.overlay_url || "";
  $("pathText").textContent = data.review_path || "";
  $("decisionBadge").textContent = data.review.image_decision || "pending";
  $("summary").textContent = "";
  setDirty(false);
  renderSamples();
}

function editorJson() {
  return JSON.parse($("jsonEditor").value);
}

async function saveReview() {
  const data = editorJson();
  await api(`/api/review?sample_id=${encodeURIComponent(activeId)}`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(data)
  });
  setDirty(false);
  setStatus("已保存");
  await loadList();
}

function acceptPending() {
  const data = editorJson();
  data.review_status = "reviewed";
  if (data.image_decision === "pending") data.image_decision = "accept";
  for (const obj of data.objects || []) {
    if (obj.decision === "pending") obj.decision = "accept";
  }
  $("jsonEditor").value = JSON.stringify(data, null, 2);
  setDirty(true);
}

async function commit(appendToDb) {
  if (dirty) await saveReview();
  const result = await api("/api/commit", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({append_to_db: appendToDb})
  });
  $("summary").textContent = JSON.stringify(result, null, 2);
  setStatus(appendToDb ? "已导入母数据库" : "已生成 accepted_records");
  await loadList();
}

$("refresh").onclick = loadList;
$("filter").onchange = renderSamples;
$("jsonEditor").addEventListener("input", () => setDirty(true));
$("save").onclick = () => saveReview().catch((err) => alert(err.message));
$("acceptPending").onclick = () => { try { acceptPending(); } catch (err) { alert(err.message); } };
$("commit").onclick = () => commit(false).catch((err) => alert(err.message));
$("append").onclick = () => {
  if (confirm("确认追加到 annotation_db/records？")) commit(true).catch((err) => alert(err.message));
};

loadList().catch((err) => {
  setStatus(err.message);
});
</script>
</body>
</html>
"""
