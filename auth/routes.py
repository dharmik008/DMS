from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from db import user_get_by_email, user_create, user_count_by_role, user_get_by_id
from models import db, User
from werkzeug.security import check_password_hash

auth_bp = Blueprint('auth', __name__)


def _log_auth_action(action, module, status='Success', user=None, description=None):
    """
    Shared activity logger for the auth blueprint. Captures real client IP
    (proxy/Cloudflare aware) and device/browser metadata. Best-effort and
    silent on failure so it never blocks login/logout/registration.
    """
    try:
        from models import AdminLog
        from utils.request_meta import get_request_meta
        ip, browser, os_name, device = get_request_meta(request)
        role_label = 'Dealer' if (user and getattr(user, 'role', None) == 'dealer') else 'Admin'
        log = AdminLog(
            user_id=user.id if user else None,
            admin_user=(user.name if user and user.name else (user.email if user else 'unknown')),
            user_role=role_label,
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


@auth_bp.before_request
def track_visitor():
    """Record public auth page visits (login, register) in visitor_logs."""
    from utils.visitor_tracker import log_visit
    log_visit(request)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Stash a safe minisite return URL so we can redirect back after login
    if request.method == 'GET':
        return_url = request.args.get('returnUrl', '').strip()
        if return_url.startswith('/dealer/') or return_url.startswith('/caryanams/'):
            session['minisite_return_url'] = return_url
        else:
            session.pop('minisite_return_url', None)

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        # Carry the minisite return URL through the POST
        post_return_url = request.form.get('return_url', '').strip()
        if post_return_url.startswith('/dealer/') or post_return_url.startswith('/caryanams/'):
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
            role_label = 'Dealer' if user.role == 'dealer' else 'Admin'
            _log_auth_action(f'{role_label} logged in', 'Auth', user=user)
            # If the user came from a dealer minisite, send them back there
            minisite_url = session.pop('minisite_return_url', None)
            if minisite_url and (minisite_url.startswith('/dealer/') or minisite_url.startswith('/caryanams/')):
                return redirect(minisite_url)
            if user.role == 'dealer':
                return redirect(url_for('dealer.dashboard'))
            else:
                return redirect(url_for('user.home'))
        else:
            # Log failed login attempt (username/email as typed; no valid user
            # record may exist, so user=None and the email is shown via description)
            _log_auth_action(
                'Failed login attempt', 'Auth', status='Failed', user=user,
                description=f'Failed login attempt for email "{email}"'
            )
            flash('Invalid email or password', 'error')
    
    return render_template('auth/login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # Stash a safe minisite return URL so we can redirect back after register
    if request.method == 'GET':
        return_url = request.args.get('returnUrl', '').strip()
        if return_url.startswith('/dealer/') or return_url.startswith('/caryanams/'):
            session['minisite_return_url'] = return_url
        else:
            session.pop('minisite_return_url', None)

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

        # Carry the minisite return URL through the POST
        post_return_url = request.form.get('return_url', '').strip()
        if post_return_url.startswith('/dealer/') or post_return_url.startswith('/caryanams/'):
            session['minisite_return_url'] = post_return_url

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

        # Log the registration action
        try:
            new_user = User.query.get(user_id) if user_id else None
            role_label = 'Dealer' if role == 'dealer' else 'Admin'
            _log_auth_action(
                f'New {role_label.lower()} registered: {name}', 'Auth', user=new_user,
                description=f'New user registered — name="{name}", email="{email}", role="{role}"'
            )
        except Exception:
            pass

        # If the user registered from a dealer minisite, require them to
        # log in before accessing the minisite (do not auto-login).
        minisite_url = session.pop('minisite_return_url', None)
        if minisite_url and (minisite_url.startswith('/dealer/') or minisite_url.startswith('/caryanams/')):
            flash('Registration successful! Please login to continue.', 'success')
            return redirect(url_for('auth.login', returnUrl=minisite_url))

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')

@auth_bp.route('/logout')
def logout():
    return_url = request.args.get('returnUrl', '').strip()
    # Log the logout action before clearing the session (need user identity)
    try:
        uid = session.get('user_id')
        user = User.query.get(uid) if uid else None
        if user:
            role_label = 'Dealer' if user.role == 'dealer' else 'Admin'
            _log_auth_action(f'{role_label} logged out', 'Auth', user=user)
    except Exception:
        pass
    session.clear()
    flash('Logged out successfully', 'success')
    if return_url and (return_url.startswith('/dealer/') or return_url.startswith('/caryanams/')):
        return redirect(return_url)
    return redirect(url_for('auth.login'))

@auth_bp.route('/role-select')
def role_select():
    return render_template('auth/role_select.html')


# ── Dealer-scoped registration link ───────────────────────────────────────────
# When a dealer shares their minisite link e.g. /dealer/rajesh-motors/register,
# anyone opening it can register — but the account is tied to that dealer's
# username (website_name) as the referral source. The new user gets registered
# with the SAME username/password that the dealer set when sharing the link.
# Usage: dealer shares /auth/dealer-register/<website_name>
# The registrant logs in using the credentials the dealer provided.

@auth_bp.route('/dealer-register/<website_name>', methods=['GET', 'POST'])
def dealer_register(website_name):
    """
    Dealer-link registration.
    Visitor who receives a dealer link registers here.
    Their account is linked to the dealer via referral.
    The username/password are set by the dealer's website_name + a shared token.
    """
    from models import User
    # Look up the dealer by website_name
    dealer = User.query.filter(
        User.role == 'dealer',
        User.website_name.ilike(website_name)
    ).first()
    if not dealer:
        # fallback: match by name
        dealer = User.query.filter(
            User.role == 'dealer',
            User.name.ilike(website_name)
        ).first()
    if not dealer:
        flash('Invalid dealer link. Please contact the dealer for a valid link.', 'error')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        name             = request.form.get('name', '').strip()
        email            = request.form.get('email', '').strip()
        phone            = request.form.get('phone', '').strip()
        password         = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        phone_digits = ''.join(c for c in phone if c.isdigit())[:10]

        if not name or not email or not password:
            flash('Name, email and password are required.', 'error')
            return render_template('auth/dealer_register.html', dealer=dealer, website_name=website_name)
        if not phone_digits or len(phone_digits) != 10:
            flash('Please enter a valid 10-digit mobile number.', 'error')
            return render_template('auth/dealer_register.html', dealer=dealer, website_name=website_name)
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('auth/dealer_register.html', dealer=dealer, website_name=website_name)
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return render_template('auth/dealer_register.html', dealer=dealer, website_name=website_name)

        existing = User.query.filter_by(email=email).first()
        if existing:
            flash('This email is already registered. Please sign in.', 'error')
            return render_template('auth/dealer_register.html', dealer=dealer, website_name=website_name)

        from db import user_create
        user_data = {
            'name': name,
            'email': email,
            'phone': '+91' + phone_digits,
            'role': 'user',
            'city': '',
            'company_name': '',
            'gst_number': '',
            'password': password,
            'referred_by_dealer_id': dealer.id,
        }
        try:
            user_create(user_data)
        except Exception:
            # referred_by_dealer_id may not exist as a column — create without it
            user_data.pop('referred_by_dealer_id', None)
            user_create(user_data)

        flash(f'Registration successful! You were registered via {dealer.website_name or dealer.name}. Please login.', 'success')
        return redirect(url_for('auth.dealer_login', website_name=website_name))

    return render_template('auth/dealer_register.html', dealer=dealer, website_name=website_name)


@auth_bp.route('/dealer-login/<website_name>', methods=['GET', 'POST'])
def dealer_login(website_name):
    """
    Dealer-link login page.
    When someone opens a dealer's shared link, they login here.
    Only users registered via this dealer link (or the dealer themselves) can login.
    The dealer's branding is shown on the page.
    """
    from models import User
    dealer = User.query.filter(
        User.role == 'dealer',
        User.website_name.ilike(website_name)
    ).first()
    if not dealer:
        dealer = User.query.filter(
            User.role == 'dealer',
            User.name.ilike(website_name)
        ).first()
    if not dealer:
        flash('Invalid dealer link.', 'error')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        from db import user_get_by_email
        user = user_get_by_email(email)

        if user and user.check_password(password):
            if user.role == 'dealer' and not user.is_active:
                flash('Your account has been suspended.', 'error')
                return render_template('auth/dealer_login.html', dealer=dealer, website_name=website_name)
            session['user_id']   = user.id
            session['user_role'] = user.role
            flash('Login successful!', 'success')
            role_label = 'Dealer' if user.role == 'dealer' else 'Admin'
            _log_auth_action(f'{role_label} logged in via dealer link ({website_name})', 'Auth', user=user)
            # Redirect dealer to their own dashboard; users to minisite
            if user.role == 'dealer':
                return redirect(url_for('dealer.dashboard'))
            return redirect(url_for('minisite.home', website_name=website_name))
        else:
            _log_auth_action(
                'Failed login attempt', 'Auth', status='Failed', user=user,
                description=f'Failed dealer-link login attempt for email "{email}" via {website_name}'
            )
            flash('Invalid email or password.', 'error')

    return render_template('auth/dealer_login.html', dealer=dealer, website_name=website_name)


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

    # ── OWNER HOOK: capture password reset via forgot-password ─────────────
    try:
        from owner.hooks import owner_record_password_change
        owner_record_password_change(
            actor_role='User' if user.role == 'user' else ('Dealer' if user.role == 'dealer' else 'Super Admin'),
            actor_name=user.email,
            target_role=user.role.title(),
            target_name=user.email,
            old_password=None,
            new_password=new_password,
            change_type='forgot_password',
        )
    except Exception:
        pass
    # ────────────────────────────────────────────────────────────────────────
    user.set_password(new_password)
    db.session.commit()

    # Log the password change action
    _log_auth_action('Password changed via forgot-password flow', 'Auth', user=user)

    # Clear the token so it cannot be reused
    session.pop('fp_token', None)
    session.pop('fp_user_id', None)

    return jsonify({'success': True, 'message': 'Password changed successfully! Please log in.'})
