# Roadmap

Date: 2026-06-05

This roadmap describes how to rebuild the Agent gradually from the v0.1 MVP toward a more complete construction-site safety assistant.

## Principle

Each version should add one meaningful capability layer while keeping the previous version runnable.

The project should not jump directly to the final system. Every stage should have:

- A clear user-visible improvement.
- A small set of new files or modules.
- Focused tests.
- Updated requirements or notes.

## v0.1: Single Image Agent MVP

Goal: prove the smallest useful Agent loop.

Capabilities:

- Minimal React/Vite web UI.
- FastAPI backend.
- SQLite persistence.
- Upload one construction-site image.
- Call real VLM through OpenAI-compatible Responses API.
- Force structured JSON hazard output.
- Use Agent model tool calling.
- Tools:
  - `analyze_image`
  - `explain_basis`
  - `rank_risks`
  - `suggest_remediation`
- Save full local audit memory.
- Support follow-up questions in one conversation.

Primary artifact:

- `docs/requirements/v0.1-mvp.md`

## v0.2: Multi-User Enterprise Backend

Goal: extend v0.1 into an enterprise-internal system with user isolation, a regulation knowledge base, and compliance reporting.

Delivered:

- Multi-user authentication (username + JWT, user data isolation).
- Regulation library — upload PDF/Word files, semantic search via ChromaDB + embeddings.
- Compliance report generation (.docx, async background task).
- Analysis confirmation flow — per-image accuracy checkbox; inaccurate images written to annotation.db for relabeling.
- History query — cross-conversation hazard statistics per user.
- Three-layer memory: sliding window (in-conversation), user preference summary (cross-conversation), hazard stats (statistical).
- Agent orchestration migrated to LangGraph `create_react_agent` with 7 tools and full audit callbacks.
- 154 backend tests passing.

## v0.3: Multi-Image Support

Goal: allow comparison across multiple construction-site images.

Possible additions:

- Upload multiple images in one conversation.
- Analyze images independently.
- Compare hazards across images.
- Rank risks across all images.
- Show image source for each hazard.

Key question:

- Should the Agent analyze all images at once or maintain one analysis result per image?

## v0.4: Rule And Standard Basis

Goal: improve professional usefulness by adding local safety rule references.

Possible additions:

- Local rule blocks for common construction-site hazards.
- Rule retrieval tool.
- Add `rule_basis` or `standard_reference` fields to hazards.
- Distinguish visual evidence from rule-based basis.

Non-goal:

- Do not claim full legal compliance coverage.

## v0.5: Report Generation

Goal: turn analysis into shareable inspection output.

Possible additions:

- `generate_report` tool.
- Markdown or PDF-style report preview.
- Include summary, hazard table, risk ranking, and remediation suggestions.
- Save generated report artifacts.

## v0.6: Human Review

Goal: let a human correct or confirm Agent findings.

Possible additions:

- Review status for hazards.
- Accept, revise, reject actions.
- Reviewer notes.
- Preserve original model output and revised output.

Key value:

- Starts moving from demo analysis toward accountable workflow.

## v0.7: Remediation Task Tracking

Goal: convert hazards into trackable correction tasks.

Possible additions:

- `create_remediation_task` tool.
- Task status, owner placeholder, due date, and notes.
- Link tasks back to hazards and images.

Non-goal:

- Full project management system.

## v0.8: Annotation Feedback Loop

Goal: collect reviewed outputs for future training or evaluation.

Possible additions:

- Export accepted hazard records.
- Generate image-level and hazard-level JSONL.
- Track training candidates.
- Add dataset quality checks.

## v0.9: Evaluation And Benchmarks

Goal: measure whether the Agent is improving.

Possible additions:

- Golden test images.
- Expected hazard labels.
- Prompt/model regression tests.
- Ranking quality checks.
- JSON schema conformance metrics.

## v1.0: Production-Oriented Baseline

Goal: prepare a stable baseline for real pilot use.

Possible additions:

- Authentication.
- User/session isolation.
- Data retention controls.
- Redaction and privacy policy.
- Deployment packaging.
- Operational logging.
- Clear limitations and safety disclaimers.

## Current Next Step

Create an implementation plan for v0.1 only.

The plan should cover:

- Project structure.
- Backend modules.
- Frontend modules.
- SQLite schema.
- Responses API client design.
- Tool calling loop.
- Test plan.
- Local run commands.
