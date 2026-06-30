from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g
from functools import wraps

from db import (
    vehicles_public, vehicles_featured, vehicles_latest, vehicles_makes_count,
    vehicles_similar, vehicle_get, inquiry_create, user_get_by_email
)
from models import db, User, VehicleImage

user_bp = Blueprint('user', __name__)


def _log_user_action(action, module, status='Success', description=None):
    """Best-effort activity logger for public-facing user actions (inquiries, etc.)."""
    try:
        from models import AdminLog
        from utils.request_meta import get_request_meta
        ip, browser, os_name, device = get_request_meta(request)
        logged_user = g.user if getattr(g, 'user', None) else None
        log = AdminLog(
            user_id=logged_user.get('id') if logged_user else None,
            admin_user=(logged_user.get('name') if logged_user else 'Guest') or 'Guest',
            user_role='User' if logged_user else 'Guest',
            action=action,
            module=module,
            description=description or action,
            ip_address=ip,
            device=device,
            browser=browser,
            timezone='Asia/Kolkata (IST)',
            status=status,
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        pass


@user_bp.before_request
def track_visitor():
    from utils.visitor_tracker import log_visit
    log_visit(request)

@user_bp.route('/')
def home():
    featured = vehicles_featured(6)
    latest = vehicles_latest(8)
    makes = vehicles_makes_count()
    
    total_cars = sum(m['cnt'] for m in makes)
    total_dealers = User.query.filter_by(role='dealer').count()
    
    return render_template('user/home.html',
        featured=featured,
        latest=latest,
        makes=makes,
        total_cars=total_cars,
        total_dealers=total_dealers
    )

@user_bp.route('/cars')
def listings():
    make = request.args.get('make', '')
    fuel = request.args.get('fuel', '')
    transmission = request.args.get('transmission', '')
    condition = request.args.get('condition', '')
    min_price = request.args.get('min_price', type=int)
    max_price = request.args.get('max_price', type=int)
    min_year = request.args.get('min_year', type=int)
    max_year = request.args.get('max_year', type=int)
    search = request.args.get('search', '')
    sort = request.args.get('sort', 'newest')
    page = request.args.get('page', 1, type=int)
    
    vehicles = vehicles_public(
        make=make, fuel=fuel, transmission=transmission, condition=condition,
        min_price=min_price, max_price=max_price, min_year=min_year, max_year=max_year,
        search=search, sort=sort, page=page
    )
    
    makes = [m['make'] for m in vehicles_makes_count()]
    
    return render_template('user/listings.html',
        vehicles=vehicles,
        makes=makes,
        make=make,
        fuel=fuel,
        transmission=transmission,
        condition=condition,
        min_price=min_price,
        max_price=max_price,
        min_year=min_year,
        max_year=max_year,
        search=search,
        sort=sort
    )

@user_bp.route('/car/<int:vid>')
def car_detail(vid):
    vehicle = vehicle_get(vid)
    
    if not vehicle or vehicle['status'] != 'available':
        flash('Car not found', 'error')
        return redirect(url_for('user.home'))
    
    similar = vehicles_similar(vid, vehicle['make'])
    dealer = None
    
    if vehicle['dealer_id']:
        dealer = User.query.get(vehicle['dealer_id'])
        dealer_dict = {
            'name': dealer.name,
            'company': dealer.company_name,
            'city': dealer.city,
            'phone': dealer.phone
        } if dealer else None
    else:
        dealer_dict = None
    
    # Provide logged-in user info for form pre-fill
    logged_user = g.user if g.user and g.user.get('role') not in ('dealer', 'admin') else None

    return render_template('user/car_detail.html',
        vehicle=vehicle,
        similar=similar,
        dealer=dealer_dict,
        logged_user=logged_user
    )

@user_bp.route('/car/<int:vid>/inquire', methods=['POST'])
def inquire(vid):
    vehicle = vehicle_get(vid)
    
    if not vehicle:
        flash('Vehicle not found', 'error')
        return redirect(url_for('user.home'))
    
    # Use logged-in user's details if available (non-dealer/admin users only)
    logged_user = g.user if g.user and g.user.get('role') not in ('dealer', 'admin') else None

    if logged_user:
        name  = logged_user.get('name') or request.form.get('name')
        phone = logged_user.get('phone') or request.form.get('phone')
        email = logged_user.get('email') or request.form.get('email')
    else:
        name  = request.form.get('name')
        phone = request.form.get('phone')
        email = request.form.get('email')

    inquiry_type = request.form.get('inquiry_type', 'general')

    # Accept a manually-edited message; auto-generate if blank
    message = (request.form.get('message') or '').strip()
    vehicle_name = f"{vehicle['make']} {vehicle['model']}"
    if not message and name:
        message = f"{name} is interested in {vehicle_name} and would like to be contacted with more details."

    if not name or not phone:
        flash('Name and phone are required', 'error')
        return redirect(url_for('user.car_detail', vid=vid))

    inquiry_data = {
        'vehicle_id': vid,
        'dealer_id': vehicle['dealer_id'],
        'name': name,
        'phone': phone,
        'email': email,
        'message': message,
        'inquiry_type': inquiry_type
    }
    
    inquiry_create(inquiry_data)
    _log_user_action(f'Sent inquiry for {vehicle_name}', 'Inquiries',
                      description=f'Inquiry from "{name}" for vehicle #{vid} ({vehicle_name})')
    flash('Inquiry sent successfully! The dealer will contact you soon.', 'success')
    return redirect(url_for('user.car_detail', vid=vid))

@user_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        subject = request.form.get('subject')
        message = request.form.get('message')
        
        if not name or not email or not message:
            flash('Please fill all required fields', 'error')
            return redirect(url_for('user.contact'))
        
        # In a real app, send email or store contact message
        flash('Thank you for your message! We\'ll get back to you soon.', 'success')
        return redirect(url_for('user.contact'))
    
    return render_template('user/contact.html')
