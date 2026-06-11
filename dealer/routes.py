from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, current_app, jsonify
from functools import wraps
import os
import uuid
from werkzeug.utils import secure_filename

from db import (
    user_get_by_id, vehicles_get_by_dealer, vehicles_inventory_summary,
    vehicles_get_fuel_breakdown, vehicle_create, vehicle_update, vehicle_delete, vehicle_get,
    leads_get_by_dealer, leads_get_stage_counts, lead_create, lead_update, lead_delete, lead_get,
    agents_get_by_dealer, agents_get_leads_count, agent_create, agent_update, agent_delete, agent_get,
    deals_get_by_dealer, deals_get_recent, deals_get_status_counts, deals_get_financial_summary,
    deals_get_monthly_revenue, deal_create, deal_update, deal_get, leads_get_source_counts,
    documents_get_by_dealer, document_create, document_delete,
    inquiries_get_by_dealer, inquiry_update_status,
    user_update_subscription
)
from models import db, User, Vehicle, VehicleImage
from utils.image_utils import save_uploaded_image, is_allowed_image

dealer_bp = Blueprint('dealer', __name__)


def log_dealer_action(action, module, status='Success'):
    """Log dealer activity into the unified AdminLog table."""
    try:
        from extensions import db
        from models import AdminLog
        from flask import request as _req, g as _g
        dealer_name = _g.user.get('name', 'Dealer') if _g.user else 'Dealer'
        log = AdminLog(
            admin_user=dealer_name,
            user_role='Dealer',
            action=action,
            module=module,
            ip_address=_req.remote_addr or '127.0.0.1',
            status=status,
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        pass


def dealer_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not g.user or g.user.get('role') != 'dealer':
            # g.user is None when user deleted from DB — session auto-invalidates
            session.clear()
            flash('Your account has been deleted. Please contact the admin.', 'error')
            return redirect(url_for('auth.login'))
        # ── Block suspended dealer even if session is active ─────────────────
        if not g.user.get('is_active', True):
            session.clear()
            flash('Your account has been suspended. Please contact the admin.', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


# ── KYC restriction: dealers without complete KYC are redirected ──────────────
# Allowed routes when KYC is incomplete (endpoint names)
_KYC_EXEMPT_ENDPOINTS = {
    'dealer.kyc_upload',     # KYC upload page
    'dealer.kyc_submit',     # KYC form POST
    'auth.logout',           # allow logout
}


def kyc_required(f):
    """Decorator that blocks access until ALL 3 KYC documents are approved by admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not g.user or g.user.get('role') != 'dealer':
            return f(*args, **kwargs)
        from models import DealerKYC
        dealer_id = g.user['id']
        kyc = DealerKYC.query.filter_by(dealer_id=dealer_id).first()

        docs_uploaded = (
            kyc is not None and
            kyc.aadhaar_front and
            kyc.aadhaar_back and
            kyc.pan_card
        )

        # Only fully approved when ALL 3 per-doc statuses are 'approved'
        all_approved = (
            docs_uploaded and
            getattr(kyc, 'aadhaar_front_status', 'pending') == 'approved' and
            getattr(kyc, 'aadhaar_back_status', 'pending') == 'approved' and
            getattr(kyc, 'pan_card_status', 'pending') == 'approved'
        )

        if not all_approved:
            if docs_uploaded:
                # Check if any doc is rejected
                rejected = [
                    d for d in ('aadhaar_front', 'aadhaar_back', 'pan_card')
                    if getattr(kyc, d + '_status', 'pending') == 'rejected'
                ]
                if rejected:
                    doc_names = {'aadhaar_front': 'Aadhaar Front', 'aadhaar_back': 'Aadhaar Back', 'pan_card': 'PAN Card'}
                    names = ', '.join(doc_names[d] for d in rejected)
                    flash(f'Some KYC documents were rejected ({names}). Please re-upload them to continue.', 'error')
                else:
                    flash('Your KYC documents are under review. Please wait for admin approval.', 'info')
            else:
                flash('Complete your KYC verification to continue using the DMS.', 'warning')
            return redirect(url_for('dealer.kyc_upload'))
        return f(*args, **kwargs)
    return decorated


def get_dealer_id():
    return g.user['id'] if g.user else None

# ========== KYC UPLOAD (dealer-side) ==========


@dealer_bp.route('/kyc', methods=['GET'])
@dealer_required
def kyc_upload():
    """Show KYC document upload page for dealers with incomplete KYC."""
    from models import DealerKYC, DealerNotification
    dealer_id = get_dealer_id()
    kyc = DealerKYC.query.filter_by(dealer_id=dealer_id).first()

    # If all 3 docs are already approved, redirect straight to dashboard
    if (kyc and
            getattr(kyc, 'aadhaar_front_status', 'pending') == 'approved' and
            getattr(kyc, 'aadhaar_back_status', 'pending') == 'approved' and
            getattr(kyc, 'pan_card_status', 'pending') == 'approved'):
        return redirect(url_for('dealer.dashboard'))

    notifications = DealerNotification.query.filter_by(
        dealer_id=dealer_id).order_by(DealerNotification.created_at.desc()).limit(10).all()
    return render_template('dealer/kyc_upload.html', kyc=kyc, notifications=notifications)


@dealer_bp.route('/api/notifications/mark-read', methods=['POST'])
@dealer_required
def mark_notifications_read():
    """Mark all dealer notifications as read."""
    from models import DealerNotification
    dealer_id = get_dealer_id()
    DealerNotification.query.filter_by(dealer_id=dealer_id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'success': True})


@dealer_bp.route('/kyc/submit', methods=['POST'])
@dealer_required
def kyc_submit():
    """Handle dealer KYC document upload."""
    from models import DealerKYC
    from utils.upload_helpers import save_image, validate_image
    dealer_id = get_dealer_id()

    kyc = DealerKYC.query.filter_by(dealer_id=dealer_id).first()
    if not kyc:
        kyc = DealerKYC(dealer_id=dealer_id, kyc_status='pending')
        db.session.add(kyc)
    from datetime import datetime
    kyc.submitted_at = datetime.utcnow()

    folder = os.path.join(
        current_app.config.get('KYC_UPLOAD_FOLDER',
                               os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', 'dealers')),
        str(dealer_id)
    )
    os.makedirs(folder, exist_ok=True)
    errors = []

    for doc_key in ('aadhaar_front', 'aadhaar_back', 'pan_card'):
        f = request.files.get(doc_key)
        if not f or not f.filename:
            continue
        # Don't overwrite an already-approved document
        current_status = getattr(kyc, doc_key + '_status', 'pending') or 'pending'
        if current_status == 'approved':
            flash(f'{doc_key.replace("_"," ").title()} is already approved — skipped.', 'info')
            continue
        ok, err = validate_image(f)
        if not ok:
            errors.append(f'{doc_key}: {err}')
            continue
        saved = save_image(f, folder, prefix=doc_key.replace('_', '-'), vehicle_mode=False)
        if saved:
            setattr(kyc, doc_key, saved)
            # Reset this doc's status back to pending (awaiting re-review)
            setattr(kyc, doc_key + '_status', 'pending')
            setattr(kyc, doc_key + '_reject', None)
            # ── Register in Centralized Document Storage ──────────────────────
            try:
                from db import cds_register
                cds_register({
                    'dealer_id':     dealer_id,
                    'file_name':     saved,
                    'original_name': f.filename,
                    'file_path':     os.path.join('uploads', 'dealers', str(dealer_id), saved),
                    'module_name':   'KYC',
                    'document_type': doc_key.replace('_', ' ').title(),
                    'uploaded_by':   dealer_id,
                    'performed_by':  f'dealer:{dealer_id}',
                })
            except Exception:
                pass  # Never break the main KYC flow
            # ─────────────────────────────────────────────────────────────────
        else:
            errors.append(f'Failed to save {doc_key}.')

    if errors:
        for e in errors:
            flash(e, 'error')
    else:
        flash('KYC documents uploaded successfully.', 'success')

    # Recalculate overall status based on per-doc statuses
    kyc.recalculate_status()
    db.session.commit()
    return redirect(url_for('dealer.kyc_upload'))


# ========== DASHBOARD ==========
@dealer_bp.route('/dashboard')
@dealer_required
@kyc_required
def dashboard():
    dealer_id = get_dealer_id()

    inventory_summary = vehicles_inventory_summary(dealer_id)
    lead_stages = leads_get_stage_counts(dealer_id)
    recent_leads = leads_get_by_dealer(dealer_id, page=1, per_page=5)['items']
    recent_deals = deals_get_recent(dealer_id)
    financial = deals_get_financial_summary(dealer_id)
    # FIXED: fetch latest 5 inquiries so the dashboard widget can display them
    recent_inquiries = inquiries_get_by_dealer(dealer_id)[:5]
    pending_inquiries = sum(
        1 for i in recent_inquiries if i['status'] == 'pending')

    return render_template('dealer/dashboard.html',
                           total_vehicles=inventory_summary['total'],
                           available=inventory_summary['available'],
                           total_leads=sum(lead_stages.values()),
                           new_leads=lead_stages.get('new', 0),
                           total_deals=financial['total_deals'],
                           delivered=financial['total_deals'],
                           revenue=financial['total_revenue'],
                           lead_stages=lead_stages,
                           recent_leads=recent_leads,
                           recent_deals=recent_deals,
                           recent_inquiries=recent_inquiries,       # FIXED: now passed to template
                           pending_inquiries=pending_inquiries,     # FIXED: badge count for pending
                           )

# ========== INVENTORY ==========


@dealer_bp.route('/inventory')
@dealer_required
@kyc_required
def inventory():
    dealer_id = get_dealer_id()
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '')
    fuel = request.args.get('fuel', '')
    search = request.args.get('search', '')

    vehicles = vehicles_get_by_dealer(
        dealer_id, status=status, fuel=fuel, search=search, page=page)
    return render_template('dealer/inventory.html', vehicles=vehicles, status_filter=status, fuel_filter=fuel, search=search)


@dealer_bp.route('/inventory/add', methods=['GET', 'POST'])
@dealer_required
@kyc_required
def add_vehicle():
    dealer_id = get_dealer_id()

    if request.method == 'POST':
        # ── Server-side: require all 7 mandatory image slots ─────────────────────
        MANDATORY_SLOTS = [
            ('img_front',      'front',      0),
            ('img_rear',       'rear',       1),
            ('img_right_side', 'right_side', 2),
            ('img_left_side',  'left_side',  3),
            ('img_engine',     'engine',     4),
            ('img_boot',       'boot',       5),
            ('img_interior',   'interior',   6),
        ]
        SLOT_LABELS = {
            'front': 'Front View', 'rear': 'Rear / Tail View',
            'right_side': 'Right Side View', 'left_side': 'Left Side View',
            'engine': 'Engine Bay', 'boot': 'Boot / Trunk', 'interior': 'Interior',
        }
        missing_slots = []
        for field_name, img_type, _ in MANDATORY_SLOTS:
            f = request.files.get(field_name)
            if not f or not f.filename or not is_allowed_image(f.filename):
                missing_slots.append(SLOT_LABELS.get(img_type, img_type))

        if missing_slots:
            flash(
                'Please upload all required vehicle photos before submitting: '
                + ', '.join(missing_slots),
                'error'
            )
            return render_template('dealer/vehicle_form.html', action='Add', vehicle=None)

        # ── Primary image: first mandatory slot (front) or explicit 'image' field ──
        # Try 'image' field first (explicit primary); fall back to 'front' slot
        image_file = request.files.get('image') or request.files.get('img_front')
        filename = 'default_car.jpg'

        if image_file and image_file.filename and is_allowed_image(image_file.filename):
            filename = save_uploaded_image(
                image_file, current_app.config['UPLOAD_FOLDER'], uuid.uuid4().hex)

        vehicle_data = {
            'dealer_id': dealer_id,
            'make': request.form.get('make'),
            'model': request.form.get('model'),
            'variant': request.form.get('variant'),
            'year': int(request.form.get('year')),
            'color': request.form.get('color'),
            'fuel_type': request.form.get('fuel_type'),
            'transmission': request.form.get('transmission'),
            'mileage': int(request.form.get('mileage') or 0),
            'engine_cc': int(request.form.get('engine_cc') or 0),
            'price': float(request.form.get('price')),
            'negotiable': request.form.get('negotiable') == 'on',
            'condition': request.form.get('condition'),
            'status': request.form.get('status'),
            'description': request.form.get('description'),
            'vin_number': request.form.get('vin_number'),
            'registration_number': request.form.get('registration_number'),
            'insurance_valid_till': request.form.get('insurance_valid_till'),
            'rc_available': request.form.get('rc_available') == 'on',
            'featured': request.form.get('featured') == 'on',
            'image_filename': filename
        }

        vehicle_id = vehicle_create(vehicle_data)

        # ── Save typed mandatory images (7 slots) into vehicle_images ────────────
        # Order matches VehicleImage.MANDATORY_TYPES; front is already primary above
        # but we ALSO store it in vehicle_images so gallery always includes it
        # (MANDATORY_SLOTS already defined above for validation — reuse here)
        gallery_sort = 10  # gallery images start at sort_order 10+
        saved_any = False

        for field_name, img_type, sort_idx in MANDATORY_SLOTS:
            f = request.files.get(field_name)
            if not f or not f.filename:
                continue
            if not is_allowed_image(f.filename):
                continue
            try:
                fname = save_uploaded_image(
                    f, current_app.config['UPLOAD_FOLDER'], uuid.uuid4().hex)
                img_rec = VehicleImage(
                    vehicle_id=vehicle_id,
                    filename=fname,
                    image_type=img_type,
                    sort_order=sort_idx
                )
                db.session.add(img_rec)
                # If no explicit primary was uploaded, use first mandatory slot
                if img_type == 'front' and filename == 'default_car.jpg':
                    from models import Vehicle as _V
                    _v = _V.query.get(vehicle_id)
                    if _v:
                        _v.image_filename = fname
                saved_any = True
            except Exception as e:
                current_app.logger.error(f'add_vehicle mandatory image error: {e}')

        # ── Save additional gallery images ────────────────────────────────────────
        extra_files = request.files.getlist('extra_images')
        for f in extra_files[:10]:  # max 10 additional
            if not f or not f.filename:
                continue
            if not is_allowed_image(f.filename):
                continue
            try:
                fname = save_uploaded_image(
                    f, current_app.config['UPLOAD_FOLDER'], uuid.uuid4().hex)
                img_rec = VehicleImage(
                    vehicle_id=vehicle_id,
                    filename=fname,
                    image_type='gallery',
                    sort_order=gallery_sort
                )
                db.session.add(img_rec)
                gallery_sort += 1
                saved_any = True
            except Exception as e:
                current_app.logger.error(f'add_vehicle gallery image error: {e}')

        if saved_any:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f'add_vehicle image commit error: {e}')

        log_dealer_action(f'Added vehicle: {vehicle_data.get("make")} {vehicle_data.get("model")} {vehicle_data.get("year")}', 'Vehicles')
        flash('Vehicle added successfully', 'success')
        return redirect(url_for('dealer.inventory'))

    return render_template('dealer/vehicle_form.html', action='Add', vehicle=None)


@dealer_bp.route('/inventory/edit/<int:vid>', methods=['GET', 'POST'])
@dealer_required
@kyc_required
def edit_vehicle(vid):
    dealer_id = get_dealer_id()
    vehicle = vehicle_get(vid)

    if not vehicle or vehicle['dealer_id'] != dealer_id:
        flash('Vehicle not found', 'error')
        return redirect(url_for('dealer.inventory'))

    if request.method == 'POST':
        image_file = request.files.get('image')

        if image_file and image_file.filename and is_allowed_image(image_file.filename):
            new_fname = save_uploaded_image(
                image_file, current_app.config['UPLOAD_FOLDER'], uuid.uuid4().hex)
            vehicle['image_filename'] = new_fname

        update_data = {
            'make': request.form.get('make'),
            'model': request.form.get('model'),
            'variant': request.form.get('variant'),
            'year': int(request.form.get('year')),
            'color': request.form.get('color'),
            'fuel_type': request.form.get('fuel_type'),
            'transmission': request.form.get('transmission'),
            'mileage': int(request.form.get('mileage') or 0),
            'engine_cc': int(request.form.get('engine_cc') or 0),
            'price': float(request.form.get('price')),
            'negotiable': request.form.get('negotiable') == 'on',
            'condition': request.form.get('condition'),
            'status': request.form.get('status'),
            'description': request.form.get('description'),
            'vin_number': request.form.get('vin_number'),
            'registration_number': request.form.get('registration_number'),
            'insurance_valid_till': request.form.get('insurance_valid_till'),
            'rc_available': request.form.get('rc_available') == 'on',
            'featured': request.form.get('featured') == 'on',
            'image_filename': vehicle.get('image_filename', 'default_car.jpg')
        }

        # ── Handle typed mandatory image uploads on edit ──────────────────────────
        MANDATORY_SLOTS = [
            ('img_front',      'front',      0),
            ('img_rear',       'rear',       1),
            ('img_right_side', 'right_side', 2),
            ('img_left_side',  'left_side',  3),
            ('img_engine',     'engine',     4),
            ('img_boot',       'boot',       5),
            ('img_interior',   'interior',   6),
        ]
        saved_any = False
        for field_name, img_type, sort_idx in MANDATORY_SLOTS:
            f = request.files.get(field_name)
            if not f or not f.filename or not is_allowed_image(f.filename):
                continue
            try:
                fname = save_uploaded_image(
                    f, current_app.config['UPLOAD_FOLDER'], uuid.uuid4().hex)
                # Check if a typed record already exists for this slot — replace it
                existing = VehicleImage.query.filter_by(
                    vehicle_id=vid, image_type=img_type).first()
                if existing:
                    existing.filename = fname
                else:
                    img_rec = VehicleImage(
                        vehicle_id=vid,
                        filename=fname,
                        image_type=img_type,
                        sort_order=sort_idx
                    )
                    db.session.add(img_rec)
                # If updating front image, also update the primary image_filename
                if img_type == 'front':
                    update_data['image_filename'] = fname
                saved_any = True
            except Exception as e:
                current_app.logger.error(f'edit_vehicle typed image error ({img_type}): {e}')

        if saved_any:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f'edit_vehicle image commit error: {e}')

        vehicle_update(vid, update_data)
        log_dealer_action(f'Updated vehicle: {update_data.get("make")} {update_data.get("model")} (ID:{vid})', 'Vehicles')
        flash('Vehicle updated successfully', 'success')
        return redirect(url_for('dealer.inventory'))

    # ── GET: load existing typed images for pre-filling the form ─────────────
    existing_typed_imgs = VehicleImage.query.filter_by(vehicle_id=vid).all()
    vehicle['extra_images_typed'] = [
        {'filename': img.filename, 'image_type': img.image_type, 'id': img.id}
        for img in existing_typed_imgs
    ]

    return render_template('dealer/vehicle_form.html', action='Edit', vehicle=vehicle)


@dealer_bp.route('/inventory/delete/<int:vid>', methods=['POST'])
@dealer_required
@kyc_required
def delete_vehicle(vid):
    dealer_id = get_dealer_id()
    vehicle = vehicle_get(vid)

    if vehicle and vehicle['dealer_id'] == dealer_id:
        vehicle_delete(vid)
        log_dealer_action(f'Deleted vehicle ID:{vid}', 'Vehicles')
        flash('Vehicle deleted successfully', 'success')
    else:
        flash('Vehicle not found', 'error')

    return redirect(url_for('dealer.inventory'))


@dealer_bp.route('/inventory/<int:car_id>')
@dealer_required
@kyc_required
def inventory_detail(car_id):
    dealer_id = get_dealer_id()
    vehicle = vehicle_get(car_id)

    if not vehicle or vehicle['dealer_id'] != dealer_id:
        flash('Vehicle not found', 'error')
        return redirect(url_for('dealer.inventory'))

    # FIXED: load extra gallery images from vehicle_images table and attach to vehicle dict
    # Without this, vehicle.get('extra_images') in the template is always None,
    # so the gallery never shows uploaded photos even after they are saved to DB.
    try:
        extra_imgs = (
            VehicleImage.query
            .filter_by(vehicle_id=car_id)
            .order_by(VehicleImage.sort_order, VehicleImage.id)
            .all()
        )
        vehicle['extra_images'] = [img.filename for img in extra_imgs]
        # Pass full image objects so template can show type labels
        vehicle['extra_images_typed'] = [
            {'filename': img.filename, 'image_type': img.image_type, 'id': img.id}
            for img in extra_imgs
        ]
    except Exception as e:
        current_app.logger.error(
            f"Could not load extra images for vehicle {car_id}: {e}")
        vehicle['extra_images'] = []
        vehicle['extra_images_typed'] = []

    return render_template('dealer/inventory_detail.html', vehicle=vehicle)


@dealer_bp.route('/inventory/upload-images', methods=['POST'])
@dealer_required
@kyc_required
def upload_vehicle_images():
    """
    AJAX endpoint — accepts multiple image files and stores them as
    extra gallery images for a vehicle.

    Request (multipart/form-data):
        vehicle_id  int
        images      file[]   (up to 15 files per batch; jpg/jpeg/png/gif/webp)

    Response (JSON):
        { "success": true,  "filenames": ["abc.jpg", ...], "count": N }
        { "success": false, "error": "..." }
    """
    dealer_id = get_dealer_id()
    vehicle_id = request.form.get('vehicle_id', type=int)

    if not vehicle_id:
        return jsonify({'success': False, 'error': 'vehicle_id required'}), 400

    vehicle = vehicle_get(vehicle_id)
    if not vehicle or vehicle['dealer_id'] != dealer_id:
        return jsonify({'success': False, 'error': 'Vehicle not found'}), 404

    files = request.files.getlist('images')
    # Support per-file image_type: client can send image_types[] matching order of images[]
    # Falls back to 'gallery' for all files if not provided
    image_types = request.form.getlist('image_types')
    saved = []
    MAX_FILES = 15
    ALLOWED = {'jpg', 'jpeg', 'png', 'webp'}  # webp accepted then converted

    # FIXED: entire file-save + DB block wrapped in try/except.
    # Previously, any filesystem or DB error would bubble up to Flask's default
    # error handler which returns an HTML 500 page. The browser JS then tried
    # to parse that HTML as JSON → "Unexpected token '<'" crash.
    # Now: errors always return {"success": false, "error": "..."} JSON + rollback.
    try:
        for idx, f in enumerate(files[:MAX_FILES]):
            if not f or not f.filename:
                continue
            if not is_allowed_image(f.filename):
                continue

            img_type = image_types[idx] if idx < len(image_types) else 'gallery'
            # Validate image_type value
            valid_types = VehicleImage.MANDATORY_TYPES + ['gallery']
            if img_type not in valid_types:
                img_type = 'gallery'

            # For typed mandatory slots: replace existing record if one exists
            if img_type != 'gallery':
                existing = VehicleImage.query.filter_by(
                    vehicle_id=vehicle_id, image_type=img_type).first()
                if existing:
                    # Remove old file from disk
                    old_path = os.path.join(
                        current_app.config['UPLOAD_FOLDER'], existing.filename)
                    if os.path.exists(old_path):
                        try:
                            os.remove(old_path)
                        except OSError:
                            pass
                    db.session.delete(existing)

            fname = save_uploaded_image(
                f, current_app.config['UPLOAD_FOLDER'], uuid.uuid4().hex)

            sort_val = VehicleImage.MANDATORY_TYPES.index(img_type) \
                if img_type in VehicleImage.MANDATORY_TYPES else 10 + len(saved)

            img_rec = VehicleImage(
                vehicle_id=vehicle_id,
                filename=fname,
                image_type=img_type,
                sort_order=sort_val
            )
            db.session.add(img_rec)
            saved.append({'filename': fname, 'image_type': img_type})

        if saved:
            db.session.commit()

        filenames = [s['filename'] for s in saved]
        return jsonify({'success': True, 'filenames': filenames,
                        'saved': saved, 'count': len(saved)})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"upload_vehicle_images error for vehicle {vehicle_id}: {e}")
        return jsonify({'success': False, 'error': 'Upload failed. Please try again.'}), 500

@dealer_bp.route('/inventory/delete-image', methods=['POST'])
@dealer_required
@kyc_required
def delete_vehicle_image():
    """AJAX endpoint — delete a single gallery image by filename."""
    dealer_id = get_dealer_id()
    vehicle_id = request.form.get('vehicle_id', type=int)
    filename = request.form.get('filename', '').strip()

    if not vehicle_id or not filename:
        return jsonify({'success': False, 'error': 'vehicle_id and filename required'}), 400

    vehicle = vehicle_get(vehicle_id)
    if not vehicle or vehicle['dealer_id'] != dealer_id:
        return jsonify({'success': False, 'error': 'Not found'}), 404

    try:
        img = VehicleImage.query.filter_by(vehicle_id=vehicle_id, filename=filename).first()
        if img:
            db.session.delete(img)
            db.session.commit()
        # Remove file from disk
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(file_path):
            os.remove(file_path)
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@dealer_bp.route('/inventory/replace-image', methods=['POST'])
@dealer_required
@kyc_required
def replace_vehicle_image():
    """
    AJAX endpoint — replace a specific VehicleImage record with a new upload.
    Overwrites the file on disk keeping the same filename (so DB stays clean),
    OR creates a new file and updates the DB record if replace_vi_id is given.

    Request (multipart/form-data):
        vehicle_id   int
        images       file   (single image)
        image_types  str    (the image_type e.g. 'front', 'interior', 'gallery')
        replace_vi_id int   (VehicleImage.id to replace)
    """
    dealer_id  = get_dealer_id()
    vehicle_id = request.form.get('vehicle_id', type=int)
    vi_id      = request.form.get('replace_vi_id', type=int)

    if not vehicle_id:
        return jsonify({'success': False, 'error': 'vehicle_id required'}), 400

    vehicle = vehicle_get(vehicle_id)
    if not vehicle or vehicle['dealer_id'] != dealer_id:
        return jsonify({'success': False, 'error': 'Vehicle not found'}), 404

    files = request.files.getlist('images')
    if not files or not files[0].filename:
        return jsonify({'success': False, 'error': 'No image provided'}), 400

    f = files[0]
    if not is_allowed_image(f.filename):
        return jsonify({'success': False, 'error': 'Invalid image type'}), 400

    img_type = (request.form.get('image_types') or 'gallery').strip()
    valid_types = VehicleImage.MANDATORY_TYPES + ['gallery']
    if img_type not in valid_types:
        img_type = 'gallery'

    try:
        # If we have a specific vi_id, overwrite that record's file
        if vi_id:
            vi = VehicleImage.query.filter_by(id=vi_id, vehicle_id=vehicle_id).first()
            if vi:
                # Save new file, delete old
                new_fname = save_uploaded_image(
                    f, current_app.config['UPLOAD_FOLDER'], uuid.uuid4().hex)
                old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], vi.filename)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass
                vi.filename  = new_fname
                vi.image_type = img_type
                db.session.commit()

                # If this was the primary image, update vehicle record too
                if vehicle.get('image_filename') == vi.filename:
                    from db import execute
                    execute("UPDATE vehicles SET image_filename=%s WHERE id=%s",
                            (new_fname, vehicle_id))

                return jsonify({'success': True, 'filename': new_fname, 'vi_id': vi_id})

        # Fallback: treat as a normal typed upload (replace by type)
        existing = VehicleImage.query.filter_by(
            vehicle_id=vehicle_id, image_type=img_type).first()
        if existing:
            old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], existing.filename)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except OSError:
                    pass
            db.session.delete(existing)

        fname = save_uploaded_image(
            f, current_app.config['UPLOAD_FOLDER'], uuid.uuid4().hex)
        sort_val = VehicleImage.MANDATORY_TYPES.index(img_type) \
            if img_type in VehicleImage.MANDATORY_TYPES else 99
        img_rec = VehicleImage(
            vehicle_id=vehicle_id, filename=fname,
            image_type=img_type, sort_order=sort_val)
        db.session.add(img_rec)
        db.session.commit()
        return jsonify({'success': True, 'filename': fname})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"replace_vehicle_image error: {e}")
        return jsonify({'success': False, 'error': 'Replace failed. Please try again.'}), 500


@dealer_bp.route('/inventory/set-primary-image', methods=['POST'])
@dealer_required
@kyc_required
def set_primary_image():
    """
    AJAX endpoint — set a VehicleImage as the primary image for a vehicle.
    Called automatically after mask editor saves a processed image.

    Request (JSON): { vi_id: int, vehicle_id: int }
    """
    dealer_id = get_dealer_id()
    data      = request.get_json(silent=True) or {}
    vi_id     = data.get('vi_id')
    vehicle_id = data.get('vehicle_id')

    if not vi_id or not vehicle_id:
        return jsonify({'success': False, 'error': 'vi_id and vehicle_id required'}), 400

    vehicle = vehicle_get(vehicle_id)
    if not vehicle or vehicle['dealer_id'] != dealer_id:
        return jsonify({'success': False, 'error': 'Vehicle not found'}), 404

    vi = VehicleImage.query.filter_by(id=int(vi_id), vehicle_id=vehicle_id).first()
    if not vi:
        return jsonify({'success': False, 'error': 'Image not found'}), 404

    try:
        from db import vehicle_update
        vehicle_update(vehicle_id, {'image_filename': vi.filename})
        return jsonify({'success': True, 'filename': vi.filename})
    except Exception as e:
        current_app.logger.error(f'set_primary_image error: {e}')
        return jsonify({'success': False, 'error': 'Could not update primary'}), 500


# ========== LEADS ==========


@dealer_bp.route('/leads')
@dealer_required
@kyc_required
def leads():
    dealer_id = get_dealer_id()
    stage = request.args.get('stage', '')
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    leads_data = leads_get_by_dealer(
        dealer_id, stage=stage, search=search, page=page)
    stage_counts = leads_get_stage_counts(dealer_id)

    return render_template('dealer/leads.html',
                           leads=leads_data['items'],
                           stage_counts=stage_counts,
                           stage_filter=stage,
                           search=search,
                           current_page=leads_data['page'],
                           total_pages=leads_data['pages'],
                           total=leads_data['total'],
                           stages=['new', 'interested',
                                   'test_drive', 'negotiation', 'lost',
                                   'connected', 'not_connected']
                           )


@dealer_bp.route('/leads/add', methods=['GET', 'POST'])
@dealer_required
@kyc_required
def add_lead():
    import re
    dealer_id = get_dealer_id()
    agents = agents_get_by_dealer(dealer_id)
    vehicles = vehicles_get_by_dealer(dealer_id, per_page=100)['items']

    if request.method == 'POST':
        follow_up_date = request.form.get('follow_up_date')
        stage = request.form.get('stage')

        # Backend validation: connected stage requires follow_up_date
        if stage == 'connected' and not follow_up_date:
            flash('Follow-up Date is required when Stage is "Connected"', 'error')
            return render_template('dealer/lead_form.html', lead=None, agents=agents, vehicles=vehicles)

        # Only connected keeps follow_up_date; all others → NULL
        if stage != 'connected':
            follow_up_date = None

        # Validate follow-up date (must be future)
        if follow_up_date:
            from datetime import datetime
            follow_dt = datetime.strptime(follow_up_date, '%Y-%m-%dT%H:%M')
            if follow_dt.date() <= datetime.now().date():
                flash(
                    'Follow-up date must be a future date (tomorrow or later)', 'error')
                return render_template('dealer/lead_form.html', lead=None, agents=agents, vehicles=vehicles)

        # Phone validation: 10-digit number only
        customer_phone = ''.join(c for c in (request.form.get('customer_phone') or '') if c.isdigit())[:10]
        phone_valid = len(customer_phone) == 10 if customer_phone else True
        if customer_phone and not phone_valid:
            flash('Phone must be a valid 10-digit number.', 'error')
            return render_template('dealer/lead_form.html', lead=None, agents=agents, vehicles=vehicles)

        lead_data = {
            'dealer_id': dealer_id,
            'agent_id': request.form.get('agent_id') or None,
            'vehicle_id': request.form.get('vehicle_id') or None,
            'customer_name': request.form.get('customer_name'),
            'customer_email': request.form.get('customer_email'),
            'customer_phone': customer_phone,
            'customer_city': request.form.get('customer_city'),
            'source': request.form.get('source'),
            'stage': request.form.get('stage'),
            'notes': request.form.get('notes'),
            'budget': float(request.form.get('budget')) if request.form.get('budget') else None,
            'assigned_to': request.form.get('assigned_to'),
            'follow_up_date': follow_up_date
        }

        lead_create(lead_data)
        log_dealer_action(f'Created lead for {lead_data.get("customer_name", "customer")}', 'Leads')
        flash('Lead added successfully', 'success')
        return redirect(url_for('dealer.leads'))

    return render_template('dealer/lead_form.html', lead=None, agents=agents, vehicles=vehicles)


@dealer_bp.route('/leads/edit/<int:lid>', methods=['GET', 'POST'])
@dealer_required
@kyc_required
def edit_lead(lid):
    dealer_id = get_dealer_id()
    lead = lead_get(lid)

    if not lead or lead['dealer_id'] != dealer_id:
        flash('Lead not found', 'error')
        return redirect(url_for('dealer.leads'))

    agents = agents_get_by_dealer(dealer_id)
    vehicles = vehicles_get_by_dealer(dealer_id, per_page=100)['items']

    if request.method == 'POST':
        follow_up_date = request.form.get('follow_up_date')
        stage = request.form.get('stage')

        # Backend validation: connected stage requires follow_up_date
        if stage == 'connected' and not follow_up_date:
            flash('Follow-up Date is required when Stage is "Connected"', 'error')
            return render_template('dealer/lead_form.html', lead=lead, agents=agents, vehicles=vehicles)

        # Only connected keeps follow_up_date; all others → NULL
        if stage != 'connected':
            follow_up_date = None

        # Validate follow-up date (must be future)
        if follow_up_date:
            from datetime import datetime
            follow_dt = datetime.strptime(follow_up_date, '%Y-%m-%dT%H:%M')
            if follow_dt.date() <= datetime.now().date():
                flash(
                    'Follow-up date must be a future date (tomorrow or later)', 'error')
                return render_template('dealer/lead_form.html', lead=lead, agents=agents, vehicles=vehicles)

        # Phone validation: +91XXXXXXXXXX or 10-digit number
        import re
        customer_phone = (request.form.get('customer_phone') or '').strip()
        phone_valid = bool(
            re.match(r'^\+91[0-9]{10}$', customer_phone) or
            re.match(r'^[0-9]{10}$', customer_phone)
        )
        if not phone_valid:
            flash('Phone must be a 10-digit number or +91 followed by 10 digits.', 'error')
            return render_template('dealer/lead_form.html', lead=lead, agents=agents, vehicles=vehicles)

        update_data = {
            'agent_id': request.form.get('agent_id') or None,
            'vehicle_id': request.form.get('vehicle_id') or None,
            'customer_name': request.form.get('customer_name'),
            'customer_email': request.form.get('customer_email'),
            'customer_phone': customer_phone,
            'customer_city': request.form.get('customer_city'),
            'source': request.form.get('source'),
            'stage': request.form.get('stage'),
            'notes': request.form.get('notes'),
            'budget': float(request.form.get('budget')) if request.form.get('budget') else None,
            'assigned_to': request.form.get('assigned_to'),
            'follow_up_date': follow_up_date
        }

        lead_update(lid, update_data)
        log_dealer_action(f'Updated lead for {update_data.get("customer_name", "customer")} (ID:{lid})', 'Leads')
        flash('Lead updated successfully', 'success')
        return redirect(url_for('dealer.leads'))

    return render_template('dealer/lead_form.html', lead=lead, agents=agents, vehicles=vehicles)


@dealer_bp.route('/leads/delete/<int:lid>', methods=['POST'])
@dealer_required
@kyc_required
def delete_lead(lid):
    dealer_id = get_dealer_id()
    lead = lead_get(lid)

    if lead and lead['dealer_id'] == dealer_id:
        lead_delete(lid)
        flash('Lead deleted successfully', 'success')
    else:
        flash('Lead not found', 'error')

    return redirect(url_for('dealer.leads'))

# ========== AGENTS ==========


@dealer_bp.route('/agents')
@dealer_required
@kyc_required
def agents():
    dealer_id = get_dealer_id()
    agents_list = agents_get_by_dealer(dealer_id)
    agent_leads_count = agents_get_leads_count(dealer_id)

    return render_template('dealer/agents.html',
                           agents=agents_list,
                           agent_leads_count=agent_leads_count
                           )


@dealer_bp.route('/agents/add', methods=['POST'])
@dealer_required
@kyc_required
def add_agent():
    import re
    dealer_id = get_dealer_id()
    phone = (request.form.get('phone') or '').strip()

    # Validate phone: 10-digit number only
    phone_digits = ''.join(c for c in phone if c.isdigit())[:10]
    phone_valid = len(phone_digits) == 10
    if not phone_valid:
        flash('Phone must be a valid 10-digit number.', 'error')
        return redirect(url_for('dealer.agents'))

    agent_data = {
        'dealer_id': dealer_id,
        'name': request.form.get('name'),
        'email': request.form.get('email'),
        'phone': phone_digits,
        'status': request.form.get('status')
    }

    agent_create(agent_data)
    flash('Agent added successfully', 'success')
    return redirect(url_for('dealer.agents'))


@dealer_bp.route('/agents/edit/<int:agent_id>', methods=['POST'])
@dealer_required
@kyc_required
def edit_agent(agent_id):
    dealer_id = get_dealer_id()
    agent = agent_get(agent_id)

    if agent and agent['dealer_id'] == dealer_id:
        update_data = {
            'name': request.form.get('name'),
            'email': request.form.get('email'),
            'phone': request.form.get('phone'),
            'status': request.form.get('status')
        }
        agent_update(agent_id, update_data)
        flash('Agent updated successfully', 'success')
    else:
        flash('Agent not found', 'error')

    return redirect(url_for('dealer.agents'))


@dealer_bp.route('/agents/update-status/<int:agent_id>', methods=['POST'])
@dealer_required
@kyc_required
def update_agent_status(agent_id):
    dealer_id = get_dealer_id()
    agent = agent_get(agent_id)

    if agent and agent['dealer_id'] == dealer_id:
        agent_update(agent_id, {'status': request.form.get('status')})
        flash('Agent status updated', 'success')

    return redirect(url_for('dealer.agents'))


@dealer_bp.route('/agents/delete/<int:agent_id>', methods=['POST'])
@dealer_required
@kyc_required
def delete_agent(agent_id):
    dealer_id = get_dealer_id()
    agent = agent_get(agent_id)

    if agent and agent['dealer_id'] == dealer_id:
        agent_delete(agent_id)
        flash('Agent deleted successfully', 'success')
    else:
        flash('Agent not found', 'error')

    return redirect(url_for('dealer.agents'))

# ========== DEALS ==========


@dealer_bp.route('/deals')
@dealer_required
@kyc_required
def deals():
    dealer_id = get_dealer_id()
    status = request.args.get('status', '')

    deals_list = deals_get_by_dealer(dealer_id, status=status)
    status_counts = deals_get_status_counts(dealer_id)

    return render_template('dealer/deals.html',
                           deals=deals_list,
                           status_counts=status_counts,
                           status_filter=status,
                           statuses=['negotiation', 'booked',
                                     'finalized', 'delivered', 'cancelled']
                           )


@dealer_bp.route('/deals/add', methods=['GET', 'POST'])
@dealer_required
@kyc_required
def add_deal():
    import re
    dealer_id = get_dealer_id()
    vehicles = vehicles_get_by_dealer(dealer_id, per_page=100)['items']

    if request.method == 'POST':
        # Phone validation: 10-digit number only (optional in deal)
        customer_phone = ''.join(c for c in (request.form.get('customer_phone') or '') if c.isdigit())[:10]
        if customer_phone and len(customer_phone) != 10:
            flash('Phone must be a valid 10-digit number.', 'error')
            return render_template('dealer/deal_form.html', deal=None, vehicles=vehicles)

        # Final price validation
        final_price_raw = request.form.get('final_price')
        if not final_price_raw or float(final_price_raw) <= 0:
            flash('Final Price is required and must be greater than 0.', 'error')
            return render_template('dealer/deal_form.html', deal=None, vehicles=vehicles)

        deal_data = {
            'dealer_id': dealer_id,
            'lead_id': request.form.get('lead_id') or None,
            'vehicle_id': int(request.form.get('vehicle_id')),
            'customer_name': request.form.get('customer_name'),
            'customer_phone': customer_phone,
            'customer_email': request.form.get('customer_email'),
            'asking_price': float(request.form.get('asking_price')) if request.form.get('asking_price') else None,
            'final_price': float(final_price_raw),
            'payment_mode': request.form.get('payment_mode'),
            'loan_amount': float(request.form.get('loan_amount')) if request.form.get('loan_amount') else None,
            'down_payment': float(request.form.get('down_payment')) if request.form.get('down_payment') else None,
            'emi_months': int(request.form.get('emi_months')) if request.form.get('emi_months') else None,
            'emi_amount': float(request.form.get('emi_amount')) if request.form.get('emi_amount') else None,
            'bank_name': request.form.get('bank_name'),
            'status': request.form.get('status'),
            'booking_amount': float(request.form.get('booking_amount')) if request.form.get('booking_amount') else 0,
            'notes': request.form.get('notes')
        }

        deal_id = deal_create(deal_data)
        log_dealer_action(f'Created deal for {deal_data.get("customer_name", "customer")} — ₹{deal_data.get("final_price", 0):,.0f}', 'Sales')
        flash('Deal created successfully', 'success')
        return redirect(url_for('dealer.deals'))

    return render_template('dealer/deal_form.html', deal=None, vehicles=vehicles)


@dealer_bp.route('/deals/edit/<int:did_>', methods=['GET', 'POST'])
@dealer_required
@kyc_required
def edit_deal(did_):
    dealer_id = get_dealer_id()
    deal = deal_get(did_)

    if not deal or deal['dealer_id'] != dealer_id:
        flash('Deal not found', 'error')
        return redirect(url_for('dealer.deals'))

    vehicles = vehicles_get_by_dealer(dealer_id, per_page=100)['items']

    if request.method == 'POST':
        import re
        # Phone validation: 10-digit number only (optional in deal)
        customer_phone = ''.join(c for c in (request.form.get('customer_phone') or '') if c.isdigit())[:10]
        if customer_phone and len(customer_phone) != 10:
            flash('Phone must be a valid 10-digit number.', 'error')
            return render_template('dealer/deal_form.html', deal=deal, vehicles=vehicles)

        # Final price validation
        final_price_raw = request.form.get('final_price')
        if not final_price_raw or float(final_price_raw) <= 0:
            flash('Final Price is required and must be greater than 0.', 'error')
            return render_template('dealer/deal_form.html', deal=deal, vehicles=vehicles)

        update_data = {
            'customer_name': request.form.get('customer_name'),
            'customer_phone': customer_phone,
            'customer_email': request.form.get('customer_email'),
            'asking_price': float(request.form.get('asking_price')) if request.form.get('asking_price') else None,
            'final_price': float(final_price_raw),
            'payment_mode': request.form.get('payment_mode'),
            'loan_amount': float(request.form.get('loan_amount')) if request.form.get('loan_amount') else None,
            'down_payment': float(request.form.get('down_payment')) if request.form.get('down_payment') else None,
            'emi_months': int(request.form.get('emi_months')) if request.form.get('emi_months') else None,
            'emi_amount': float(request.form.get('emi_amount')) if request.form.get('emi_amount') else None,
            'bank_name': request.form.get('bank_name'),
            'status': request.form.get('status'),
            'booking_amount': float(request.form.get('booking_amount')) if request.form.get('booking_amount') else 0,
            'notes': request.form.get('notes')
        }

        deal_update(did_, update_data)
        log_dealer_action(f'Updated deal ID:{did_} for {update_data.get("customer_name", "customer")}', 'Sales')
        flash('Deal updated successfully', 'success')
        return redirect(url_for('dealer.deals'))

    return render_template('dealer/deal_form.html', deal=deal, vehicles=vehicles)


@dealer_bp.route('/deals/invoice/<int:did_>')
@dealer_required
@kyc_required
def invoice(did_):
    dealer_id = get_dealer_id()
    deal = deal_get(did_)

    if not deal or deal['dealer_id'] != dealer_id:
        flash('Deal not found', 'error')
        return redirect(url_for('dealer.deals'))

    vehicle = deal.get('vehicle')
    dealer_info = g.user

    return render_template('dealer/invoice.html', deal=deal, vehicle=vehicle, dealer=dealer_info)

# ========== FINANCE ==========


@dealer_bp.route('/finance')
@dealer_required
@kyc_required
def finance():
    dealer_id = get_dealer_id()
    financial = deals_get_financial_summary(dealer_id)
    recent_deals = deals_get_by_dealer(dealer_id)[:10]

    return render_template('dealer/finance.html',
                           total_revenue=financial['total_revenue'],
                           total_deals=financial['total_deals'],
                           loan_deals=financial['loan_deals'],
                           cash_deals=financial['cash_deals'],
                           total_gst=financial['total_gst'],
                           recent_deals=recent_deals
                           )

# ========== DOCUMENTS ==========


@dealer_bp.route('/documents')
@dealer_required
@kyc_required
def documents():
    dealer_id = get_dealer_id()
    # Own uploaded documents (dealer's Documents table)
    docs = documents_get_by_dealer(dealer_id)
    vehicles = vehicles_get_by_dealer(dealer_id, per_page=100)['items']
    # CDS documents assigned to this dealer by admin
    try:
        from db import cds_dealer_active_docs
        cds_docs = cds_dealer_active_docs(dealer_id)
    except Exception:
        cds_docs = []

    return render_template('dealer/documents.html', documents=docs, vehicles=vehicles, cds_docs=cds_docs)


@dealer_bp.route('/documents/upload', methods=['POST'])
@dealer_required
@kyc_required
def upload_document():
    dealer_id = get_dealer_id()

    file = request.files.get('document')
    if not file or not file.filename:
        flash('Please select a file', 'error')
        return redirect(url_for('dealer.documents'))

    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in ['pdf', 'jpg', 'jpeg', 'png']:
        flash('Invalid file type. Allowed: PDF, JPG, PNG', 'error')
        return redirect(url_for('dealer.documents'))

    filename = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

    doc_data = {
        'dealer_id': dealer_id,
        'vehicle_id': request.form.get('vehicle_id') or None,
        'customer_name': request.form.get('customer_name'),
        'doc_type': request.form.get('doc_type'),
        'filename': filename,
        'original_name': file.filename,
        'notes': request.form.get('notes')
    }

    document_create(doc_data)

    # ── Register in Centralized Document Storage ──────────────────────────────
    try:
        from db import cds_register
        cds_register({
            'dealer_id':     dealer_id,
            'file_name':     filename,
            'original_name': file.filename,
            'file_path':     os.path.join('images', 'uploads', filename),
            'module_name':   'Documents',
            'document_type': request.form.get('doc_type', ''),
            'uploaded_by':   dealer_id,
            'performed_by':  f'dealer:{dealer_id}',
            'user_role':     'Dealer',
        })
    except Exception:
        pass  # Never break the main upload flow
    # ─────────────────────────────────────────────────────────────────────────

    flash('Document uploaded successfully', 'success')
    return redirect(url_for('dealer.documents'))


@dealer_bp.route('/documents/delete/<int:docid>', methods=['POST'])
@dealer_required
@kyc_required
def delete_document(docid):
    dealer_id = get_dealer_id()
    docs = documents_get_by_dealer(dealer_id)
    doc = next((d for d in docs if d['id'] == docid), None)

    if doc:
        # Delete file
        filepath = os.path.join(
            current_app.config['UPLOAD_FOLDER'], doc['filename'])
        if os.path.exists(filepath):
            os.remove(filepath)
        document_delete(docid)
        flash('Document deleted successfully', 'success')
    else:
        flash('Document not found', 'error')

    return redirect(url_for('dealer.documents'))

# ========== REPORTS ==========


@dealer_bp.route('/reports')
@dealer_required
@kyc_required
def reports():
    dealer_id = get_dealer_id()

    inventory_summary = vehicles_inventory_summary(dealer_id)
    lead_stages = leads_get_stage_counts(dealer_id)
    total_leads = sum(lead_stages.values())
    converted = lead_stages.get('converted', 0)
    conversion_rate = round(
        (converted / total_leads * 100) if total_leads > 0 else 0)

    sources = leads_get_source_counts(dealer_id)
    fuels = vehicles_get_fuel_breakdown(dealer_id)
    monthly = deals_get_monthly_revenue(dealer_id)
    all_deals = deals_get_by_dealer(dealer_id)

    return render_template('dealer/reports.html',
                           total_revenue=sum(
                               d['final_price'] for d in all_deals if d['status'] == 'delivered'),
                           total_inventory=inventory_summary['total'],
                           available_count=inventory_summary['available'],
                           sold_count=inventory_summary['sold'],
                           conversion_rate=conversion_rate,
                           converted=converted,
                           total_leads=total_leads,
                           all_deals=all_deals,
                           sources=sources,
                           fuels=fuels,
                           monthly=monthly
                           )

# ========== INQUIRIES ==========


@dealer_bp.route('/inquiries')
@dealer_required
@kyc_required
def inquiries():
    dealer_id = get_dealer_id()
    inquiries_list = inquiries_get_by_dealer(dealer_id)

    return render_template('dealer/inquiries.html', inquiries=inquiries_list)


@dealer_bp.route('/inquiries/respond/<int:iid>', methods=['POST'])
@dealer_required
@kyc_required
def respond_inquiry(iid):
    dealer_id = get_dealer_id()
    inquiries_list = inquiries_get_by_dealer(dealer_id)
    inquiry = next((i for i in inquiries_list if i['id'] == iid), None)

    if inquiry:
        inquiry_update_status(iid, 'responded')
        flash('Inquiry marked as responded', 'success')
    else:
        flash('Inquiry not found', 'error')

    return redirect(url_for('dealer.inquiries'))

# ========== SUBSCRIPTION ==========


@dealer_bp.route('/subscription')
@dealer_required
def subscription():
    plans = [
        {'name': 'Starter', 'price': '0', 'period': 'month', 'recommended': False,
         'features': ['25 Listings', '50 Leads/month', 'Basic CRM', '100MB Storage']},
        {'name': 'Growth', 'price': '2,999', 'period': 'month', 'recommended': True,
         'features': ['100 Listings', '500 Leads/month', 'Full CRM', '5GB Storage', 'EMI Calculator', 'Analytics Dashboard']},
        {'name': 'Pro', 'price': '5,999', 'period': 'month', 'recommended': False,
         'features': ['Unlimited Listings', 'Unlimited Leads', 'Multi-Branch Support', 'Staff Roles', 'Priority Support', 'API Access']}
    ]

    return render_template('dealer/subscription.html', plans=plans, dealer=g.user)


@dealer_bp.route('/subscription/upgrade/<plan>', methods=['POST'])
@dealer_required
def upgrade_subscription(plan):
    from datetime import datetime, timedelta

    dealer_id = get_dealer_id()
    expiry = datetime.utcnow() + timedelta(days=365)

    user_update_subscription(dealer_id, plan, expiry)
    flash(f'Upgraded to {plan.title()} plan successfully!', 'success')

    return redirect(url_for('dealer.subscription'))

# ========== MY ACCOUNT ==========


@dealer_bp.route('/my-account', methods=['GET', 'POST'])
@dealer_required
def my_account():
    from models import db, User
    dealer_id = get_dealer_id()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update_profile':
            user = User.query.get(dealer_id)
            if user:
                name = request.form.get('name', '').strip()
                phone = request.form.get('phone', '').strip()
                if name:
                    user.name = name
                user.phone = phone
                db.session.commit()
                # Refresh session
                session['user_name'] = user.name
                flash('Profile updated successfully!', 'success')
            return redirect(url_for('dealer.my_account'))

        elif action == 'change_password':
            user = User.query.get(dealer_id)
            if user:
                current_password = request.form.get('current_password', '')
                new_password = request.form.get('new_password', '')
                confirm_password = request.form.get('confirm_password', '')

                if not user.check_password(current_password):
                    flash('Current password is incorrect.', 'error')
                elif len(new_password) < 6:
                    flash('New password must be at least 6 characters.', 'error')
                elif new_password != confirm_password:
                    flash('New passwords do not match.', 'error')
                else:
                    user.set_password(new_password)
                    db.session.commit()
                    flash('Password changed successfully!', 'success')
            return redirect(url_for('dealer.my_account'))

    return render_template('dealer/my_account.html', current_user=g.user)


# ========== WEBSITE SETTINGS ==========


@dealer_bp.route('/website-settings', methods=['GET', 'POST'])
@dealer_required
@kyc_required
def website_settings():
    """Dealer can set their website_name, upload website_logo, and fill contact info."""
    dealer_id = get_dealer_id()
    dealer_user = User.query.get(dealer_id)

    if request.method == 'POST':
        # ── Website name: sanitise to a clean slug ─────────────────────────
        raw_name = request.form.get('website_name', '').strip()
        slug_error = None

        if raw_name:
            import re
            # Keep only alphanumerics, hyphens, underscores; convert spaces → hyphens
            slug = re.sub(r'[^a-zA-Z0-9_-]', '-', raw_name.strip())
            slug = re.sub(r'-{2,}', '-', slug).strip('-')   # collapse multiple hyphens
            slug = slug[:80]                                  # max length

            if not slug:
                slug_error = 'Website name can only contain letters, numbers, hyphens and underscores.'
            else:
                # Check for duplicate (exclude current dealer)
                existing = User.query.filter(
                    User.role == 'dealer',
                    User.website_name == slug,
                    User.id != dealer_id
                ).first()
                if existing:
                    slug_error = f'The name "{slug}" is already taken by another dealer. Please choose a different name.'
                else:
                    dealer_user.website_name = slug

        if slug_error:
            flash(slug_error, 'error')
            # Re-render with error (don't save anything)
            return render_template('dealer/website_settings.html', dealer=dealer_user)

        # ── Optional logo upload ─────────────────────────────────────────
        logo_file = request.files.get('website_logo')
        if logo_file and logo_file.filename and is_allowed_image(logo_file.filename):
            logo_fname = save_uploaded_image(
                logo_file, current_app.config['UPLOAD_FOLDER'],
                f"wlogo_{dealer_id}_{uuid.uuid4().hex[:8]}",
                vehicle_mode=False
            )
            dealer_user.website_logo = logo_fname

        # ── Other fields ─────────────────────────────────────────────────
        dealer_user.whatsapp_number = request.form.get(
            'whatsapp_number', '').strip() or dealer_user.whatsapp_number
        dealer_user.address = request.form.get('address', '').strip()
        dealer_user.google_maps_url = request.form.get(
            'google_maps_url', '').strip()
        dealer_user.years_in_business = request.form.get(
            'years_in_business', type=int) or dealer_user.years_in_business
        dealer_user.business_hours = request.form.get(
            'business_hours', '').strip()

        db.session.commit()
        flash('Website settings saved!', 'success')
        return redirect(url_for('dealer.website_settings'))

    return render_template('dealer/website_settings.html', dealer=dealer_user)
