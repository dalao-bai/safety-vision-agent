CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '施工安全隐患识别会话',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS uploaded_files (
  id TEXT PRIMARY KEY,
  conversation_id TEXT,
  original_name TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  mime_type TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_tasks (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  image_path TEXT NOT NULL,
  user_message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tool_calls (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  analysis_id TEXT,
  tool_name TEXT NOT NULL,
  status TEXT NOT NULL,
  input_json TEXT NOT NULL DEFAULT '{}',
  output_json TEXT NOT NULL DEFAULT '{}',
  latency_ms REAL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vlm_results (
  id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL,
  result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS yolo_results (
  id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL,
  result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fused_results (
  id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL,
  result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reports (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  analysis_id TEXT,
  title TEXT NOT NULL,
  markdown TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS human_reviews (
  id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL,
  item_type TEXT NOT NULL DEFAULT 'hazard',
  item_index INTEGER NOT NULL DEFAULT 0,
  reviewer TEXT,
  decision TEXT NOT NULL DEFAULT 'pending',
  revised_json TEXT NOT NULL DEFAULT '{}',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS remediation_tasks (
  id TEXT PRIMARY KEY,
  conversation_id TEXT,
  analysis_id TEXT NOT NULL,
  hazard_index INTEGER NOT NULL DEFAULT 0,
  title TEXT NOT NULL,
  recommendation TEXT NOT NULL,
  responsible_person TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  hazard_json TEXT NOT NULL DEFAULT '{}',
  due_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS remediation_evidence (
  id TEXT PRIMARY KEY,
  remediation_task_id TEXT NOT NULL,
  image_path TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS annotation_batches (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL DEFAULT 'analysis_review',
  status TEXT NOT NULL DEFAULT 'open',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS annotation_samples (
  id TEXT PRIMARY KEY,
  batch_id TEXT,
  analysis_id TEXT,
  conversation_id TEXT,
  image_path TEXT NOT NULL,
  width INTEGER,
  height INTEGER,
  status TEXT NOT NULL DEFAULT 'pending_review',
  source_type TEXT NOT NULL DEFAULT 'analysis_review',
  model_output_json TEXT NOT NULL DEFAULT '{}',
  yolo_output_json TEXT NOT NULL DEFAULT '{}',
  fused_result_json TEXT NOT NULL DEFAULT '{}',
  draft_json TEXT NOT NULL DEFAULT '{}',
  review_json TEXT NOT NULL DEFAULT '{}',
  accepted_record_json TEXT NOT NULL DEFAULT '{}',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS annotation_object_drafts (
  id TEXT PRIMARY KEY,
  sample_id TEXT NOT NULL,
  draft_object_index INTEGER NOT NULL DEFAULT 0,
  object_json TEXT NOT NULL DEFAULT '{}',
  decision TEXT NOT NULL DEFAULT 'pending',
  revised_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS training_candidates (
  id TEXT PRIMARY KEY,
  sample_id TEXT NOT NULL,
  analysis_id TEXT,
  candidate_type TEXT NOT NULL DEFAULT 'sft',
  status TEXT NOT NULL DEFAULT 'ready',
  source_reason TEXT NOT NULL DEFAULT 'human_revised_model_output',
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_conversation ON uploaded_files(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_analysis_conversation ON analysis_tasks(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tool_calls_conversation ON tool_calls(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_vlm_analysis ON vlm_results(analysis_id, created_at);
CREATE INDEX IF NOT EXISTS idx_yolo_analysis ON yolo_results(analysis_id, created_at);
CREATE INDEX IF NOT EXISTS idx_fused_analysis ON fused_results(analysis_id, created_at);
CREATE INDEX IF NOT EXISTS idx_reviews_analysis ON human_reviews(analysis_id, created_at);
CREATE INDEX IF NOT EXISTS idx_remediation_analysis ON remediation_tasks(analysis_id, created_at);
CREATE INDEX IF NOT EXISTS idx_annotation_analysis ON annotation_samples(analysis_id, created_at);
