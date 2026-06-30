"""
visitor_tracker.py — Log public website visits to the visitor_logs table.

Features
- Real IP extraction behind proxies/CDN, delegated to utils.ip_utils
  (single source of truth — see that module for full detection logic)
- User-Agent parsing: browser, OS, device type
- Optional throttle: skip duplicate logs from same IP within N seconds
- Graceful: any error is swallowed so it never breaks a page load
"""

from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone

# ── Throttle: minimum gap between two logs from the same IP ──────────────────
THROTTLE_SECONDS = 30


def _get_real_ip(request) -> str:
    """
    Return the best-guess real client IP. Thin wrapper kept for backward
    compatibility (other modules may still import this name) — all actual
    detection logic now lives in utils.ip_utils.get_real_ip, the single
    source of truth shared with the Activity Logs system.
    """
    from utils.ip_utils import get_real_ip as _shared_get_real_ip
    return _shared_get_real_ip(request)


def _parse_ua(ua: str):
    """
    Minimal UA parser — returns (browser, os, device_type).
    Good enough for admin dashboards without a heavy dependency.
    """
    ua_lower = ua.lower()

    # ── Device ────────────────────────────────────────────────────────────────
    if any(k in ua_lower for k in ('ipad', 'tablet', 'kindle', 'playbook', 'silk')):
        device = 'Tablet'
    elif any(k in ua_lower for k in ('mobile', 'android', 'iphone', 'ipod',
                                      'blackberry', 'windows phone', 'opera mini',
                                      'opera mobi')):
        device = 'Mobile'
    else:
        device = 'Desktop'

    # ── Browser ───────────────────────────────────────────────────────────────
    if 'edg/' in ua_lower or 'edge/' in ua_lower:
        browser = 'Edge'
    elif 'opr/' in ua_lower or 'opera' in ua_lower:
        browser = 'Opera'
    elif 'samsungbrowser' in ua_lower:
        browser = 'Samsung Browser'
    elif 'chrome' in ua_lower:
        browser = 'Chrome'
    elif 'firefox' in ua_lower:
        browser = 'Firefox'
    elif 'safari' in ua_lower:
        browser = 'Safari'
    elif 'msie' in ua_lower or 'trident' in ua_lower:
        browser = 'Internet Explorer'
    else:
        browser = 'Other'

    # ── OS ────────────────────────────────────────────────────────────────────
    if 'windows nt 10' in ua_lower:
        os_name = 'Windows 10/11'
    elif 'windows nt 6.3' in ua_lower:
        os_name = 'Windows 8.1'
    elif 'windows nt 6.1' in ua_lower:
        os_name = 'Windows 7'
    elif 'windows' in ua_lower:
        os_name = 'Windows'
    elif 'mac os x' in ua_lower or 'macos' in ua_lower:
        os_name = 'macOS'
    elif 'android' in ua_lower:
        m = re.search(r'android\s([\d.]+)', ua_lower)
        os_name = f'Android {m.group(1)}' if m else 'Android'
    elif 'iphone os' in ua_lower or 'ipad; cpu os' in ua_lower:
        m = re.search(r'os ([\d_]+)', ua_lower)
        ver = m.group(1).replace('_', '.') if m else ''
        os_name = f'iOS {ver}' if ver else 'iOS'
    elif 'linux' in ua_lower:
        os_name = 'Linux'
    elif 'cros' in ua_lower:
        os_name = 'ChromeOS'
    else:
        os_name = 'Other'

    return browser, os_name, device


# ── Readable page name mapping ────────────────────────────────────────────────
# Maps Flask endpoint names (request.endpoint) to human-readable page labels.
# Add new routes here as the app grows. Fallback: request.path is used.
_ENDPOINT_PAGE_NAMES = {
    # Auth
    'auth.login':                   'Login',
    'auth.register':                'Register',
    'auth.role_select':             'Role Select',
    'auth.forgot_password':         'Forgot Password',
    'auth.dealer_login':            'Dealer Login',
    'auth.dealer_register':         'Dealer Register',
    'auth.logout':                  'Logout',
    # User-facing
    'user.home':                    'Home',
    'user.listings':                'Listings',
    'user.car_detail':              'Car Detail',
    'user.contact':                 'Contact',
    # Minisite
    'minisite.home':                'Minisite Home',
    'minisite.inventory':           'Minisite Inventory',
    'minisite.car_detail':          'Minisite Car Detail',
    'minisite.about':               'Minisite About',
    'minisite.contact':             'Minisite Contact',
    'minisite.featured_deals':      'Featured Deals',
    'minisite.dashboard':           'Minisite Dashboard',
    # Dealer DMS
    'dealer.dashboard':             'Dealer Dashboard',
    'dealer.inventory':             'Inventory',
    'dealer.inventory_detail':      'Inventory Detail',
    'dealer.deals':                 'Deals',
    'dealer.deal_form':             'Deal Form',
    'dealer.leads':                 'Leads',
    'dealer.lead_form':             'Lead Form',
    'dealer.agents':                'Agents',
    'dealer.documents':             'Documents',
    'dealer.finance':               'Finance',
    'dealer.reports':               'Reports',
    'dealer.inquiries':             'Inquiries',
    'dealer.my_account':            'My Account',
    'dealer.subscription':          'Subscription',
    'dealer.website_settings':      'Website Settings',
    'dealer.kyc_upload':            'KYC Upload',
    'dealer.invoice':               'Invoice',
    # Admin
    'admin.dashboard':              'Admin Dashboard',
    'admin.dealers':                'Dealers',
    'admin.users':                  'Users',
    'admin.vehicles':               'Vehicles',
    'admin.leads':                  'Leads',
    'admin.sales':                  'Sales',
    'admin.reports':                'Reports',
    'admin.activity':               'Activity Logs',
    'admin.visitor_logs':           'Visitor Logs',
    'admin.settings':               'Settings',
    'admin.inquiries':              'Inquiries',
    'admin.notifications':          'Notifications',
    'admin.sub_admins':             'Sub Admins',
    'admin.kyc_list':               'KYC List',
    'admin.kyc_detail':             'KYC Detail',
    'admin.document_storage':       'Document Storage',
    'admin.add_dealer':             'Add Dealer',
    'admin.edit_dealer':            'Edit Dealer',
    'admin.view_dealer':            'View Dealer',
    'admin.add_user':               'Add User',
    'admin.edit_user':              'Edit User',
    'admin.view_user':              'View User',
    'admin.add_vehicle':            'Add Vehicle',
    'admin.edit_vehicle':           'Edit Vehicle',
    'admin.view_vehicle':           'View Vehicle',
    'admin.add_lead':               'Add Lead',
    'admin.edit_lead':              'Edit Lead',
    'admin.view_lead':              'View Lead',
    'admin.import_leads':           'Import Leads',
    'admin.add_sub_admin':          'Add Sub Admin',
    'admin.edit_sub_admin':         'Edit Sub Admin',
    'admin.dealer_requests':        'Dealer Requests',
    'admin.vehicle_images':         'Vehicle Images',
    # Background / misc
    'background.remove':            'Background Remove',
    'policies.privacy_policy':      'Privacy Policy',
    'policies.refund_policy':       'Refund Policy',
}


def _resolve_page_name(request) -> str:
    """
    Return a human-readable page label for the current request.
    Priority: endpoint map → path-prefix heuristics → raw path.
    """
    endpoint = getattr(request, 'endpoint', None) or ''
    if endpoint in _ENDPOINT_PAGE_NAMES:
        return _ENDPOINT_PAGE_NAMES[endpoint]

    # Path-prefix fallback for dynamic routes not in the map
    path = request.path or '/'
    segments = [s for s in path.strip('/').split('/') if s]
    if not segments:
        return 'Home'

    # Convert first meaningful segment to title case as a best guess
    label = segments[0].replace('-', ' ').replace('_', ' ').title()
    return label or path


# ── Static asset extensions to ignore ────────────────────────────────────────
_SKIP_EXTENSIONS = {
    '.css', '.js', '.ico', '.png', '.jpg', '.jpeg', '.gif', '.svg',
    '.webp', '.woff', '.woff2', '.ttf', '.eot', '.map', '.json',
}


def log_visit(request, app=None):
    """
    Record a visitor_log row.  Call from a blueprint before_request hook.
    Silently no-ops on any error.
    """
    try:
        from flask import current_app
        path = request.path or '/'

        # Skip static assets
        ext = '.' + path.rsplit('.', 1)[-1].lower() if '.' in path.split('/')[-1] else ''
        if ext in _SKIP_EXTENSIONS:
            return
        if path.startswith('/static/') or path.startswith('/favicon'):
            return

        ip = _get_real_ip(request)
        ua = request.headers.get('User-Agent', '')
        browser, os_name, device = _parse_ua(ua)
        # CHANGED: store a human-readable page name instead of raw localhost URL
        page_url = _resolve_page_name(request)
        referrer = (request.referrer or '')[:500]
        # Use IST (UTC+5:30) for all timestamps
        IST = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(IST).replace(tzinfo=None)  # store as naive IST datetime

        # Stable anonymous session id for this browser session (does not
        # touch login session keys — separate namespaced key).
        session_id = None
        try:
            from flask import session as _flask_session
            import uuid as _uuid
            session_id = _flask_session.get('_visitor_sid')
            if not session_id:
                session_id = _uuid.uuid4().hex[:32]
                _flask_session['_visitor_sid'] = session_id
        except Exception:
            session_id = None

        from models import VisitorLog, db

        # If the visitor happens to be logged in (dealer/user account) at the
        # time of this page view, capture who they are. g.user is set by the
        # app's global before_request loader for every request, so this is
        # safe to read here regardless of which blueprint triggered the visit.
        visitor_user_id = None
        visitor_name = None
        visitor_role = None
        try:
            from flask import g as _g
            if getattr(_g, 'user', None):
                visitor_user_id = _g.user.get('id')
                # CHANGED: prefer 'username' (login handle) over 'name' (display name)
                visitor_name = _g.user.get('username') or _g.user.get('name')
                role_raw = _g.user.get('role')
                visitor_role = 'Dealer' if role_raw == 'dealer' else ('User' if role_raw else None)
        except Exception:
            pass

        # Throttle: skip if same IP visited same page within THROTTLE_SECONDS
        cutoff = now - timedelta(seconds=THROTTLE_SECONDS)
        existing = VisitorLog.query.filter(
            VisitorLog.ip_address == ip,
            VisitorLog.page_url == page_url,
            VisitorLog.visited_at >= cutoff,
        ).first()
        if existing:
            return

        log = VisitorLog(
            ip_address=ip,
            country=None,   # geo-lookup would require an external call
            city=None,
            browser=browser,
            operating_system=os_name,
            device_type=device,
            page_url=page_url,
            referrer=referrer or None,
            session_id=session_id,
            user_id=visitor_user_id,
            visitor_name=visitor_name,
            visitor_role=visitor_role,
            visited_at=now,
            created_at=now,
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        pass
