# CarYanams v26 — Owner Supreme Upgrade Notes

## What Changed

### New Files
| File | Purpose |
|------|---------|
| `owner/routes.py` | **Full rewrite** — 40+ routes covering all CRUD operations |
| `templates/owner/base_owner.html` | New shared sidebar layout for all owner pages |
| `templates/owner/users.html` | Users CRUD with modals |
| `templates/owner/dealers.html` | Dealers CRUD with modals |
| `templates/owner/sub_admins.html` | Sub Admin CRUD + permissions manager |
| `templates/owner/audit_logs.html` | Tabbed event + password log viewer |
| `templates/owner/dashboard.html` | **Upgraded** — stats cards + tabbed recent activity |
| `templates/owner/login.html` | **Upgraded** — polished dark login page |
| `migrate_owner_v26.py` | One-time standalone migration script |

### Models Changed
- `models.py` → `User` model gets 2 new columns:
  - `is_locked` (Boolean, default False)
  - `force_password_change` (Boolean, default False)
- Auto-migration added in `app.py` (runs on startup, safe to re-run)

---

## Deploy Steps

### 1. Replace files
Copy the following into your project root:
```
owner/routes.py               ← full replacement
templates/owner/base_owner.html
templates/owner/users.html
templates/owner/dealers.html
templates/owner/sub_admins.html
templates/owner/audit_logs.html
templates/owner/dashboard.html  ← full replacement
templates/owner/login.html      ← full replacement
UPGRADE_NOTES_v26.md
migrate_owner_v26.py
```

And patch these existing files (already done in the output zip):
```
models.py          ← 2 new columns added to User
app.py             ← v26 migration block added
```

### 2. Run migration (optional — app.py auto-migrates on startup)
```bash
python migrate_owner_v26.py
```

### 3. Restart the app
```bash
flask run
# or
gunicorn app:app
```

---

## Route Reference

### Users (`/xo/users/…`)
| Method | URL | Action |
|--------|-----|--------|
| GET | `/xo/users` | List + search + paginate |
| POST | `/xo/users/create` | Create new user |
| POST | `/xo/users/<id>/edit` | Edit name/phone/city |
| POST | `/xo/users/<id>/delete` | Hard delete |
| POST | `/xo/users/<id>/toggle` | Activate / Deactivate |
| POST | `/xo/users/<id>/reset-password` | Reset password |
| POST | `/xo/users/<id>/lock` | Lock account |
| POST | `/xo/users/<id>/unlock` | Unlock account |
| GET | `/xo/api/user/<id>` | JSON detail + pw history |

### Dealers (`/xo/dealers/…`)
| Method | URL | Action |
|--------|-----|--------|
| GET | `/xo/dealers` | List + search + paginate |
| POST | `/xo/dealers/create` | Create dealer |
| POST | `/xo/dealers/<id>/edit` | Edit dealer details + plan |
| POST | `/xo/dealers/<id>/delete` | Hard delete |
| POST | `/xo/dealers/<id>/toggle` | Activate / Suspend |
| POST | `/xo/dealers/<id>/reset-password` | Reset password |

### Sub Admins (`/xo/sub-admins/…`)
| Method | URL | Action |
|--------|-----|--------|
| GET | `/xo/sub-admins` | List + search + paginate |
| POST | `/xo/sub-admins/create` | Create + assign permissions |
| POST | `/xo/sub-admins/<id>/edit` | Edit name/email/phone |
| POST | `/xo/sub-admins/<id>/delete` | Hard delete |
| POST | `/xo/sub-admins/<id>/toggle` | Enable / Disable |
| POST | `/xo/sub-admins/<id>/permissions` | Assign / Revoke / Set all |
| POST | `/xo/sub-admins/<id>/reset-password` | Reset password |
| GET | `/xo/api/sub-admin/<id>` | JSON detail + permissions |

### Audit Logs
| Method | URL | Action |
|--------|-----|--------|
| GET | `/xo/audit-logs` | System events + pw changes |
| GET | `/xo/api/password-logs` | All pw logs as JSON |
| GET | `/xo/api/event-logs` | All events as JSON |

---

## Security Architecture

### What stays secret
- URL prefix `/xo` — no obvious name like `/owner` or `/admin`
- No `role='owner'` stored anywhere in DB
- Session uses a SHA-256 token derived from credentials + salt
- Zero writes to `admin_logs`, `visitor_logs`, or any other visible table
- All owner actions log only to `xo_pw_audit` and `xo_event_audit`

### Owner credentials
Set via environment variables (defaults shown — **change in production**):
```bash
export OWNER_USERNAME="owner"
export OWNER_PASSWORD="Owner@Supreme#2025!"
```

### Password security
- All passwords stored via `werkzeug.security.generate_password_hash()`
- Plain-text only appears in `xo_pw_audit` (owner-only table, invisible to all roles)
- `force_password_change` flag forces user/dealer to reset on next login

---

## UI Features

### Dashboard (`/xo/dashboard`)
- 4 stat cards: Total Dealers, Total Users, Sub Admins, PW Resets
- Tabbed recent activity: last 15 pw changes + last 20 system events
- All cards are clickable links to respective management pages

### All CRUD Pages
- **Search** with `?q=` filtering across name/email/phone/company
- **Pagination** (20 per page with ellipsis navigation)
- **Action buttons** per row: View | Edit | Reset PW | Activate/Deactivate | Lock/Unlock | Delete
- **Modals** for all CRUD operations (no page reloads)
- **Toast notifications** for all actions (success / error / info)
- **Password reveal** toggle on all password inputs
- **Auto-generated passwords** when field left blank

### Sub Admin Permissions
- Checklist modal to set/revoke individual permissions
- "Revoke All" one-click button
- Permissions displayed as badges in table row
- Supported: `dealers`, `vehicles`, `leads`, `kyc`, `users`, `reports`, `settings`, `imports`, `inquiries`

### Audit Logs (`/xo/audit-logs`)
- Tab 1: System events (create, delete, login, settings changes)
- Tab 2: Password changes with old + new plaintext side-by-side
- Search across actor name, description, event type
- Color-coded event type badges

---

## No Breaking Changes
- All existing admin/sub-admin/dealer/user routes untouched
- Existing `/xo/in` login, `/xo/out` logout, and password hook functions preserved
- `OwnerPasswordLog` and `OwnerEventLog` models unchanged
- `owner/hooks.py` unchanged
