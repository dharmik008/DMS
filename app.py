"""
app.py — Caryanams DMS
Fixed:
  1. Import ALL models (including StudioImage from background/routes) inside
     app context BEFORE db.create_all() so every table is registered.
  2. db.create_all() now sees StudioImage → studio_image table is created.
"""

from flask import Flask, session, g
import os


def create_app():
    app = Flask(__name__)
    app.secret_key = 'Caryanams-secret-2025-xK9mP'
    app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'images', 'uploads')
    app.config['KYC_UPLOAD_FOLDER']     = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'dealers')
    app.config['VEHICLE_UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'vehicles')
    app.config['ALLOWED_IMAGE_EXTENSIONS'] = {'jpg', 'jpeg', 'png', 'webp'}
    app.config['MAX_IMAGE_SIZE']        = 10 * 1024 * 1024   # 10 MB per image
    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024   # 100 MB
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///Caryanams.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # ── Public base URL — used for minisite full URLs ──────────────────────────
    # Set APP_URL env var in production: export APP_URL=https://yourdomain.com
    # Falls back to http://localhost:5000 for local dev.
    _raw_app_url = os.environ.get('APP_URL', 'http://localhost:5000').rstrip('/')
    app.config['APP_URL'] = _raw_app_url

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['KYC_UPLOAD_FOLDER'],     exist_ok=True)
    os.makedirs(app.config['VEHICLE_UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), 'static', 'processed'),           exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), 'static', 'custom_bgs'),         exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), 'static', 'images', 'defaults'), exist_ok=True)

    # ── Ensure default_car.jpg placeholder always exists ─────────────────────
    _default_car_path = os.path.join(
        os.path.dirname(__file__), 'static', 'images', 'defaults', 'default_car.jpg'
    )
    if not os.path.isfile(_default_car_path):
        try:
            from PIL import Image as _PI, ImageDraw as _PID, ImageFont as _PIF
            W, H = 1280, 720
            _im = _PI.new('RGB', (W, H), (240, 240, 240))
            _dr = _PID.Draw(_im)
            _cc, _oc = (180,180,190), (120,120,130)
            _dr.polygon([(200,420),(200,380),(280,280),(420,240),(640,230),(820,240),(960,280),(1060,380),(1060,420)], fill=_cc, outline=_oc)
            _dr.rectangle([200,400,1060,470], fill=_cc, outline=_oc)
            _dr.polygon([(300,380),(380,270),(640,250),(840,260),(940,380)], fill=(200,200,210), outline=_oc)
            _dr.polygon([(320,375),(385,275),(590,258),(590,375)], fill=(160,200,220), outline=_oc)
            _dr.polygon([(610,258),(840,265),(930,375),(610,375)], fill=(160,200,220), outline=_oc)
            _dr.ellipse([290,430,430,530], fill=(60,60,70), outline=_oc)
            _dr.ellipse([320,455,400,505], fill=(200,200,200))
            _dr.ellipse([830,430,970,530], fill=(60,60,70), outline=_oc)
            _dr.ellipse([860,455,940,505], fill=(200,200,200))
            _dr.ellipse([195,370,230,400], fill=(255,250,200), outline=_oc)
            _dr.rectangle([1055,375,1070,405], fill=(220,50,50), outline=_oc)
            try:
                _fn = _PIF.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 36)
                _fn2 = _PIF.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 22)
            except Exception:
                _fn = _fn2 = _PIF.load_default()
            _dr.text((W//2, 600), 'No Image Available', fill=(150,150,160), font=_fn, anchor='mm')
            _dr.text((W//2, 645), 'Vehicle image will appear here', fill=(170,170,180), font=_fn2, anchor='mm')
            _im.save(_default_car_path, 'JPEG', quality=85, optimize=True)
        except Exception:
            try:
                from PIL import Image as _PIX
                _PIX.new('RGB', (4,3), (200,200,200)).save(_default_car_path, 'JPEG')
            except Exception:
                pass

    from extensions import db, login_manager
    db.init_app(app)
    login_manager.init_app(app)

    # ── Register Blueprints first so their models are imported ────────────────
    # FIX: StudioImage is defined inside background/routes.py (not models.py).
    # If background_bp is registered AFTER db.create_all(), SQLAlchemy never
    # sees StudioImage and skips creating the studio_image table.
    # Solution: register blueprints BEFORE the app context / create_all block.
    from auth.routes       import auth_bp
    from dealer.routes     import dealer_bp
    from user.routes       import user_bp
    from background.routes import background_bp   # ← imports StudioImage into metadata
    from minisite.routes   import minisite_bp
    from admin.routes      import admin_bp
    from policies.routes   import policies_bp         # ← Privacy & Refund Policy pages

    app.register_blueprint(auth_bp,        url_prefix='/auth')
    app.register_blueprint(dealer_bp,      url_prefix='/dealer')
    app.register_blueprint(user_bp,        url_prefix='/')
    app.register_blueprint(background_bp,  url_prefix='/studio')
    app.register_blueprint(minisite_bp,    url_prefix='')
    app.register_blueprint(admin_bp,       url_prefix='/admin')
    app.register_blueprint(policies_bp,    url_prefix='')

    # ── Create all tables (including studio_image and admin_logs) ─────────────
    from models import (seed_demo_data, AdminLog, SubAdmin,
                        CentralDocumentStorage, CentralDocumentAuditLog,
                        LeadImportFile, ImportedLead, LeadAssignmentHistory,
                        VisitorLog)
    with app.app_context():
        db.create_all()        # now sees ALL models including StudioImage + Lead Import
        # ── Migrate: add new columns to admin_logs if they don't exist ──────────
        try:
            from sqlalchemy import text
            with db.engine.connect() as conn:
                cols = {row[1] for row in conn.execute(text("PRAGMA table_info(admin_logs)"))}
                if 'user_role' not in cols:
                    conn.execute(text("ALTER TABLE admin_logs ADD COLUMN user_role VARCHAR(30) DEFAULT 'Admin'"))
                if 'status' not in cols:
                    conn.execute(text("ALTER TABLE admin_logs ADD COLUMN status VARCHAR(20) DEFAULT 'Success'"))
                conn.commit()
        except Exception:
            pass

        # ── Migrate: visitor_logs table (create_all handles new DBs; existing DBs need this) ──
        try:
            from sqlalchemy import text as _vt
            with db.engine.connect() as _vc:
                _vc.execute(_vt("""
                    CREATE TABLE IF NOT EXISTS visitor_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ip_address VARCHAR(45) NOT NULL DEFAULT 'unknown',
                        country VARCHAR(100),
                        city VARCHAR(100),
                        browser VARCHAR(80),
                        operating_system VARCHAR(80),
                        device_type VARCHAR(20),
                        page_url VARCHAR(500),
                        referrer VARCHAR(500),
                        visited_at DATETIME,
                        created_at DATETIME
                    )
                """))
                _vc.commit()
        except Exception:
            pass

        # ── Migrate: make leads.dealer_id nullable on existing SQLite DBs ────
        # SQLite doesn't support ALTER COLUMN, so we use the recommended
        # table-rename + recreate approach, but only if needed.
        try:
            from sqlalchemy import text as _lt
            with db.engine.connect() as _lc:
                _lead_cols = {r[1]: r[3] for r in _lc.execute(_lt("PRAGMA table_info(leads)"))}
                # r[3] is "notnull": 1=NOT NULL, 0=nullable
                # Only rebuild if dealer_id is currently NOT NULL
                if _lead_cols.get('dealer_id') == 1:
                    _lc.execute(_lt("PRAGMA foreign_keys=OFF"))
                    _lc.execute(_lt("""
                        CREATE TABLE IF NOT EXISTS leads_new (
                            id INTEGER PRIMARY KEY,
                            dealer_id INTEGER REFERENCES users(id),
                            agent_id INTEGER REFERENCES agents(id),
                            vehicle_id INTEGER REFERENCES vehicles(id),
                            customer_name VARCHAR(100) NOT NULL,
                            customer_email VARCHAR(120),
                            customer_phone VARCHAR(20) NOT NULL,
                            customer_city VARCHAR(100),
                            source VARCHAR(50) DEFAULT 'website',
                            stage VARCHAR(30) DEFAULT 'new',
                            notes TEXT,
                            follow_up_date DATETIME,
                            assigned_to VARCHAR(100),
                            budget FLOAT,
                            created_at DATETIME,
                            updated_at DATETIME
                        )
                    """))
                    _lc.execute(_lt("""
                        INSERT INTO leads_new SELECT
                            id, dealer_id, agent_id, vehicle_id,
                            customer_name, customer_email, customer_phone, customer_city,
                            source, stage, notes, follow_up_date, assigned_to, budget,
                            created_at, updated_at
                        FROM leads
                    """))
                    _lc.execute(_lt("DROP TABLE leads"))
                    _lc.execute(_lt("ALTER TABLE leads_new RENAME TO leads"))
                    _lc.execute(_lt("PRAGMA foreign_keys=ON"))
                    _lc.commit()
        except Exception:
            pass

        seed_demo_data()

        # ── Migrate: Reassign display IDs (D1/D2, U1/U2, SA1/SA2) ───────────
        try:
            from sqlalchemy import text as _text
            with db.engine.connect() as _conn:
                _sa_cols = {r[1] for r in _conn.execute(_text("PRAGMA table_info(sub_admins)"))}
                if 'display_id' not in _sa_cols:
                    _conn.execute(_text("ALTER TABLE sub_admins ADD COLUMN display_id TEXT"))
                _u_cols = {r[1] for r in _conn.execute(_text("PRAGMA table_info(users)"))}
                if 'display_id' not in _u_cols:
                    _conn.execute(_text("ALTER TABLE users ADD COLUMN display_id TEXT"))
                for _role, _pfx in (('dealer', 'D'), ('user', 'U')):
                    _rows = _conn.execute(_text(
                        f"SELECT id FROM users WHERE role='{_role}' "
                        "ORDER BY COALESCE(created_at,'1970-01-01'), id"
                    )).fetchall()
                    for _i, _r in enumerate(_rows, 1):
                        _conn.execute(_text("UPDATE users SET display_id=:d WHERE id=:i"),
                                      {"d": f"{_pfx}{_i}", "i": _r[0]})
                _sa_rows = _conn.execute(_text(
                    "SELECT id FROM sub_admins ORDER BY COALESCE(created_at,'1970-01-01'), id"
                )).fetchall()
                for _i, _r in enumerate(_sa_rows, 1):
                    _conn.execute(_text("UPDATE sub_admins SET display_id=:d WHERE id=:i"),
                                  {"d": f"SA{_i}", "i": _r[0]})
                _conn.commit()
        except Exception:
            pass

    from db import user_get_by_id

    @app.before_request
    def load_user():
        uid = session.get('user_id')
        g.user = user_get_by_id(uid) if uid else None

    @app.context_processor
    def inject_user():
        return dict(current_user=g.user)  # None when not logged in

    # ── Minisite URL helper — available in ALL templates ──────────────────────
    # Usage in Jinja:  {{ minisite_url('ABC') }}
    # Returns:  https://yourdomain.com/dealer/ABC
    @app.context_processor
    def inject_minisite_url():
        def minisite_url(website_name):
            if not website_name:
                return ''
            base = app.config.get('APP_URL', '').rstrip('/')
            if not base:
                # Fallback: build from current request context
                from flask import request as _req
                try:
                    base = _req.url_root.rstrip('/')
                except RuntimeError:
                    base = 'http://localhost:5000'
            slug = website_name.strip().lower().replace(' ', '-')
            return f'{base}/dealer/{slug}'
        return dict(minisite_url=minisite_url)

    @app.template_global('minisite_url')
    def minisite_url_global(website_name):
        if not website_name:
            return ''
        base = app.config.get('APP_URL', '').rstrip('/')
        slug = website_name.strip().lower().replace(' ', '-')
        return f'{base}/dealer/{slug}'

    @app.template_filter('fmtdate')
    def fmtdate(s, fmt='%d %b %Y'):
        if not s:
            return '—'
        try:
            from datetime import datetime, timedelta
            if isinstance(s, str):
                s = s[:19]
                dt = datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
            else:
                dt = s
            # Convert stored UTC → IST (UTC+5:30)
            dt = dt + timedelta(hours=5, minutes=30)
            return dt.strftime(fmt)
        except Exception:
            return str(s)[:10]

    @app.template_filter('fmtprice')
    def fmtprice(v):
        try:
            return '₹{:,.0f}'.format(float(v))
        except Exception:
            return '—'

    # ── Global JSON error handlers (prevent HTML error pages reaching JS) ─────
    # FIX: Without these, Flask returns HTML 404/500 pages which cause the
    # "Unexpected token '<'" JSON parse error in the frontend fetch() calls.
    # Covers all status codes. Uses success:false format matching upload route.
    from flask import jsonify

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({'success': False, 'error': 'Bad request', 'code': 400}), 400

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({'success': False, 'error': 'Forbidden', 'code': 403}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({'success': False, 'error': 'Not found', 'code': 404}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({'success': False, 'error': 'Method not allowed', 'code': 405}), 405

    @app.errorhandler(413)
    def request_too_large(e):
        return jsonify({'success': False, 'error': 'File too large. Maximum size is 100 MB.', 'code': 413}), 413

    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({'success': False, 'error': 'Internal server error', 'code': 500}), 500

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5000)
