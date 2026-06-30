"""
owner/hooks.py — CarYanams Owner Supreme Layer — Silent Interceptors

These functions are called from:
  • admin/routes.py      — super admin password change, sub-admin creation/edit,
                           dealer/user admin resets
  • auth/routes.py       — forgot-password flow, initial dealer/user registration
  • dealer/routes.py     — dealer self-service password change

They write to owner_password_logs / owner_event_logs and NEVER write to
admin_logs, visitor_logs, or any other table visible to other roles.

Usage pattern (inside the route, AFTER the plain-text password is known
but BEFORE set_password() is called):
    from owner.hooks import owner_record_password_change
    owner_record_password_change(
        actor_role='Super Admin',
        actor_name='admin',
        target_role='Sub Admin',
        target_name=sa.username,
        old_password=None,          # pass old if you have it
        new_password=new_pw,
        change_type='admin_reset',
    )
"""

from flask import request as _flask_request


def _get_ip():
    """Best-effort client IP — does not log to any visible table."""
    try:
        r = _flask_request
        return r.headers.get('X-Forwarded-For', r.remote_addr or 'unknown').split(',')[0].strip()
    except Exception:
        return 'unknown'


def owner_record_password_change(
    actor_role: str,
    actor_name: str,
    target_role: str,
    target_name: str,
    new_password: str,
    old_password: str = None,
    change_type: str = 'admin_reset',
):
    """
    Silently record a password change to the owner-only audit table.
    Never raises — swallows all exceptions so it cannot break the caller.
    """
    try:
        from extensions import db
        from owner.log_model import OwnerPasswordLog
        entry = OwnerPasswordLog(
            actor_role=actor_role,
            actor_name=actor_name,
            target_role=target_role,
            target_name=target_name,
            old_password=old_password,
            new_password=new_password,
            change_type=change_type,
            ip_address=_get_ip(),
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        pass   # MUST NOT propagate — caller must not be affected


def owner_record_event(
    event_type: str,
    description: str,
    actor_role: str = None,
    actor_name: str = None,
):
    """
    Silently record a system event (login, account creation, etc.)
    to the owner-only event table.
    """
    try:
        from extensions import db
        from owner.log_model import OwnerEventLog
        entry = OwnerEventLog(
            event_type=event_type,
            actor_role=actor_role,
            actor_name=actor_name,
            description=description,
            ip_address=_get_ip(),
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        pass
