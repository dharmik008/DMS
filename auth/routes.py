from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from db import user_get_by_email, user_create, user_count_by_role
from models import db, User
from werkzeug.security import check_password_hash

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Stash a safe minisite return URL so we can redirect back after login
    if request.method == 'GET':
        return_url = request.args.get('returnUrl', '').strip()
        if return_url.startswith('/dealer/'):
            session['minisite_return_url'] = return_url
        else:
            session.pop('minisite_return_url', None)

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        # Carry the minisite return URL through the POST
        post_return_url = request.form.get('return_url', '').strip()
        if post_return_url.startswith('/dealer/'):
            session['minisite_return_url'] = post_return_url
        
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
            # If the user came from a dealer minisite, send them back there
            minisite_url = session.pop('minisite_return_url', None)
            if minisite_url and minisite_url.startswith('/dealer/'):
                return redirect(minisite_url)
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

        if not phone_digits or len(phone_digits) != 10:
            flash('Please enter a valid 10-digit mobile number.', 'error')
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


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = user_get_by_email(email)
        # Always show success message to prevent email enumeration
        flash('If that email is registered, a password reset link has been sent. Please check your inbox.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/forgot_password.html')

# ── Forgot Password: verify email + phone, then reset ─────────────────────────

@auth_bp.route('/api/forgot-password/verify', methods=['POST'])
def forgot_password_verify():
    """Step 1 — check that email + phone both match a registered account."""
    from flask import jsonify
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    phone_raw = (data.get('phone') or '').strip()

    # Accept 10-digit input or +91XXXXXXXXXX
    phone_digits = ''.join(c for c in phone_raw if c.isdigit())
    if len(phone_digits) == 12 and phone_digits.startswith('91'):
        phone_digits = phone_digits[2:]   # strip country code
    phone_digits = phone_digits[-10:]     # keep last 10

    if not email or len(phone_digits) != 10:
        return jsonify({'success': False, 'message': 'Please enter a valid email and 10-digit mobile number.'})

    # Case-insensitive email lookup so capitalisation differences don't block valid users
    user = User.query.filter(User.email.ilike(email)).first()
    if not user:
        return jsonify({'success': False, 'message': 'No account found with this email address.'})

    # phone stored as "+91XXXXXXXXXX" — compare last 10 digits only
    stored_digits = ''.join(c for c in (user.phone or '') if c.isdigit())[-10:]
    if stored_digits != phone_digits:
        return jsonify({'success': False, 'message': 'Mobile number does not match our records.'})

    # Both match — store a short-lived token in session so the reset step is gated
    import secrets
    token = secrets.token_hex(16)
    session['fp_token'] = token
    session['fp_user_id'] = user.id
    return jsonify({'success': True, 'token': token})


@auth_bp.route('/api/forgot-password/reset', methods=['POST'])
def forgot_password_reset():
    """Step 2 — set a new password; requires the token from step 1."""
    from flask import jsonify
    data = request.get_json(silent=True) or {}
    token = (data.get('token') or '').strip()
    new_password = data.get('password') or ''
    confirm = data.get('confirm') or ''

    if not token or token != session.get('fp_token'):
        return jsonify({'success': False, 'message': 'Session expired. Please start over.'})

    user_id = session.get('fp_user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'Session expired. Please start over.'})

    if len(new_password) < 6:
        return jsonify({'success': False, 'message': 'Password must be at least 6 characters.'})
    if new_password != confirm:
        return jsonify({'success': False, 'message': 'Passwords do not match.'})

    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'message': 'Account not found.'})

    user.set_password(new_password)
    db.session.commit()

    # Clear the token so it cannot be reused
    session.pop('fp_token', None)
    session.pop('fp_user_id', None)

    return jsonify({'success': True, 'message': 'Password changed successfully! Please log in.'})
