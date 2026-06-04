import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from app.db.sqlite import connection_scope


JSON_COLUMNS = {
    "input_json",
    "output_json",
    "result_json",
    "revised_json",
    "hazard_json",
    "model_output_json",
    "yolo_output_json",
    "fused_result_json",
    "draft_json",
    "review_json",
    "accepted_record_json",
    "object_json",
    "payload_json",
}


class Record(dict):
    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _dump(value: dict | list | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def _record(row: sqlite3.Row | None) -> Record | None:
    if row is None:
        return None
    data = dict(row)
    for key in JSON_COLUMNS:
        if key in data and isinstance(data[key], str):
            data[key] = json.loads(data[key] or "{}")
    return Record(data)


def _records(rows: list[sqlite3.Row]) -> list[Record]:
    return [record for row in rows if (record := _record(row)) is not None]


def _insert(connection: sqlite3.Connection, table: str, values: dict) -> Record:
    columns = list(values)
    placeholders = ", ".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        [values[column] for column in columns],
    )
    row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (values["id"],)).fetchone()
    record = _record(row)
    if record is None:
        raise RuntimeError(f"failed to insert {table}")
    return record


def _get(connection: sqlite3.Connection, table: str, record_id: str) -> Record | None:
    return _record(connection.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone())


def get_or_create_conversation(conversation_id: str | None = None, title: str = "施工安全隐患识别会话", db=None) -> Record:
    with connection_scope() as connection:
        if conversation_id:
            existing = _get(connection, "conversations", conversation_id)
            if existing:
                return existing
        return _insert(
            connection,
            "conversations",
            {
                "id": conversation_id or new_id("conv"),
                "title": title,
                "created_at": _now(),
                "updated_at": _now(),
            },
        )


def add_message(conversation_id: str, role: str, content: str, db=None) -> Record:
    with connection_scope() as connection:
        return _insert(
            connection,
            "messages",
            {
                "id": new_id("msg"),
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "created_at": _now(),
            },
        )


def list_messages(conversation_id: str, limit: int = 20) -> list[Record]:
    with connection_scope() as connection:
        rows = connection.execute(
            """
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (conversation_id, limit),
        ).fetchall()
    return list(reversed(_records(rows)))


def add_uploaded_file(
    original_name: str,
    stored_path: str,
    mime_type: str | None,
    conversation_id: str | None = None,
    db=None,
) -> Record:
    with connection_scope() as connection:
        return _insert(
            connection,
            "uploaded_files",
            {
                "id": new_id("file"),
                "conversation_id": conversation_id,
                "original_name": original_name,
                "stored_path": stored_path,
                "mime_type": mime_type,
                "created_at": _now(),
            },
        )


def get_uploaded_file(file_id: str) -> Record | None:
    with connection_scope() as connection:
        return _get(connection, "uploaded_files", file_id)


def latest_uploaded_file(conversation_id: str) -> Record | None:
    with connection_scope() as connection:
        return _record(
            connection.execute(
                """
                SELECT * FROM uploaded_files
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
        )


def create_analysis_task(conversation_id: str, image_path: str, user_message: str, status: str = "pending", db=None) -> Record:
    with connection_scope() as connection:
        return _insert(
            connection,
            "analysis_tasks",
            {
                "id": new_id("analysis"),
                "conversation_id": conversation_id,
                "image_path": image_path,
                "user_message": user_message,
                "status": status,
                "created_at": _now(),
                "updated_at": _now(),
            },
        )


def get_analysis_task(analysis_id: str) -> Record | None:
    with connection_scope() as connection:
        return _get(connection, "analysis_tasks", analysis_id)


def latest_analysis_for_conversation(conversation_id: str) -> Record | None:
    with connection_scope() as connection:
        return _record(
            connection.execute(
                """
                SELECT * FROM analysis_tasks
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
        )


def update_analysis_status(analysis_id: str, status: str, db=None) -> None:
    with connection_scope() as connection:
        connection.execute(
            "UPDATE analysis_tasks SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), analysis_id),
        )


def save_analysis_results(analysis_id: str, vlm_json: dict, yolo_json: dict, fused_json: dict, db=None) -> None:
    with connection_scope() as connection:
        _insert(connection, "vlm_results", {"id": new_id("vlm"), "analysis_id": analysis_id, "result_json": _dump(vlm_json), "created_at": _now()})
        _insert(connection, "yolo_results", {"id": new_id("yolo"), "analysis_id": analysis_id, "result_json": _dump(yolo_json), "created_at": _now()})
        _insert(connection, "fused_results", {"id": new_id("fused"), "analysis_id": analysis_id, "result_json": _dump(fused_json), "created_at": _now()})
        connection.execute("UPDATE analysis_tasks SET status = ?, updated_at = ? WHERE id = ?", ("completed", _now(), analysis_id))


def save_fused_result(analysis_id: str, fused_json: dict, db=None) -> None:
    with connection_scope() as connection:
        _insert(connection, "fused_results", {"id": new_id("fused"), "analysis_id": analysis_id, "result_json": _dump(fused_json), "created_at": _now()})
        connection.execute("UPDATE analysis_tasks SET status = ?, updated_at = ? WHERE id = ?", ("completed", _now(), analysis_id))


def latest_fused_result(analysis_id: str, db=None) -> Record | None:
    with connection_scope() as connection:
        return _record(
            connection.execute(
                "SELECT * FROM fused_results WHERE analysis_id = ? ORDER BY created_at DESC LIMIT 1",
                (analysis_id,),
            ).fetchone()
        )


def latest_fused_result_for_conversation(conversation_id: str) -> tuple[Record, Record] | None:
    with connection_scope() as connection:
        row = connection.execute(
            """
            SELECT a.*, f.id AS fused_id, f.result_json AS fused_result_json, f.created_at AS fused_created_at
            FROM analysis_tasks a
            JOIN fused_results f ON f.analysis_id = a.id
            WHERE a.conversation_id = ?
            ORDER BY f.created_at DESC
            LIMIT 1
            """,
            (conversation_id,),
        ).fetchone()
    if not row:
        return None
    analysis = Record({key: row[key] for key in row.keys() if key in {"id", "conversation_id", "image_path", "user_message", "status", "created_at", "updated_at"}})
    fused = Record(
        {
            "id": row["fused_id"],
            "analysis_id": row["id"],
            "result_json": json.loads(row["fused_result_json"] or "{}"),
            "created_at": row["fused_created_at"],
        }
    )
    return analysis, fused


def latest_vlm_result(analysis_id: str, db=None) -> Record | None:
    with connection_scope() as connection:
        return _record(
            connection.execute("SELECT * FROM vlm_results WHERE analysis_id = ? ORDER BY created_at DESC LIMIT 1", (analysis_id,)).fetchone()
        )


def latest_yolo_result(analysis_id: str, db=None) -> Record | None:
    with connection_scope() as connection:
        return _record(
            connection.execute("SELECT * FROM yolo_results WHERE analysis_id = ? ORDER BY created_at DESC LIMIT 1", (analysis_id,)).fetchone()
        )


def create_tool_call(
    conversation_id: str,
    analysis_id: str | None,
    tool_name: str,
    status: str,
    input_json: dict,
    output_json: dict,
    latency_ms: float | None = None,
    db=None,
) -> Record:
    with connection_scope() as connection:
        return _insert(
            connection,
            "tool_calls",
            {
                "id": new_id("tool"),
                "conversation_id": conversation_id,
                "analysis_id": analysis_id,
                "tool_name": tool_name,
                "status": status,
                "input_json": _dump(input_json),
                "output_json": _dump(output_json),
                "latency_ms": latency_ms,
                "created_at": _now(),
            },
        )


def list_tool_calls(conversation_id: str, analysis_id: str | None = None, limit: int = 20) -> list[Record]:
    with connection_scope() as connection:
        if analysis_id:
            rows = connection.execute(
                """
                SELECT * FROM tool_calls
                WHERE conversation_id = ? AND analysis_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (conversation_id, analysis_id, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT * FROM tool_calls
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
    return list(reversed(_records(rows)))


def timed_tool_call(conversation_id: str, analysis_id: str | None, tool_name: str, input_json: dict, fn: Callable[[], object]):
    started = perf_counter()
    try:
        result = fn()
        output_json = result if isinstance(result, dict) else {"result": str(result)}
        create_tool_call(conversation_id, analysis_id, tool_name, "ok", input_json, output_json, (perf_counter() - started) * 1000)
        return result
    except Exception as exc:
        create_tool_call(conversation_id, analysis_id, tool_name, "error", input_json, {"error": str(exc)}, (perf_counter() - started) * 1000)
        raise


def create_human_review(
    analysis_id: str,
    item_type: str,
    item_index: int,
    decision: str,
    reviewer: str | None,
    revised_json: dict,
    note: str,
    db=None,
) -> Record:
    with connection_scope() as connection:
        return _insert(
            connection,
            "human_reviews",
            {
                "id": new_id("review"),
                "analysis_id": analysis_id,
                "item_type": item_type,
                "item_index": item_index,
                "reviewer": reviewer,
                "decision": decision,
                "revised_json": _dump(revised_json),
                "note": note,
                "created_at": _now(),
            },
        )


def create_remediation_task(
    conversation_id: str | None,
    analysis_id: str,
    hazard_index: int,
    title: str,
    recommendation: str,
    responsible_person: str | None,
    due_at,
    hazard_json: dict,
    db=None,
) -> Record:
    with connection_scope() as connection:
        return _insert(
            connection,
            "remediation_tasks",
            {
                "id": new_id("remed"),
                "conversation_id": conversation_id,
                "analysis_id": analysis_id,
                "hazard_index": hazard_index,
                "title": title,
                "recommendation": recommendation,
                "responsible_person": responsible_person,
                "status": "open",
                "hazard_json": _dump(hazard_json),
                "due_at": due_at.isoformat() if hasattr(due_at, "isoformat") else due_at,
                "created_at": _now(),
                "updated_at": _now(),
            },
        )


def get_remediation_task(task_id: str) -> Record | None:
    with connection_scope() as connection:
        return _get(connection, "remediation_tasks", task_id)


def list_remediation_tasks(conversation_id: str | None = None, analysis_id: str | None = None) -> list[Record]:
    query = "SELECT * FROM remediation_tasks"
    params: list[str] = []
    clauses: list[str] = []
    if conversation_id:
        clauses.append("conversation_id = ?")
        params.append(conversation_id)
    if analysis_id:
        clauses.append("analysis_id = ?")
        params.append(analysis_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC"
    with connection_scope() as connection:
        return _records(connection.execute(query, params).fetchall())


def add_remediation_evidence(task_id: str, image_path: str, note: str, db=None) -> Record:
    with connection_scope() as connection:
        evidence = _insert(
            connection,
            "remediation_evidence",
            {
                "id": new_id("evid"),
                "remediation_task_id": task_id,
                "image_path": image_path,
                "note": note,
                "created_at": _now(),
            },
        )
        connection.execute("UPDATE remediation_tasks SET status = ?, updated_at = ? WHERE id = ?", ("submitted", _now(), task_id))
        return evidence


def update_remediation_status(task_id: str, status: str, db=None) -> Record | None:
    with connection_scope() as connection:
        connection.execute("UPDATE remediation_tasks SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), task_id))
        return _get(connection, "remediation_tasks", task_id)


def create_report(conversation_id: str, analysis_id: str | None, title: str, markdown: str) -> Record:
    with connection_scope() as connection:
        return _insert(
            connection,
            "reports",
            {
                "id": new_id("report"),
                "conversation_id": conversation_id,
                "analysis_id": analysis_id,
                "title": title,
                "markdown": markdown,
                "created_at": _now(),
            },
        )


def create_annotation_batch(source: str, note: str = "", db=None) -> Record:
    with connection_scope() as connection:
        return _insert(
            connection,
            "annotation_batches",
            {"id": new_id("annbatch"), "source": source, "status": "open", "note": note, "created_at": _now(), "updated_at": _now()},
        )


def create_annotation_sample(
    batch_id: str | None,
    analysis_id: str | None,
    conversation_id: str | None,
    image_path: str,
    source_type: str,
    model_output_json: dict,
    yolo_output_json: dict,
    fused_result_json: dict,
    draft_json: dict,
    review_json: dict,
    note: str,
    db=None,
) -> Record:
    with connection_scope() as connection:
        sample = _insert(
            connection,
            "annotation_samples",
            {
                "id": new_id("annsample"),
                "batch_id": batch_id,
                "analysis_id": analysis_id,
                "conversation_id": conversation_id,
                "image_path": image_path,
                "status": "pending_review",
                "source_type": source_type,
                "model_output_json": _dump(model_output_json),
                "yolo_output_json": _dump(yolo_output_json),
                "fused_result_json": _dump(fused_result_json),
                "draft_json": _dump({**draft_json, "sample_id": "pending"}),
                "review_json": _dump({**review_json, "sample_id": "pending"}),
                "accepted_record_json": "{}",
                "note": note,
                "created_at": _now(),
                "updated_at": _now(),
            },
        )
        draft_json = {**draft_json, "sample_id": sample.id}
        review_json = {**review_json, "sample_id": sample.id}
        connection.execute(
            "UPDATE annotation_samples SET draft_json = ?, review_json = ? WHERE id = ?",
            (_dump(draft_json), _dump(review_json), sample.id),
        )
        for obj in draft_json.get("objects") or []:
            _insert(
                connection,
                "annotation_object_drafts",
                {
                    "id": new_id("annobj"),
                    "sample_id": sample.id,
                    "draft_object_index": int(obj.get("draft_object_index", 0)),
                    "object_json": _dump(obj),
                    "decision": "pending",
                    "revised_json": _dump(obj),
                    "created_at": _now(),
                },
            )
        return _get(connection, "annotation_samples", sample.id)


def get_annotation_sample(sample_id: str) -> Record | None:
    with connection_scope() as connection:
        return _get(connection, "annotation_samples", sample_id)


def update_annotation_review(sample_id: str, review_json: dict, db=None) -> Record:
    with connection_scope() as connection:
        connection.execute(
            "UPDATE annotation_samples SET review_json = ?, status = ?, updated_at = ? WHERE id = ?",
            (_dump(review_json), "reviewed", _now(), sample_id),
        )
        for item in review_json.get("objects") or []:
            connection.execute(
                """
                UPDATE annotation_object_drafts
                SET decision = ?, revised_json = ?
                WHERE sample_id = ? AND draft_object_index = ?
                """,
                (
                    item.get("decision", "pending"),
                    _dump(item.get("revised") or {}),
                    sample_id,
                    item.get("draft_object_index"),
                ),
            )
        record = _get(connection, "annotation_samples", sample_id)
        if record is None:
            raise ValueError("annotation sample not found")
        return record


def commit_annotation_sample(sample_id: str, accepted_record_json: dict, candidate_type: str, db=None) -> Record | None:
    accepted_count = len(accepted_record_json.get("objects") or [])
    status = "committed" if accepted_count else "reviewed"
    with connection_scope() as connection:
        connection.execute(
            "UPDATE annotation_samples SET accepted_record_json = ?, status = ?, updated_at = ? WHERE id = ?",
            (_dump(accepted_record_json), status, _now(), sample_id),
        )
        if not accepted_count:
            return None
        sample = _get(connection, "annotation_samples", sample_id)
        return _insert(
            connection,
            "training_candidates",
            {
                "id": new_id("traincand"),
                "sample_id": sample_id,
                "analysis_id": sample.analysis_id if sample else None,
                "candidate_type": candidate_type,
                "status": "ready",
                "source_reason": "human_revised_model_output",
                "payload_json": _dump(accepted_record_json),
                "created_at": _now(),
            },
        )
