import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

from services.encryption import decrypt_api_key, encrypt_api_key

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "rotate_encryption_key.py"

OLD_KEY = bytes(range(32))
NEW_KEY = bytes(range(32, 64))
OTHER_KEY = bytes(range(64, 96))


def _load_script():
    spec = importlib.util.spec_from_file_location("rotate_encryption_key", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Query:
    def __init__(self, client):
        self.client = client
        self.filters = {}
        self.update_values = None
        self.window = None

    def select(self, _columns):
        return self

    def order(self, _column):
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def update(self, values):
        self.update_values = values
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def execute(self):
        rows = self.client.rows
        if self.update_values is None:
            start, end = self.window
            return SimpleNamespace(data=[dict(row) for row in rows[start:end + 1]])
        matched = [
            row for row in rows
            if all(row[column] == value for column, value in self.filters.items())
        ]
        for row in matched:
            row.update(self.update_values)
            self.client.writes += 1
        return SimpleNamespace(data=[dict(row) for row in matched])


class _Client:
    def __init__(self, rows):
        self.rows = rows
        self.writes = 0

    def table(self, name):
        assert name == "user_api_keys"
        return _Query(self)


def _rows():
    return [
        {"id": "a", "encrypted_key": encrypt_api_key("sk-old-one", OLD_KEY)},
        {"id": "b", "encrypted_key": encrypt_api_key("sk-old-two", OLD_KEY)},
        {"id": "c", "encrypted_key": encrypt_api_key("sk-already-new", NEW_KEY)},
    ]


def test_dry_run_reports_without_writing():
    script = _load_script()
    client = _Client(_rows())
    before = [row["encrypted_key"] for row in client.rows]

    report = script.rotate_rows(client, OLD_KEY, NEW_KEY, apply=False)

    assert (report.total, report.rotated, report.already_rotated) == (3, 2, 1)
    assert client.writes == 0
    assert [row["encrypted_key"] for row in client.rows] == before


def test_apply_reencrypts_and_second_run_is_a_noop():
    script = _load_script()
    client = _Client(_rows())

    first = script.rotate_rows(client, OLD_KEY, NEW_KEY, apply=True)
    assert first.rotated == 2 and first.ok
    assert [decrypt_api_key(row["encrypted_key"], NEW_KEY) for row in client.rows] == [
        "sk-old-one", "sk-old-two", "sk-already-new",
    ]

    writes_after_first = client.writes
    second = script.rotate_rows(client, OLD_KEY, NEW_KEY, apply=True)
    assert (second.rotated, second.already_rotated) == (0, 3)
    assert client.writes == writes_after_first


def test_undecryptable_rows_are_left_alone_and_fail_the_run():
    script = _load_script()
    foreign = encrypt_api_key("sk-foreign", OTHER_KEY)
    client = _Client(_rows() + [{"id": "d", "encrypted_key": foreign}])

    report = script.rotate_rows(client, OLD_KEY, NEW_KEY, apply=True)

    assert report.undecryptable == ["d"]
    assert not report.ok
    assert client.rows[3]["encrypted_key"] == foreign
    assert report.rotated == 2


def test_row_resaved_during_the_run_is_not_overwritten():
    script = _load_script()
    client = _Client(_rows())
    resaved = encrypt_api_key("sk-resaved", NEW_KEY)
    original_fetch = script._fetch_rows

    def fetch_then_resave(target):
        rows = original_fetch(target)
        target.rows[0]["encrypted_key"] = resaved
        return rows

    script._fetch_rows = fetch_then_resave
    report = script.rotate_rows(client, OLD_KEY, NEW_KEY, apply=True)

    assert report.changed_concurrently == 1
    assert client.rows[0]["encrypted_key"] == resaved


def test_no_key_material_is_tracked_and_local_data_is_ignored():
    ignore_rules = (BACKEND / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "local_data/" in ignore_rules
    assert "*.key" in ignore_rules

    tracked = subprocess.run(
        ["git", "ls-files", "--", "*.key", "*.pem", "backend/local_data"],
        cwd=BACKEND.parent, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert tracked == []


def test_encryption_key_is_only_loaded_from_vault():
    source = (BACKEND / "services" / "encryption.py").read_text(encoding="utf-8")
    assert 'rpc("get_vault_secret"' in source
    assert "open(" not in source
    assert "os.getenv" not in source and "os.environ" not in source
