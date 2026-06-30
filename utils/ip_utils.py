"""
ip_utils.py — Single source of truth for real client IP detection.

Used by BOTH the Visitor Logs system (utils/visitor_tracker.py) and the
Activity Logs system (utils/request_meta.py) so there is exactly one place
that knows how to find a visitor's real IP address. Nothing else in the
codebase should re-implement this logic.

Why this exists
----------------
Flask's `request.remote_addr` only reflects the IP of the TCP connection
into the Flask process. When the app sits behind a reverse proxy (Nginx,
Apache), a load balancer, or Cloudflare, that connection is from the proxy
itself — so `remote_addr` is the proxy's address (often 127.0.0.1 or an
internal/private IP), never the visitor's. The real client IP is instead
carried in a request header set by the proxy.

This module:
  1. Reads a small set of well-known proxy/CDN headers, in priority order.
  2. Walks every IP listed in each header (X-Forwarded-For can contain a
     whole hop chain: "client, proxy1, proxy2") rather than blindly trusting
     the first entry.
  3. Validates every candidate with Python's stdlib `ipaddress` module and
     SKIPS anything invalid, empty, loopback, link-local, private, or
     carrier-grade-NAT — only a plausible public IP is accepted.
  4. Falls back to `request.remote_addr` only if no header yields a usable
     public IP (correct behavior for local development, where remote_addr
     IS the real, useful value).

Production note
----------------
Trusting `X-Forwarded-For` / `X-Real-IP` / `CF-Connecting-IP` is only safe
when the app is actually deployed behind the proxy that sets them — an
internet-facing Flask process with no proxy in front of it would let any
client simply fake these headers. For real production hardening you should
also configure your web server (Nginx/Apache) to strip any client-supplied
copies of these headers before forwarding, and/or list your proxy's own
address(es) in TRUSTED_PROXY_IPS below so spoofed headers from elsewhere
are ignored. Both are supported but optional — by default this module
trusts the headers as long as the value resolves to a plausible public IP,
which matches how the existing system already worked and keeps local/dev
environments working without extra configuration.
"""

from __future__ import annotations
import ipaddress
import os

# ── Header priority order ───────────────────────────────────────────────────
# Checked top to bottom; the first header that yields a valid public IP wins.
#   CF-Connecting-IP   → set by Cloudflare, always the true client IP
#   True-Client-IP     → set by some CDNs (Cloudflare Enterprise, Akamai)
#   X-Real-IP          → common single-IP header set by Nginx configs
#   X-Forwarded-For    → standard multi-hop header (Nginx, Apache, most LBs)
PROXY_HEADERS = (
    'CF-Connecting-IP',
    'True-Client-IP',
    'X-Real-IP',
    'X-Forwarded-For',
)

# ── Optional hardening: known trusted proxy IPs ────────────────────────────
# If set (comma-separated in the TRUSTED_PROXY_IPS env var), only requests
# whose DIRECT connection (request.remote_addr) comes from one of these
# IPs will have their proxy headers trusted at all. Leave unset (default)
# to trust headers unconditionally, which is the common/simple case for
# a single Nginx/Apache box or Cloudflare in front of the app.
_TRUSTED_PROXY_IPS = {
    ip.strip() for ip in os.environ.get('TRUSTED_PROXY_IPS', '').split(',') if ip.strip()
}


def _is_valid_public_ip(candidate: str) -> bool:
    """
    Return True only if `candidate` is a syntactically valid IPv4/IPv6
    address AND is a plausible public (routable) address — i.e. not empty,
    not malformed, not loopback, not link-local, not private/internal,
    and not in the carrier-grade NAT range (100.64.0.0/10).
    """
    if not candidate:
        return False
    try:
        addr = ipaddress.ip_address(candidate)
    except ValueError:
        return False  # empty / malformed / not an IP at all

    if addr.is_loopback or addr.is_link_local or addr.is_private \
       or addr.is_multicast or addr.is_reserved or addr.is_unspecified:
        return False

    # Carrier-grade NAT (RFC 6598) — not flagged as private by ipaddress
    # on some Python versions, so check it explicitly.
    if isinstance(addr, ipaddress.IPv4Address) and addr in ipaddress.ip_network('100.64.0.0/10'):
        return False

    return True


def _candidates_from_header(raw_value: str):
    """
    Split a header value into individual IP candidates, trimmed and in
    order. X-Forwarded-For may look like "client, proxy1, proxy2" — we
    yield every entry so the caller can walk past invalid/private hops
    to find the first genuinely public address.
    """
    for part in raw_value.split(','):
        ip = part.strip()
        # Headers occasionally include a port (e.g. "1.2.3.4:5678") —
        # strip it for IPv4; IPv6 with brackets "[::1]:443" handled too.
        if ip.startswith('['):
            ip = ip.split(']')[0].lstrip('[')
        elif ip.count(':') == 1:  # IPv4:port, not IPv6 (which has 2+ colons)
            ip = ip.split(':')[0]
        if ip:
            yield ip


def get_real_ip(request) -> str:
    """
    Return the best available real client IP for this request.

    Resolution order:
      1. Each header in PROXY_HEADERS, in priority order — every candidate
         IP in that header is checked, and the first valid PUBLIC IP found
         is returned immediately.
      2. If no header yields a valid public IP, fall back to
         request.remote_addr (correct for local/dev, or any setup where
         the direct connection IS the real client — e.g. no proxy in front).
      3. If even that is missing/invalid, return 'unknown' rather than a
         misleading default like '127.0.0.1'.

    Never raises — always returns a string.
    """
    try:
        # Optional hardening: only trust proxy headers if the direct
        # connection itself comes from a known/trusted proxy IP.
        if _TRUSTED_PROXY_IPS and request.remote_addr not in _TRUSTED_PROXY_IPS:
            headers_to_check = ()
        else:
            headers_to_check = PROXY_HEADERS

        for header in headers_to_check:
            raw_value = (request.headers.get(header) or '').strip()
            if not raw_value:
                continue
            for candidate in _candidates_from_header(raw_value):
                if _is_valid_public_ip(candidate):
                    return candidate
                # Invalid/private/malformed candidate — keep walking the
                # rest of this header's chain and then the next header,
                # instead of giving up or saving a bad value.

        # No proxy header produced a usable public IP. Fall back to the
        # direct socket address. This is the CORRECT value in local dev
        # (no proxy at all) and in any deployment without a reverse proxy.
        remote = (request.remote_addr or '').strip()
        if remote:
            try:
                ipaddress.ip_address(remote)  # just confirm it's a real IP
                return remote
            except ValueError:
                pass

        return 'unknown'
    except Exception:
        return 'unknown'
