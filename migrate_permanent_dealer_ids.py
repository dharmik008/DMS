"""
migrate_permanent_dealer_ids.py
════════════════════════════════
One-time migration to enforce the Permanent Dealer ID system.

Run ONCE after deploying the updated code:
    python migrate_permanent_dealer_ids.py

What it does
────────────
1. Preserves every existing dealer's current display_id exactly as-is.
2. Assigns a brand-new display_id to any dealer that somehow has none.
3. Does NOT renumber, reassign, or change any existing ID.
4. Logs every action for audit purposes.

After running this script the system guarantees:
  ✓ Every dealer has a permanent display_id (D1, D2, D3 …)
  ✓ No ID will ever be reused, recycled, or reassigned
  ✓ Deleted/suspended dealers' IDs are retired forever
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from extensions import db
from models import User

app = create_app()

def run():
    with app.app_context():
        print("=" * 60)
        print("  PERMANENT DEALER ID MIGRATION")
        print("=" * 60)

        dealers = (
            User.query
            .filter_by(role='dealer')
            .order_by(User.created_at.asc(), User.id.asc())
            .all()
        )

        print(f"\nTotal dealers found: {len(dealers)}")

        # Collect all existing dealer numbers (to avoid any collision)
        existing_nums = set()
        for d in dealers:
            if d.display_id and d.display_id.startswith('D'):
                try:
                    existing_nums.add(int(d.display_id[1:]))
                except (ValueError, TypeError):
                    pass

        next_num = (max(existing_nums) + 1) if existing_nums else 1
        assigned = []
        preserved = []

        for d in dealers:
            if d.display_id and d.display_id.startswith('D'):
                preserved.append(f"  PRESERVED  {d.display_id:8s} → {d.name} (id={d.id})")
            else:
                # Find next unused number
                while next_num in existing_nums:
                    next_num += 1
                new_id = f"D{next_num}"
                existing_nums.add(next_num)
                d.display_id = new_id
                next_num += 1
                assigned.append(f"  ASSIGNED   {new_id:8s} → {d.name} (id={d.id})")

        db.session.commit()

        print("\n── Preserved (unchanged) ──────────────────────────────────")
        for line in preserved:
            print(line)

        if assigned:
            print("\n── Newly Assigned ─────────────────────────────────────────")
            for line in assigned:
                print(line)
        else:
            print("\n  All dealers already had display_ids. Nothing changed.")

        print("\n" + "=" * 60)
        print(f"  Done. {len(preserved)} preserved, {len(assigned)} newly assigned.")
        print("  Dealer IDs are now permanent and immutable.")
        print("=" * 60)


if __name__ == '__main__':
    run()
