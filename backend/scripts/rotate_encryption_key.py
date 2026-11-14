"""Re-encrypt every stored user API key from the old encryption key to a new one.

Dry-run by default; pass --apply to write. Safe to re-run: rows already under
the new key are detected and skipped. Runbook: docs/GCP_OPERATIONS.md.

    OLD_ENCRYPTION_KEY_HEX=... NEW_ENCRYPTION_KEY_HEX=... \
        python scripts/rotate_encryption_key.py            # dry run
    OLD_ENCRYPTION_KEY_HEX=... NEW_ENCRYPTION_KEY_HEX=... \
        python scripts/rotate_encryption_key.py --apply
"""

import argparse
import contextlib
import io
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.encryption import decrypt_api_key, encrypt_api_key  # noqa: E402

TABLE = "user_api_keys"
PAGE_SIZE = 500


@dataclass
class RotationReport:
    total: int = 0
    rotated: int = 0
    already_rotated: int = 0
    changed_concurrently: int = 0
    undecryptable: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.undecryptable and not self.changed_concurrently


def _try_decrypt(ciphertext: str, key: bytes) -> Optional[str]:
    # decrypt_api_key logs every failure; probing with the wrong key is expected here.
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            return decrypt_api_key(ciphertext, key)
        except Exception:
            return None


def _load_key(env_name: str) -> bytes:
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise SystemExit(f"{env_name} is not set")
    try:
        key = bytes.fromhex(value)
    except ValueError:
        raise SystemExit(f"{env_name} is not valid hex") from None
    if len(key) != 32:
        raise SystemExit(f"{env_name} must be 32 bytes (64 hex characters)")
    return key


def _fetch_rows(client) -> List[dict]:
    rows: List[dict] = []
    offset = 0
    while True:
        page = (
            client.table(TABLE)
            .select("id,encrypted_key")
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        ).data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def rotate_rows(client, old_key: bytes, new_key: bytes, apply: bool) -> RotationReport:
    report = RotationReport()
    for row in _fetch_rows(client):
        report.total += 1
        ciphertext = row["encrypted_key"]

        # GCM authenticates the ciphertext, so a successful decrypt identifies the key.
        if _try_decrypt(ciphertext, new_key) is not None:
            report.already_rotated += 1
            continue

        plaintext = _try_decrypt(ciphertext, old_key)
        if plaintext is None:
            report.undecryptable.append(row["id"])
            continue

        if not apply:
            report.rotated += 1
            continue

        # Matching on the old ciphertext keeps a key the user re-saved mid-run intact.
        updated = (
            client.table(TABLE)
            .update({"encrypted_key": encrypt_api_key(plaintext, new_key)})
            .eq("id", row["id"])
            .eq("encrypted_key", ciphertext)
            .execute()
        ).data
        if updated:
            report.rotated += 1
        else:
            report.changed_concurrently += 1
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    args = parser.parse_args(argv)

    old_key = _load_key("OLD_ENCRYPTION_KEY_HEX")
    new_key = _load_key("NEW_ENCRYPTION_KEY_HEX")
    if old_key == new_key:
        raise SystemExit("Old and new keys are identical")

    from services.supabase_service import SupabaseService

    report = rotate_rows(SupabaseService.get_client(), old_key, new_key, args.apply)

    mode = "APPLY" if args.apply else "DRY RUN"
    verb = "rotated" if args.apply else "would rotate"
    print(f"[{mode}] {report.total} rows: {verb} {report.rotated}, "
          f"already on new key {report.already_rotated}, "
          f"changed during run {report.changed_concurrently}, "
          f"undecryptable {len(report.undecryptable)}")
    for row_id in report.undecryptable:
        print(f"  undecryptable with either key: {TABLE}.id={row_id}")
    if report.changed_concurrently:
        print("Some rows changed while the script ran; run it again.")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
