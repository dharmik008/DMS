"""
minisite/routes.py — Caryanams Mini Dealer Website

Each dealer gets a public mini-website at:
    /caryanams/<dealer_name>/<website_name>/

Pages:
  home          /caryanams/<dealer_name>/<website_name>/
  inventory     /caryanams/<dealer_name>/<website_name>/inventory
  car details   /caryanams/<dealer_name>/<website_name>/car/<int:car_id>
  about/profile /caryanams/<dealer_name>/<website_name>/about
  contact       /caryanams/<dealer_name>/<website_name>/contact
  deals         /caryanams/<dealer_name>/<website_name>/deals
  dashboard     /caryanams/<dealer_name>/<website_name>/dashboard

Data is pulled live from the same DB — no duplication.
Images are resolved from the same static folders as the DMS.
"""

import os
from functools import wraps
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, jsonify, current_app, g, session
)
from models import db, User, Vehicle, VehicleImage, Inquiry, Lead, Deal
from sqlalchemy import or_, func
from subscription_features import feature_required, feature_allowed

minisite_bp = Blueprint('minisite', __name__, template_folder='../templates/minisite')

@minisite_bp.before_request
def track_visitor():
    from utils.visitor_tracker import log_visit
    from flask import request as _req
    log_visit(_req)


# ─────────────────────────────────────────────────────────────────────────────
# Image resolution helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_image_filename(raw: str | None) -> str | None:
    """
    Turn any image reference stored in the DB into a URL-safe filename
    that exists under static/.

    Handles:
      • None / 'None' / empty string → return None (show default)
      • Windows absolute path (contains backslash or drive letter) → extract basename
      • proc_<id>.jpg  → lives in static/processed/
      • nobg_<id>.png  → lives in static/processed/
      • anything else  → lives in static/images/uploads/
    """
    if not raw or raw == 'None':
        return None

    # Strip Windows or Unix absolute paths to just the filename
    basename = os.path.basename(raw.replace('\\', '/'))
    if not basename:
        return None

    root = current_app.root_path

    # processed/ files (proc_*.jpg  or  nobg_*.png)
    if basename.startswith(('proc_', 'nobg_')):
        if os.path.exists(os.path.join(root, 'static', 'processed', basename)):
            return ('processed', basename)
        return None

    # uploads/ files
    if os.path.exists(os.path.join(root, 'static', 'images', 'uploads', basename)):
        return ('uploads', basename)

    return None


def _image_url(raw: str | None) -> str | None:
    """Return a static URL string for an image reference, or None."""
    result = _resolve_image_filename(raw)
    if result is None:
        return None
    folder, basename = result
    if folder == 'processed':
        return '/static/processed/' + basename
    return '/static/images/uploads/' + basename


def _best_image_url(vehicle_dict: dict) -> str | None:
    """
    Pick the best display image for a vehicle dict:
    1. Front-typed image from extra_images_typed (the actual front photo)
    2. First extra_image by sort order
    3. image_filename (may be a studio-processed file)
    4. None → caller should show default
    """
    # Priority 1: front-typed image specifically
    for img in vehicle_dict.get('extra_images_typed') or []:
        if img.get('image_type') == 'front':
            url = _image_url(img['filename'])
            if url:
                return url
    # Priority 2: first available extra image by sort order
    for img in vehicle_dict.get('extra_images') or []:
        url = _image_url(img)
        if url:
            return url
    # Priority 3: image_filename cover
    return _image_url(vehicle_dict.get('image_filename'))


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_dealer_by_wname(website_name: str):
    """
    Return dealer User by website_name.

    Lookup order:
      1. Exact match on website_name column
      2. Case-insensitive match on website_name column (handles /dealer/ABC vs stored 'abc')
      3. Fallback: case-insensitive match on dealer's actual name
    """
    if not website_name:
        return None
    # 1. Exact
    dealer = User.query.filter_by(role='dealer', website_name=website_name).first()
    if dealer:
        return dealer
    # 2. Case-insensitive slug match
    dealer = User.query.filter(
        User.role == 'dealer',
        User.website_name.ilike(website_name)
    ).first()
    if dealer:
        return dealer
    # 3. Fallback to dealer name
    dealer = User.query.filter(
        User.role == 'dealer',
        User.name.ilike(website_name)
    ).first()
    return dealer


def _minisite_enabled(dealer: User) -> bool:
    """Mini Website (the public storefront) is a Pro-plan-only feature."""
    if not dealer:
        return False
    from subscription_features import plan_has_feature
    return plan_has_feature(getattr(dealer, 'subscription_plan', None), 'mini_website')


def _dealer_logo_ctx(dealer: User) -> dict:
    """Return logo display context for templates."""
    if dealer.website_logo:
        return {'logo_type': 'image', 'logo_value': dealer.website_logo}
    display_name = dealer.website_name or dealer.name or 'D'
    return {'logo_type': 'letter', 'logo_value': display_name[0].upper()}


def _build_vehicle_dict(v: Vehicle) -> dict:
    """Convert Vehicle ORM object to dict with extra_images and resolved image URLs."""
    imgs = (
        VehicleImage.query
        .filter_by(vehicle_id=v.id)
        .order_by(VehicleImage.sort_order, VehicleImage.id)
        .all()
    )
    extra_filenames = [i.filename for i in imgs]

    d = {
        **v.to_dict(),
        'extra_images': extra_filenames,
        # Include typed image data so templates can show labelled gallery
        'extra_images_typed': [
            {'filename': i.filename, 'image_type': i.image_type}
            for i in imgs
        ],
    }

    # Attach resolved URLs so templates never have to guess the folder
    d['display_image_url'] = _best_image_url(d)
    d['all_image_urls'] = []

    # Build ordered list: mandatory typed images front-first, then gallery, then cover
    ORDERED_TYPES = ['front','rear','right_side','left_side','engine','boot','interior','gallery']
    seen = set()

    for t in ORDERED_TYPES:
        for img in imgs:
            if img.image_type == t:
                url = _image_url(img.filename)
                if url and url not in seen:
                    d['all_image_urls'].append(url)
                    seen.add(url)

    # Only prepend image_filename cover if no front-typed image was found in gallery
    # This prevents the "extra unwanted image" when image_filename differs from
    # the VehicleImage front record (both are the same photo, different UUID files)
    has_front_typed = any(
        img.image_type == 'front'
        for img in imgs
    )
    cover_url = _image_url(d.get('image_filename'))
    if cover_url and cover_url not in seen and not has_front_typed:
        d['all_image_urls'].insert(0, cover_url)

    return d


# ─── Auth decorator for dashboard ────────────────────────────────────────────

def _require_dealer_auth(website_name_param='website_name'):
    """
    Decorator: only lets the logged-in dealer whose website_name matches
    the URL parameter through. Redirects to DMS login otherwise.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            website_name = kwargs.get(website_name_param) or (args[1] if len(args) > 1 else args[0])
            uid = session.get('user_id')
            if not uid:
                flash('Please log in to access the dashboard.', 'error')
                return redirect(url_for('auth.login', returnUrl=request.full_path.rstrip('?')))
            dealer = _get_dealer_by_wname(website_name)
            if not dealer or dealer.id != uid:
                flash('Access denied.', 'error')
                return redirect(url_for('auth.login', returnUrl=request.full_path.rstrip('?')))
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ─── Home ─────────────────────────────────────────────────────────────────────

@minisite_bp.route('/caryanams/<dealer_name>/<website_name>/')
@minisite_bp.route('/caryanams/<dealer_name>/<website_name>')
def home(dealer_name, website_name):
    dealer = _get_dealer_by_wname(website_name)
    if not dealer or not _minisite_enabled(dealer):
        return render_template('minisite/404.html'), 404

    featured = (
        Vehicle.query
        .filter_by(dealer_id=dealer.id, status='available', featured=True)
        .order_by(Vehicle.created_at.desc())
        .limit(6).all()
    )
    if len(featured) < 3:
        extra = (
            Vehicle.query
            .filter_by(dealer_id=dealer.id, status='available', featured=False)
            .order_by(Vehicle.created_at.desc())
            .limit(6 - len(featured)).all()
        )
        featured = featured + extra

    featured_dicts = [_build_vehicle_dict(v) for v in featured]
    logo_ctx = _dealer_logo_ctx(dealer)

    return render_template(
        'minisite/home.html',
        dealer=dealer,
        website_name=website_name, dealer_name=dealer_name,
        featured=featured_dicts,
        **logo_ctx,
    )


# ─── Inventory ────────────────────────────────────────────────────────────────

@minisite_bp.route('/caryanams/<dealer_name>/<website_name>/inventory')
def inventory(dealer_name, website_name):
    dealer = _get_dealer_by_wname(website_name)
    if not dealer or not _minisite_enabled(dealer):
        return render_template('minisite/404.html'), 404

    brand        = request.args.get('brand', '').strip()
    fuel         = request.args.get('fuel', '').strip()
    transmission = request.args.get('transmission', '').strip()
    min_price    = request.args.get('min_price', type=float)
    max_price    = request.args.get('max_price', type=float)
    sort         = request.args.get('sort', 'newest')
    page         = request.args.get('page', 1, type=int)
    per_page     = 12

    q = Vehicle.query.filter_by(dealer_id=dealer.id, status='available')

    if brand:
        q = q.filter(Vehicle.make.ilike(f'%{brand}%'))
    if fuel:
        q = q.filter(Vehicle.fuel_type.ilike(f'%{fuel}%'))
    if transmission:
        q = q.filter(Vehicle.transmission.ilike(f'%{transmission}%'))
    if min_price is not None:
        q = q.filter(Vehicle.price >= min_price)
    if max_price is not None:
        q = q.filter(Vehicle.price <= max_price)

    if sort == 'price_asc':
        q = q.order_by(Vehicle.price.asc())
    elif sort == 'price_desc':
        q = q.order_by(Vehicle.price.desc())
    else:
        q = q.order_by(Vehicle.created_at.desc())

    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    vehicles   = [_build_vehicle_dict(v) for v in pagination.items]

    brands = [
        r[0] for r in db.session.query(Vehicle.make)
        .filter_by(dealer_id=dealer.id, status='available')
        .distinct().order_by(Vehicle.make).all()
    ]

    logo_ctx = _dealer_logo_ctx(dealer)

    return render_template(
        'minisite/inventory.html',
        dealer=dealer,
        website_name=website_name, dealer_name=dealer_name,
        vehicles=vehicles,
        pagination=pagination,
        brands=brands,
        filters={'brand': brand, 'fuel': fuel, 'transmission': transmission,
                 'min_price': min_price, 'max_price': max_price, 'sort': sort},
        **logo_ctx,
    )


# ─── Car Details ──────────────────────────────────────────────────────────────

@minisite_bp.route('/caryanams/<dealer_name>/<website_name>/car/<int:car_id>')
def car_detail(dealer_name, website_name, car_id):
    dealer = _get_dealer_by_wname(website_name)
    if not dealer or not _minisite_enabled(dealer):
        return render_template('minisite/404.html'), 404

    vehicle_obj = Vehicle.query.filter_by(id=car_id, dealer_id=dealer.id).first()
    if not vehicle_obj:
        return render_template('minisite/404.html'), 404

    vehicle  = _build_vehicle_dict(vehicle_obj)
    logo_ctx = _dealer_logo_ctx(dealer)

    similar = (
        Vehicle.query
        .filter(
            Vehicle.dealer_id == dealer.id,
            Vehicle.status == 'available',
            Vehicle.id != car_id,
            or_(Vehicle.make == vehicle_obj.make, Vehicle.fuel_type == vehicle_obj.fuel_type)
        )
        .limit(4).all()
    )
    similar_dicts = [_build_vehicle_dict(v) for v in similar]

    return render_template(
        'minisite/car_detail.html',
        dealer=dealer,
        website_name=website_name, dealer_name=dealer_name,
        vehicle=vehicle,
        similar=similar_dicts,
        **logo_ctx,
    )


# ─── About / Profile ─────────────────────────────────────────────────────────

@minisite_bp.route('/caryanams/<dealer_name>/<website_name>/about')
def about(dealer_name, website_name):
    dealer = _get_dealer_by_wname(website_name)
    if not dealer or not _minisite_enabled(dealer):
        return render_template('minisite/404.html'), 404

    total_vehicles = Vehicle.query.filter_by(dealer_id=dealer.id, status='available').count()
    logo_ctx       = _dealer_logo_ctx(dealer)

    return render_template(
        'minisite/about.html',
        dealer=dealer,
        website_name=website_name, dealer_name=dealer_name,
        total_vehicles=total_vehicles,
        **logo_ctx,
    )


# ─── Contact ──────────────────────────────────────────────────────────────────

@minisite_bp.route('/caryanams/<dealer_name>/<website_name>/contact', methods=['GET', 'POST'])
def contact(dealer_name, website_name):
    dealer = _get_dealer_by_wname(website_name)
    if not dealer or not _minisite_enabled(dealer):
        return render_template('minisite/404.html'), 404

    if request.method == 'POST':
        inq = Inquiry(
            dealer_id=dealer.id,
            vehicle_id=None,
            name=request.form.get('name', ''),
            email=request.form.get('email', ''),
            phone=request.form.get('phone', ''),
            message=request.form.get('message', ''),
            inquiry_type='contact',
            status='pending',
        )
        db.session.add(inq)
        db.session.commit()
        flash('Message sent! We will get back to you soon.', 'success')
        return redirect(url_for('minisite.contact', dealer_name=dealer_name, website_name=website_name))

    logo_ctx = _dealer_logo_ctx(dealer)
    return render_template(
        'minisite/contact.html',
        dealer=dealer,
        website_name=website_name, dealer_name=dealer_name,
        **logo_ctx,
    )


# ─── Featured Deals ──────────────────────────────────────────────────────────

@minisite_bp.route('/caryanams/<dealer_name>/<website_name>/deals')
def featured_deals(dealer_name, website_name):
    dealer = _get_dealer_by_wname(website_name)
    if not dealer or not _minisite_enabled(dealer):
        return render_template('minisite/404.html'), 404

    featured = (
        Vehicle.query
        .filter_by(dealer_id=dealer.id, status='available', featured=True)
        .order_by(Vehicle.created_at.desc())
        .all()
    )
    featured_dicts = [_build_vehicle_dict(v) for v in featured]
    logo_ctx       = _dealer_logo_ctx(dealer)

    return render_template(
        'minisite/featured_deals.html',
        dealer=dealer,
        website_name=website_name, dealer_name=dealer_name,
        featured=featured_dicts,
        **logo_ctx,
    )


# ─── Minisite Dashboard (dealer-authenticated) ────────────────────────────────

@minisite_bp.route('/caryanams/<dealer_name>/<website_name>/dashboard')
@_require_dealer_auth()
@feature_required('mini_website')
def dashboard(dealer_name, website_name):
    dealer = _get_dealer_by_wname(website_name)

    # ── Inventory overview ────────────────────────────────────────────────────
    total_vehicles   = Vehicle.query.filter_by(dealer_id=dealer.id).count()
    available        = Vehicle.query.filter_by(dealer_id=dealer.id, status='available').count()
    sold             = Vehicle.query.filter_by(dealer_id=dealer.id, status='sold').count()
    reserved         = Vehicle.query.filter_by(dealer_id=dealer.id, status='reserved').count()
    featured_count   = Vehicle.query.filter_by(dealer_id=dealer.id, featured=True, status='available').count()

    # ── Lead stats ────────────────────────────────────────────────────────────
    total_leads   = Lead.query.filter_by(dealer_id=dealer.id).count()
    new_leads     = Lead.query.filter_by(dealer_id=dealer.id, stage='new').count()
    open_inquiries = Inquiry.query.filter_by(dealer_id=dealer.id, status='pending').count()

    # ── Deal stats ────────────────────────────────────────────────────────────
    total_deals    = Deal.query.filter_by(dealer_id=dealer.id).count()
    closed_deals   = Deal.query.filter_by(dealer_id=dealer.id, status='delivered').count()
    total_revenue  = (
        db.session.query(func.sum(Deal.final_price))
        .filter_by(dealer_id=dealer.id, status='delivered')
        .scalar() or 0
    )

    # ── Recent activity ───────────────────────────────────────────────────────
    recent_vehicles = (
        Vehicle.query
        .filter_by(dealer_id=dealer.id)
        .order_by(Vehicle.created_at.desc())
        .limit(8).all()
    )
    recent_vehicles_dicts = [_build_vehicle_dict(v) for v in recent_vehicles]

    recent_leads = (
        Lead.query
        .filter_by(dealer_id=dealer.id)
        .order_by(Lead.created_at.desc())
        .limit(5).all()
    )

    recent_inquiries = (
        Inquiry.query
        .filter_by(dealer_id=dealer.id)
        .order_by(Inquiry.created_at.desc())
        .limit(5).all()
    )

    # ── Fuel type breakdown ───────────────────────────────────────────────────
    fuel_breakdown = (
        db.session.query(Vehicle.fuel_type, func.count(Vehicle.id))
        .filter_by(dealer_id=dealer.id, status='available')
        .group_by(Vehicle.fuel_type)
        .all()
    )

    # ── Price band breakdown ──────────────────────────────────────────────────
    bands = [
        ('Under ₹5L',     0,       500000),
        ('₹5L–₹10L',  500000,  1000000),
        ('₹10L–₹20L', 1000000, 2000000),
        ('Above ₹20L', 2000000, 999999999),
    ]
    price_bands = []
    for label, lo, hi in bands:
        cnt = Vehicle.query.filter(
            Vehicle.dealer_id == dealer.id,
            Vehicle.status == 'available',
            Vehicle.price >= lo,
            Vehicle.price < hi,
        ).count()
        price_bands.append({'label': label, 'count': cnt})

    logo_ctx = _dealer_logo_ctx(dealer)

    return render_template(
        'minisite/dashboard.html',
        dealer=dealer,
        website_name=website_name, dealer_name=dealer_name,
        # inventory
        total_vehicles=total_vehicles,
        available=available,
        sold=sold,
        reserved=reserved,
        featured_count=featured_count,
        # leads
        total_leads=total_leads,
        new_leads=new_leads,
        open_inquiries=open_inquiries,
        # deals
        total_deals=total_deals,
        closed_deals=closed_deals,
        total_revenue=total_revenue,
        # lists
        recent_vehicles=recent_vehicles_dicts,
        recent_leads=recent_leads,
        recent_inquiries=recent_inquiries,
        fuel_breakdown=fuel_breakdown,
        price_bands=price_bands,
        **logo_ctx,
    )


# ─── Inquiry / Lead Capture (AJAX) ───────────────────────────────────────────

@minisite_bp.route('/caryanams/<dealer_name>/<website_name>/inquiry', methods=['POST'])
def submit_inquiry(dealer_name, website_name):
    dealer = _get_dealer_by_wname(website_name)
    if not dealer or not _minisite_enabled(dealer):
        return jsonify({'success': False, 'error': 'Dealer not found'}), 404

    vehicle_id = request.form.get('vehicle_id', type=int)
    inq = Inquiry(
        dealer_id=dealer.id,
        vehicle_id=vehicle_id,
        name=request.form.get('name', ''),
        email=request.form.get('email', ''),
        phone=request.form.get('phone', ''),
        message=request.form.get('message', ''),
        inquiry_type='vehicle' if vehicle_id else 'general',
        status='pending',
    )
    db.session.add(inq)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Inquiry submitted!'})
