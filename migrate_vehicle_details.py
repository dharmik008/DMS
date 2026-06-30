"""
migrate_vehicle_details.py
Adds 6 new vehicle detail columns to the vehicles table.
Safe to run on existing data — uses ADD COLUMN IF NOT EXISTS pattern.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'kyc.db')

COLUMNS = [
    ("accident_history",   "VARCHAR(20) DEFAULT 'NA'"),
    ("loan_status",        "VARCHAR(20) DEFAULT 'NA'"),
    ("rc_service_records", "VARCHAR(20) DEFAULT 'NA'"),
    ("major_issues",       "TEXT DEFAULT 'None'"),       # comma-separated
    ("keys_available",     "VARCHAR(20) DEFAULT 'NA'"),
    ("body_panel_status",  "VARCHAR(20) DEFAULT 'NA'"),
]

def run():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(vehicles)")
    existing = {row[1] for row in cur.fetchall()}
    for col_name, col_def in COLUMNS:
        if col_name not in existing:
            cur.execute(f"ALTER TABLE vehicles ADD COLUMN {col_name} {col_def}")
            print(f"  Added column: {col_name}")
        else:
            print(f"  Already exists: {col_name}")
    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == '__main__':
    run()
