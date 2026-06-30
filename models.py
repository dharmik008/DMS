"""
models.py — CarYanams DMS
Fixed: SQLAlchemy relationship conflicts using back_populates on both sides.
"""

from extensions import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, timezone as _tz

# ── IST timestamp helper (UTC+5:30, stored as naive datetime) ────────────────
_IST = _tz(timedelta(hours=5, minutes=30))


def _now_ist():
    """Return current IST time as a naive datetime (for DB storage)."""
    return datetime.now(_IST).replace(tzinfo=None)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def generate_display_id(role):
    """
    PERMANENT DEALER/USER ID SYSTEM
    ════════════════════════════════
    Dealer IDs (D1, D2, D3 …) are IMMUTABLE and NEVER recycled or reassigned.
    Once a Dealer ID is assigned it belongs to that dealer forever — even if
    the dealer is suspended, deleted, deactivated, or inactive.

    New IDs are always  max_existing + 1  so no previously-issued number is
    ever reused, regardless of gaps in the sequence caused by deletions.

    Users      → U1,  U2,  U3  ...  (completely independent from dealers)
    Sub Admins → SA1, SA2, SA3 ...  (completely independent)
    """
    from sqlalchemy import text as _text
    from extensions import db as _db

    if role == 'sub_admin':
        rows = _db.session.execute(
            _text("SELECT display_id FROM sub_admins WHERE display_id LIKE 'SA%'")
        ).fetchall()
        prefix = 'SA'
        nums = []
        for row in rows:
            try:
                nums.append(int(row[0][len(prefix):]))
            except (ValueError, TypeError, IndexError):
                pass
        return f'{prefix}{max(nums, default=0) + 1}'

    if role == 'dealer':
        prefix = 'D'
        # Include ALL dealers (active, suspended, deleted) — IDs must never be reused
        rows = _db.session.execute(
            _text("SELECT display_id FROM users WHERE role='dealer' AND display_id LIKE 'D%'")
        ).fetchall()
    else:  # role == 'user'
        prefix = 'U'
        rows = _db.session.execute(
            _text("SELECT display_id FROM users WHERE role='user' AND display_id LIKE 'U%'")
        ).fetchall()

    nums = []
    for row in rows:
        try:
            nums.append(int(row[0][len(prefix):]))
        except (ValueError, TypeError, IndexError):
            pass
    # Always max+1 — guaranteed unique, never reuses a retired ID
    return f'{prefix}{max(nums, default=0) + 1}'


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    display_id = db.Column(db.String(20), unique=True, nullable=True)  # U1, U2... or D1, D2...
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    company_name = db.Column(db.String(150))
    gst_number = db.Column(db.String(20))
    city = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    is_locked = db.Column(db.Boolean, default=False)               # v26: Owner can lock accounts
    force_password_change = db.Column(db.Boolean, default=False)   # v26: Force PW change on next login
    created_at = db.Column(db.DateTime, default=_now_ist)
    subscription_plan = db.Column(db.String(50), default='starter')
    subscription_expiry = db.Column(db.DateTime, nullable=True)
    subscription_status = db.Column(db.String(20), default='active')

    # Mini-website identity (public-facing)
    # defaults to username
    website_name = db.Column(db.String(100), nullable=True)
    # uploaded logo filename
    website_logo = db.Column(db.String(255), nullable=True)
    # for mini-site WhatsApp btn
    whatsapp_number = db.Column(db.String(20), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    google_maps_url = db.Column(db.String(500), nullable=True)
    years_in_business = db.Column(db.Integer, nullable=True)
    business_hours = db.Column(db.String(200), nullable=True)

    # FIX: back_populates replaces backref to prevent auto-generated conflicts
    # cascade='all, delete-orphan' ensures dealer delete removes all related records
    vehicles = db.relationship('Vehicle', back_populates='dealer', lazy=True,
                               cascade='all, delete-orphan')
    leads = db.relationship(
        'Lead',    back_populates='dealer', lazy=True, foreign_keys='Lead.dealer_id',
        cascade='all, delete-orphan')
    deals = db.relationship(
        'Deal',    back_populates='dealer', lazy=True, foreign_keys='Deal.dealer_id',
        cascade='all, delete-orphan')
    agents = db.relationship(
        'Agent',   back_populates='dealer', lazy=True, cascade='all, delete-orphan')
    inquiries = db.relationship('Inquiry', back_populates='dealer', lazy=True,
                                cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_active_subscription(self):
        if not self.subscription_expiry:
            return True
        return self.subscription_expiry > _now_ist() and self.subscription_status == 'active'

    def get_subscription_limits(self):
        limits = {
            'starter': {'listings': 25,  'leads': 50,  'storage_mb': 100},
            'growth':  {'listings': 100, 'leads': 500, 'storage_mb': 5120},
            'pro':     {'listings': -1,  'leads': -1,  'storage_mb': -1}
        }
        return limits.get(self.subscription_plan, limits['starter'])

    def __repr__(self):
        return f'<User {self.email}>'


class Agent(db.Model):
    __tablename__ = 'agents'
    id = db.Column(db.Integer, primary_key=True)
    dealer_id = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20),  nullable=False)
    status = db.Column(db.String(20),  default='available')
    created_at = db.Column(db.DateTime,    default=_now_ist)
    updated_at = db.Column(
        db.DateTime,    default=_now_ist, onupdate=_now_ist)

    dealer = db.relationship(
        'User',  back_populates='agents', foreign_keys=[dealer_id])
    leads = db.relationship('Lead',  back_populates='agent',
                            lazy=True, foreign_keys='Lead.agent_id')

    def to_dict(self):
        return {'id': self.id, 'dealer_id': self.dealer_id,
                'name': self.name, 'email': self.email,
                'phone': self.phone, 'status': self.status,
                'created_at': self.created_at.isoformat() if self.created_at else ''}

    def __repr__(self):
        return f'<Agent {self.name}>'


class Vehicle(db.Model):
    __tablename__ = 'vehicles'
    id = db.Column(db.Integer, primary_key=True)
    dealer_id = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=False)
    make = db.Column(db.String(50),  nullable=False)
    model = db.Column(db.String(50),  nullable=False)
    variant = db.Column(db.String(100))
    year = db.Column(db.Integer, nullable=False)
    color = db.Column(db.String(50))
    fuel_type = db.Column(db.String(30))
    transmission = db.Column(db.String(30))
    mileage = db.Column(db.Integer, default=0)
    engine_cc = db.Column(db.Integer)
    price = db.Column(db.Float, nullable=False)
    negotiable = db.Column(db.Boolean, default=True)
    condition = db.Column(db.String(20), default='used')
    status = db.Column(db.String(20), default='available')
    description = db.Column(db.Text)
    image_filename = db.Column(db.String(255), nullable=True)
    vin_number = db.Column(db.String(50))
    registration_number = db.Column(db.String(30))
    insurance_valid_till = db.Column(db.Date)
    rc_available = db.Column(db.Boolean, default=True)
    featured = db.Column(db.Boolean, default=False)
    # approved/pending/rejected
    approval_status = db.Column(db.String(20), default='Pending')
    created_at = db.Column(db.DateTime, default=_now_ist)
    updated_at = db.Column(
        db.DateTime, default=_now_ist, onupdate=_now_ist)

    # ── New vehicle condition details (v18) ──────────────────────────────────
    # All fields default to 'NA' so existing records remain unaffected.
    accident_history   = db.Column(db.String(20), default='NA')   # No/Minor/Major/NA
    loan_status        = db.Column(db.String(20), default='NA')   # Active/Closed/No Loan/NA
    rc_service_records = db.Column(db.String(20), default='NA')   # Yes/No/Partial/NA
    major_issues       = db.Column(db.Text,        default='None') # comma-separated multi-select
    keys_available     = db.Column(db.String(20), default='NA')   # One/Two/Three/NA
    body_panel_status  = db.Column(db.String(20), default='NA')   # No/Repainted/Replaced/NA

    # FIX: 'deals' declared here + 'vehicle' on Deal — both use back_populates.
    # Old code had Vehicle.deals(backref='vehicle_ref') AND Deal.vehicle()
    # pointing at the same FK, which SQLAlchemy flagged as a conflict.
    dealer = db.relationship(
        'User',    back_populates='vehicles', foreign_keys=[dealer_id])
    leads = db.relationship('Lead',    back_populates='vehicle',
                            lazy=True, foreign_keys='Lead.vehicle_id')
    deals = db.relationship('Deal',    back_populates='vehicle',
                            lazy=True, foreign_keys='Deal.vehicle_id')
    inquiries = db.relationship(
        'Inquiry', back_populates='vehicle',  lazy=True)
    extra_images_rel = db.relationship(
        'VehicleImage',
        backref='vehicle',
        cascade='all, delete-orphan',
        lazy='select'
    )

    def to_dict(self):
        return {
            'id': self.id, 'dealer_id': self.dealer_id,
            'make': self.make, 'model': self.model, 'variant': self.variant,
            'year': self.year, 'color': self.color, 'fuel_type': self.fuel_type,
            'transmission': self.transmission, 'mileage': self.mileage,
            'engine_cc': self.engine_cc, 'price': self.price,
            'negotiable': self.negotiable, 'condition': self.condition,
            'status': self.status, 'description': self.description,
            'image_filename': self.image_filename, 'vin_number': self.vin_number,
            'registration_number': self.registration_number,
            'rc_available': self.rc_available, 'featured': self.featured,
            'created_at': self.created_at, 'insurance_till': self.insurance_valid_till,
            # new condition detail fields
            'accident_history':   self.accident_history   or 'NA',
            'loan_status':        self.loan_status        or 'NA',
            'rc_service_records': self.rc_service_records or 'NA',
            'major_issues':       self.major_issues       or 'None',
            'keys_available':     self.keys_available     or 'NA',
            'body_panel_status':  self.body_panel_status  or 'NA',
        }

    def __repr__(self):
        return f'<Vehicle {self.year} {self.make} {self.model}>'


class VehicleImage(db.Model):
    __tablename__ = 'vehicle_images'

    # Recognised image_type values (7 mandatory slots + 'gallery' for additional)
    MANDATORY_TYPES = [
        'front', 'rear', 'right_side', 'left_side',
        'engine', 'boot', 'interior'
    ]

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey(
        'vehicles.id', ondelete='CASCADE'), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    # image_type: one of MANDATORY_TYPES or 'gallery' for additional images
    image_type = db.Column(db.String(30), default='gallery', nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=_now_ist)


class Lead(db.Model):
    __tablename__ = 'leads'
    id = db.Column(db.Integer, primary_key=True)
    dealer_id = db.Column(db.Integer, db.ForeignKey(
        'users.id'),    nullable=True)
    agent_id = db.Column(db.Integer, db.ForeignKey(
        'agents.id'),   nullable=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey(
        'vehicles.id'), nullable=True)
    customer_name = db.Column(db.String(100), nullable=False)
    customer_email = db.Column(db.String(120))
    customer_phone = db.Column(db.String(20),  nullable=False)
    customer_city = db.Column(db.String(100))
    source = db.Column(db.String(50),  default='website')
    stage = db.Column(db.String(30),  default='new')
    notes = db.Column(db.Text)
    follow_up_date = db.Column(db.DateTime)
    assigned_to = db.Column(db.String(100))
    budget = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=_now_ist)
    updated_at = db.Column(
        db.DateTime, default=_now_ist, onupdate=_now_ist)

    dealer = db.relationship(
        'User',    back_populates='leads',   foreign_keys=[dealer_id])
    agent = db.relationship(
        'Agent',   back_populates='leads',   foreign_keys=[agent_id])
    vehicle = db.relationship(
        'Vehicle', back_populates='leads',   foreign_keys=[vehicle_id])
    deal = db.relationship('Deal',    back_populates='lead',
                           uselist=False, foreign_keys='Deal.lead_id')

    def to_dict(self):
        return {
            'id': self.id, 'dealer_id': self.dealer_id, 'agent_id': self.agent_id,
            'vehicle_id': self.vehicle_id, 'customer_name': self.customer_name,
            'customer_email': self.customer_email, 'customer_phone': self.customer_phone,
            'customer_city': self.customer_city, 'source': self.source,
            'stage': self.stage, 'notes': self.notes,
            'follow_up_date': self.follow_up_date, 'assigned_to': self.assigned_to,
            'budget': self.budget, 'created_at': self.created_at
        }

    def __repr__(self):
        return f'<Lead {self.customer_name} - {self.stage}>'


class Deal(db.Model):
    __tablename__ = 'deals'
    id = db.Column(db.Integer, primary_key=True)
    dealer_id = db.Column(db.Integer, db.ForeignKey(
        'users.id'),    nullable=False)
    lead_id = db.Column(db.Integer, db.ForeignKey(
        'leads.id'),    nullable=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey(
        'vehicles.id'), nullable=False)
    customer_name = db.Column(db.String(100), nullable=False)
    customer_phone = db.Column(db.String(20))
    customer_email = db.Column(db.String(120))
    asking_price = db.Column(db.Float)
    negotiated_price = db.Column(db.Float)
    final_price = db.Column(db.Float, nullable=False)
    payment_mode = db.Column(db.String(30), default='cash')
    loan_amount = db.Column(db.Float)
    down_payment = db.Column(db.Float)
    emi_months = db.Column(db.Integer)
    emi_amount = db.Column(db.Float)
    bank_name = db.Column(db.String(100))
    status = db.Column(db.String(30), default='negotiation')
    booking_amount = db.Column(db.Float, default=0)
    gst_amount = db.Column(db.Float, default=0)
    total_amount = db.Column(db.Float)
    notes = db.Column(db.Text)
    deal_date = db.Column(db.DateTime, default=_now_ist)
    delivery_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=_now_ist)

    # FIX: Deal.vehicle now uses back_populates='deals' matching Vehicle.deals.
    # Old code: Vehicle had backref='vehicle_ref' AND Deal had a separate
    # relationship() — both pointed at the same FK causing SQLAlchemy to
    # raise the "conflicts with vehicle_ref / deals" warning.
    dealer = db.relationship(
        'User',    back_populates='deals',   foreign_keys=[dealer_id])
    vehicle = db.relationship(
        'Vehicle', back_populates='deals',   foreign_keys=[vehicle_id])
    lead = db.relationship(
        'Lead',    back_populates='deal',    foreign_keys=[lead_id])

    def to_dict(self):
        return {
            'id': self.id, 'dealer_id': self.dealer_id, 'lead_id': self.lead_id,
            'vehicle_id': self.vehicle_id, 'customer_name': self.customer_name,
            'customer_phone': self.customer_phone, 'customer_email': self.customer_email,
            'asking_price': self.asking_price, 'final_price': self.final_price,
            'payment_mode': self.payment_mode, 'loan_amount': self.loan_amount,
            'down_payment': self.down_payment, 'emi_months': self.emi_months,
            'emi_amount': self.emi_amount, 'bank_name': self.bank_name,
            'status': self.status, 'booking_amount': self.booking_amount,
            'gst_amount': self.gst_amount, 'total_amount': self.total_amount,
            'notes': self.notes, 'created_at': self.created_at
        }

    def __repr__(self):
        return f'<Deal {self.customer_name} - {self.status}>'


class Document(db.Model):
    __tablename__ = 'documents'
    id = db.Column(db.Integer, primary_key=True)
    dealer_id = db.Column(db.Integer, db.ForeignKey(
        'users.id'),    nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey(
        'vehicles.id'), nullable=True)
    customer_name = db.Column(db.String(100))
    doc_type = db.Column(db.String(50))
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255))
    notes = db.Column(db.Text)
    uploaded_at = db.Column(db.DateTime, default=_now_ist)

    def __repr__(self):
        return f'<Document {self.doc_type}>'


class Inquiry(db.Model):
    __tablename__ = 'inquiries'
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey(
        'vehicles.id'), nullable=True)
    dealer_id = db.Column(db.Integer, db.ForeignKey(
        'users.id'),    nullable=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20),  nullable=False)
    message = db.Column(db.Text)
    inquiry_type = db.Column(db.String(30),  default='general')
    status = db.Column(db.String(20),  default='pending')
    created_at = db.Column(db.DateTime,    default=_now_ist)

    vehicle = db.relationship(
        'Vehicle', back_populates='inquiries', foreign_keys=[vehicle_id])
    dealer = db.relationship(
        'User',    back_populates='inquiries', foreign_keys=[dealer_id])

    def __repr__(self):
        return f'<Inquiry {self.name}>'


class AdminLog(db.Model):
    """Stores all user/role actions for the unified Activity Log page."""
    __tablename__ = 'admin_logs'
    id         = db.Column(db.Integer, primary_key=True)
    # Numeric id of the acting user (users.id or sub_admins.id) when known.
    # Nullable — kept optional so existing call sites that don't pass it
    # keep working exactly as before.
    user_id    = db.Column(db.Integer,     nullable=True)
    admin_user = db.Column(db.String(100), default='admin')
    # Super Admin | Sub Admin | Admin | Dealer
    user_role  = db.Column(db.String(30),  default='Admin')
    action     = db.Column(db.String(255), nullable=False)
    module     = db.Column(db.String(50),  default='System')
    # Optional longer-form description shown in the expanded row / export.
    # Falls back to `action` everywhere it's displayed when blank.
    description = db.Column(db.Text,       nullable=True)
    ip_address = db.Column(db.String(45),  default='127.0.0.1')
    device     = db.Column(db.String(20),  nullable=True)   # Desktop | Mobile | Tablet
    browser    = db.Column(db.String(80),  nullable=True)   # Chrome | Firefox | Safari …
    # IANA-style label of the timezone timestamps are stored in (always IST here)
    timezone   = db.Column(db.String(50),  default='Asia/Kolkata (IST)')
    # Success | Failed | Warning
    status     = db.Column(db.String(20),  default='Success')
    created_at = db.Column(db.DateTime,    default=_now_ist)

    def __repr__(self):
        return f'<AdminLog {self.action}>'


class CentralDocumentStorage(db.Model):
    """
    Centralized master repository for all uploaded files across all modules.
    Documents are permanent — they never expire automatically.
    Access is revoked only when an admin explicitly deletes or reassigns a document.
    """
    __tablename__ = 'central_document_storage'

    id            = db.Column(db.Integer, primary_key=True)
    dealer_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    file_name     = db.Column(db.String(255), nullable=False)        # stored filename (uuid.ext)
    original_name = db.Column(db.String(255), nullable=True)         # original upload name
    file_path     = db.Column(db.String(500), nullable=False)        # relative path from static/
    module_name   = db.Column(db.String(100), nullable=False)        # Documents|KYC|Vehicles|Deals|Invoices|Reports|CRM
    document_type = db.Column(db.String(100), nullable=True)         # e.g. RC Book, Invoice, Pan Card …
    uploaded_by   = db.Column(db.Integer,     nullable=True)         # user id who triggered upload
    created_at    = db.Column(db.DateTime,    default=_now_ist)
    # active | deleted
    status        = db.Column(db.String(50),  default='active')
    # Optional reassignment / ownership notes
    ownership_note = db.Column(db.Text,       nullable=True)

    dealer = db.relationship('User', foreign_keys=[dealer_id],
                             backref=db.backref('central_docs', lazy='dynamic'))

    def to_dict(self):
        return {
            'id':            self.id,
            'dealer_id':     self.dealer_id,
            'file_name':     self.file_name,
            'original_name': self.original_name,
            'file_path':     self.file_path,
            'module_name':   self.module_name,
            'document_type': self.document_type,
            'uploaded_by':   self.uploaded_by,
            'created_at':    self.created_at.isoformat() if self.created_at else None,
            'status':        self.status,
        }

    def __repr__(self):
        return f'<CentralDocumentStorage {self.module_name}/{self.file_name}>'


class CentralDocumentAuditLog(db.Model):
    """Audit trail for every admin action on centralized document storage."""
    __tablename__ = 'central_doc_audit_logs'

    id               = db.Column(db.Integer, primary_key=True)
    document_id      = db.Column(db.Integer, db.ForeignKey('central_document_storage.id',
                                                           ondelete='SET NULL'), nullable=True)
    # uploaded | deleted | reassigned
    action           = db.Column(db.String(100), nullable=False)
    performed_by     = db.Column(db.String(100), default='admin')
    user_role        = db.Column(db.String(50),  nullable=True)   # Super Admin | Admin | Sub Admin
    notes            = db.Column(db.Text,         nullable=True)
    dealer_name      = db.Column(db.String(255), nullable=True)   # snapshot of dealer name
    document_type    = db.Column(db.String(100), nullable=True)   # snapshot of doc type

    created_at       = db.Column(db.DateTime,    default=_now_ist)

    document = db.relationship('CentralDocumentStorage',
                               backref=db.backref('audit_logs', lazy='dynamic'))

    def __repr__(self):
        return f'<CentralDocAudit {self.action} doc={self.document_id}>'


# ─────────────────────────────────────────────────────────────────────────────
def seed_demo_data():
    """Seed demo data if database is empty."""
    from datetime import timedelta

    if User.query.first():
        return

    dealer = User(
        name='Rajesh Motors', email='dealer@caryanams.com', phone='9876543210',
        role='dealer', company_name='Rajesh Motors Pvt Ltd',
        gst_number='27AABCU9603R1ZX', city='Mumbai',
        subscription_plan='growth',
        subscription_expiry=_now_ist() + timedelta(days=365),
        subscription_status='active'
    )
    dealer.set_password('dealer123')
    db.session.add(dealer)
    db.session.commit()

    agents = [
        Agent(dealer_id=dealer.id, name='Rajesh Kumar',
              email='rajesh@rajeshmotors.com', phone='9876543211', status='available'),
        Agent(dealer_id=dealer.id, name='Priya Singh',
              email='priya@rajeshmotors.com',  phone='9876543212', status='available'),
        Agent(dealer_id=dealer.id, name='Amit Sharma',  email='amit@rajeshmotors.com',
              phone='9876543213', status='not_available'),
    ]
    db.session.add_all(agents)
    db.session.commit()

    user = User(name='Amit Shah', email='user@caryanams.com',
                phone='9123456789', role='user', city='Mumbai')
    user.set_password('user123')
    db.session.add(user)
    db.session.commit()

    cars = [
        Vehicle(dealer_id=dealer.id, make='Maruti',   model='Swift',         variant='ZXi AMT', year=2022, color='Red',    fuel_type='Petrol',  transmission='Automatic', mileage=18000,
                engine_cc=1197, price=680000,  condition='used', status='available', description='Well maintained, single owner.',              image_filename='None', featured=True),
        Vehicle(dealer_id=dealer.id, make='Hyundai',  model='Creta',         variant='SX(O)',   year=2023, color='White',  fuel_type='Diesel',  transmission='Automatic', mileage=12000,
                engine_cc=1493, price=1650000, condition='used', status='available', description='Premium SUV, sunroof, leather seats.',        image_filename='None', featured=True),
        Vehicle(dealer_id=dealer.id, make='Tata',     model='Nexon',         variant='XZ+ DT',  year=2023, color='Blue',   fuel_type='Electric', transmission='Automatic', mileage=8000,
                engine_cc=0,    price=1450000, condition='used', status='available', description='Electric SUV, 5-star safety rating.',         image_filename='None', featured=True),
        Vehicle(dealer_id=dealer.id, make='Honda',    model='City',          variant='ZX CVT',  year=2021, color='Silver', fuel_type='Petrol',  transmission='Automatic', mileage=32000,
                engine_cc=1498, price=1020000, condition='used', status='available', description='Sedan in pristine condition.',                image_filename='None', featured=False),
        Vehicle(dealer_id=dealer.id, make='Mahindra', model='Scorpio-N',     variant='Z8 L',    year=2023, color='Black',  fuel_type='Diesel',  transmission='Manual',    mileage=9500,
                engine_cc=2184, price=2050000, condition='used', status='available', description='7-seater SUV, diesel, well maintained.',     image_filename='None', featured=True),
        Vehicle(dealer_id=dealer.id, make='Toyota',   model='Innova Crysta', variant='GX MT',   year=2020, color='White',  fuel_type='Diesel',  transmission='Manual',    mileage=65000,
                engine_cc=2393, price=1580000, condition='used', status='available', description='Family MPV, all service records available.', image_filename='None', featured=False),
    ]
    db.session.add_all(cars)
    db.session.commit()

    leads = [
        Lead(dealer_id=dealer.id, agent_id=agents[0].id, vehicle_id=cars[0].id, customer_name='Priya Sharma', customer_phone='9000000001',
             customer_email='priya@email.com', source='website',  stage='interested',  notes='Interested in Swift, budget 7L'),
        Lead(dealer_id=dealer.id, agent_id=agents[0].id, vehicle_id=cars[1].id, customer_name='Karan Mehta',
             customer_phone='9000000002', source='walk-in',  stage='test_drive',  notes='Came in for test drive of Creta'),
        Lead(dealer_id=dealer.id, agent_id=agents[1].id, vehicle_id=cars[2].id, customer_name='Sunita Patel',
             customer_phone='9000000003', source='referral', stage='negotiation', notes='Negotiating price for Nexon EV', budget=1400000),
        Lead(dealer_id=dealer.id, agent_id=None,          customer_name='Rahul Gupta',
             customer_phone='9000000004', source='phone', stage='new', notes='Called about SUV options'),
    ]
    db.session.add_all(leads)
    db.session.commit()

    deal = Deal(
        dealer_id=dealer.id, vehicle_id=cars[3].id, customer_name='Vikram Singh',
        customer_phone='9000000005', asking_price=1100000, final_price=1020000,
        payment_mode='loan', loan_amount=800000, down_payment=220000,
        emi_months=60, emi_amount=17500, bank_name='HDFC Bank',
        status='delivered', gst_amount=183600, total_amount=1203600
    )
    db.session.add(deal)
    db.session.commit()

    # Seed demo KYC record linked to the existing demo files on disk
    kyc = DealerKYC(
        dealer_id=dealer.id,
        aadhaar_front='aadhaar-front.png',
        aadhaar_back='aadhaar-back.png',
        pan_card='pan-card.png',
        kyc_status='pending',
    )
    db.session.add(kyc)
    db.session.commit()


class DealerKYC(db.Model):
    """KYC documents submitted by dealers for admin verification."""
    __tablename__ = 'dealer_kyc'
    id = db.Column(db.Integer, primary_key=True)
    dealer_id = db.Column(db.Integer, db.ForeignKey(
        'users.id', ondelete='CASCADE'), nullable=False, unique=True)
    aadhaar_front = db.Column(db.String(255), nullable=True)
    aadhaar_back = db.Column(db.String(255), nullable=True)
    pan_card = db.Column(db.String(255), nullable=True)
    # Per-document statuses: pending | approved | rejected
    aadhaar_front_status = db.Column(db.String(20), default='pending')
    aadhaar_back_status = db.Column(db.String(20), default='pending')
    pan_card_status = db.Column(db.String(20), default='pending')
    # Per-document rejection reasons
    aadhaar_front_reject = db.Column(db.Text, nullable=True)
    aadhaar_back_reject = db.Column(db.Text, nullable=True)
    pan_card_reject = db.Column(db.Text, nullable=True)
    # Per-document reviewed_by / reviewed_at
    aadhaar_front_reviewed_by = db.Column(db.String(100), nullable=True)
    aadhaar_front_reviewed_at = db.Column(db.DateTime, nullable=True)
    aadhaar_back_reviewed_by = db.Column(db.String(100), nullable=True)
    aadhaar_back_reviewed_at = db.Column(db.DateTime, nullable=True)
    pan_card_reviewed_by = db.Column(db.String(100), nullable=True)
    pan_card_reviewed_at = db.Column(db.DateTime, nullable=True)
    # Overall KYC status: pending | approved | rejected
    # 'approved' only when ALL 3 docs are approved
    kyc_status = db.Column(db.String(20), default='pending')
    rejection_reason = db.Column(db.Text, nullable=True)
    submitted_at = db.Column(db.DateTime, default=_now_ist)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.String(100), nullable=True)

    dealer = db.relationship(
        'User', backref=db.backref('kyc_record', uselist=False,
                                   cascade='all, delete-orphan',
                                   single_parent=True))

    def recalculate_status(self):
        """Auto-update overall kyc_status based on per-doc statuses."""
        doc_fields = ['aadhaar_front', 'aadhaar_back', 'pan_card']
        statuses = [getattr(self, f + '_status') or 'pending' for f in doc_fields]
        if all(s == 'approved' for s in statuses):
            self.kyc_status = 'approved'
        elif any(s == 'rejected' for s in statuses):
            self.kyc_status = 'rejected'
        else:
            self.kyc_status = 'pending'

    def __getitem__(self, key):
        """Support bracket-style access: kyc['aadhaar_front'] == kyc.aadhaar_front"""
        return getattr(self, key)

    def __repr__(self):
        return f'<DealerKYC dealer_id={self.dealer_id} status={self.kyc_status}>'


class DealerNotification(db.Model):
    """Notifications sent to dealers (KYC approvals, rejections, etc.)."""
    __tablename__ = 'dealer_notifications'
    id = db.Column(db.Integer, primary_key=True)
    dealer_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notif_type = db.Column(db.String(30), default='info')  # success | warning | danger | info
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=_now_ist)

    dealer = db.relationship('User', backref=db.backref('notifications', lazy='dynamic', cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<DealerNotification dealer_id={self.dealer_id} title={self.title}>'


class SubAdmin(db.Model):
    """Sub-admin accounts created by the main admin."""
    __tablename__ = 'sub_admins'
    id = db.Column(db.Integer, primary_key=True)
    display_id = db.Column(db.String(20), unique=True, nullable=True)  # SA1, SA2, SA3 ...
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    # Permissions as comma-separated string
    permissions = db.Column(db.String(500), default='dealers,vehicles,leads,kyc')
    created_at = db.Column(db.DateTime, default=_now_ist)
    last_login = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.String(100), default='admin')

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

    def get_permissions(self):
        return [p.strip() for p in (self.permissions or '').split(',') if p.strip()]

    def has_permission(self, perm):
        return perm in self.get_permissions()

    def __repr__(self):
        return f'<SubAdmin {self.username}>'


# ═══════════════════════════════════════════════════════════════════════════════
# LEAD IMPORT & ASSIGNMENT MODULE — New Models
# ═══════════════════════════════════════════════════════════════════════════════

class LeadImportFile(db.Model):
    """Tracks every CSV/Excel file imported by admin."""
    __tablename__ = 'lead_import_files'

    id            = db.Column(db.Integer, primary_key=True)
    file_name     = db.Column(db.String(255), nullable=False)   # original filename
    stored_name   = db.Column(db.String(255), nullable=True)    # uuid-based stored name
    file_type     = db.Column(db.String(10),  nullable=False)   # csv / xlsx / xls
    total_rows    = db.Column(db.Integer, default=0)
    imported_rows = db.Column(db.Integer, default=0)
    duplicate_rows= db.Column(db.Integer, default=0)
    failed_rows   = db.Column(db.Integer, default=0)
    uploaded_by   = db.Column(db.String(100), default='admin')
    status        = db.Column(db.String(20),  default='processing')  # processing|done|failed
    error_message = db.Column(db.Text, nullable=True)
    uploaded_at   = db.Column(db.DateTime, default=_now_ist)

    # relationship to leads created from this file
    imported_leads = db.relationship('ImportedLead', back_populates='import_file',
                                     cascade='all, delete-orphan', lazy='dynamic')

    def to_dict(self):
        return {
            'id':             self.id,
            'file_name':      self.file_name,
            'file_type':      self.file_type,
            'total_rows':     self.total_rows,
            'imported_rows':  self.imported_rows,
            'duplicate_rows': self.duplicate_rows,
            'failed_rows':    self.failed_rows,
            'uploaded_by':    self.uploaded_by,
            'status':         self.status,
            'uploaded_at':    self.uploaded_at.isoformat() if self.uploaded_at else None,
        }

    def __repr__(self):
        return f'<LeadImportFile {self.file_name}>'


class ImportedLead(db.Model):
    """A lead record created via CSV/Excel import — fully self-contained."""
    __tablename__ = 'imported_leads'

    id              = db.Column(db.Integer, primary_key=True)
    import_file_id  = db.Column(db.Integer, db.ForeignKey('lead_import_files.id',
                                                          ondelete='SET NULL'), nullable=True)
    # core fields
    name            = db.Column(db.String(150), nullable=False)
    phone           = db.Column(db.String(30),  nullable=False)
    email           = db.Column(db.String(150), nullable=True)
    company         = db.Column(db.String(150), nullable=True)
    address         = db.Column(db.String(300), nullable=True)
    source          = db.Column(db.String(100), default='Import')
    # extra columns captured from file
    extra_data      = db.Column(db.Text, nullable=True)  # JSON string of extra columns

    # assignment
    assigned_dealer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    assigned_at        = db.Column(db.DateTime, nullable=True)
    assigned_by        = db.Column(db.String(100), nullable=True)

    # status
    status          = db.Column(db.String(30), default='New')
    # New | Assigned | Contacted | Follow-up | Converted | Rejected

    created_at      = db.Column(db.DateTime, default=_now_ist)
    updated_at      = db.Column(db.DateTime, default=_now_ist, onupdate=_now_ist)

    # relationships
    import_file     = db.relationship('LeadImportFile', back_populates='imported_leads')
    assigned_dealer = db.relationship('User', foreign_keys=[assigned_dealer_id],
                                      backref=db.backref('imported_leads', lazy='dynamic'))

    def get_extra(self):
        import json
        try:
            return json.loads(self.extra_data) if self.extra_data else {}
        except Exception:
            return {}

    def to_dict(self):
        return {
            'id':               self.id,
            'import_file_id':   self.import_file_id,
            'import_file_name': self.import_file.file_name if self.import_file else '—',
            'name':             self.name,
            'phone':            self.phone,
            'email':            self.email,
            'company':          self.company,
            'address':          self.address,
            'source':           self.source,
            'extra_data':       self.get_extra(),
            'assigned_dealer_id': self.assigned_dealer_id,
            'assigned_dealer':  self.assigned_dealer.name if self.assigned_dealer else None,
            'assigned_at':      self.assigned_at.isoformat() if self.assigned_at else None,
            'status':           self.status,
            'created_at':       self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<ImportedLead {self.name} - {self.status}>'


class LeadAssignmentHistory(db.Model):
    """Audit trail for every dealer assignment on an ImportedLead."""
    __tablename__ = 'lead_assignment_history'

    id              = db.Column(db.Integer, primary_key=True)
    lead_id         = db.Column(db.Integer, db.ForeignKey('imported_leads.id',
                                                          ondelete='CASCADE'), nullable=False)
    dealer_id       = db.Column(db.Integer, db.ForeignKey('users.id',
                                                          ondelete='SET NULL'), nullable=True)
    dealer_name     = db.Column(db.String(150), nullable=True)   # snapshot
    assigned_by     = db.Column(db.String(100), default='admin')
    action          = db.Column(db.String(30),  default='assigned')  # assigned | reassigned | unassigned
    notes           = db.Column(db.Text, nullable=True)
    assigned_at     = db.Column(db.DateTime, default=_now_ist)

    lead   = db.relationship('ImportedLead', backref=db.backref('assignment_history',
                                                                 lazy='dynamic',
                                                                 order_by='LeadAssignmentHistory.assigned_at.desc()'))
    dealer = db.relationship('User', foreign_keys=[dealer_id])

    def __repr__(self):
        return f'<LeadAssignmentHistory lead={self.lead_id} dealer={self.dealer_name}>'


class VisitorLog(db.Model):
    """Tracks public website visitors — IP, browser, device, page, country."""
    __tablename__ = 'visitor_logs'

    id               = db.Column(db.Integer,     primary_key=True)
    ip_address       = db.Column(db.String(45),  nullable=False, default='unknown')
    country          = db.Column(db.String(100), nullable=True)
    city             = db.Column(db.String(100), nullable=True)
    browser          = db.Column(db.String(80),  nullable=True)
    operating_system = db.Column(db.String(80),  nullable=True)
    device_type      = db.Column(db.String(20),  nullable=True)   # Desktop / Mobile / Tablet
    page_url         = db.Column(db.String(500), nullable=True)
    referrer         = db.Column(db.String(500), nullable=True)
    # Stable anonymous id grouping multiple page visits from the same browser session.
    session_id       = db.Column(db.String(64),  nullable=True)
    # If the visitor was logged in at the time of this page view (dealer/user
    # account), their identity is captured here — nullable, since most public
    # visitors are anonymous. Lets the Visitor Logs page show WHO a visit
    # belongs to, not just where it came from.
    user_id          = db.Column(db.Integer,     nullable=True)
    visitor_name     = db.Column(db.String(100), nullable=True)
    visitor_role     = db.Column(db.String(30),  nullable=True)   # Dealer | User
    visited_at       = db.Column(db.DateTime,    default=_now_ist)
    created_at       = db.Column(db.DateTime,    default=_now_ist)

    def __repr__(self):
        return f'<VisitorLog {self.ip_address} {self.page_url}>'


# ─────────────────────────────────────────────────────────────────────────────
# KYC REVIEW AUDIT TABLE
# ─────────────────────────────────────────────────────────────────────────────

class KYCReview(db.Model):
    """
    Full audit trail for every KYC approve / reject / reset action.

    document_type values:
        aadhaar_front | aadhaar_back | pan_card | complete_kyc

    status values:
        approved | rejected | reset | pending

    Soft-delete via deleted_at (NULL = active record).
    """
    __tablename__ = 'kyc_reviews'

    id                  = db.Column(db.Integer,     primary_key=True)
    dealer_id           = db.Column(db.Integer,     db.ForeignKey('users.id', ondelete='CASCADE'),
                                    nullable=False, index=True)
    # aadhaar_front | aadhaar_back | pan_card | complete_kyc
    document_type       = db.Column(db.String(30),  nullable=False)
    # approved | rejected | reset | pending
    status              = db.Column(db.String(20),  nullable=False)
    reason              = db.Column(db.Text,         nullable=True)
    # snapshot of previous status before this action
    previous_status     = db.Column(db.String(20),  nullable=True)
    reviewed_by         = db.Column(db.String(100), nullable=False, default='admin')
    reviewed_by_id      = db.Column(db.Integer,     nullable=True)   # sub-admin id if applicable
    reviewed_at         = db.Column(db.DateTime,    default=_now_ist)
    created_at          = db.Column(db.DateTime,    default=_now_ist)
    updated_at          = db.Column(db.DateTime,    default=_now_ist, onupdate=_now_ist)
    # soft-delete: set deleted_at to remove from active views, keep for audit
    deleted_at          = db.Column(db.DateTime,    nullable=True)

    dealer = db.relationship('User', foreign_keys=[dealer_id],
                             backref=db.backref('kyc_reviews', lazy='dynamic',
                                                order_by='KYCReview.reviewed_at.desc()'))

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def soft_delete(self):
        self.deleted_at = _now_ist()

    def to_dict(self):
        return {
            'id':             self.id,
            'dealer_id':      self.dealer_id,
            'document_type':  self.document_type,
            'status':         self.status,
            'reason':         self.reason,
            'previous_status': self.previous_status,
            'reviewed_by':    self.reviewed_by,
            'reviewed_at':    self.reviewed_at.isoformat() if self.reviewed_at else None,
            'deleted_at':     self.deleted_at.isoformat() if self.deleted_at else None,
        }

    def __repr__(self):
        return f'<KYCReview dealer={self.dealer_id} doc={self.document_type} status={self.status}>'


# ─────────────────────────────────────────────────────────────────────────────
# Razorpay Payment Orders — tracks every payment attempt for subscriptions
# ─────────────────────────────────────────────────────────────────────────────
class PaymentOrder(db.Model):
    __tablename__ = 'payment_orders'

    id              = db.Column(db.Integer,     primary_key=True)
    dealer_id       = db.Column(db.Integer,     db.ForeignKey('users.id'), nullable=False)
    razorpay_order_id   = db.Column(db.String(100), unique=True, nullable=False)
    razorpay_payment_id = db.Column(db.String(100), nullable=True)   # filled after success
    razorpay_signature  = db.Column(db.String(256), nullable=True)   # filled after success
    plan            = db.Column(db.String(50),  nullable=False)       # starter/growth/pro
    amount_paise    = db.Column(db.Integer,     nullable=False)       # amount in paise (₹2999 = 299900)
    currency        = db.Column(db.String(10),  default='INR')
    status          = db.Column(db.String(30),  default='created')   # created / paid / failed
    created_at      = db.Column(db.DateTime,    default=_now_ist)
    paid_at         = db.Column(db.DateTime,    nullable=True)

    dealer = db.relationship('User', foreign_keys=[dealer_id])

    def to_dict(self):
        return {
            'id':                   self.id,
            'dealer_id':            self.dealer_id,
            'razorpay_order_id':    self.razorpay_order_id,
            'razorpay_payment_id':  self.razorpay_payment_id,
            'plan':                 self.plan,
            'amount_paise':         self.amount_paise,
            'status':               self.status,
            'created_at':           self.created_at.isoformat() if self.created_at else None,
            'paid_at':              self.paid_at.isoformat() if self.paid_at else None,
        }

    def __repr__(self):
        return f'<PaymentOrder {self.razorpay_order_id} {self.status}>'


# ─────────────────────────────────────────────────────────────────────────────
# Dealer Subscription — current/active subscription record for a dealer.
# Demo payment flow today; designed so Razorpay can be plugged in later
# without changing this schema (see RAZORPAY_ENABLED in dealer/routes.py).
# ─────────────────────────────────────────────────────────────────────────────
class DealerSubscription(db.Model):
    __tablename__ = 'dealer_subscriptions'

    id              = db.Column(db.Integer,     primary_key=True)
    dealer_id       = db.Column(db.Integer,     db.ForeignKey('users.id'), nullable=False)
    plan_name       = db.Column(db.String(50),  nullable=False)        # starter/growth/pro
    price           = db.Column(db.Integer,     default=0)             # ₹ per month
    payment_method  = db.Column(db.String(20),  default='Demo')        # Demo / Free / Razorpay
    payment_status  = db.Column(db.String(30),  default='Pending')     # Pending / Free Trial / Paid / Active
    transaction_id  = db.Column(db.String(100), nullable=True)
    activated_at    = db.Column(db.DateTime,    default=_now_ist)
    expires_at      = db.Column(db.DateTime,    nullable=True)
    is_active       = db.Column(db.Boolean,     default=True)
    created_at      = db.Column(db.DateTime,    default=_now_ist)
    updated_at      = db.Column(db.DateTime,    default=_now_ist, onupdate=_now_ist)

    dealer = db.relationship('User', foreign_keys=[dealer_id])
    payments = db.relationship('DealerPayment', backref='subscription', lazy='dynamic',
                                order_by='DealerPayment.created_at.desc()')

    def to_dict(self):
        return {
            'id':             self.id,
            'dealer_id':      self.dealer_id,
            'plan_name':      self.plan_name,
            'price':          self.price,
            'payment_method': self.payment_method,
            'payment_status': self.payment_status,
            'transaction_id': self.transaction_id,
            'activated_at':   self.activated_at.isoformat() if self.activated_at else None,
            'expires_at':     self.expires_at.isoformat() if self.expires_at else None,
            'is_active':      self.is_active,
        }

    def __repr__(self):
        return f'<DealerSubscription dealer={self.dealer_id} plan={self.plan_name} active={self.is_active}>'


# ─────────────────────────────────────────────────────────────────────────────
# Dealer Payment — one row per payment attempt (demo or, later, real Razorpay)
# ─────────────────────────────────────────────────────────────────────────────
class DealerPayment(db.Model):
    __tablename__ = 'dealer_payments'

    id              = db.Column(db.Integer,     primary_key=True)
    dealer_id       = db.Column(db.Integer,     db.ForeignKey('users.id'), nullable=False)
    subscription_id = db.Column(db.Integer,     db.ForeignKey('dealer_subscriptions.id'), nullable=True)
    amount          = db.Column(db.Integer,     default=0)
    payment_method  = db.Column(db.String(20),  default='Demo')        # Demo / Free / Razorpay
    payment_status  = db.Column(db.String(30),  default='Pending')     # Pending / Free Trial / Paid / Failed
    transaction_id  = db.Column(db.String(100), nullable=True)
    notes           = db.Column(db.Text,        nullable=True)
    created_at      = db.Column(db.DateTime,    default=_now_ist)

    dealer = db.relationship('User', foreign_keys=[dealer_id])

    def to_dict(self):
        return {
            'id':              self.id,
            'dealer_id':       self.dealer_id,
            'subscription_id': self.subscription_id,
            'amount':          self.amount,
            'payment_method':  self.payment_method,
            'payment_status':  self.payment_status,
            'transaction_id':  self.transaction_id,
            'notes':           self.notes,
            'created_at':      self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<DealerPayment dealer={self.dealer_id} amount={self.amount} status={self.payment_status}>'
