-- v0.1 SQLite schema for the construction-safety Agent.
-- Stores full local audit memory: conversations, messages, uploaded images,
-- structured analysis results, tool calls, and raw model responses.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,          -- 'user' | 'assistant' | 'system'
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS uploaded_images (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    stored_path     TEXT NOT NULL,          -- server-side path under runtime/uploads
    stored_filename TEXT NOT NULL,          -- generated safe filename
    mime_type       TEXT NOT NULL,
    byte_size       INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS analysis_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    image_id        INTEGER,                -- nullable: analysis may predate image linkage
    result_json     TEXT NOT NULL,          -- serialized AnalysisResult
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id),
    FOREIGN KEY (image_id) REFERENCES uploaded_images(id)
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    call_id         TEXT,                   -- provider function-call id linking this tool call to the Agent response that requested it
    tool_name       TEXT NOT NULL,
    input_json      TEXT,                   -- serialized tool input
    output_json     TEXT,                   -- serialized tool output
    status          TEXT NOT NULL,          -- 'success' | 'error'
    error           TEXT,
    duration_ms     INTEGER,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS model_responses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    model_role      TEXT NOT NULL,          -- 'vlm' | 'agent'
    provider_id     TEXT,                   -- provider response id when available
    status          TEXT NOT NULL,          -- 'success' | 'error'
    raw_text        TEXT,                   -- raw response payload (JSON or text)
    error           TEXT,
    duration_ms     INTEGER,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_images_conversation ON uploaded_images(conversation_id);
CREATE INDEX IF NOT EXISTS idx_analysis_conversation ON analysis_results(conversation_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_conversation ON tool_calls(conversation_id);
CREATE INDEX IF NOT EXISTS idx_model_responses_conversation ON model_responses(conversation_id);

-- ============================================================
-- v0.2 新增表和索引
-- ============================================================

-- 用户认证表
CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,          -- uuid4
    username     TEXT NOT NULL UNIQUE,
    api_key_hash TEXT NOT NULL,             -- 哈希值，绝不存明文
    created_at   TEXT NOT NULL
);

-- 用户偏好（每用户一行，对话结束后异步更新）
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id            TEXT PRIMARY KEY,
    preference_summary TEXT,               -- ≤100字自然语言摘要
    focus_hazard_types TEXT,               -- JSON 数组
    frequent_questions TEXT,               -- JSON 数组
    updated_at         TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 用户隐患统计（用户确认准确后 upsert）
CREATE TABLE IF NOT EXISTS user_hazard_stats (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          TEXT    NOT NULL,
    hazard_type      TEXT    NOT NULL,
    risk_level       TEXT    NOT NULL,     -- 'high' | 'medium' | 'low'
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    last_seen_at     TEXT    NOT NULL,
    conversation_ids TEXT    NOT NULL DEFAULT '[]', -- JSON 数组
    UNIQUE (user_id, hazard_type, risk_level),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 规范文件元数据（向量存 ChromaDB，文件元数据存这里）
CREATE TABLE IF NOT EXISTS regulation_files (
    id            TEXT PRIMARY KEY,        -- uuid4
    filename      TEXT NOT NULL,           -- 服务端存储文件名
    original_name TEXT NOT NULL,           -- 用户上传的原始文件名
    file_path     TEXT NOT NULL,           -- 服务端完整路径
    file_type     TEXT NOT NULL,           -- 'pdf' | 'docx'
    chunk_count   INTEGER NOT NULL DEFAULT 0,
    deleted_at    TEXT,                    -- NULL 表示未删除（软删除）
    created_at    TEXT NOT NULL
);

-- conversations 新增列通过 sqlite.py init_db() 的 Python 侧 ALTER TABLE 完成
-- 原因：SQLite 不支持 ADD COLUMN IF NOT EXISTS，无法写成幂等 DDL
-- idx_conversations_user_date 同样在 Python 侧创建，依赖 user_id 列先存在

CREATE INDEX IF NOT EXISTS idx_user_hazard_stats_user
    ON user_hazard_stats(user_id);

CREATE INDEX IF NOT EXISTS idx_regulation_files_deleted
    ON regulation_files(deleted_at);
