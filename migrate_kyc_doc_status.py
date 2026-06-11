"""
Migration: Add per-document status and rejection reason columns to dealer_kyc table.
Run ONCE with: python migrate_kyc_doc_status.py
"""
import sqlite3
import os

DB_PATH = os.environ.get('DATABASE_URL', 'caryanams.db')
# For SQLite file path (strip sqlite:/// prefix if present)
if DB_PATH.startswith('sqlite:///'):
    DB_PATH = DB_PATH[len('sqlite:///'):]

NEW_COLUMNS = [
    ('aadhaar_front_status', "VARCHAR(20) DEFAULT 'pending'"),
    ('aadhaar_back_status',  "VARCHAR(20) DEFAULT 'pending'"),
    ('pan_card_status',      "VARCHAR(20) DEFAULT 'pending'"),
    ('aadhaar_front_reject', 'TEXT'),
    ('aadhaar_back_reject',  'TEXT'),
    ('pan_card_reject',      'TEXT'),
]

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at: {DB_PATH}")
        print("Run this after your app has created the DB at least once.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get existing columns
    cur.execute("PRAGMA table_info(dealer_kyc)")
    existing = {row[1] for row in cur.fetchall()}

    added = []
    for col_name, col_def in NEW_COLUMNS:
        if col_name not in existing:
            sql = f"ALTER TABLE dealer_kyc ADD COLUMN {col_name} {col_def}"
            cur.execute(sql)
            added.append(col_name)
            print(f"  ✅ Added column: {col_name}")
        else:
            print(f"  ⏭  Column already exists: {col_name}")

    # For existing approved KYC records, set all doc statuses to 'approved'
    if added:
        cur.execute("""
            UPDATE dealer_kyc
            SET aadhaar_front_status = 'approved',
                aadhaar_back_status  = 'approved',
                pan_card_status      = 'approved'
            WHERE kyc_status = 'approved'
        """)
        rows = cur.rowcount
        print(f"  ✅ Backfilled {rows} approved KYC records with per-doc approved status")

    conn.commit()
    conn.close()
    print("\nMigration complete.")

if __name__ == '__main__':
    migrate()
