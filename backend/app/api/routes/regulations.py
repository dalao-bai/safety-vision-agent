"""规范库管理路由 (v0.2)。

提供规范文件的列表、上传、删除。上传时校验大小与扩展名，存盘后解析、切分、
写入向量库，并把元数据落 SQLite。删除走软删除 + 向量库清理。

所有端点需登录（Depends(get_current_user)）。RegulationStore 的获取做成
get_regulation_store() 依赖函数，测试可通过 dependency_overrides 注入 fake。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.auth_deps import CurrentUser, get_current_user
from app.api.dependencies import get_app_settings, get_db, get_vlm_client
from app.core.config import Settings
from app.db import repositories as repo
from app.services.regulation_store import RegulationStore
from app.services.responses_client import ResponsesClient

router = APIRouter(prefix="/api/regulations", tags=["regulations"])

# 允许的扩展名 -> 规范化 file_type。
_ALLOWED_EXTENSIONS = {".pdf": "pdf", ".docx": "docx"}


def get_regulation_store(
    settings: Settings = Depends(get_app_settings),
    vlm_client: ResponsesClient = Depends(get_vlm_client),
) -> RegulationStore:
    """构造生产用 RegulationStore：向量计算复用模型端点的 embed。"""
    return RegulationStore(
        chroma_dir=settings.chroma_dir,
        embed_fn=lambda texts: vlm_client.embed(settings.embedding_model, texts),
    )


@router.get("")
def list_regulations(
    conn: sqlite3.Connection = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    """返回未软删除的规范文件元数据列表。"""
    return [dict(row) for row in repo.list_regulation_files(conn)]


@router.post("/upload")
async def upload_regulation(
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    store: RegulationStore = Depends(get_regulation_store),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    """上传一份规范：校验 -> 存盘 -> 解析切分 -> 写向量库 -> 落元数据。"""
    original_name = file.filename or ""
    ext = Path(original_name).suffix.lower()
    file_type = _ALLOWED_EXTENSIONS.get(ext)
    if file_type is None:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported file type: {ext or '(none)'}; allowed: pdf, docx",
        )

    data = await file.read()
    if len(data) > settings.max_regulation_bytes:
        raise HTTPException(
            status_code=422,
            detail=f"file exceeds max size {settings.max_regulation_bytes} bytes",
        )
    if not data:
        raise HTTPException(status_code=422, detail="empty file")

    # 存到 regulation_dir 下的 uuid 文件名，保留原扩展名。
    reg_dir = Path(settings.regulation_dir)
    reg_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{uuid.uuid4()}{ext}"
    stored_path = reg_dir / stored_filename
    stored_path.write_bytes(data)

    # 解析 + 切分 + 写向量库。先生成元数据 id 作为向量库分组键。
    file_id = repo.create_regulation_file(
        conn,
        filename=stored_filename,
        original_name=original_name,
        file_path=str(stored_path),
        file_type=file_type,
        chunk_count=0,
    )
    try:
        text = store.parse_file(str(stored_path), file_type)
        chunks = store.chunk_text(text)
        chunk_count = store.add_regulation(file_id, original_name, chunks)
    except Exception as exc:  # noqa: BLE001 - 解析/嵌入失败回滚已落记录与文件
        repo.soft_delete_regulation_file(conn, file_id)
        stored_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422, detail=f"failed to process regulation file: {exc}"
        ) from exc

    # 回填真实 chunk 数。
    conn.execute(
        "UPDATE regulation_files SET chunk_count = ? WHERE id = ?",
        (chunk_count, file_id),
    )
    conn.commit()

    row = conn.execute(
        "SELECT * FROM regulation_files WHERE id = ?", (file_id,)
    ).fetchone()
    return dict(row)


@router.delete("/{file_id}")
def delete_regulation(
    file_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    store: RegulationStore = Depends(get_regulation_store),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    """软删除元数据并清理向量库中该文件的全部 chunk。"""
    found = repo.soft_delete_regulation_file(conn, file_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"unknown file_id: {file_id}")
    store.delete_regulation(file_id)
    return {"deleted": file_id}
