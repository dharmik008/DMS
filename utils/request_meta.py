"""
request_meta.py — Shared helpers for extracting real client metadata from a
Flask request: real IP (proxy/Cloudflare-aware), browser, OS/device.

Used by the Activity Log system (AdminLog) so the same battle-tested
IP + User-Agent parsing logic that already powers Visitor Logs is reused
instead of duplicated. Real IP detection delegates entirely to
utils.ip_utils — the single source of truth shared by both logging systems.
"""

from __future__ import annotations


def get_real_ip(request) -> str:
    """
    Return the best available real client IP for this request.
    Thin wrapper around utils.ip_utils.get_real_ip — see that module for
    the full validated, proxy/CDN-aware detection logic.
    """
    from utils.ip_utils import get_real_ip as _shared_get_real_ip
    return _shared_get_real_ip(request)


def get_browser_os_device(request):
    """
    Return (browser, os_name, device_type) parsed from the request's
    User-Agent header. Delegates to visitor_tracker's parser so Activity
    Logs and Visitor Logs always agree on device/browser naming.
    """
    try:
        from utils.visitor_tracker import _parse_ua
        ua = request.headers.get('User-Agent', '') or ''
        return _parse_ua(ua)
    except Exception:
        return 'Other', 'Other', 'Desktop'


def get_request_meta(request):
    """
    Convenience bundle: (ip, browser, os_name, device_type).
    Never raises — always returns safe fallback values.
    """
    ip = get_real_ip(request)
    browser, os_name, device = get_browser_os_device(request)
    return ip, browser, os_name, device
