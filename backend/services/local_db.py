"""
LOCAL_MODE: SQLite-backed drop-in replacement for the supabase-py client.

Implements the exact postgrest fluent surface the backend uses
(select/insert/update/delete/upsert, eq/neq/in_/is_/gte/gt/lte/lt/or_/match,
not_, order/range/limit/single, count="exact") plus the four RPCs
(search_images_by_embedding, match_faces_by_embedding,
videos_missing_face_presence, get_vault_secret). Vector similarity is computed
in Python with numpy over JSON-stored embeddings — plenty fast at
single-machine scale.

The DB file lives at {LOCAL_DATA_DIR}/local.db and is shared between the API
process and worker subprocesses (WAL mode + busy_timeout make that safe).
"""
import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import settings

LOCAL_USER_ID = "00000000-0000-4000-8000-000000000001"
LOCAL_USER_EMAIL = "local@localhost"

# Columns stored as JSON text in SQLite but dict/list in the app
_JSON_COLUMNS = {
    "jobs": {"params", "result_json"},
    "usage_logs": {"metadata"},
    "image_embeddings": {"embedding", "caption_embedding"},
    "image_caption_sentences": {"embedding"},
    "image_face_presence": {"face_embedding", "bbox"},
    "face_tags": {"embedding"},
    "pipeline_cache": {"data"},
    "speaker_voiceprints": {"embedding"},
    "transcript_embeddings": {"embedding"},
    "audio_event_embeddings": {"embedding"},
}

# Columns that postgrest returns as true/false/null — SQLite stores 0/1
_BOOL_COLUMNS = {
    "user_profiles": {"email_verified", "is_admin"},
    "user_api_keys": {"is_valid"},
    "password_resets": {"used"},
    "audio_event_embeddings": {"has_speech"},
}

# Columns that get a generated UUID on insert when absent (pg gen_random_uuid())
_UUID_DEFAULTS = {
    "jobs": ("id", "access_token"),
    "invite_codes": ("id", "code"),
    "image_caption_sentences": ("id",),
    "user_usage_monthly": (),
    "speaker_voiceprints": ("id",),
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalAPIError(Exception):
    """Raised where postgrest would raise APIError (e.g. .single() mismatch)."""


class _APIResponse:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


def _cosine(a: List[float], b: List[float]) -> float:
    import numpy as np

    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 0.0
    return float(np.dot(va, vb) / denom)


class _TableQuery:
    _FILTER_OPS = {
        "eq": "=", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
    }

    def __init__(self, db: "LocalSupabaseClient", table: str):
        self._db = db
        self._table = table
        self._op: Optional[str] = None
        self._payload: Optional[List[Dict]] = None
        self._columns = "*"
        self._count_mode: Optional[str] = None
        self._filters: List[tuple] = []  # (sql_fragment, [params])
        self._order: List[str] = []
        self._limit_n: Optional[int] = None
        self._offset_n: Optional[int] = None
        self._single = False
        self._negate_next = False
        self._on_conflict: Optional[str] = None

    # ── verbs ────────────────────────────────────────────────────────────
    def select(self, columns: str = "*", count: Optional[str] = None, **_):
        self._op = "select"
        self._columns = columns
        self._count_mode = count
        return self

    def insert(self, payload, **_):
        self._op = "insert"
        self._payload = payload if isinstance(payload, list) else [payload]
        return self

    def upsert(self, payload, on_conflict: Optional[str] = None, **_):
        self._op = "upsert"
        self._payload = payload if isinstance(payload, list) else [payload]
        self._on_conflict = on_conflict
        return self

    def update(self, payload, **_):
        self._op = "update"
        self._payload = [payload]
        return self

    def delete(self, **_):
        self._op = "delete"
        return self

    # ── filters ──────────────────────────────────────────────────────────
    @property
    def not_(self):
        self._negate_next = True
        return self

    def _add(self, fragment: str, params: List[Any]):
        if self._negate_next:
            fragment = f"NOT ({fragment})"
            self._negate_next = False
        self._filters.append((fragment, params))
        return self

    def _adapt(self, table: str, col: str, val: Any) -> Any:
        if isinstance(val, bool):
            return int(val)
        if isinstance(val, (dict, list)):
            return json.dumps(val)
        if isinstance(val, uuid.UUID):
            return str(val)
        return val

    def eq(self, col, val):
        return self._add(f'"{col}" = ?', [self._adapt(self._table, col, val)])

    def neq(self, col, val):
        return self._add(f'"{col}" != ?', [self._adapt(self._table, col, val)])

    def gt(self, col, val):
        return self._add(f'"{col}" > ?', [self._adapt(self._table, col, val)])

    def gte(self, col, val):
        return self._add(f'"{col}" >= ?', [self._adapt(self._table, col, val)])

    def lt(self, col, val):
        return self._add(f'"{col}" < ?', [self._adapt(self._table, col, val)])

    def lte(self, col, val):
        return self._add(f'"{col}" <= ?', [self._adapt(self._table, col, val)])

    def in_(self, col, values):
        values = list(values)
        if not values:
            return self._add("0 = 1", [])
        marks = ",".join("?" for _ in values)
        return self._add(
            f'"{col}" IN ({marks})',
            [self._adapt(self._table, col, v) for v in values],
        )

    def is_(self, col, val):
        if val is None or (isinstance(val, str) and val.lower() == "null"):
            return self._add(f'"{col}" IS NULL', [])
        if isinstance(val, str) and val.lower() in ("true", "false"):
            return self._add(f'"{col}" = ?', [1 if val.lower() == "true" else 0])
        if isinstance(val, bool):
            return self._add(f'"{col}" = ?', [int(val)])
        raise LocalAPIError(f"Unsupported is_ value: {val!r}")

    def match(self, query: Dict):
        for col, val in query.items():
            self.eq(col, val)
        return self

    def or_(self, filter_str: str):
        """Parse a postgrest disjunction like
        'user_id.eq.X,access_token.in.(a,b)' into SQL."""
        parts, buf, depth = [], "", 0
        for ch in filter_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append(buf)
                buf = ""
            else:
                buf += ch
        if buf:
            parts.append(buf)

        fragments, params = [], []
        for part in parts:
            m = re.match(r"^([\w]+)\.(eq|neq|gt|gte|lt|lte|is|in)\.(.*)$", part.strip())
            if not m:
                raise LocalAPIError(f"Cannot parse or_ filter part: {part!r}")
            col, op, raw = m.groups()
            if op == "in":
                values = [v.strip() for v in raw.strip("()").split(",") if v.strip()]
                if not values:
                    fragments.append("0 = 1")
                    continue
                marks = ",".join("?" for _ in values)
                fragments.append(f'"{col}" IN ({marks})')
                params.extend(values)
            elif op == "is":
                if raw.lower() == "null":
                    fragments.append(f'"{col}" IS NULL')
                else:
                    fragments.append(f'"{col}" = ?')
                    params.append(1 if raw.lower() == "true" else 0)
            else:
                fragments.append(f'"{col}" {self._FILTER_OPS[op]} ?')
                params.append(raw)
        return self._add("(" + " OR ".join(fragments) + ")", params)

    # ── modifiers ────────────────────────────────────────────────────────
    def order(self, column: str, desc: bool = False, **_):
        self._order.append(f'"{column}" {"DESC" if desc else "ASC"}')
        return self

    def limit(self, n: int, **_):
        self._limit_n = n
        return self

    def range(self, start: int, end: int, **_):
        self._offset_n = start
        self._limit_n = end - start + 1
        return self

    def single(self):
        self._single = True
        return self

    def maybe_single(self):
        self._single = "maybe"
        return self

    # ── execution ────────────────────────────────────────────────────────
    def _where(self) -> tuple:
        if not self._filters:
            return "", []
        sql = " WHERE " + " AND ".join(f for f, _ in self._filters)
        params = [p for _, ps in self._filters for p in ps]
        return sql, params

    def _decode_row(self, row: sqlite3.Row) -> Dict:
        out = dict(row)
        json_cols = _JSON_COLUMNS.get(self._table, set())
        bool_cols = _BOOL_COLUMNS.get(self._table, set())
        for col in list(out.keys()):
            val = out[col]
            if col in json_cols and isinstance(val, str):
                try:
                    out[col] = json.loads(val)
                except json.JSONDecodeError:
                    pass
            elif col in bool_cols and val is not None:
                out[col] = bool(val)
        return out

    def _encode_payload(self, row: Dict) -> Dict:
        return {
            col: self._adapt(self._table, col, val)
            for col, val in row.items()
        }

    def _prepare_insert_row(self, row: Dict) -> Dict:
        row = dict(row)
        table_cols = self._db.table_columns(self._table)
        for col in _UUID_DEFAULTS.get(self._table, ("id",)):
            if not row.get(col):
                row[col] = str(uuid.uuid4())
        for col in ("created_at", "updated_at"):
            if col in table_cols and not row.get(col):
                row[col] = _utcnow()
        if "window_start" in table_cols and not row.get("window_start"):
            row["window_start"] = _utcnow()
        return self._encode_payload(row)

    def execute(self) -> _APIResponse:
        op = self._op or "select"
        with self._db.lock:
            conn = self._db.conn
            if op == "select":
                return self._execute_select(conn)
            if op == "insert":
                return self._execute_insert(conn)
            if op == "upsert":
                return self._execute_upsert(conn)
            if op == "update":
                return self._execute_update(conn)
            if op == "delete":
                return self._execute_delete(conn)
        raise LocalAPIError(f"Unsupported operation: {op}")

    def _execute_select(self, conn) -> _APIResponse:
        where_sql, params = self._where()
        cols = self._columns.strip()
        if cols != "*":
            cols = ", ".join(f'"{c.strip()}"' for c in cols.split(","))
        sql = f'SELECT {cols} FROM "{self._table}"{where_sql}'
        if self._order:
            sql += " ORDER BY " + ", ".join(self._order)
        if self._limit_n is not None:
            sql += f" LIMIT {int(self._limit_n)}"
            if self._offset_n:
                sql += f" OFFSET {int(self._offset_n)}"
        rows = [self._decode_row(r) for r in conn.execute(sql, params).fetchall()]

        count = None
        if self._count_mode:
            count_sql = f'SELECT COUNT(*) FROM "{self._table}"{where_sql}'
            count = conn.execute(count_sql, params).fetchone()[0]

        if self._single:
            if len(rows) == 1:
                return _APIResponse(rows[0], count)
            if self._single == "maybe" and len(rows) == 0:
                return _APIResponse(None, count)
            raise LocalAPIError(
                f"single() expected exactly 1 row from {self._table}, got {len(rows)}"
            )
        return _APIResponse(rows, count)

    def _execute_insert(self, conn) -> _APIResponse:
        results = []
        for raw in self._payload or []:
            row = self._prepare_insert_row(raw)
            cols = list(row.keys())
            col_sql = ", ".join(f'"{c}"' for c in cols)
            marks = ", ".join("?" for _ in cols)
            cur = conn.execute(
                f'INSERT INTO "{self._table}" ({col_sql}) VALUES ({marks}) RETURNING *',
                [row[c] for c in cols],
            )
            results.append(self._decode_row(cur.fetchone()))
        conn.commit()
        return _APIResponse(results)

    def _execute_upsert(self, conn) -> _APIResponse:
        conflict_cols = [
            c.strip() for c in (self._on_conflict or "id").split(",") if c.strip()
        ]
        results = []
        for raw in self._payload or []:
            row = self._prepare_insert_row(raw)
            cols = list(row.keys())
            col_sql = ", ".join(f'"{c}"' for c in cols)
            marks = ", ".join("?" for _ in cols)
            update_cols = [c for c in cols if c not in conflict_cols and c != "id"]
            set_sql = ", ".join(f'"{c}" = excluded."{c}"' for c in update_cols)
            conflict_sql = ", ".join(f'"{c}"' for c in conflict_cols)
            sql = (
                f'INSERT INTO "{self._table}" ({col_sql}) VALUES ({marks}) '
                f"ON CONFLICT({conflict_sql}) DO UPDATE SET {set_sql} RETURNING *"
            )
            cur = conn.execute(sql, [row[c] for c in cols])
            results.append(self._decode_row(cur.fetchone()))
        conn.commit()
        return _APIResponse(results)

    def _execute_update(self, conn) -> _APIResponse:
        payload = dict((self._payload or [{}])[0])
        table_cols = self._db.table_columns(self._table)
        if "updated_at" in table_cols and "updated_at" not in payload:
            payload["updated_at"] = _utcnow()
        payload = self._encode_payload(payload)
        where_sql, where_params = self._where()
        set_sql = ", ".join(f'"{c}" = ?' for c in payload)
        sql = f'UPDATE "{self._table}" SET {set_sql}{where_sql} RETURNING *'
        cur = conn.execute(sql, list(payload.values()) + where_params)
        rows = [self._decode_row(r) for r in cur.fetchall()]
        conn.commit()
        return _APIResponse(rows)

    def _execute_delete(self, conn) -> _APIResponse:
        where_sql, params = self._where()
        cur = conn.execute(
            f'DELETE FROM "{self._table}"{where_sql} RETURNING *', params
        )
        rows = [self._decode_row(r) for r in cur.fetchall()]
        conn.commit()
        return _APIResponse(rows)


class _RpcQuery:
    def __init__(self, db: "LocalSupabaseClient", fn: str, params: Dict):
        self._db = db
        self._fn = fn
        self._params = params or {}

    def execute(self) -> _APIResponse:
        handler = getattr(self, f"_rpc_{self._fn}", None)
        if handler is None:
            raise LocalAPIError(f"RPC '{self._fn}' is not implemented in LOCAL_MODE")
        with self._db.lock:
            return _APIResponse(handler())

    def _rpc_get_vault_secret(self) -> List[Dict]:
        return [{"secret": self._db.encryption_key_hex}]

    def _rpc_consume_rate_limit(self) -> bool:
        """Mirrors migrations/005's consume_rate_limit(): atomic check-and-increment
        keyed on (user_id, limit_type), resetting count when the window rolls over.
        Returns a bare bool (postgrest RPC scalar return), not a row list."""
        p = self._params
        user_id = p["p_user_id"]
        limit_type = p["p_limit_type"]
        limit = int(p["p_limit"])
        window_start = p["p_window_start"]
        now = _utcnow()

        row = self._db.conn.execute(
            "SELECT count, window_start FROM rate_limits WHERE user_id = ? AND limit_type = ?",
            [user_id, limit_type],
        ).fetchone()

        if row is None:
            self._db.conn.execute(
                "INSERT INTO rate_limits (id, user_id, limit_type, count, window_start, created_at, updated_at) "
                "VALUES (?, ?, ?, 1, ?, ?, ?)",
                [str(uuid.uuid4()), user_id, limit_type, window_start, now, now],
            )
            self._db.conn.commit()
            return 1 <= limit

        existing_count = row["count"]
        existing_window = row["window_start"]

        if existing_window is None or existing_window < window_start:
            self._db.conn.execute(
                "UPDATE rate_limits SET count = 1, window_start = ?, updated_at = ? "
                "WHERE user_id = ? AND limit_type = ?",
                [window_start, now, user_id, limit_type],
            )
            self._db.conn.commit()
            return 1 <= limit

        if existing_count < limit:
            new_count = existing_count + 1
            self._db.conn.execute(
                "UPDATE rate_limits SET count = ?, updated_at = ? "
                "WHERE user_id = ? AND limit_type = ?",
                [new_count, now, user_id, limit_type],
            )
            self._db.conn.commit()
            return new_count <= limit

        return False

    def _job_row_to_dict(self, row: sqlite3.Row) -> Dict:
        """Job rows carry JSON-text columns (params, result_json) that need
        decoding back to Python objects, matching _TableQuery._decode_row's
        behavior for the jobs table."""
        out = dict(row)
        for col in ("params", "result_json"):
            val = out.get(col)
            if isinstance(val, str):
                try:
                    out[col] = json.loads(val)
                except json.JSONDecodeError:
                    pass
        return out

    @staticmethod
    def _current_period() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-01")

    # ---- Job lifecycle RPCs (mirrors migrations 005-008) ----------------
    # Every RPC handler already runs under self._db.lock (see execute()
    # above), so unlike the real Postgres functions these don't need their
    # own advisory locking - the wrapping lock already serializes everything
    # on this single connection/process.

    def _rpc_create_job_secure(self) -> List[Dict]:
        p = self._params
        user_id = p["p_user_id"]
        video_hash = p["p_video_hash"]
        if not user_id or not re.match(r"^[0-9a-f]{64}$", video_hash or ""):
            raise LocalAPIError("invalid job identity")

        gcs_path = p["p_gcs_path"]
        intent = self._db.conn.execute(
            "SELECT * FROM upload_intents WHERE user_id = ? AND gcs_path = ?",
            [user_id, gcs_path],
        ).fetchone()
        now = _utcnow()
        if intent is None or intent["status"] != "pending" or (intent["expires_at"] or "") <= now:
            raise LocalAPIError("invalid_or_expired_upload_intent")
        if (
            intent["expected_size_bytes"] != p["p_file_size_bytes"]
            or intent["original_filename"] != p["p_filename"]
            or not gcs_path.startswith(f"uploads/{user_id}/")
        ):
            raise LocalAPIError("upload_intent_mismatch")

        # Dedup: reuse the user's most-recently-completed job with this hash.
        existing = self._db.conn.execute(
            "SELECT * FROM jobs WHERE user_id = ? AND video_hash = ? AND status = 'completed' "
            "ORDER BY completed_at DESC LIMIT 1",
            [user_id, video_hash],
        ).fetchone()
        if existing is not None:
            self._db.conn.execute(
                "UPDATE upload_intents SET status = 'consumed', consumed_at = ?, job_id = ?, "
                "content_sha256 = ? WHERE id = ?",
                [now, existing["id"], video_hash, intent["id"]],
            )
            self._db.conn.commit()
            return [self._job_row_to_dict(existing)]

        global_limit = p.get("p_global_processing_limit")
        if global_limit is not None:
            active = self._db.conn.execute(
                "SELECT COUNT(*) AS c FROM jobs WHERE status = 'processing'"
            ).fetchone()["c"]
            if active >= global_limit:
                raise LocalAPIError("global_processing_limit_reached")

        user_limit = p.get("p_user_concurrent_limit")
        if user_limit is not None:
            active = self._db.conn.execute(
                "SELECT COUNT(*) AS c FROM jobs WHERE user_id = ? AND status IN ('pending','processing')",
                [user_id],
            ).fetchone()["c"]
            if active >= user_limit:
                raise LocalAPIError("user_concurrent_limit_reached")

        period = self._current_period()
        self._db.conn.execute(
            "INSERT INTO user_usage_monthly (user_id, period_start) VALUES (?, ?) "
            "ON CONFLICT(user_id, period_start) DO NOTHING",
            [user_id, period],
        )
        usage = self._db.conn.execute(
            "SELECT * FROM user_usage_monthly WHERE user_id = ? AND period_start = ?",
            [user_id, period],
        ).fetchone()

        reservation = max(int(p.get("p_duration_seconds") or 0), 0)
        monthly_limit = p.get("p_monthly_limit_seconds")
        if monthly_limit is not None and (
            usage["transcription_seconds"] + usage["reserved_transcription_seconds"] + reservation
            > monthly_limit
        ):
            raise LocalAPIError("monthly_quota_exceeded")

        self._db.conn.execute(
            "UPDATE user_usage_monthly SET reserved_transcription_seconds = "
            "reserved_transcription_seconds + ?, updated_at = ? WHERE user_id = ? AND period_start = ?",
            [reservation, now, user_id, period],
        )

        job_id = p["p_job_id"]
        self._db.conn.execute(
            "INSERT INTO jobs (id, access_token, user_id, filename, gcs_path, file_size_bytes, "
            "video_hash, status, progress, stage, message, estimated_duration_seconds, "
            "video_duration_seconds, quota_reserved_seconds, quota_reservation_period, "
            "upload_intent_id, retry_count, params, created_at, updated_at, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, 'queued', 'Job created and queued', "
            "?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
            [
                job_id, p["p_access_token"], user_id, p["p_filename"], gcs_path,
                p["p_file_size_bytes"], video_hash, p.get("p_estimated_duration_seconds"),
                p.get("p_duration_seconds"), reservation, period, intent["id"],
                json.dumps(p.get("p_params") or {}), now, now, now,
            ],
        )
        self._db.conn.execute(
            "UPDATE upload_intents SET status = 'consumed', consumed_at = ?, job_id = ?, "
            "content_sha256 = ? WHERE id = ?",
            [now, job_id, video_hash, intent["id"]],
        )
        self._db.conn.commit()
        new_row = self._db.conn.execute("SELECT * FROM jobs WHERE id = ?", [job_id]).fetchone()
        return [self._job_row_to_dict(new_row)]

    def _rpc_claim_job(self) -> bool:
        p = self._params
        limit = p.get("p_global_processing_limit")
        if limit is not None:
            active = self._db.conn.execute(
                "SELECT COUNT(*) AS c FROM jobs WHERE status = 'processing'"
            ).fetchone()["c"]
            if active >= limit:
                return False
        now = _utcnow()
        cur = self._db.conn.execute(
            "UPDATE jobs SET status = 'processing', started_at = ?, updated_at = ?, last_seen = ?, "
            "progress = 0, stage = 'starting', message = 'Job processing started' "
            "WHERE id = ? AND status = 'pending'",
            [now, now, now, p["p_job_id"]],
        )
        self._db.conn.commit()
        return cur.rowcount > 0

    def _rpc_adjust_job_quota_reservation(self) -> bool:
        p = self._params
        job_id = p["p_job_id"]
        user_id = p["p_user_id"]
        actual = max(int(p.get("p_actual_seconds") or 0), 0)

        job = self._db.conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?", [job_id, user_id]
        ).fetchone()
        if job is None or job["status"] != "processing":
            return False

        period = job["quota_reservation_period"] or self._current_period()
        self._db.conn.execute(
            "INSERT INTO user_usage_monthly (user_id, period_start) VALUES (?, ?) "
            "ON CONFLICT(user_id, period_start) DO NOTHING",
            [user_id, period],
        )
        usage = self._db.conn.execute(
            "SELECT * FROM user_usage_monthly WHERE user_id = ? AND period_start = ?",
            [user_id, period],
        ).fetchone()

        monthly_limit = p.get("p_monthly_limit_seconds")
        if monthly_limit is not None and (
            usage["transcription_seconds"] + usage["reserved_transcription_seconds"]
            - job["quota_reserved_seconds"] + actual
            > monthly_limit
        ):
            return False

        now = _utcnow()
        self._db.conn.execute(
            "UPDATE user_usage_monthly SET reserved_transcription_seconds = "
            "reserved_transcription_seconds - ? + ?, updated_at = ? WHERE user_id = ? AND period_start = ?",
            [job["quota_reserved_seconds"], actual, now, user_id, period],
        )
        self._db.conn.execute(
            "UPDATE jobs SET quota_reserved_seconds = ?, quota_reservation_period = ?, "
            "video_duration_seconds = ?, updated_at = ? WHERE id = ?",
            [actual, period, actual, now, job_id],
        )
        self._db.conn.commit()
        return True

    def _rpc_begin_job_finalization(self) -> bool:
        p = self._params
        job_id = p["p_job_id"]
        user_id = p["p_user_id"]
        final_key = p["p_final_media_key"] or ""
        video_hash = p.get("p_video_hash")

        if (
            not job_id or not user_id
            or not final_key.startswith(f"processed/{user_id}/")
            or ".." in final_key or "\\" in final_key
        ):
            return False

        job = self._db.conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?", [job_id, user_id]
        ).fetchone()
        if job is None:
            return False
        if job["status"] == "finalizing":
            return job["final_media_key"] == final_key and job["video_hash"] == video_hash
        if job["status"] != "processing" or job["quota_reservation_period"] is None:
            return False
        gcs_path = job["gcs_path"] or ""
        if not (gcs_path.startswith(f"uploads/{user_id}/") or gcs_path == final_key):
            return False

        now = _utcnow()
        duration = max(int(p.get("p_video_duration_seconds") or 0), 0)
        cur = self._db.conn.execute(
            "UPDATE jobs SET status = 'finalizing', stage = 'finalizing', "
            "message = 'Finalizing media and transcription results', video_hash = ?, "
            "result_json = ?, result_srt = ?, result_vtt = ?, video_duration_seconds = ?, "
            "gpu_seconds = ?, final_media_key = ?, finalization_started_at = ?, "
            "updated_at = ?, last_seen = ? WHERE id = ? AND user_id = ? AND status = 'processing'",
            [
                video_hash, json.dumps(p.get("p_result_json")), p.get("p_result_srt"),
                p.get("p_result_vtt"), duration, p.get("p_gpu_seconds"), final_key, now,
                now, now, job_id, user_id,
            ],
        )
        self._db.conn.commit()
        return cur.rowcount > 0

    def _rpc_settle_finalizing_job(self) -> bool:
        p = self._params
        job_id = p["p_job_id"]
        user_id = p["p_user_id"]

        job = self._db.conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?", [job_id, user_id]
        ).fetchone()
        if job is None:
            return False
        if job["status"] == "completed":
            return True
        if (
            job["status"] != "finalizing"
            or job["quota_reservation_period"] is None
            or job["final_media_key"] is None
        ):
            return False

        period = job["quota_reservation_period"]
        source_key = job["gcs_path"]
        final_key = job["final_media_key"]
        now = _utcnow()

        # Snapshot exclusivity of the source key BEFORE this job's own
        # gcs_path moves to final_key below.
        ref_rows = self._db.conn.execute(
            "SELECT id, user_id FROM jobs WHERE gcs_path = ?", [source_key]
        ).fetchall()
        source_exclusive = (
            len(ref_rows) == 1 and ref_rows[0]["id"] == job_id and ref_rows[0]["user_id"] == user_id
        )

        self._db.conn.execute(
            "INSERT INTO user_usage_monthly (user_id, period_start) VALUES (?, ?) "
            "ON CONFLICT(user_id, period_start) DO NOTHING",
            [user_id, period],
        )
        self._db.conn.execute(
            "UPDATE user_usage_monthly SET transcription_seconds = transcription_seconds + ?, "
            "reserved_transcription_seconds = MAX(reserved_transcription_seconds - ?, 0), "
            "updated_at = ? WHERE user_id = ? AND period_start = ?",
            [max(job["video_duration_seconds"] or 0, 0), job["quota_reserved_seconds"], now, user_id, period],
        )

        cur = self._db.conn.execute(
            "UPDATE jobs SET status = 'completed', progress = 100, stage = 'completed', "
            "message = 'Transcription completed successfully', gcs_path = ?, "
            "quota_reserved_seconds = 0, quota_reservation_period = NULL, final_media_key = NULL, "
            "completed_at = ?, updated_at = ?, last_seen = ? "
            "WHERE id = ? AND user_id = ? AND status = 'finalizing'",
            [final_key, now, now, now, job_id, user_id],
        )
        self._db.conn.commit()
        if cur.rowcount == 0:
            return False

        if (
            source_key and source_key != final_key and source_exclusive
            and source_key.startswith(f"uploads/{user_id}/")
        ):
            self._db.conn.execute(
                "INSERT INTO media_delete_outbox (id, source_job_id, user_id, media_key, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(media_key) DO NOTHING",
                [str(uuid.uuid4()), job_id, user_id, source_key, now, now],
            )
            self._db.conn.commit()
        return True

    def _rpc_fail_job_secure(self) -> bool:
        p = self._params
        job_id = p["p_job_id"]
        job = self._db.conn.execute("SELECT * FROM jobs WHERE id = ?", [job_id]).fetchone()
        if job is None or not job["user_id"]:
            return False
        if job["status"] not in ("pending", "processing"):
            return False

        user_id = job["user_id"]
        if job["quota_reserved_seconds"] and job["quota_reservation_period"] is None:
            return False

        now = _utcnow()
        if job["quota_reserved_seconds"]:
            cur = self._db.conn.execute(
                "UPDATE user_usage_monthly SET reserved_transcription_seconds = "
                "MAX(reserved_transcription_seconds - ?, 0), updated_at = ? "
                "WHERE user_id = ? AND period_start = ?",
                [job["quota_reserved_seconds"], now, user_id, job["quota_reservation_period"]],
            )
            if cur.rowcount == 0:
                self._db.conn.commit()
                return False

        error_message = p.get("p_error_message")
        cur = self._db.conn.execute(
            "UPDATE jobs SET status = 'failed', stage = 'failed', message = ?, error_code = ?, "
            "error_message = ?, quota_reserved_seconds = 0, quota_reservation_period = NULL, "
            "failed_at = ?, updated_at = ?, last_seen = ? "
            "WHERE id = ? AND status IN ('pending', 'processing')",
            [error_message, p.get("p_error_code"), error_message, now, now, now, job_id],
        )
        self._db.conn.commit()
        return cur.rowcount > 0

    def _rpc_cancel_job_secure(self) -> bool:
        p = self._params
        job_id = p["p_job_id"]
        user_id = p["p_user_id"]
        job = self._db.conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?", [job_id, user_id]
        ).fetchone()
        if job is None or job["status"] not in ("pending", "processing"):
            return False
        if job["quota_reserved_seconds"] and job["quota_reservation_period"] is None:
            return False

        now = _utcnow()
        if job["quota_reserved_seconds"]:
            cur = self._db.conn.execute(
                "UPDATE user_usage_monthly SET reserved_transcription_seconds = "
                "MAX(reserved_transcription_seconds - ?, 0), updated_at = ? "
                "WHERE user_id = ? AND period_start = ?",
                [job["quota_reserved_seconds"], now, user_id, job["quota_reservation_period"]],
            )
            if cur.rowcount == 0:
                self._db.conn.commit()
                return False

        cur = self._db.conn.execute(
            "UPDATE jobs SET status = 'cancelled', stage = 'cancelled', "
            "message = 'Job cancelled by user', quota_reserved_seconds = 0, "
            "quota_reservation_period = NULL, cancelled_at = ?, updated_at = ?, last_seen = ? "
            "WHERE id = ? AND user_id = ? AND status IN ('pending', 'processing')",
            [now, now, now, job_id, user_id],
        )
        self._db.conn.commit()
        return cur.rowcount > 0

    def _rpc_retry_job_secure(self) -> List[Dict]:
        """008 semantics: bypasses the retry-limit for finalization_retries_exhausted
        jobs (resetting retry_count to 0), blocks retry while orphaned finalized
        media cleanup is still pending, and counts 'finalizing' as active."""
        p = self._params
        job_id = p["p_job_id"]
        user_id = p["p_user_id"]
        max_retries = p["p_max_retries"]

        job = self._db.conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?", [job_id, user_id]
        ).fetchone()
        if job is None:
            raise LocalAPIError("job_not_found")
        if job["status"] != "failed":
            raise LocalAPIError("job_not_retryable")

        retry_count = job["retry_count"] or 0
        exhausted = job["error_code"] == "finalization_retries_exhausted"
        if retry_count >= max_retries and not exhausted:
            raise LocalAPIError("max_retries_reached")

        final_key = job["final_media_key"]
        if final_key:
            outbox = self._db.conn.execute(
                "SELECT * FROM media_delete_outbox WHERE media_key = ?", [final_key]
            ).fetchone()
            if outbox is not None:
                if outbox["status"] != "completed":
                    raise LocalAPIError("finalization_cleanup_pending")
                self._db.conn.execute("DELETE FROM media_delete_outbox WHERE id = ?", [outbox["id"]])

        user_limit = p.get("p_user_concurrent_limit")
        if user_limit is not None:
            active = self._db.conn.execute(
                "SELECT COUNT(*) AS c FROM jobs WHERE user_id = ? "
                "AND status IN ('pending','processing','finalizing')",
                [user_id],
            ).fetchone()["c"]
            if active >= user_limit:
                raise LocalAPIError("user_concurrent_limit_reached")

        now = _utcnow()
        new_retry_count = 0 if exhausted else retry_count + 1
        cur = self._db.conn.execute(
            "UPDATE jobs SET status = 'pending', stage = 'queued', message = 'Job queued for retry', "
            "error_code = NULL, error_message = NULL, failed_at = NULL, result_json = NULL, "
            "result_srt = NULL, result_vtt = NULL, final_media_key = NULL, "
            "finalization_started_at = NULL, completed_at = NULL, quota_reserved_seconds = 0, "
            "quota_reservation_period = NULL, retry_count = ?, updated_at = ?, last_seen = ? "
            "WHERE id = ? AND user_id = ? AND status = 'failed'",
            [new_retry_count, now, now, job_id, user_id],
        )
        self._db.conn.commit()
        if cur.rowcount == 0:
            raise LocalAPIError("retry_compare_and_set_failed")
        row = self._db.conn.execute("SELECT * FROM jobs WHERE id = ?", [job_id]).fetchone()
        return [self._job_row_to_dict(row)]

    def _rpc_increment_monthly_usage(self):
        p = self._params
        user_id = p["p_user_id"]
        t_sec = max(int(p.get("p_transcription_seconds") or 0), 0)
        llm = max(int(p.get("p_llm_tokens") or 0), 0)
        chat = max(int(p.get("p_chat_messages") or 0), 0)
        period = self._current_period()
        now = _utcnow()

        cur = self._db.conn.execute(
            "UPDATE user_usage_monthly SET transcription_seconds = transcription_seconds + ?, "
            "llm_tokens = llm_tokens + ?, chat_messages = chat_messages + ?, updated_at = ? "
            "WHERE user_id = ? AND period_start = ?",
            [t_sec, llm, chat, now, user_id, period],
        )
        if cur.rowcount == 0:
            self._db.conn.execute(
                "INSERT INTO user_usage_monthly (user_id, period_start, transcription_seconds, "
                "llm_tokens, chat_messages, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                [user_id, period, t_sec, llm, chat, now],
            )
        self._db.conn.commit()
        return None

    def _rpc_claim_media_deletes(self) -> List[Dict]:
        p = self._params
        limit = max(1, min(int(p.get("p_limit") or 10), 100))
        outbox_id = p.get("p_outbox_id")

        if outbox_id:
            rows = self._db.conn.execute(
                "SELECT * FROM media_delete_outbox WHERE id = ? AND status = 'pending'", [outbox_id]
            ).fetchall()
        else:
            rows = self._db.conn.execute(
                "SELECT * FROM media_delete_outbox WHERE status = 'pending' ORDER BY created_at LIMIT ?",
                [limit],
            ).fetchall()

        now = _utcnow()
        claimed = []
        for row in rows:
            self._db.conn.execute(
                "UPDATE media_delete_outbox SET status = 'processing', claimed_at = ?, "
                "attempt_count = attempt_count + 1, updated_at = ? WHERE id = ?",
                [now, now, row["id"]],
            )
            updated = self._db.conn.execute(
                "SELECT * FROM media_delete_outbox WHERE id = ?", [row["id"]]
            ).fetchone()
            claimed.append(dict(updated))
        self._db.conn.commit()
        return claimed

    def _rpc_finish_media_delete(self) -> bool:
        p = self._params
        outbox_id = p["p_outbox_id"]
        error = p.get("p_error")
        now = _utcnow()
        if error is None:
            cur = self._db.conn.execute(
                "UPDATE media_delete_outbox SET status = 'completed', completed_at = ?, "
                "claimed_at = NULL, last_error = NULL, updated_at = ? WHERE id = ? AND status = 'processing'",
                [now, now, outbox_id],
            )
        else:
            cur = self._db.conn.execute(
                "UPDATE media_delete_outbox SET status = 'pending', completed_at = NULL, "
                "claimed_at = NULL, last_error = ?, updated_at = ? WHERE id = ? AND status = 'processing'",
                [str(error)[:2000], now, outbox_id],
            )
        self._db.conn.commit()
        return cur.rowcount > 0

    def _rpc_delete_job_permanent_secure(self) -> List[Dict]:
        p = self._params
        job_id = p["p_job_id"]
        user_id = p["p_user_id"]
        if not job_id or not user_id:
            raise LocalAPIError("invalid deletion identity")

        job = self._db.conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?", [job_id, user_id]
        ).fetchone()
        if job is None:
            return [{"deleted": False, "outbox_id": None, "media_key": None, "error_code": "job_not_found"}]
        if job["status"] not in ("completed", "failed", "cancelled"):
            return [{
                "deleted": False, "outbox_id": None,
                "media_key": job["gcs_path"], "error_code": "job_not_terminal",
            }]

        now = _utcnow()
        outbox_id = None
        gcs_path = job["gcs_path"]
        if gcs_path:
            ref_rows = self._db.conn.execute(
                "SELECT id, user_id FROM jobs WHERE gcs_path = ?", [gcs_path]
            ).fetchall()
            exclusive = (
                len(ref_rows) == 1 and ref_rows[0]["id"] == job_id and ref_rows[0]["user_id"] == user_id
            )
            owner_scoped = (
                gcs_path.startswith(f"uploads/{user_id}/") or gcs_path.startswith(f"processed/{user_id}/")
            ) and ".." not in gcs_path and "\\" not in gcs_path
            if exclusive and owner_scoped:
                existing = self._db.conn.execute(
                    "SELECT id FROM media_delete_outbox WHERE media_key = ?", [gcs_path]
                ).fetchone()
                if existing is None:
                    outbox_id = str(uuid.uuid4())
                    self._db.conn.execute(
                        "INSERT INTO media_delete_outbox (id, source_job_id, user_id, media_key, "
                        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        [outbox_id, job_id, user_id, gcs_path, now, now],
                    )
                else:
                    outbox_id = existing["id"]

        if job["quota_reserved_seconds"]:
            if job["quota_reservation_period"] is None:
                raise LocalAPIError("job quota reservation is missing its period")
            cur = self._db.conn.execute(
                "UPDATE user_usage_monthly SET reserved_transcription_seconds = "
                "MAX(reserved_transcription_seconds - ?, 0), updated_at = ? "
                "WHERE user_id = ? AND period_start = ?",
                [job["quota_reserved_seconds"], now, user_id, job["quota_reservation_period"]],
            )
            if cur.rowcount == 0:
                raise LocalAPIError("job quota ledger row is missing")

        self._db.conn.execute("DELETE FROM jobs WHERE id = ? AND user_id = ?", [job_id, user_id])
        self._db.conn.commit()
        return [{"deleted": True, "outbox_id": outbox_id, "media_key": gcs_path, "error_code": None}]

    def _rpc_claim_stale_finalizing_job(self) -> List[Dict]:
        p = self._params
        cutoff = p["p_cutoff"]
        max_retries = max(int(p.get("p_max_retries") or 0), 0)

        job = self._db.conn.execute(
            "SELECT * FROM jobs WHERE status = 'finalizing' AND last_seen < ? ORDER BY last_seen LIMIT 1",
            [cutoff],
        ).fetchone()
        if job is None:
            return []

        now = _utcnow()
        retry_count = job["retry_count"] or 0
        if retry_count >= max_retries:
            final_key = job["final_media_key"]
            if final_key and final_key.startswith(f"processed/{job['user_id']}/"):
                refs = self._db.conn.execute(
                    "SELECT COUNT(*) AS c FROM jobs WHERE gcs_path = ?", [final_key]
                ).fetchone()["c"]
                if refs == 0:
                    existing = self._db.conn.execute(
                        "SELECT id FROM media_delete_outbox WHERE media_key = ?", [final_key]
                    ).fetchone()
                    if existing is None:
                        self._db.conn.execute(
                            "INSERT INTO media_delete_outbox (id, source_job_id, user_id, media_key, "
                            "available_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            [str(uuid.uuid4()), job["id"], job["user_id"], final_key, now, now, now],
                        )
            if job["quota_reserved_seconds"]:
                self._db.conn.execute(
                    "UPDATE user_usage_monthly SET reserved_transcription_seconds = "
                    "MAX(reserved_transcription_seconds - ?, 0), updated_at = ? "
                    "WHERE user_id = ? AND period_start = ?",
                    [job["quota_reserved_seconds"], now, job["user_id"], job["quota_reservation_period"]],
                )
            self._db.conn.execute(
                "UPDATE jobs SET status = 'failed', stage = 'failed', "
                "message = 'Media finalization could not be recovered. Retry manually.', "
                "error_code = 'finalization_retries_exhausted', "
                "error_message = 'Media finalization retries exhausted', "
                "quota_reserved_seconds = 0, quota_reservation_period = NULL, "
                "failed_at = ?, updated_at = ?, last_seen = ? WHERE id = ? AND status = 'finalizing'",
                [now, now, now, job["id"]],
            )
            self._db.conn.commit()
            return [{"job_id": job["id"], "action": "failed", "retry_count": retry_count}]

        new_retry_count = retry_count + 1
        self._db.conn.execute(
            "UPDATE jobs SET retry_count = ?, message = 'Recovering interrupted media finalization', "
            "updated_at = ?, last_seen = ? WHERE id = ? AND status = 'finalizing'",
            [new_retry_count, now, now, job["id"]],
        )
        self._db.conn.commit()
        return [{"job_id": job["id"], "action": "redispatch", "retry_count": new_retry_count}]

    def _rpc_settle_completed_job(self) -> bool:
        """No live caller today (superseded by begin/settle_finalizing_job), but
        implemented for parity in case anything re-wires onto it."""
        p = self._params
        job_id = p["p_job_id"]
        user_id = p["p_user_id"]
        job = self._db.conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?", [job_id, user_id]
        ).fetchone()
        if job is None or job["status"] != "processing" or job["quota_reservation_period"] is None:
            return False

        period = job["quota_reservation_period"]
        now = _utcnow()
        seconds = max(int(p.get("p_video_duration_seconds") or 0), 0)

        self._db.conn.execute(
            "INSERT INTO user_usage_monthly (user_id, period_start) VALUES (?, ?) "
            "ON CONFLICT(user_id, period_start) DO NOTHING",
            [user_id, period],
        )
        self._db.conn.execute(
            "UPDATE user_usage_monthly SET transcription_seconds = transcription_seconds + ?, "
            "reserved_transcription_seconds = MAX(reserved_transcription_seconds - ?, 0), updated_at = ? "
            "WHERE user_id = ? AND period_start = ?",
            [seconds, job["quota_reserved_seconds"], now, user_id, period],
        )
        self._db.conn.execute(
            "UPDATE jobs SET status = 'completed', progress = 100, stage = 'completed', "
            "message = 'Transcription completed successfully', video_hash = ?, result_json = ?, "
            "result_srt = ?, result_vtt = ?, video_duration_seconds = ?, gpu_seconds = ?, "
            "gcs_path = COALESCE(?, gcs_path), quota_reserved_seconds = 0, "
            "quota_reservation_period = NULL, completed_at = ?, updated_at = ?, last_seen = ? "
            "WHERE id = ?",
            [
                p.get("p_video_hash"), json.dumps(p.get("p_result_json")), p.get("p_result_srt"),
                p.get("p_result_vtt"), seconds, p.get("p_gpu_seconds"), p.get("p_gcs_path"),
                now, now, now, job_id,
            ],
        )
        self._db.conn.commit()
        return True

    def _rpc_release_job_quota_reservation(self) -> bool:
        """No live caller today, implemented for parity."""
        p = self._params
        job_id = p["p_job_id"]
        job = self._db.conn.execute("SELECT * FROM jobs WHERE id = ?", [job_id]).fetchone()
        if job is None or not job["user_id"]:
            return False
        user_id = job["user_id"]
        now = _utcnow()

        if not job["quota_reserved_seconds"]:
            self._db.conn.execute(
                "UPDATE jobs SET quota_reservation_period = NULL WHERE id = ?", [job_id]
            )
            self._db.conn.commit()
            return True

        if job["quota_reservation_period"] is None:
            return False

        cur = self._db.conn.execute(
            "UPDATE user_usage_monthly SET reserved_transcription_seconds = "
            "MAX(reserved_transcription_seconds - ?, 0), updated_at = ? "
            "WHERE user_id = ? AND period_start = ?",
            [job["quota_reserved_seconds"], now, user_id, job["quota_reservation_period"]],
        )
        if cur.rowcount == 0:
            self._db.conn.commit()
            return False

        self._db.conn.execute(
            "UPDATE jobs SET quota_reserved_seconds = 0, quota_reservation_period = NULL WHERE id = ?",
            [job_id],
        )
        self._db.conn.commit()
        return True

    def _rpc_search_images_by_embedding(self) -> List[Dict]:
        p = self._params
        query = p["query_embedding"]
        video_hash = p["target_video_hash"]
        match_count = int(p.get("match_count") or 5)
        speaker_filter = p.get("speaker_filter")

        sql = (
            "SELECT id, video_hash, segment_id, start_time, end_time, speaker, "
            "screenshot_url, embedding FROM image_embeddings WHERE video_hash = ?"
        )
        params: List[Any] = [video_hash]
        if speaker_filter is not None:
            sql += " AND speaker = ?"
            params.append(speaker_filter)

        scored = []
        for row in self._db.conn.execute(sql, params).fetchall():
            row = dict(row)
            embedding = json.loads(row.pop("embedding"))
            row["similarity"] = _cosine(query, embedding)
            scored.append(row)
        scored.sort(key=lambda r: r["similarity"], reverse=True)
        return scored[:match_count]

    def _rpc_match_faces_by_embedding(self) -> List[Dict]:
        p = self._params
        query = p["query_embedding"]
        video_hash = p["target_video_hash"]
        threshold = float(p.get("similarity_threshold") or 0.5)
        match_limit = int(p.get("match_limit") or 500)

        scored = []
        rows = self._db.conn.execute(
            "SELECT image_embedding_id, start_time, end_time, face_embedding "
            "FROM image_face_presence WHERE video_hash = ?",
            [video_hash],
        ).fetchall()
        for row in rows:
            row = dict(row)
            embedding = json.loads(row.pop("face_embedding"))
            similarity = _cosine(query, embedding)
            if similarity >= threshold:
                row["similarity"] = similarity
                scored.append(row)
        scored.sort(key=lambda r: r["similarity"], reverse=True)
        return scored[:match_limit]

    def _rpc_search_speaker_voiceprints_by_embedding(self) -> List[Dict]:
        p = self._params
        query = p["query_embedding"]
        user_id = p["p_user_id"]
        match_count = int(p.get("match_count") or 1)

        scored = []
        rows = self._db.conn.execute(
            "SELECT speaker_name, samples_count, embedding FROM speaker_voiceprints "
            "WHERE user_id = ?",
            [user_id],
        ).fetchall()
        for row in rows:
            row = dict(row)
            embedding = json.loads(row.pop("embedding"))
            row["similarity"] = _cosine(query, embedding)
            scored.append(row)
        scored.sort(key=lambda r: r["similarity"], reverse=True)
        return scored[:match_count]

    def _rpc_search_transcript_chunks_by_embedding(self) -> List[Dict]:
        p = self._params
        query = p["query_embedding"]
        user_id = p["p_user_id"]
        video_hash = p["target_video_hash"]
        match_count = int(p.get("match_count") or 5)
        index_config = p.get("target_index_config") or "chunk_size_3"

        scored = []
        rows = self._db.conn.execute(
            "SELECT id, video_hash, chunk_index, start_time, end_time, start_timestamp, "
            "end_timestamp, speaker, segment_count, chunk_text, embedding "
            "FROM transcript_embeddings WHERE user_id = ? AND video_hash = ? AND index_config = ?",
            [user_id, video_hash, index_config],
        ).fetchall()
        for row in rows:
            row = dict(row)
            embedding = json.loads(row.pop("embedding"))
            row["similarity"] = _cosine(query, embedding)
            scored.append(row)
        scored.sort(key=lambda r: r["similarity"], reverse=True)
        return scored[:match_count]

    def _rpc_search_audio_events_by_embedding(self) -> List[Dict]:
        p = self._params
        query = p["query_embedding"]
        user_id = p["p_user_id"]
        video_hash = p["target_video_hash"]
        match_count = int(p.get("match_count") or 5)

        scored = []
        rows = self._db.conn.execute(
            "SELECT id, video_hash, segment_id, start_time, end_time, speaker, has_speech, "
            "primary_event, speech_emotion, description, embedding "
            "FROM audio_event_embeddings WHERE user_id = ? AND video_hash = ?",
            [user_id, video_hash],
        ).fetchall()
        for row in rows:
            row = dict(row)
            embedding = json.loads(row.pop("embedding"))
            row["has_speech"] = bool(row["has_speech"])
            row["similarity"] = _cosine(query, embedding)
            scored.append(row)
        scored.sort(key=lambda r: r["similarity"], reverse=True)
        return scored[:match_count]

    def _rpc_search_images_by_caption_embedding(self) -> List[Dict]:
        p = self._params
        query = p["query_embedding"]
        video_hash = p["target_video_hash"]
        match_count = int(p.get("match_count") or 5)

        scored = []
        rows = self._db.conn.execute(
            "SELECT id, video_hash, segment_id, start_time, end_time, speaker, "
            "screenshot_url, caption, caption_embedding FROM image_embeddings "
            "WHERE video_hash = ? AND caption_embedding IS NOT NULL",
            [video_hash],
        ).fetchall()
        for row in rows:
            row = dict(row)
            embedding = json.loads(row.pop("caption_embedding"))
            row["similarity"] = _cosine(query, embedding)
            scored.append(row)
        scored.sort(key=lambda r: r["similarity"], reverse=True)
        return scored[:match_count]

    def _rpc_search_images_by_caption_sentences(self) -> List[Dict]:
        p = self._params
        query = p["query_embedding"]
        video_hash = p["target_video_hash"]
        match_count = int(p.get("match_count") or 5)

        # Per-image max over sentence similarities
        best: Dict[str, float] = {}
        rows = self._db.conn.execute(
            "SELECT image_embedding_id, embedding FROM image_caption_sentences "
            "WHERE video_hash = ?",
            [video_hash],
        ).fetchall()
        for row in rows:
            sim = _cosine(query, json.loads(row["embedding"]))
            image_id = row["image_embedding_id"]
            if sim > best.get(image_id, -1.0):
                best[image_id] = sim

        top = sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:match_count]
        results = []
        for image_id, sim in top:
            img = self._db.conn.execute(
                "SELECT id, video_hash, segment_id, start_time, end_time, speaker, "
                "screenshot_url, caption FROM image_embeddings WHERE id = ?",
                [image_id],
            ).fetchone()
            if img:
                row = dict(img)
                row["similarity"] = sim
                results.append(row)
        return results

    def _rpc_videos_missing_captions(self) -> List[Dict]:
        limit = int(self._params.get("batch_limit") or 10)
        rows = self._db.conn.execute(
            "SELECT DISTINCT video_hash FROM image_embeddings "
            "WHERE caption IS NULL ORDER BY video_hash LIMIT ?",
            [limit],
        ).fetchall()
        return [{"video_hash": r["video_hash"]} for r in rows]

    def _rpc_videos_missing_face_presence(self) -> List[Dict]:
        limit = int(self._params.get("batch_limit") or 10)
        rows = self._db.conn.execute(
            "SELECT DISTINCT ie.video_hash FROM image_embeddings ie "
            "WHERE NOT EXISTS (SELECT 1 FROM image_face_presence ifp "
            "WHERE ifp.video_hash = ie.video_hash) "
            "ORDER BY ie.video_hash LIMIT ?",
            [limit],
        ).fetchall()
        return [{"video_hash": r["video_hash"]} for r in rows]


class _LocalAuthStub:
    """client.auth is never used in LOCAL_MODE (auth middleware short-circuits);
    fail loudly if something reaches for it anyway."""

    def __getattr__(self, name):
        raise RuntimeError(
            f"Supabase auth.{name} is not available in LOCAL_MODE - "
            "auth is bypassed with a fixed local user."
        )


class LocalSupabaseClient:
    """SQLite-backed stand-in for supabase-py's Client."""

    def __init__(self, db_path: Optional[str] = None):
        data_dir = os.path.abspath(settings.LOCAL_DATA_DIR)
        os.makedirs(data_dir, exist_ok=True)
        self._db_path = db_path or os.path.join(data_dir, "local.db")
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=15000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._table_columns_cache: Dict[str, set] = {}
        self.auth = _LocalAuthStub()
        self._init_schema()
        self._seed()
        print(f"[LocalDB] initialized at {self._db_path}")

    # Columns added to local_schema.sql after the first release. CREATE TABLE
    # IF NOT EXISTS won't alter existing DBs, so patch them explicitly here.
    _COLUMN_MIGRATIONS = [
        ("image_embeddings", "user_id", "TEXT"),
        ("image_embeddings", "caption", "TEXT"),
        ("image_embeddings", "caption_embedding", "TEXT"),
        ("jobs", "quota_reserved_seconds", "INTEGER NOT NULL DEFAULT 0"),
        ("jobs", "quota_reservation_period", "TEXT"),
        ("jobs", "upload_intent_id", "TEXT"),
        ("jobs", "final_media_key", "TEXT"),
        ("jobs", "finalization_started_at", "TEXT"),
        ("user_usage_monthly", "reserved_transcription_seconds", "INTEGER NOT NULL DEFAULT 0"),
        ("transcript_embeddings", "index_config", "TEXT NOT NULL DEFAULT 'chunk_size_3'"),
    ]

    def _init_schema(self):
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "sql",
            "local_schema.sql",
        )
        with open(schema_path) as f:
            with self.lock:
                self.conn.executescript(f.read())
                for table, col, decl in self._COLUMN_MIGRATIONS:
                    cols = {
                        r["name"]
                        for r in self.conn.execute(f'PRAGMA table_info("{table}")')
                    }
                    if col not in cols:
                        self.conn.execute(
                            f'ALTER TABLE "{table}" ADD COLUMN "{col}" {decl}'
                        )
                        print(f"[LocalDB] migrated: {table}.{col}")
                self._migrate_image_embeddings_unique_constraint()
                self._migrate_transcript_embeddings_unique_constraint()
                self.conn.commit()

    def _migrate_image_embeddings_unique_constraint(self):
        """image_embeddings originally had UNIQUE(video_hash, segment_id); owner
        scoping later widened the app's on_conflict key to (user_id, video_hash,
        segment_id). SQLite can't ALTER a UNIQUE constraint, so rebuild the table
        when an old-shape DB is detected (upsert fails with 'ON CONFLICT clause
        does not match any PRIMARY KEY or UNIQUE constraint' otherwise)."""
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='image_embeddings'"
        ).fetchone()
        if row is None or "UNIQUE(user_id, video_hash, segment_id)" in (row["sql"] or ""):
            return
        self.conn.executescript(
            """
            ALTER TABLE image_embeddings RENAME TO image_embeddings_old;
            CREATE TABLE image_embeddings (
                id TEXT PRIMARY KEY,
                video_hash TEXT NOT NULL,
                segment_id TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                speaker TEXT,
                screenshot_url TEXT NOT NULL,
                embedding TEXT NOT NULL,
                caption TEXT,
                caption_embedding TEXT,
                user_id TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(user_id, video_hash, segment_id)
            );
            INSERT OR IGNORE INTO image_embeddings
                SELECT id, video_hash, segment_id, start_time, end_time, speaker,
                       screenshot_url, embedding, caption, caption_embedding,
                       user_id, created_at, updated_at
                FROM image_embeddings_old;
            DROP TABLE image_embeddings_old;
            CREATE INDEX IF NOT EXISTS idx_image_embeddings_video_hash ON image_embeddings(video_hash);
            """
        )
        print("[LocalDB] migrated: image_embeddings UNIQUE(user_id, video_hash, segment_id)")

    def _migrate_transcript_embeddings_unique_constraint(self):
        """transcript_embeddings originally had UNIQUE(user_id, video_hash,
        chunk_index); retrieval-index experiments widened the app's on_conflict
        key to (user_id, video_hash, index_config, chunk_index) so multiple
        chunk-size configs can coexist per video. SQLite can't ALTER a UNIQUE
        constraint, so rebuild the table when an old-shape DB is detected
        (upsert fails with 'ON CONFLICT clause does not match any PRIMARY KEY
        or UNIQUE constraint' otherwise)."""
        row = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='transcript_embeddings'"
        ).fetchone()
        if row is None or "UNIQUE(user_id, video_hash, index_config, chunk_index)" in (row["sql"] or ""):
            return
        self.conn.executescript(
            """
            ALTER TABLE transcript_embeddings RENAME TO transcript_embeddings_old;
            CREATE TABLE transcript_embeddings (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                video_hash TEXT NOT NULL,
                index_config TEXT NOT NULL DEFAULT 'chunk_size_3',
                chunk_index INTEGER NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                start_timestamp TEXT NOT NULL,
                end_timestamp TEXT NOT NULL,
                speaker TEXT,
                segment_count INTEGER NOT NULL DEFAULT 1,
                chunk_text TEXT NOT NULL,
                embedding TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(user_id, video_hash, index_config, chunk_index)
            );
            INSERT OR IGNORE INTO transcript_embeddings
                SELECT id, user_id, video_hash,
                       COALESCE(index_config, 'chunk_size_3'), chunk_index,
                       start_time, end_time, start_timestamp, end_timestamp,
                       speaker, segment_count, chunk_text, embedding,
                       created_at, updated_at
                FROM transcript_embeddings_old;
            DROP TABLE transcript_embeddings_old;
            CREATE INDEX IF NOT EXISTS idx_transcript_embeddings_owner_video ON transcript_embeddings(user_id, video_hash);
            """
        )
        print(
            "[LocalDB] migrated: transcript_embeddings "
            "UNIQUE(user_id, video_hash, index_config, chunk_index)"
        )

    def _seed(self):
        with self.lock:
            existing = self.conn.execute(
                "SELECT id FROM user_profiles WHERE id = ?", [LOCAL_USER_ID]
            ).fetchone()
            if not existing:
                now = _utcnow()
                # default_llm_provider left NULL so settings.DEFAULT_LLM_PROVIDER
                # (e.g. Ollama) wins instead of a hardcoded cloud provider.
                self.conn.execute(
                    "INSERT INTO user_profiles "
                    "(id, email, display_name, email_verified, is_admin, "
                    " subscription_plan, created_at, updated_at) "
                    "VALUES (?, ?, ?, 1, 1, 'free', ?, ?)",
                    [LOCAL_USER_ID, LOCAL_USER_EMAIL, "Local User", now, now],
                )
                self.conn.commit()
                print(f"[LocalDB] seeded local admin user {LOCAL_USER_EMAIL}")

    def table_columns(self, table: str) -> set:
        if table not in self._table_columns_cache:
            rows = self.conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            if not rows:
                raise LocalAPIError(f"Unknown table in LOCAL_MODE: {table}")
            self._table_columns_cache[table] = {r["name"] for r in rows}
        return self._table_columns_cache[table]

    @property
    def encryption_key_hex(self) -> str:
        if settings.LOCAL_ENCRYPTION_KEY:
            return settings.LOCAL_ENCRYPTION_KEY
        key_path = os.path.join(os.path.abspath(settings.LOCAL_DATA_DIR), "encryption.key")
        if os.path.exists(key_path):
            with open(key_path) as f:
                return f.read().strip()
        key = secrets.token_hex(32)
        with open(key_path, "w") as f:
            f.write(key)
        os.chmod(key_path, 0o600)
        print(f"[LocalDB] generated BYOK encryption key at {key_path}")
        return key

    # ── supabase-py Client surface ───────────────────────────────────────
    def table(self, name: str) -> _TableQuery:
        return _TableQuery(self, name)

    # supabase-py alias
    def from_(self, name: str) -> _TableQuery:
        return _TableQuery(self, name)

    def rpc(self, fn: str, params: Optional[Dict] = None) -> _RpcQuery:
        return _RpcQuery(self, fn, params)


_local_client: Optional[LocalSupabaseClient] = None
_client_lock = threading.Lock()


def get_local_client() -> LocalSupabaseClient:
    global _local_client
    if _local_client is None:
        with _client_lock:
            if _local_client is None:
                _local_client = LocalSupabaseClient()
    return _local_client
