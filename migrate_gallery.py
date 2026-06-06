"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  migrate_gallery.py                                                         ║
║  Run ONCE to create the vehicle_images table.                               ║
║  Safe to run multiple times — create_all() skips existing tables.          ║
║                                                                              ║
║  Usage:                                                                      ║
║      python migrate_gallery.py                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import sys


def run():
    try:
        from app import app          # ← adjust if your entrypoint is named differently
    except ImportError:
        print("❌  Could not import 'app'. Edit this file and fix the import.")
        print("    Common patterns:  'from run import app'  or  'from wsgi import app'")
        sys.exit(1)

    # Import VehicleImage so SQLAlchemy registers it before create_all
    try:
        from models import db, VehicleImage   # noqa: F401
    except ImportError as e:
        print(f"❌  Import error: {e}")
        print("    Make sure you've added VehicleImage to models.py first.")
        sys.exit(1)

    with app.app_context():
        db.create_all()
        print("✅  Migration complete.")
        print("    Table 'vehicle_images' created (or already existed).")
        print("    Columns: id, vehicle_id, filename, sort_order, created_at")


if __name__ == '__main__':
    run()
