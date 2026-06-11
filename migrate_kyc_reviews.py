"""
Migration: Create kyc_reviews table for full KYC approve/reject audit trail.
Run ONCE with: python migrate_kyc_reviews.py

This is safe to re-run — it skips creation if the table already exists.
"""
import sqlite3
import os

DB_PATH = os.environ.get('DATABASE_URL', 'caryanams.db')
if DB_PATH.startswith('sqlite:///'):
    DB_PATH = DB_PATH[len('sqlite:///'):]


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS kyc_reviews (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    dealer_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_type    VARCHAR(30)  NOT NULL,
    status           VARCHAR(20)  NOT NULL,
    reason           TEXT,
    previous_status  VARCHAR(20),
    reviewed_by      VARCHAR(100) NOT NULL DEFAULT 'admin',
    reviewed_by_id   INTEGER,
    reviewed_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    created_at       DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME     DEFAULT CURRENT_TIMESTAMP,
    deleted_at       DATETIME
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS ix_kyc_reviews_dealer_id ON kyc_reviews(dealer_id);
"""


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"[WARN] Database not found at: {DB_PATH}")
        print("       Run this migration after the app has initialised the DB at least once.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(CREATE_TABLE_SQL)
    print("  ✅ kyc_reviews table created (or already existed).")

    cur.execute(CREATE_INDEX_SQL)
    print("  ✅ Index ix_kyc_reviews_dealer_id ensured.")

    conn.commit()
    conn.close()
    print("\nMigration complete ✔")


if __name__ == '__main__':
    migrate()
