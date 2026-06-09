"""认证登录路由（v0.2）。

单一登录端点：用户名 + 静态 API 密钥。首次登录的用户名自动注册，
后续登录用 API 密钥校验。成功后签发 JWT 供受保护端点使用。
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_app_settings, get_db
from app.core.config import Settings
from app.db import repositories as repo
from app.models.schemas import LoginRequest, LoginResponse
from app.services.security import (
    create_access_token,
    hash_api_key,
    verify_api_key,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> LoginResponse:
    user = repo.get_user_by_username(conn, body.username)
    if user is None:
        # 首次登录：自动注册，密钥即首次提供的密钥。
        user_id = repo.create_user(conn, body.username, hash_api_key(body.api_key))
    else:
        # 已存在：校验密钥，失败 401。
        if not verify_api_key(body.api_key, user["api_key_hash"]):
            raise HTTPException(status_code=401, detail="用户名或密钥错误")
        user_id = user["id"]

    token = create_access_token(
        user_id,
        body.username,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expire_minutes=settings.jwt_expire_minutes,
    )
    return LoginResponse(token=token, user_id=user_id, username=body.username)
