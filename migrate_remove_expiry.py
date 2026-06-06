"""
Migration: Remove document expiry system from Centralized Document Storage.

Documents are now permanent — they never expire automatically.
Access is revoked only by explicit admin deletion or reassignment.

What this script does:
  1. Drops expiry columns from central_document_storage
     (expires_at, is_expired, expired_at, restored_at)
  2. Resets any 'expired' or 'restored' status rows → 'active'
  3. Drops expiry-specific columns from central_doc_audit_logs
     (prev_expiry_date, new_expiry_date, prev_remaining, new_remaining,
      adjustment_days, modification_reason)
  4. Removes audit log rows with action='expiry_modified' or 'restored'
     (they reference a concept that no longer exists)

SQLite does not support DROP COLUMN before version 3.35.0.
This script recreates the tables if DROP COLUMN fails.

Run once:
    python migrate_remove_expiry.py

Safe to re-run — checks for column existence before acting.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'Caryanams.db')

EXPIRY_COLS_CDS  = {'expires_at', 'is_expired', 'expired_at', 'restored_at'}
EXPIRY_COLS_AUDIT = {'prev_expiry_date', 'new_expiry_date', 'prev_remaining',
                     'new_remaining', 'adjustment_days', 'modification_reason'}


def col_names(cur, table):
    return {r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}


def sqlite_version_supports_drop_column(cur):
    ver = cur.execute("SELECT sqlite_version()").fetchone()[0]
    major, minor, *_ = (int(x) for x in ver.split('.'))
    return (major, minor) >= (3, 35)


def drop_cols_via_recreate(conn, cur, table, cols_to_drop):
    """Recreate table without the listed columns (SQLite <3.35 workaround)."""
    all_cols = cur.execute(f"PRAGMA table_info({table})").fetchall()
    keep = [c for c in all_cols if c[1] not in cols_to_drop]
    col_defs = ', '.join(f'"{c[1]}" {c[2]}' for c in keep)
    col_names_csv = ', '.join(f'"{c[1]}"' for c in keep)

    cur.execute(f"ALTER TABLE {table} RENAME TO _{table}_old")
    cur.execute(f"CREATE TABLE {table} ({col_defs})")
    cur.execute(f"INSERT INTO {table} ({col_names_csv}) SELECT {col_names_csv} FROM _{table}_old")
    cur.execute(f"DROP TABLE _{table}_old")
    print(f"  ✅ Recreated {table} without columns: {cols_to_drop}")


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    supports_drop = sqlite_version_supports_drop_column(cur)
    print(f"SQLite DROP COLUMN supported: {supports_drop}")

    # ── 1. central_document_storage ─────────────────────────────────────────
    existing_cds = col_names(cur, 'central_document_storage')
    cols_to_drop_cds = EXPIRY_COLS_CDS & existing_cds

    if cols_to_drop_cds:
        if supports_drop:
            for col in cols_to_drop_cds:
                cur.execute(f"ALTER TABLE central_document_storage DROP COLUMN {col}")
                print(f"  Dropped central_document_storage.{col}")
        else:
            drop_cols_via_recreate(conn, cur, 'central_document_storage', cols_to_drop_cds)
    else:
        print("ℹ️  central_document_storage: expiry columns already absent")

    # ── 2. Reset expired/restored rows → active ──────────────────────────────
    cur.execute(
        "UPDATE central_document_storage SET status='active' "
        "WHERE status IN ('expired', 'restored')"
    )
    changed = cur.rowcount
    if changed:
        print(f"✅ Reset {changed} expired/restored row(s) → active")
    else:
        print("ℹ️  No expired/restored rows to reset")

    # ── 3. central_doc_audit_logs ────────────────────────────────────────────
    existing_audit = col_names(cur, 'central_doc_audit_logs')
    cols_to_drop_audit = EXPIRY_COLS_AUDIT & existing_audit

    # Remove expiry-related audit rows first (they reference removed concepts)
    cur.execute(
        "DELETE FROM central_doc_audit_logs WHERE action IN ('expiry_modified', 'restored')"
    )
    deleted_rows = cur.rowcount
    if deleted_rows:
        print(f"✅ Removed {deleted_rows} expiry/restore audit log row(s)")

    if cols_to_drop_audit:
        if supports_drop:
            for col in cols_to_drop_audit:
                cur.execute(f"ALTER TABLE central_doc_audit_logs DROP COLUMN {col}")
                print(f"  Dropped central_doc_audit_logs.{col}")
        else:
            drop_cols_via_recreate(conn, cur, 'central_doc_audit_logs', cols_to_drop_audit)
    else:
        print("ℹ️  central_doc_audit_logs: expiry columns already absent")

    conn.commit()
    conn.close()
    print("\n🎉 Expiry removal migration complete. Documents are now permanent.")


if __name__ == '__main__':
    run()
