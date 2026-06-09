"""合规报告生成服务（任务 C）。

跨对话汇总某用户在指定时间区间内的隐患，生成一份 .docx 合规报告：
标题页 + 隐患统计表 + 逐条隐患明细（含嵌入图片，可选规范原文引用）。

报告生成是同步的 CPU/IO 任务，由路由层用 BackgroundTasks 在后台线程调用。
本模块另提供一个进程内任务注册表，用于查询后台任务的状态与下载地址。
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Callable

from docx import Document
from docx.shared import Inches

from app.db import repositories as repo

# search_fn: 给定隐患名称，返回若干条规范片段（dict 列表）。形如
# [{"text": "...", "source": "..."}]，键名按实现可能不同，下面取文本时做容错。
SearchFn = Callable[[str], list[dict]]

# 风险等级英文枚举值 → 中文展示，未知值原样显示。
_RISK_LABELS = {
    "low": "低",
    "medium": "中",
    "high": "高",
    "critical": "严重",
}

# 嵌入图片的显示宽度（英寸）。
_IMAGE_WIDTH = Inches(3.5)


def _risk_label(value: str) -> str:
    return _RISK_LABELS.get(value, value or "未知")


def _ref_text(item: Any) -> str:
    """从一条规范检索结果里提取可读原文，兼容不同实现的键名。"""
    if isinstance(item, dict):
        for key in ("text", "content", "chunk", "原文", "excerpt"):
            if item.get(key):
                return str(item[key])
        return json.dumps(item, ensure_ascii=False)
    return str(item)


def _ref_source(item: Any) -> str | None:
    """提取规范来源名（文件名/规范编号），无则 None。"""
    if isinstance(item, dict):
        for key in ("source", "filename", "original_name", "来源"):
            if item.get(key):
                return str(item[key])
    return None


def generate_report_docx(
    conn,
    user_id: str,
    username: str,
    start: str | None,
    end: str | None,
    output_dir: str,
    search_fn: SearchFn | None = None,
) -> str:
    """生成合规报告 .docx，返回文件绝对路径。

    汇总 ``user_id`` 在 ``[start, end]`` 内全部对话的隐患。所有查询均带
    user_id 过滤（list_conversations_by_user），不会读到他人数据。
    文件名为 ``uuid4().hex + ".docx"``，落在 ``output_dir`` 下。
    """
    os.makedirs(output_dir, exist_ok=True)

    conversations = repo.list_conversations_by_user(conn, user_id, start=start, end=end)

    document = Document()

    # --- 标题页 ---
    document.add_heading("工地安全隐患合规报告", level=0)
    document.add_paragraph(f"用户：{username}")
    document.add_paragraph(f"统计区间：{start or '不限'} ~ {end or '不限'}")
    document.add_paragraph(f"涉及对话数：{len(conversations)}")
    document.add_page_break()

    # 逐对话遍历，边收集统计边渲染明细。stat_counter 聚合 (名称, 等级) → 次数。
    stat_counter: dict[tuple[str, str], int] = {}
    detail_blocks: list[dict[str, Any]] = []

    for conv in conversations:
        cid = conv["id"]
        # 该对话的图片：先一次性取出建索引，按 image_id 命中，未命中再单查兜底。
        images = {row["id"]: row for row in repo.list_images(conn, cid)}
        for entry in repo.list_analysis_results(conn, cid):
            result = entry.get("result") or {}
            hazards = result.get("hazards") or []
            if not hazards:
                continue
            image_id = entry.get("image_id")
            image_row = None
            if image_id is not None:
                image_row = images.get(image_id) or repo.get_image_by_id(conn, image_id)
            detail_blocks.append(
                {
                    "summary": result.get("summary") or "",
                    "hazards": hazards,
                    "image_row": image_row,
                }
            )
            for hazard in hazards:
                key = (hazard.get("name") or "未命名隐患", hazard.get("risk_level") or "")
                stat_counter[key] = stat_counter.get(key, 0) + 1

    # --- 统计表 ---
    document.add_heading("隐患统计", level=1)
    if stat_counter:
        table = document.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        header = table.rows[0].cells
        header[0].text = "隐患名称"
        header[1].text = "风险等级"
        header[2].text = "出现次数"
        for (name, risk), count in sorted(
            stat_counter.items(), key=lambda kv: kv[1], reverse=True
        ):
            cells = table.add_row().cells
            cells[0].text = name
            cells[1].text = _risk_label(risk)
            cells[2].text = str(count)
    else:
        document.add_paragraph("该区间内暂无隐患记录。")

    # --- 逐条隐患明细 ---
    document.add_heading("隐患明细", level=1)
    if not detail_blocks:
        document.add_paragraph("该区间内暂无隐患明细。")

    for idx, block in enumerate(detail_blocks, start=1):
        document.add_heading(f"分析 {idx}", level=2)
        if block["summary"]:
            document.add_paragraph(f"概述：{block['summary']}")

        # 嵌入图片：文件存在才插入，否则标注缺失，绝不让缺图中断整篇报告。
        image_row = block["image_row"]
        if image_row is not None:
            stored_path = image_row["stored_path"]
            if stored_path and os.path.exists(stored_path):
                try:
                    document.add_picture(stored_path, width=_IMAGE_WIDTH)
                except Exception as exc:  # noqa: BLE001 - 图片损坏/格式不支持，跳过即可
                    document.add_paragraph(f"（图片无法嵌入：{image_row['stored_filename']}，{exc}）")
            else:
                document.add_paragraph(f"（图片缺失：{image_row['stored_filename']}）")

        for hazard in block["hazards"]:
            name = hazard.get("name") or "未命名隐患"
            document.add_heading(name, level=3)
            document.add_paragraph(f"位置：{hazard.get('location') or '未指明'}")
            document.add_paragraph(f"风险等级：{_risk_label(hazard.get('risk_level') or '')}")
            document.add_paragraph(f"判定依据：{hazard.get('basis') or ''}")
            document.add_paragraph(f"整改建议：{hazard.get('remediation') or ''}")
            confidence = hazard.get("confidence")
            if confidence is not None:
                document.add_paragraph(f"置信度：{confidence}")

            # 可选：检索规范库，附原文引用。
            if search_fn is not None:
                try:
                    refs = search_fn(name) or []
                except Exception as exc:  # noqa: BLE001 - 检索失败不应中断报告
                    refs = []
                    document.add_paragraph(f"（规范检索失败：{exc}）")
                for ref in refs:
                    para = document.add_paragraph()
                    para.add_run("参见规范：").bold = True
                    source = _ref_source(ref)
                    prefix = f"[{source}] " if source else ""
                    para.add_run(prefix + _ref_text(ref))

    filename = uuid.uuid4().hex + ".docx"
    out_path = os.path.abspath(os.path.join(output_dir, filename))
    document.save(out_path)
    return out_path


# ============================================================
# 进程内后台任务注册表
# ============================================================
# 报告生成放在后台执行，前端轮询状态后再下载。注册表存活于单进程内存中
# （v0.2 单实例部署足够），重启即清空。

_TASKS: dict[str, dict[str, Any]] = {}


def create_task(user_id: str) -> str:
    """登记一个待执行的报告任务，返回 task_id。"""
    task_id = uuid.uuid4().hex
    _TASKS[task_id] = {
        "status": "pending",
        "user_id": user_id,
        "path": None,
        "error": None,
    }
    return task_id


def set_task_done(task_id: str, path: str) -> None:
    task = _TASKS.get(task_id)
    if task is not None:
        task["status"] = "done"
        task["path"] = path


def set_task_error(task_id: str, msg: str) -> None:
    task = _TASKS.get(task_id)
    if task is not None:
        task["status"] = "error"
        task["error"] = msg


def get_task(task_id: str) -> dict[str, Any] | None:
    """返回任务状态视图，未知 task_id 返回 None。

    始终携带 user_id 供路由层做越权校验；done 时附 download_url 与本地 path，
    error 时附 error 文本。
    """
    task = _TASKS.get(task_id)
    if task is None:
        return None
    view: dict[str, Any] = {"status": task["status"], "user_id": task["user_id"]}
    if task["status"] == "done":
        view["download_url"] = f"/api/report/download/{task_id}"
        view["path"] = task["path"]
    elif task["status"] == "error":
        view["error"] = task["error"]
    return view
