"""
Migration: Add per-doc reviewed_by/at columns to dealer_kyc,
           and create dealer_notifications table.

Run ONCE with: python migrate_kyc_notifications.py
"""
import sqlite3
import os

DB_PATH = os.environ.get('DATABASE_URL', 'caryanams.db')
if DB_PATH.startswith('sqlite:///'):
    DB_PATH = DB_PATH[len('sqlite:///') :]

NEW_KYC_COLUMNS = [
    ('aadhaar_front_reviewed_by', 'VARCHAR(100)'),
    ('aadhaar_front_reviewed_at', 'DATETIME'),
    ('aadhaar_back_reviewed_by',  'VARCHAR(100)'),
    ('aadhaar_back_reviewed_at',  'DATETIME'),
    ('pan_card_reviewed_by',      'VARCHAR(100)'),
    ('pan_card_reviewed_at',      'DATETIME'),
]


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at: {DB_PATH}")
        print("Run this after your app has created the DB at least once.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ── 1. dealer_kyc: add per-doc reviewed_by / reviewed_at ─────────────────
    cur.execute("PRAGMA table_info(dealer_kyc)")
    existing_kyc = {row[1] for row in cur.fetchall()}

    for col_name, col_def in NEW_KYC_COLUMNS:
        if col_name not in existing_kyc:
            cur.execute(f"ALTER TABLE dealer_kyc ADD COLUMN {col_name} {col_def}")
            print(f"  ✅ dealer_kyc: added column {col_name}")
        else:
            print(f"  ⏭  dealer_kyc: column already exists: {col_name}")

    # Back-fill reviewed_by / reviewed_at from overall reviewed_by / reviewed_at
    # for records that are already approved or rejected
    cur.execute("""
        UPDATE dealer_kyc
        SET aadhaar_front_reviewed_by = reviewed_by,
            aadhaar_front_reviewed_at = reviewed_at,
            aadhaar_back_reviewed_by  = reviewed_by,
            aadhaar_back_reviewed_at  = reviewed_at,
            pan_card_reviewed_by      = reviewed_by,
            pan_card_reviewed_at      = reviewed_at
        WHERE reviewed_by IS NOT NULL
          AND aadhaar_front_reviewed_by IS NULL
    """)
    print(f"  ✅ dealer_kyc: back-filled {cur.rowcount} rows with reviewed_by/at")

    # ── 2. dealer_notifications table ─────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dealer_notifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            dealer_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title      VARCHAR(200) NOT NULL,
            message    TEXT NOT NULL,
            notif_type VARCHAR(30) DEFAULT 'info',
            is_read    BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("  ✅ dealer_notifications table created (or already existed)")

    conn.commit()
    conn.close()
    print("\nMigration complete.")


if __name__ == '__main__':
    migrate()
