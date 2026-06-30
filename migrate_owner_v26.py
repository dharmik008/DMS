"""
migrate_owner_v26.py — Add is_locked + force_password_change columns to users table.
Run ONCE after deploying v26:
    python migrate_owner_v26.py
"""
from app import app, db
from sqlalchemy import text

with app.app_context():
    with db.engine.connect() as conn:
        # --- users table ---
        for col, defn in [
            ('is_locked', 'BOOLEAN DEFAULT FALSE'),
            ('force_password_change', 'BOOLEAN DEFAULT FALSE'),
        ]:
            try:
                conn.execute(text(f'ALTER TABLE users ADD COLUMN {col} {defn}'))
                conn.commit()
                print(f'  ✓ users.{col} added')
            except Exception as e:
                print(f'  · users.{col} already exists or error: {e}')

        # --- xo_pw_audit and xo_event_audit (auto-created by SQLAlchemy) ---
        db.create_all()
        print('  ✓ xo_pw_audit / xo_event_audit ensured')

    print('\nMigration complete.')
