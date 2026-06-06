"""
policies/routes.py — Caryanams DMS
Isolated blueprint for Privacy Policy and Refund Policy pages.
SAFE INTEGRATION: This file is completely standalone.
It does NOT modify any existing auth, dealer, admin, or other routes.
"""

from flask import Blueprint, render_template

policies_bp = Blueprint('policies', __name__)


@policies_bp.route('/privacy-policy')
def privacy_policy():
    """Render the Privacy Policy page. No auth required — public page."""
    return render_template('privacy_policy.html')


@policies_bp.route('/refund-policy')
def refund_policy():
    """Render the Refund & Cancellation Policy page. No auth required — public page."""
    return render_template('refund_policy.html')
