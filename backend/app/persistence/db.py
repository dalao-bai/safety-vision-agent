from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Correction, Hazard, ImageRecord, Message

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS images (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL,
  path TEXT NOT NULL,
  scene TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hazards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  image_id INTEGER NOT NULL,
  object_id TEXT NOT NULL,
  status TEXT NOT NULL,
  hazard_type_id TEXT,
  bbox TEXT,
  reasoning_chain TEXT,
  visual_evidence TEXT,
  rule_basis TEXT,
  evidence_sufficiency TEXT,
  uncertainty_reason TEXT,
  missing_evidence TEXT,
  confirmed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS corrections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  image_id INTEGER NOT NULL,
  note TEXT NOT NULL,
  intake_path TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()

    # sessions / messages
    def create_session(self) -> int:
        with self._lock:
            cur = self._conn.execute("INSERT INTO sessions(created_at) VALUES(?)", (_now(),))
            self._conn.commit()
            return int(cur.lastrowid)

    def session_exists(self, sid: int) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone()
            return row is not None

    def add_message(self, sid: int, role: str, content: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages(session_id, role, content, created_at) VALUES(?,?,?,?)",
                (sid, role, content, _now()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def get_messages(self, sid: int) -> list[Message]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY id", (sid,)
            ).fetchall()
            return [Message(**dict(r)) for r in rows]

    # images / hazards
    def add_image(self, sid: int, path: str, scene: str, _created_at: str | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO images(session_id, path, scene, status, created_at) VALUES(?,?,?,?,?)",
                (sid, path, scene, "awaiting_confirmation", _created_at or _now()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def get_image(self, img_id: int) -> ImageRecord:
        with self._lock:
            r = self._conn.execute("SELECT * FROM images WHERE id=?", (img_id,)).fetchone()
            if r is None:
                raise KeyError(f"image {img_id} not found")
            return ImageRecord(**dict(r))

    def set_image_status(self, img_id: int, status: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE images SET status=? WHERE id=?", (status, img_id))
            self._conn.commit()

    def add_hazards(self, img_id: int, hazards: list[dict[str, Any]]) -> None:
        with self._lock:
            for h in hazards:
                self._conn.execute(
                    """INSERT INTO hazards(image_id, object_id, status, hazard_type_id, bbox,
                        reasoning_chain, visual_evidence, rule_basis, evidence_sufficiency,
                        uncertainty_reason, missing_evidence, confirmed)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,0)""",
                    (
                        img_id, h.get("object_id", ""), h.get("status", ""), h.get("hazard_type_id"),
                        json.dumps(h.get("bbox"), ensure_ascii=False),
                        json.dumps(h.get("reasoning_chain") or [], ensure_ascii=False),
                        h.get("visual_evidence", ""), h.get("rule_basis", ""),
                        h.get("evidence_sufficiency", ""),
                        h.get("uncertainty_reason"), h.get("missing_evidence"),
                    ),
                )
            self._conn.commit()

    def _row_to_hazard(self, r: sqlite3.Row) -> Hazard:
        d = dict(r)
        d["bbox"] = json.loads(d["bbox"]) if d["bbox"] else None
        val = json.loads(d["reasoning_chain"]) if d["reasoning_chain"] else []
        d["reasoning_chain"] = val if isinstance(val, list) else []
        d["confirmed"] = bool(d["confirmed"])
        return Hazard(**d)

    def get_hazards(self, img_id: int) -> list[Hazard]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM hazards WHERE image_id=? ORDER BY id", (img_id,)).fetchall()
            return [self._row_to_hazard(r) for r in rows]

    def mark_hazards_confirmed(self, img_id: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE hazards SET confirmed=1 WHERE image_id=?", (img_id,))
            self._conn.commit()

    def get_pending_image_ids(self, session_id: int) -> list[int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM images WHERE session_id=? AND status='awaiting_confirmation'",
                (session_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def get_confirmed_hazards(self, sid: int) -> list[Hazard]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT h.* FROM hazards h JOIN images i ON h.image_id=i.id
                   WHERE i.session_id=? AND h.confirmed=1 ORDER BY h.id""", (sid,)
            ).fetchall()
            return [self._row_to_hazard(r) for r in rows]

    def get_session_hazards(self, sid: int) -> list[Hazard]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT h.* FROM hazards h JOIN images i ON h.image_id=i.id
                   WHERE i.session_id=? ORDER BY h.id""", (sid,)
            ).fetchall()
            return [self._row_to_hazard(r) for r in rows]

    # corrections
    def add_correction(self, img_id: int, note: str, intake_path: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO corrections(image_id, note, intake_path, created_at) VALUES(?,?,?,?)",
                (img_id, note, intake_path, _now()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def get_corrections(self, img_id: int) -> list[Correction]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM corrections WHERE image_id=? ORDER BY id", (img_id,)).fetchall()
            return [Correction(**dict(r)) for r in rows]

    def query_hazard_stats(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        hazard_type_id: str | None = None,
        object_id: str | None = None,
        confirmed_only: bool = True,
        top_n: int = 10,
    ) -> dict:
        conditions: list[str] = []
        params: list[Any] = []
        if confirmed_only:
            conditions.append("h.status = 'confirmed_hazard'")
        if date_from:
            conditions.append("date(i.created_at) >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("date(i.created_at) <= ?")
            params.append(date_to)
        if hazard_type_id:
            conditions.append("h.hazard_type_id = ?")
            params.append(hazard_type_id)
        if object_id:
            conditions.append("h.object_id = ?")
            params.append(object_id)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        base = f"FROM hazards h JOIN images i ON h.image_id=i.id {where}"
        with self._lock:
            total = self._conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
            rows = self._conn.execute(
                f"SELECT h.hazard_type_id, h.object_id, COUNT(*) AS count {base} "
                f"GROUP BY h.hazard_type_id, h.object_id ORDER BY count DESC LIMIT ?",
                params + [top_n],
            ).fetchall()
        return {
            "total": total,
            "date_from": date_from,
            "date_to": date_to,
            "confirmed_only": confirmed_only,
            "breakdown": [{"hazard_type_id": r[0], "object_id": r[1], "count": r[2]} for r in rows],
        }
