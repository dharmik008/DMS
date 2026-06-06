"""
Migration: Reassign ALL display IDs from scratch in strict chronological order.

This fixes cases where:
  - Dealers got wrong IDs like D3, D4 (due to old shared counter bug)
  - Users got wrong IDs like U4, U5 (due to old shared counter bug)
  - Sub Admins have no display_id column at all

After this migration:
  Dealers    → D1, D2, D3 ...  ordered by created_at then id
  Users      → U1, U2, U3 ...  ordered by created_at then id
  Sub Admins → SA1, SA2, SA3 ... ordered by created_at then id

Run once:
    python migrate_reassign_display_ids.py

Safe to re-run — always does a full clean reassignment.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'Caryanams.db')


def reassign(cur, conn):

    # ── 1. Ensure display_id column exists on sub_admins ─────────────────────
    sa_cols = {r[1] for r in cur.execute("PRAGMA table_info(sub_admins)").fetchall()}
    if 'display_id' not in sa_cols:
        cur.execute("ALTER TABLE sub_admins ADD COLUMN display_id TEXT")
        print("✅ Added display_id column to sub_admins table")
    else:
        print("ℹ️  display_id already exists on sub_admins")

    # ── 2. Ensure display_id column exists on users (safety check) ────────────
    u_cols = {r[1] for r in cur.execute("PRAGMA table_info(users)").fetchall()}
    if 'display_id' not in u_cols:
        cur.execute("ALTER TABLE users ADD COLUMN display_id TEXT")
        print("✅ Added display_id column to users table")
    else:
        print("ℹ️  display_id already exists on users")

    # ── 3. Reassign Dealers → D1, D2, D3 ... ─────────────────────────────────
    dealers = cur.execute(
        "SELECT id FROM users WHERE role='dealer' "
        "ORDER BY COALESCE(created_at, '1970-01-01'), id"
    ).fetchall()

    for i, row in enumerate(dealers, start=1):
        new_id = f"D{i}"
        cur.execute("UPDATE users SET display_id=? WHERE id=?", (new_id, row[0]))
        print(f"  Dealer id={row[0]} → {new_id}")
    print(f"✅ Reassigned {len(dealers)} dealer ID(s)")

    # ── 4. Reassign Users → U1, U2, U3 ... ───────────────────────────────────
    users = cur.execute(
        "SELECT id FROM users WHERE role='user' "
        "ORDER BY COALESCE(created_at, '1970-01-01'), id"
    ).fetchall()

    for i, row in enumerate(users, start=1):
        new_id = f"U{i}"
        cur.execute("UPDATE users SET display_id=? WHERE id=?", (new_id, row[0]))
        print(f"  User   id={row[0]} → {new_id}")
    print(f"✅ Reassigned {len(users)} user ID(s)")

    # ── 5. Reassign Sub Admins → SA1, SA2, SA3 ... ───────────────────────────
    sub_admins = cur.execute(
        "SELECT id FROM sub_admins "
        "ORDER BY COALESCE(created_at, '1970-01-01'), id"
    ).fetchall()

    for i, row in enumerate(sub_admins, start=1):
        new_id = f"SA{i}"
        cur.execute("UPDATE sub_admins SET display_id=? WHERE id=?", (new_id, row[0]))
        print(f"  SubAdmin id={row[0]} → {new_id}")
    print(f"✅ Reassigned {len(sub_admins)} sub admin ID(s)")

    # ── 6. Unique indexes ─────────────────────────────────────────────────────
    for idx, tbl, col in [
        ('ix_users_display_id',      'users',      'display_id'),
        ('ix_sub_admins_display_id', 'sub_admins', 'display_id'),
    ]:
        try:
            cur.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {idx} ON {tbl}({col})")
            print(f"✅ Unique index on {tbl}.{col} ensured")
        except sqlite3.OperationalError as e:
            print(f"ℹ️  Index note ({tbl}): {e}")

    conn.commit()


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print(f"Database: {DB_PATH}\n")

    # Preview current state
    print("── Current state before migration ──")
    for role in ('dealer', 'user'):
        rows = cur.execute(
            f"SELECT id, display_id, name FROM users WHERE role='{role}' ORDER BY id"
        ).fetchall()
        for r in rows:
            print(f"  [{role}] id={r['id']}  display_id={r['display_id']}  name={r['name']}")
    sa_rows = cur.execute("SELECT id, name FROM sub_admins ORDER BY id").fetchall()
    for r in sa_rows:
        print(f"  [sub_admin] id={r['id']}  name={r['name']}")
    print()

    reassign(cur, conn)

    print()
    print("── Final state after migration ──")
    for role in ('dealer', 'user'):
        rows = cur.execute(
            f"SELECT id, display_id, name FROM users WHERE role='{role}' ORDER BY id"
        ).fetchall()
        for r in rows:
            print(f"  [{role}] id={r['id']}  display_id={r['display_id']}  name={r['name']}")
    sa_rows = cur.execute(
        "SELECT id, display_id, name FROM sub_admins ORDER BY id"
    ).fetchall()
    for r in sa_rows:
        print(f"  [sub_admin] id={r['id']}  display_id={r['display_id']}  name={r['name']}")

    conn.close()
    print("\n🎉 Reassignment complete.")


if __name__ == '__main__':
    run()
