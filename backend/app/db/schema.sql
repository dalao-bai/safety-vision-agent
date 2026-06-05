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
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_images_conversation ON uploaded_images(conversation_id);
CREATE INDEX IF NOT EXISTS idx_analysis_conversation ON analysis_results(conversation_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_conversation ON tool_calls(conversation_id);
CREATE INDEX IF NOT EXISTS idx_model_responses_conversation ON model_responses(conversation_id);
