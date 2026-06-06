from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from db import user_get_by_email, user_create, user_count_by_role
from models import db, User
from werkzeug.security import check_password_hash

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = user_get_by_email(email)
        
        if user and user.check_password(password):
            # ── Block suspended dealers ──────────────────────────────────────
            if user.role == 'dealer' and not user.is_active:
                flash('Your account has been suspended. Please contact the admin.', 'error')
                return render_template('auth/login.html')

            session['user_id'] = user.id
            session['user_role'] = user.role
            flash('Login successful!', 'success')
            # Log the login action
            try:
                from models import AdminLog
                role_label = 'Dealer' if user.role == 'dealer' else 'Admin'
                log = AdminLog(
                    admin_user=user.name or email,
                    user_role=role_label,
                    action=f'{role_label} logged in',
                    module='Auth',
                    ip_address=request.remote_addr or '127.0.0.1',
                    status='Success',
                )
                db.session.add(log)
                db.session.commit()
            except Exception:
                pass
            if user.role == 'dealer':
                return redirect(url_for('dealer.dashboard'))
            else:
                return redirect(url_for('user.home'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('auth/login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name     = request.form.get('name')
        email    = request.form.get('email')
        password = request.form.get('password')          # ← FIX: moved up before validation
        confirm_password = request.form.get('confirm_password')
        phone    = request.form.get('phone', '').strip()
        role     = request.form.get('role')
        city     = request.form.get('city')
        company_name = request.form.get('company_name')
        gst_number   = request.form.get('gst_number')

        # Sanitise phone: keep digits only, cap at 10
        phone_digits = ''.join(c for c in phone if c.isdigit())[:10]

        # ── Validation ───────────────────────────────────────────────────────
        if not name or not email or not password:
            flash('Name, email, and password are required.', 'error')
            return redirect(url_for('auth.register'))

        if not phone_digits or len(phone_digits) != 10 or phone_digits[0] not in '6789':
            flash('Please enter a valid 10-digit Indian mobile number (starting with 6–9).', 'error')
            return redirect(url_for('auth.register'))

        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('auth.register'))

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return redirect(url_for('auth.register'))

        # Check if user already exists
        existing = user_get_by_email(email)
        if existing:
            flash('This email is already registered. Please sign in.', 'error')
            return redirect(url_for('auth.register'))

        # Create user — store phone with +91 country code
        user_data = {
            'name': name,
            'email': email,
            'phone': '+91' + phone_digits,
            'role': role,
            'city': city,
            'company_name': company_name if role == 'dealer' else '',
            'gst_number': gst_number if role == 'dealer' else '',
            'password': password
        }
        
        user_id = user_create(user_data)
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('auth.login'))

@auth_bp.route('/role-select')
def role_select():
    return render_template('auth/role_select.html')
