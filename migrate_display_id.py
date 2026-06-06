"""
Migration: Add/backfill display_id for Dealers, Users, and Sub Admins.

Independent sequences — each type uses its own table/prefix:
  Dealers    → D1,  D2,  D3  ...  (users table, role='dealer')
  Users      → U1,  U2,  U3  ...  (users table, role='user')
  Sub Admins → SA1, SA2, SA3 ...  (sub_admins table)

Run once:
    python migrate_display_id.py

Safe to run multiple times (skips already-assigned rows).
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'Caryanams.db')


def _backfill(cur, table, role_filter, prefix, id_col='id',
              role_col=None, display_col='display_id'):
    """Generic backfill helper for one account type."""
    # Build WHERE clause
    role_clause = f"AND {role_col}='{role_filter}'" if role_col else ''

    unassigned = cur.execute(
        f"SELECT {id_col} FROM {table} "
        f"WHERE ({display_col} IS NULL OR {display_col}='') "
        f"{role_clause} "
        f"ORDER BY COALESCE(created_at, '1970-01-01'), {id_col}"
    ).fetchall()

    if not unassigned:
        print(f"ℹ️  No {prefix}-type rows need backfilling")
        return

    # Find the highest existing number for this prefix only
    existing = cur.execute(
        f"SELECT {display_col} FROM {table} "
        f"WHERE {display_col} LIKE '{prefix}%' {role_clause}"
    ).fetchall()
    nums = []
    for row in existing:
        try:
            nums.append(int(row[0][len(prefix):]))
        except (ValueError, TypeError):
            pass
    counter = max(nums, default=0) + 1

    for row in unassigned:
        cur.execute(
            f"UPDATE {table} SET {display_col}=? WHERE {id_col}=?",
            (f'{prefix}{counter}', row[0])
        )
        print(f"  {table} id={row[0]} → {prefix}{counter}")
        counter += 1
    print(f"✅ Assigned display_ids to {len(unassigned)} {prefix}-type record(s)")


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ── 1. users table — add display_id column if missing ─────────────────
    users_cols = [r[1] for r in cur.execute("PRAGMA table_info(users)").fetchall()]
    if 'display_id' not in users_cols:
        cur.execute("ALTER TABLE users ADD COLUMN display_id TEXT")
        print("✅ Added display_id column to users table")
    else:
        print("ℹ️  display_id column already exists in users table")

    # ── 2. sub_admins table — add display_id column if missing ────────────
    sa_cols = [r[1] for r in cur.execute("PRAGMA table_info(sub_admins)").fetchall()]
    if 'display_id' not in sa_cols:
        cur.execute("ALTER TABLE sub_admins ADD COLUMN display_id TEXT")
        print("✅ Added display_id column to sub_admins table")
    else:
        print("ℹ️  display_id column already exists in sub_admins table")

    # ── 3. Backfill Dealers → D1, D2, D3 ... ─────────────────────────────
    _backfill(cur, table='users', role_filter='dealer',
              prefix='D', role_col='role')

    # ── 4. Backfill Users → U1, U2, U3 ... ───────────────────────────────
    _backfill(cur, table='users', role_filter='user',
              prefix='U', role_col='role')

    # ── 5. Backfill Sub Admins → SA1, SA2, SA3 ... ────────────────────────
    _backfill(cur, table='sub_admins', role_filter=None,
              prefix='SA', role_col=None)

    # ── 6. Unique index on users.display_id ───────────────────────────────
    try:
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_display_id ON users(display_id)"
        )
        print("✅ Unique index on users.display_id ensured")
    except sqlite3.OperationalError as e:
        print(f"ℹ️  Index note (users): {e}")

    # ── 7. Unique index on sub_admins.display_id ──────────────────────────
    try:
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_sub_admins_display_id ON sub_admins(display_id)"
        )
        print("✅ Unique index on sub_admins.display_id ensured")
    except sqlite3.OperationalError as e:
        print(f"ℹ️  Index note (sub_admins): {e}")

    conn.commit()
    conn.close()
    print("\n🎉 Migration complete.")


if __name__ == '__main__':
    run()
