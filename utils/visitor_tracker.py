"""
visitor_tracker.py — Log public website visits to the visitor_logs table.

Features
- Real IP extraction behind proxies/CDN (X-Forwarded-For, X-Real-IP)
- User-Agent parsing: browser, OS, device type
- Optional throttle: skip duplicate logs from same IP within N seconds
- Graceful: any error is swallowed so it never breaks a page load
"""

from __future__ import annotations
import re
from datetime import datetime, timedelta

# ── Throttle: minimum gap between two logs from the same IP ──────────────────
THROTTLE_SECONDS = 30


def _get_real_ip(request) -> str:
    """Return the best-guess real client IP, respecting proxy headers."""
    for header in ('X-Forwarded-For', 'X-Real-IP'):
        value = request.headers.get(header, '').strip()
        if value:
            # X-Forwarded-For may be comma-separated; first is the client
            return value.split(',')[0].strip()
    return request.remote_addr or 'unknown'


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
        page_url = request.url[:500] if request.url else path
        referrer = (request.referrer or '')[:500]
        now = datetime.utcnow()

        from models import VisitorLog, db

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
            visited_at=now,
            created_at=now,
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        pass
