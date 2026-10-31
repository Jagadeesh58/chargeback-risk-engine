"""Export and verify the cryptographic head hash of the SQLite audit log.

Allows external anchoring of the local audit hash chain to an external
immutable log, Git commit, or remote verification service.

Usage:
    # Export current audit head
    python scripts/export_audit_head.py [--db path/to/audit.db] [--out output.json]

    # Verify audit head against an anchored hash
    python scripts/export_audit_head.py --verify --against <EXPECTED_HASH> [--db path/to/audit.db]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from chargeback_risk_engine.audit_log import DB_PATH, verify_audit_integrity


def export_audit_head(db_path: str = DB_PATH) -> dict:
    """Verify integrity and export current head hash and record count."""
    res = verify_audit_integrity(db_path)
    if not res.get("valid"):
        raise ValueError(
            f"Audit log integrity check failed at dispute_id: {res.get('failed_dispute_id')}"
        )

    return {
        "status": "valid",
        "db_path": str(Path(db_path).resolve()),
        "head_hash": res.get("head_hash", ""),
        "checked_records": res.get("checked", 0),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


def verify_against_head(expected_hash: str, db_path: str = DB_PATH) -> bool:
    """Verify that the database integrity is valid and its head hash matches the expected hash."""
    res = verify_audit_integrity(db_path)
    if not res.get("valid"):
        print(
            f"FAILED: Hash chain verification failed at dispute_id '{res.get('failed_dispute_id')}'",
            file=sys.stderr,
        )
        return False

    actual_head = res.get("head_hash", "")
    if actual_head != expected_hash:
        print(
            f"FAILED: Head hash mismatch!\n  Expected: {expected_hash}\n  Actual:   {actual_head}",
            file=sys.stderr,
        )
        return False

    print(
        f"SUCCESS: Audit chain verified ({res.get('checked', 0)} records). Head hash matches: {actual_head}"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Export and verify audit head hash.")
    parser.add_argument("--db", default=DB_PATH, help="Path to SQLite audit database.")
    parser.add_argument("--verify", action="store_true", help="Verify against an anchored hash.")
    parser.add_argument("--against", help="Expected head hash to verify against.")
    parser.add_argument("--out", help="Write export JSON to this file path.")

    args = parser.parse_args()

    if args.verify:
        if not args.against:
            print(
                "Error: --against <head_hash> is required when --verify is specified.",
                file=sys.stderr,
            )
            return 1
        success = verify_against_head(args.against, args.db)
        return 0 if success else 1

    # Export mode
    try:
        data = export_audit_head(args.db)
        output_str = json.dumps(data, indent=2)
        if args.out:
            Path(args.out).write_text(output_str, encoding="utf-8")
            print(f"Exported audit head to {args.out}")
        else:
            print(output_str)
        return 0
    except Exception as e:
        print(f"Error exporting audit head: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
