"""
subscription_features.py — CarYanams DMS
Strict Subscription Feature Control System
═══════════════════════════════════════════
Single source of truth for which features each subscription plan
(Starter / Growth / Pro) unlocks, plus the `feature_required` decorator
that enforces it on every protected route (backend firewall — UI, API,
and direct-URL access are all covered the same way).

Behaviour on a blocked feature:
  • Normal page request  → flash an upgrade message + redirect to /dealer/subscription
  • AJAX / JSON / *.../api/* request → 403 JSON body describing the block
    and the redirect target, with no feature data/schema leaked.

This file does not change any existing route's business logic — it only
adds an additional guard that existing decorators (dealer_required,
kyc_required, _studio_dealer_required, _require_dealer_auth, etc.) can be
stacked with.
"""

from functools import wraps
from flask import g, request, redirect, url_for, flash, jsonify


# ── Plan → allowed feature keys ───────────────────────────────────────────
# Keys correspond to logical feature areas, not URLs, so the same map can
# gate routes across dealer/, background/ (Studio) and minisite/ blueprints.
PLAN_FEATURES = {
    'starter': {
        'dashboard', 'crm_leads', 'inquiries', 'inventory',
        'agents', 'deals_sales', 'documents',
    },
    'growth': {
        'dashboard', 'crm_leads', 'inquiries', 'inventory',
        'agents', 'deals_sales', 'documents',
        'finance', 'reports', 'studio',
    },
    'pro': {
        'dashboard', 'crm_leads', 'inquiries', 'inventory',
        'agents', 'deals_sales', 'documents',
        'finance', 'reports', 'studio',
        'mini_website', 'api_access',
    },
}

# Human-readable labels used in upgrade messages / UI badges
FEATURE_LABELS = {
    'dashboard':    'Dashboard',
    'crm_leads':    'CRM / Leads',
    'inquiries':    'Inquiries',
    'inventory':    'Inventory',
    'agents':       'Agents',
    'deals_sales':  'Deals & Sales',
    'documents':    'Documents',
    'finance':      'Finance',
    'reports':      'Reports',
    'studio':       'Caryanams Studio',
    'mini_website': 'Mini Website',
    'api_access':   'API Access',
}

# Smallest plan that unlocks a given feature — used for "Upgrade to X" copy
_PLAN_ORDER = ['starter', 'growth', 'pro']
_PLAN_DISPLAY_NAME = {'starter': 'Starter', 'growth': 'Growth', 'pro': 'Pro'}


def _normalize_plan(plan):
    plan = (plan or 'starter').lower().strip()
    return plan if plan in PLAN_FEATURES else 'starter'


def plan_has_feature(plan, feature_key):
    """True if the given subscription plan includes this feature."""
    return feature_key in PLAN_FEATURES.get(_normalize_plan(plan), PLAN_FEATURES['starter'])


def min_plan_for_feature(feature_key):
    """Return the cheapest plan key that unlocks a feature (for upgrade CTAs)."""
    for plan in _PLAN_ORDER:
        if feature_key in PLAN_FEATURES[plan]:
            return plan
    return 'pro'


def current_user_plan():
    """Reads the active dealer's plan off g.user (set by app.before_request)."""
    user = getattr(g, 'user', None)
    return _normalize_plan(user.get('subscription_plan') if user else None)


def feature_allowed(feature_key):
    """Template/route-friendly helper: is this feature unlocked for the logged-in dealer?"""
    return plan_has_feature(current_user_plan(), feature_key)


def _wants_json_response():
    """Decide whether to answer with a JSON error or an HTML redirect."""
    if request.is_json:
        return True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    if '/api/' in request.path:
        return True
    best = request.accept_mimetypes.best_match(['application/json', 'text/html'])
    return best == 'application/json' and request.accept_mimetypes[best] >= request.accept_mimetypes['text/html']


def feature_required(feature_key):
    """
    Subscription firewall for a single feature.

    Usage:
        @dealer_bp.route('/finance')
        @dealer_required
        @kyc_required
        @feature_required('finance')
        def finance():
            ...

    If the logged-in dealer's plan does not include `feature_key`:
      - API / AJAX calls receive a 403 JSON error (no data/schema is rendered)
      - Normal browser requests are redirected to /dealer/subscription with
        an upgrade message (manual URL entry is blocked the same way)
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            plan = current_user_plan()
            if not plan_has_feature(plan, feature_key):
                label = FEATURE_LABELS.get(feature_key, feature_key.replace('_', ' ').title())
                required_plan = _PLAN_DISPLAY_NAME.get(min_plan_for_feature(feature_key), 'Pro')
                message = (
                    f'You need to upgrade your plan to access {label}. '
                    f'Please upgrade your subscription to continue.'
                )

                if _wants_json_response():
                    return jsonify({
                        'error': 'FEATURE_NOT_AVAILABLE',
                        'feature': feature_key,
                        'required_plan': required_plan,
                        'redirect': url_for('dealer.subscription'),
                        'message': message,
                    }), 403

                flash(message, 'warning')
                return redirect(url_for('dealer.subscription'))
            return f(*args, **kwargs)
        return wrapper
    return decorator
