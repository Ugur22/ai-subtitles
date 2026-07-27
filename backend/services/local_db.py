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
}

# Columns that postgrest returns as true/false/null — SQLite stores 0/1
_BOOL_COLUMNS = {
    "user_profiles": {"email_verified", "is_admin"},
    "user_api_keys": {"is_valid"},
    "password_resets": {"used"},
}

# Columns that get a generated UUID on insert when absent (pg gen_random_uuid())
_UUID_DEFAULTS = {
    "jobs": ("id", "access_token"),
    "invite_codes": ("id", "code"),
    "image_caption_sentences": ("id",),
    "user_usage_monthly": (),
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
                self.conn.commit()

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
