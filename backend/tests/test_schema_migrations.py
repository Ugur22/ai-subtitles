import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend" / "sql" / "migrations"
CHECK = REPO / "infra" / "scripts" / "check_migrations.sh"
FIRST_TRACKED = 23


def _forward_migrations():
    return sorted(
        f for f in MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql") if not f.name.endswith("_rollback.sql")
    )


def _repo_versions():
    return sorted({f.name[:3] for f in _forward_migrations()})


def test_023_backfills_every_earlier_migration_and_itself():
    sql = (MIGRATIONS / "023_schema_migrations.sql").read_text(encoding="utf-8")
    backfill = sql[sql.index("INSERT INTO public.schema_migrations"):]
    recorded = set(re.findall(r"\('(\d{3})'\)", backfill))
    assert recorded == {v for v in _repo_versions() if int(v) <= FIRST_TRACKED}


def test_anon_can_only_read_schema_migrations():
    sql = (MIGRATIONS / "023_schema_migrations.sql").read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "GRANT SELECT ON public.schema_migrations TO anon;" in sql
    assert re.search(r"FOR SELECT TO anon USING \(true\)", sql)
    assert not re.search(r"GRANT (INSERT|UPDATE|DELETE|ALL)[^;]*schema_migrations", sql)


@pytest.mark.parametrize(
    "migration",
    [f for f in _forward_migrations() if int(f.name[:3]) > FIRST_TRACKED],
    ids=lambda f: f.name,
)
def test_new_migrations_record_themselves_and_have_a_rollback(migration):
    version = migration.name[:3]
    sql = migration.read_text(encoding="utf-8")
    assert f"INSERT INTO public.schema_migrations (version) VALUES ('{version}')" in sql, (
        "end the migration with its schema_migrations row (see 023_schema_migrations.sql)"
    )
    assert sql.rstrip().endswith("COMMIT;")
    assert (MIGRATIONS / migration.name.replace(".sql", "_rollback.sql")).exists()


def _run_check(tmp_path, status, body, key="anon-key"):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "curl"
    stub.write_text(f"#!/bin/sh\nprintf '%s\\n%s' '{body}' '{status}'\n")
    stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    env.pop("SUPABASE_ANON_KEY", None)
    if key:
        env["SUPABASE_ANON_KEY"] = key
    return subprocess.run(
        ["bash", str(CHECK), "https://example.supabase.co"],
        env=env, capture_output=True, text=True, cwd=tmp_path,
    )


def _rows(versions):
    return "[" + ",".join(f'{{"version":"{v}"}}' for v in versions) + "]"


def test_check_passes_when_every_repo_migration_is_applied(tmp_path):
    result = _run_check(tmp_path, 200, _rows(_repo_versions()))
    assert result.returncode == 0, result.stderr
    assert f"latest {_repo_versions()[-1]}" in result.stdout


def test_check_names_the_unapplied_migrations(tmp_path):
    applied = _repo_versions()[:-1]
    result = _run_check(tmp_path, 200, _rows(applied))
    assert result.returncode == 1
    newest = next(f.name for f in _forward_migrations() if f.name.startswith(_repo_versions()[-1]))
    assert f"backend/sql/migrations/{newest}" in result.stderr
    assert f"latest applied: {applied[-1]}" in result.stderr


def test_check_explains_a_missing_table(tmp_path):
    body = '{"code":"PGRST205","message":"Could not find the table public.schema_migrations"}'
    result = _run_check(tmp_path, 404, body)
    assert result.returncode == 1
    assert "Apply backend/sql/migrations/023_schema_migrations.sql first" in result.stderr


@pytest.mark.skipif(
    any((REPO / "frontend" / name).exists() for name in (".env", ".env.local")),
    reason="a local frontend env file supplies the key",
)
def test_check_requires_the_anon_key(tmp_path):
    result = _run_check(tmp_path, 200, "[]", key=None)
    assert result.returncode == 1
    assert "SUPABASE_ANON_KEY is not set" in result.stderr
