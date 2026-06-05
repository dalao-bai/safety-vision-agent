// Frontend mirror of backend/app/models/schemas.py (U3).
// Keep these aligned with the Pydantic models — they define the API contract.

export type RiskLevel = "low" | "medium" | "high" | "critical";

export interface Hazard {
  name: string;
  location: string;
  risk_level: RiskLevel;
  basis: string;
  remediation: string;
  confidence: number;
}

export interface AnalysisResult {
  summary: string;
  hazards: Hazard[];
  needs_followup: boolean;
  followup_question: string | null;
}

export interface ToolCallSummary {
  tool_name: string;
  status: string;
  input?: Record<string, unknown> | null;
  output?: Record<string, unknown> | null;
  error?: string | null;
  duration_ms?: number | null;
}

export interface ChatResponse {
  conversation_id: string;
  answer: string;
  analysis: AnalysisResult | null;
  tool_calls: ToolCallSummary[];
}

export interface ApiError {
  error: string;
  detail?: string | null;
}
