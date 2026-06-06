"""
Migration: Add Modify Expiry audit columns to central_doc_audit_logs table.

Run once after the app has been started at least once (so Flask-SQLAlchemy
creates the base tables), then run this script:

    python migrate_modify_expiry.py

Safe to run multiple times.
"""
import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'Caryanams.db')

TABLE = 'central_doc_audit_logs'

NEW_COLUMNS = [
    # (column_name, sql_type)
    ('user_role',            'TEXT'),
    ('prev_expiry_date',     'DATETIME'),
    ('new_expiry_date',      'DATETIME'),
    ('prev_remaining',       'INTEGER'),
    ('new_remaining',        'INTEGER'),
    ('adjustment_days',      'INTEGER'),
    ('modification_reason',  'TEXT'),
    ('dealer_name',          'TEXT'),
    ('document_type',        'TEXT'),
]

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id          INTEGER REFERENCES central_document_storage(id) ON DELETE SET NULL,
    action               TEXT    NOT NULL,
    performed_by         TEXT    DEFAULT 'admin',
    user_role            TEXT,
    notes                TEXT,
    prev_expiry_date     DATETIME,
    new_expiry_date      DATETIME,
    prev_remaining       INTEGER,
    new_remaining        INTEGER,
    adjustment_days      INTEGER,
    modification_reason  TEXT,
    dealer_name          TEXT,
    document_type        TEXT,
    created_at           DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] Database not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # Check if table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (TABLE,))
    table_exists = cur.fetchone() is not None

    if not table_exists:
        print(f"  [CREATE] Table '{TABLE}' does not exist — creating with all columns...")
        cur.execute(CREATE_TABLE_SQL)
        conn.commit()
        print(f"✅ Table '{TABLE}' created successfully with all Modify Expiry columns.")
        conn.close()
        return

    # Table exists — add missing columns
    cur.execute(f"PRAGMA table_info({TABLE})")
    existing = {row[1] for row in cur.fetchall()}

    added = []
    for col_name, col_type in NEW_COLUMNS:
        if col_name not in existing:
            try:
                cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col_name} {col_type}")
                added.append(col_name)
                print(f"  [ADDED] {col_name} ({col_type})")
            except sqlite3.OperationalError as e:
                print(f"  [SKIP]  {col_name}: {e}")
        else:
            print(f"  [OK]    {col_name} already exists")

    conn.commit()
    conn.close()

    if added:
        print(f"\n✅ Migration complete. Added {len(added)} column(s): {', '.join(added)}")
    else:
        print("\n✅ No changes needed — all columns already present.")


if __name__ == '__main__':
    print(f"Running Modify Expiry migration on:\n  {DB_PATH}\n")
    migrate()
