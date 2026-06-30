"""
Caryanams Studio — Background Removal Blueprint
Registered at url_prefix='/studio'
"""

import os
import io
import uuid
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone as _tz

_IST = _tz(timedelta(hours=5, minutes=30))


def _now_ist():
    return datetime.now(_IST).replace(tzinfo=None)

from functools import wraps

from flask import (
    Blueprint, render_template, request, jsonify,
    send_file, flash, redirect, url_for, current_app, g, session
)
from PIL import Image

from extensions import db

from subscription_features import feature_required


# ─── Dealer Auth Guard ────────────────────────────────────────────────────────
# Reuses the same g.user session mechanism as dealer/routes.py.
# Does NOT change dealer/routes.py; this is a thin local wrapper.

def _studio_dealer_required(f):
    """Require an active, non-suspended dealer session to access Studio routes."""
    @wraps(f)
    def _decorated(*args, **kwargs):
        user = getattr(g, 'user', None)
        if not user or user.get('role') != 'dealer':
            session.clear()
            if request.is_json or request.path.startswith('/studio/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            flash('Please log in as a dealer to access Caryanams Studio.', 'error')
            return redirect(url_for('auth.login'))
        if not user.get('is_active', True):
            session.clear()
            if request.is_json or request.path.startswith('/studio/api/'):
                return jsonify({'error': 'Account suspended'}), 403
            flash('Your account has been suspended. Please contact the admin.', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return _decorated


from .utils import (
    remove_bg_ai, generate_mask_preview, apply_background_color,
    composite_car_on_static_bg, create_watermark_layer, hex_to_rgb,
    keep_largest_component, remove_persons_and_objects, remove_connected_persons,
    trim_side_cars, trim_top_objects, remove_thin_protrusions,
    restore_tyres, restore_windshield, clean_edges,
    BACKGROUNDS, SWATCHES, STATIC_BG_PATH, allowed_file,
    apply_60_percent_background_blur
)
from utils.image_utils import save_uploaded_image, is_allowed_image

background_bp = Blueprint('background', __name__,
                           template_folder='../templates/background')

# ─── DB Models (local to Studio, separate table) ─────────────────────────────

class StudioImage(db.Model):
    __tablename__ = 'studio_image'
    id                = db.Column(db.String(50),  primary_key=True)
    filename          = db.Column(db.String(255))
    car_name          = db.Column(db.String(255))
    original_path     = db.Column(db.String(500))
    nobg_path         = db.Column(db.String(500))
    processed_path    = db.Column(db.String(500))
    status            = db.Column(db.String(20),  default='uploaded')
    in_gallery        = db.Column(db.Boolean,     default=False)
    bg_removal_method = db.Column(db.String(50),  default='none')
    bg_removal_quality= db.Column(db.String(20),  default='standard')
    session_group     = db.Column(db.String(50),  default=None)
    frame_order       = db.Column(db.Integer,     default=0)
    created_at        = db.Column(db.DateTime,    default=_now_ist)


class StudioCreditLog(db.Model):
    __tablename__ = 'studio_credit_log'
    id        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    action    = db.Column(db.String(100))
    cost      = db.Column(db.Integer, default=0)
    timestamp = db.Column(db.DateTime, default=_now_ist)


# ─── Folder helpers ───────────────────────────────────────────────────────────

def _upload_folder():
    folder = os.path.join(current_app.root_path, 'static', 'images', 'uploads')
    os.makedirs(folder, exist_ok=True)
    return folder

def _processed_folder():
    folder = os.path.join(current_app.root_path, 'static', 'processed')
    os.makedirs(folder, exist_ok=True)
    return folder

def _custom_bg_folder():
    folder = os.path.join(current_app.root_path, 'static', 'custom_bgs')
    os.makedirs(folder, exist_ok=True)
    return folder


# ─── Main Studio Page ─────────────────────────────────────────────────────────

@background_bp.route('/')
@_studio_dealer_required
@feature_required('studio')
def background_removal():
    return render_template('background/remove.html',
                           backgrounds=BACKGROUNDS,
                           swatches=SWATCHES)


# ─── Upload → No BG (with session grouping for 360°) ─────────────────────────

@background_bp.route('/api/upload', methods=['POST'])
@_studio_dealer_required
@feature_required('studio')
def direct_upload_no_bg():
    upload_folder    = _upload_folder()
    processed_folder = _processed_folder()
    os.makedirs(upload_folder, exist_ok=True)

    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': 'No files received'}), 400

    session_group = str(uuid.uuid4())[:12]
    results, errors = [], []
    frame_idx = 0

    for f in files:
        if not f or not f.filename:
            continue
        if not allowed_file(f.filename):
            errors.append(f'{f.filename}: unsupported file type')
            continue
        try:
            uid   = str(uuid.uuid4())[:12]
            # Use save_uploaded_image: converts webp→jpg, keeps png/jpg as-is
            fname = save_uploaded_image(f, upload_folder, f'car_{uid}')
            path  = os.path.join(upload_folder, fname)

            if not os.path.exists(path) or os.path.getsize(path) == 0:
                errors.append(f'{f.filename}: save failed')
                continue

            car = StudioImage(
                id=uid, filename=fname,
                car_name=os.path.splitext(f.filename)[0],
                original_path=path,
                nobg_path=None, status='uploaded',
                bg_removal_method='none', bg_removal_quality='standard',
                session_group=session_group, frame_order=frame_idx
            )
            db.session.add(car)
            frame_idx += 1

            # Assign default view angle based on upload order (0=Front,1=Back,2=Left,3=Right)
            VIEW_ANGLES = ['front', 'back', 'left', 'right']
            view_angle = VIEW_ANGLES[frame_idx - 1] if frame_idx <= 4 else 'other'

            results.append({
                'id': uid, 'filename': fname,
                'car_name': car.car_name,
                'original_url': '/static/images/uploads/' + fname,
                'nobg_url': None,
                'bg_removed': False, 'method': None,
                'session_group': session_group,
                'view_angle': view_angle
            })
        except Exception as e:
            errors.append(str(e))

    if not results and errors:
        db.session.rollback()
        return jsonify({'error': '; '.join(errors)}), 500

    db.session.commit()
    return jsonify(results)


# ─── Remove BG (single) ───────────────────────────────────────────────────────

@background_bp.route('/api/remove-bg/<image_id>', methods=['POST'])
@_studio_dealer_required
@feature_required('studio')
def remove_bg_route(image_id):
    car  = StudioImage.query.get(image_id)
    if car is None:
        return jsonify({'error': 'Image not found'}), 404
    data = request.get_json(silent=True) or {}
    engine         = data.get('engine', 'auto')
    quality        = data.get('quality', 'standard')
    despill_enable = bool(data.get('despill', False))

    result, method = remove_bg_ai(car.original_path, quality=quality,
                                   engine=engine, despill_enable=despill_enable)
    bg_removed = True
    if result is None:
        result     = Image.open(car.original_path).convert('RGBA')
        method     = 'original_kept'
        bg_removed = False

    # ── New masking engine post-processing chain ──────────────────────────────
    if bg_removed:
        try:
            result = keep_largest_component(result)
            result = remove_persons_and_objects(result)
            result = remove_connected_persons(result)
            result = trim_side_cars(result)
            result = trim_top_objects(result)
            result = remove_thin_protrusions(result)
            result = restore_tyres(result)
            result = restore_windshield(result)
        except Exception as _e_clean:
            current_app.logger.warning(f'[remove_bg] post-cleanup error (non-fatal): {_e_clean}')

    processed_folder = _processed_folder()
    out_path = os.path.join(processed_folder, f'nobg_{car.id}.png')
    result.save(out_path, 'PNG')
    preview_b64 = generate_mask_preview(result)

    car.nobg_path          = out_path
    car.status             = 'bg_removed' if bg_removed else 'uploaded'
    car.bg_removal_method  = method
    car.bg_removal_quality = quality
    db.session.add(StudioCreditLog(action=f'BG Removal [{method}]', cost=0))
    db.session.commit()

    return jsonify({
        'nobg_url':    '/static/images/uploads/' + os.path.basename(out_path),
        'status':      car.status,
        'method':      method,
        'quality':     quality,
        'bg_removed':  bg_removed,
        'preview_b64': preview_b64,
        'image_size':  list(result.size)
    })


# ─── Remove BG Batch ──────────────────────────────────────────────────────────

@background_bp.route('/api/remove-bg-batch', methods=['POST'])
@_studio_dealer_required
@feature_required('studio')
def remove_bg_batch():
    data       = request.get_json(silent=True) or {}
    ids        = data.get('ids', [])
    engine     = data.get('engine', 'auto')
    quality    = data.get('quality', 'standard')
    despill_en = bool(data.get('despill', False))

    if not ids:
        return jsonify({'error': 'No image IDs provided'}), 400

    processed_folder = _processed_folder()
    cars = {cid: StudioImage.query.get(cid) for cid in ids}

    def _process_one(args):
        car_id, orig_path = args
        try:
            img, method = remove_bg_ai(orig_path, quality=quality,
                                        engine=engine, despill_enable=despill_en)
            if img is None:
                img    = Image.open(orig_path).convert('RGBA')
                method = 'original_kept'

            # New masking engine post-processing chain
            if method != 'original_kept':
                try:
                    img = keep_largest_component(img)
                    img = remove_persons_and_objects(img)
                    img = remove_connected_persons(img)
                    img = trim_side_cars(img)
                    img = trim_top_objects(img)
                    img = remove_thin_protrusions(img)
                    img = restore_tyres(img)
                    img = restore_windshield(img)
                except Exception as _ec:
                    pass  # non-fatal

            out = os.path.join(processed_folder, f'nobg_{car_id}.png')
            img.save(out, 'PNG')
            preview = generate_mask_preview(img)
            return {'id': car_id, 'nobg_path': out, 'method': method,
                    'preview_b64': preview, 'success': True,
                    'bg_removed': method != 'original_kept'}
        except Exception as e:
            return {'id': car_id, 'error': str(e), 'success': False}

    task_args = [(cid, cars[cid].original_path) for cid in ids if cid in cars]
    results   = []
    with ThreadPoolExecutor(max_workers=min(len(task_args), 4)) as ex:
        futs = {ex.submit(_process_one, a): a[0] for a in task_args}
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({'id': futs[fut], 'error': str(e), 'success': False})

    for res in results:
        if res.get('success'):
            car = cars.get(res['id'])
            if car:
                car.nobg_path          = res['nobg_path']
                car.status             = 'bg_removed' if res.get('bg_removed') else 'uploaded'
                car.bg_removal_method  = res.get('method', 'auto')
                car.bg_removal_quality = quality
                db.session.add(StudioCreditLog(action=f'Batch BG [{res.get("method")}]', cost=0))
    db.session.commit()

    done = sum(1 for r in results if r.get('success'))
    return jsonify({'results': results, 'done': done, 'total': len(ids)})


# ─── Apply Background ─────────────────────────────────────────────────────────

@background_bp.route('/api/apply-bg/<image_id>', methods=['POST'])
@_studio_dealer_required
@feature_required('studio')
def apply_bg_route(image_id):
    car  = StudioImage.query.get(image_id)
    if car is None:
        return jsonify({'error': 'Image not found'}), 404
    data = request.json or {}

    bg_id            = data.get('bg_id', 'studio_white')
    custom_color     = data.get('custom_color')
    custom_bg_path   = data.get('custom_bg_path')
    use_static_bg    = bool(data.get('use_static_bg', True))
    use_blur_bg      = bool(data.get('use_blur_bg', False))
    lighting         = float(data.get('lighting', 1.0))
    shadow           = data.get('shadow', True)
    shadow_intensity = float(data.get('shadow_intensity', 0.85))
    shadow_blur      = int(data.get('shadow_blur', 40))
    width            = int(data.get('width', 1200))
    height           = int(data.get('height', 800))
    car_size_percent = float(data.get('car_size_percent', 78))
    engine           = data.get('engine', 'auto')
    quality          = data.get('quality', 'standard')

    # Auto-remove bg if not done yet
    auto_removed = False
    if not car.nobg_path or not os.path.exists(car.nobg_path):
        try:
            result, method = remove_bg_ai(car.original_path, quality=quality, engine=engine)
            if result is not None:
                # New masking engine post-processing chain
                try:
                    result = keep_largest_component(result)
                    result = remove_persons_and_objects(result)
                    result = remove_connected_persons(result)
                    result = trim_side_cars(result)
                    result = trim_top_objects(result)
                    result = remove_thin_protrusions(result)
                    result = restore_tyres(result)
                    result = restore_windshield(result)
                except Exception as _ec:
                    pass  # non-fatal
                pf = _processed_folder()
                nobg_path = os.path.join(pf, f'nobg_{car.id}.png')
                result.save(nobg_path, 'PNG')
                car.nobg_path          = nobg_path
                car.status             = 'bg_removed'
                car.bg_removal_method  = method
                car.bg_removal_quality = quality
                db.session.add(StudioCreditLog(action=f'Auto BG [{method}]', cost=0))
                auto_removed = True
        except Exception as e:
            print(f'Auto BG remove failed: {e}')

    src = car.nobg_path if (car.nobg_path and os.path.exists(car.nobg_path)) else car.original_path
    fg  = Image.open(src).convert('RGBA')

    # Get original image dimensions to preserve size
    original_img = Image.open(car.original_path)
    orig_w, orig_h = original_img.size
    original_img.close()
    orig_size = (orig_w, orig_h)

    processed_folder = _processed_folder()

    if use_blur_bg:
        result  = apply_60_percent_background_blur(car.original_path, fg)
        bg_used = 'blur_real_background'
    elif use_static_bg and os.path.exists(STATIC_BG_PATH):
        tint_color = None
        if bg_id and bg_id != 'studio_white':
            if bg_id == 'custom' and custom_color:
                tint_color = hex_to_rgb(custom_color)
            else:
                all_bgs = BACKGROUNDS['studio'] + BACKGROUNDS['outdoor']
                found   = next((b for b in all_bgs if b['id'] == bg_id), None)
                if found:
                    tint_color = hex_to_rgb(found['color'])
        result = composite_car_on_static_bg(fg, car_size_percent=car_size_percent,
                                             lighting=lighting, tint_color=tint_color,
                                             preserve_size=True, original_size=orig_size)
        bg_used = 'static_studio_' + (bg_id or 'default')
    else:
        bg_rgb = None
        bg_image_path = None
        if custom_bg_path and os.path.exists(custom_bg_path):
            bg_image_path = custom_bg_path
        elif bg_id == 'custom' and custom_color:
            bg_rgb = hex_to_rgb(custom_color)
        else:
            all_bgs = BACKGROUNDS['studio'] + BACKGROUNDS['outdoor']
            found   = next((b for b in all_bgs if b['id'] == bg_id), None)
            bg_rgb  = hex_to_rgb(found['color']) if found else (255, 255, 255)
        result = apply_background_color(
            fg, bg_rgb, width, height, lighting=lighting, shadow=shadow,
            shadow_intensity=shadow_intensity, shadow_blur=shadow_blur,
            bg_image_path=bg_image_path, car_size_percent=car_size_percent,
            preserve_size=True, original_size=orig_size
        )
        bg_used = bg_id

    out_path = os.path.join(processed_folder, f'proc_{car.id}.jpg')
    result.save(out_path, 'JPEG', quality=95)
    car.processed_path = out_path
    car.status         = 'completed'
    db.session.add(StudioCreditLog(action=f'Apply Background [{bg_used}]', cost=0))
    db.session.commit()

    return jsonify({
        'processed_url':  '/static/processed/' + os.path.basename(out_path),
        'status':         'completed',
        'auto_bg_removed': auto_removed,
        'bg_used':        bg_used
    })


# ─── Apply to All ─────────────────────────────────────────────────────────────

@background_bp.route('/api/apply-to-all', methods=['POST'])
@_studio_dealer_required
@feature_required('studio')
def apply_to_all():
    data             = request.json or {}
    ids              = data.get('ids', [])
    bg_id            = data.get('bg_id', 'studio_white')
    custom_color     = data.get('custom_color')
    custom_bg_path   = data.get('custom_bg_path')
    use_static_bg    = bool(data.get('use_static_bg', True))
    lighting         = float(data.get('lighting', 1.0))
    shadow           = data.get('shadow', True)
    shadow_intensity = float(data.get('shadow_intensity', 0.85))
    shadow_blur      = int(data.get('shadow_blur', 40))
    width            = int(data.get('width', 1200))
    height           = int(data.get('height', 800))
    car_size_percent = float(data.get('car_size_percent', 78))
    engine           = data.get('engine', 'auto')
    quality          = data.get('quality', 'standard')

    tint_color = bg_rgb = bg_image_path = None
    if use_static_bg:
        if bg_id == 'custom' and custom_color:
            tint_color = hex_to_rgb(custom_color)
        elif bg_id and bg_id not in ('studio_white', ''):
            all_bgs = BACKGROUNDS['studio'] + BACKGROUNDS['outdoor']
            found   = next((b for b in all_bgs if b['id'] == bg_id), None)
            if found:
                tint_color = hex_to_rgb(found['color'])
    else:
        if custom_bg_path and os.path.exists(custom_bg_path):
            bg_image_path = custom_bg_path
        elif bg_id == 'custom' and custom_color:
            bg_rgb = hex_to_rgb(custom_color)
        else:
            all_bgs = BACKGROUNDS['studio'] + BACKGROUNDS['outdoor']
            found   = next((b for b in all_bgs if b['id'] == bg_id), None)
            bg_rgb  = hex_to_rgb(found['color']) if found else (255, 255, 255)

    pf   = _processed_folder()
    cars = {cid: StudioImage.query.get(cid) for cid in ids}

    def _process_one(cid):
        car = cars.get(cid)
        if not car:
            return cid, False, None
        nobg_path   = car.nobg_path if car.nobg_path and os.path.exists(car.nobg_path) else None
        method_used = 'none'
        if not nobg_path:
            try:
                img, method_used = remove_bg_ai(car.original_path, quality=quality, engine=engine)
                if img is not None:
                    # New masking engine post-processing chain
                    try:
                        img = keep_largest_component(img)
                        img = remove_persons_and_objects(img)
                        img = remove_connected_persons(img)
                        img = trim_side_cars(img)
                        img = trim_top_objects(img)
                        img = remove_thin_protrusions(img)
                        img = restore_tyres(img)
                        img = restore_windshield(img)
                    except Exception as _ec:
                        pass  # non-fatal
                    nobg_path = os.path.join(pf, f'nobg_{cid}.png')
                    img.save(nobg_path, 'PNG')
            except Exception as e:
                print(f'BG remove failed {cid}: {e}')
                nobg_path = None
        try:
            src = nobg_path or car.original_path
            fg  = Image.open(src).convert('RGBA')
            # Preserve original image dimensions
            orig_img  = Image.open(car.original_path)
            orig_size = orig_img.size
            orig_img.close()
            if use_static_bg and os.path.exists(STATIC_BG_PATH):
                proc = composite_car_on_static_bg(fg, car_size_percent=car_size_percent,
                                                   lighting=lighting, tint_color=tint_color,
                                                   preserve_size=True, original_size=orig_size)
            else:
                proc = apply_background_color(
                    fg, bg_rgb, width, height, lighting=lighting, shadow=shadow,
                    shadow_intensity=shadow_intensity, shadow_blur=shadow_blur,
                    bg_image_path=bg_image_path, car_size_percent=car_size_percent,
                    preserve_size=True, original_size=orig_size
                )
            out = os.path.join(pf, f'proc_{cid}.jpg')
            proc.save(out, 'JPEG', quality=95)
            return cid, True, {'nobg': nobg_path, 'proc': out, 'method': method_used}
        except Exception as e:
            print(f'Apply BG failed {cid}: {e}')
            return cid, False, None

    futures_results = []
    with ThreadPoolExecutor(max_workers=min(len(ids), 4)) as ex:
        futs = {ex.submit(_process_one, cid): cid for cid in ids}
        for fut in as_completed(futs):
            try:
                futures_results.append(fut.result())
            except Exception as e:
                futures_results.append((futs[fut], False, None))

    done = 0
    for cid, success, info in futures_results:
        car = cars.get(cid)
        if car and success and info:
            if info.get('nobg'):
                car.nobg_path = info['nobg']
            car.processed_path = info['proc']
            car.status         = 'completed'
            db.session.add(StudioCreditLog(action='Bulk Process', cost=0))
            done += 1
    db.session.commit()
    return jsonify({'done': done, 'total': len(ids)})


# ─── Upload Custom BG Image ───────────────────────────────────────────────────

@background_bp.route('/api/upload-bg-image', methods=['POST'])
@_studio_dealer_required
@feature_required('studio')
def upload_bg_image():
    folder = _custom_bg_folder()
    f = request.files.get('bg_image')
    if not f or not f.filename:
        return jsonify({'error': 'No file'}), 400
    ext   = os.path.splitext(f.filename)[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
        ext = '.jpg'
    uid   = str(uuid.uuid4())[:10]
    fname = f'bg_{uid}{ext}'
    path  = os.path.join(folder, fname)
    f.save(path)
    try:
        img = Image.open(path).convert('RGB')
        img.thumbnail((240, 160), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=70)
        thumb_b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception:
        thumb_b64 = ''
    return jsonify({'bg_id': 'custom_img_' + uid, 'path': path,
                    'url': '/static/custom_bgs/' + fname, 'thumb_b64': thumb_b64})


# ─── Static BG Thumb ─────────────────────────────────────────────────────────

@background_bp.route('/api/static-bg-thumb')
@_studio_dealer_required
@feature_required('studio')
def static_bg_thumb():
    if not os.path.exists(STATIC_BG_PATH):
        return jsonify({'error': 'Static BG not found'}), 404
    try:
        img = Image.open(STATIC_BG_PATH).convert('RGB')
        img.thumbnail((280, 124), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=75)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return jsonify({'thumb_b64': b64, 'available': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─── Gallery ──────────────────────────────────────────────────────────────────

@background_bp.route('/api/gallery')
@_studio_dealer_required
@feature_required('studio')
def get_gallery():
    cars = StudioImage.query.filter_by(in_gallery=True)\
                .order_by(StudioImage.created_at.desc()).all()
    return jsonify([{
        'id': c.id, 'car_name': c.car_name, 'status': c.status,
        'original_url':  ('/static/images/uploads/' + os.path.basename(c.original_path))  if c.original_path else None,
        'nobg_url':      ('/static/images/uploads/' + os.path.basename(c.nobg_path))      if c.nobg_path      else None,
        'processed_url': ('/static/processed/'      + os.path.basename(c.processed_path)) if c.processed_path else None,
        'bg_removal_method':  c.bg_removal_method,
        'bg_removal_quality': c.bg_removal_quality,
        'session_group': c.session_group,
        'frame_order':   c.frame_order or 0
    } for c in cars])


@background_bp.route('/api/save-gallery', methods=['POST'])
@_studio_dealer_required
@feature_required('studio')
def save_gallery():
    for cid in request.json.get('ids', []):
        car = StudioImage.query.get(cid)
        if car:
            car.in_gallery = True
    db.session.commit()
    return jsonify({'ok': True})


# ── FEATURE 1 FIX: Save processed Studio image back to a Vehicle record ───────
# Called by the "Save to Inventory" button in Studio (only visible when Studio
# was opened with ?vehicle_id=X from the vehicle edit page).
# Copies the processed file into static/images/uploads/ and updates the
# vehicle's image_filename column — no manual re-upload needed.
@background_bp.route('/api/save-to-inventory', methods=['POST'])
@_studio_dealer_required
@feature_required('studio')
def save_to_inventory():
    import shutil
    try:
        data       = request.get_json(silent=True) or {}
        image_id   = data.get('image_id')
        vehicle_id = data.get('vehicle_id')

        if not image_id or not vehicle_id:
            return jsonify({'error': 'image_id and vehicle_id are required'}), 400

        car = StudioImage.query.get(image_id)
        if not car:
            return jsonify({'error': 'Studio image not found'}), 404

        # Prefer fully composited image; fall back to no-bg PNG
        source_path = car.processed_path or car.nobg_path
        if not source_path or not os.path.exists(source_path):
            return jsonify({'error': 'No processed image found. Apply a background in Studio first, or just remove background.'}), 400

        from models import Vehicle
        vehicle = Vehicle.query.get(int(vehicle_id))
        if not vehicle:
            return jsonify({'error': f'Vehicle {vehicle_id} not found'}), 404

        # Copy into uploads folder with a unique filename
        upload_folder = os.path.join(current_app.root_path, 'static', 'images', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)

        new_fname = f'studio_{vehicle_id}_{uuid.uuid4().hex[:8]}.jpg'
        dest_path = os.path.join(upload_folder, new_fname)
        shutil.copy2(source_path, dest_path)

        # ── Dedup guard: check if this exact studio_image_id was already pushed ──
        from models import VehicleImage
        existing = VehicleImage.query.filter_by(
            vehicle_id=int(vehicle_id),
            filename=new_fname  # new_fname is always unique (uuid), so check via image_id tag
        ).first()

        # Update the vehicle primary image
        vehicle.image_filename = new_fname
        db.session.flush()

        # Also register in VehicleImage gallery for multi-image display
        # Tag the filename with studio source id to prevent re-push duplicates
        studio_tag_fname = f'studio_{image_id}_{new_fname}'
        already_in_gallery = VehicleImage.query.filter(
            VehicleImage.vehicle_id == int(vehicle_id),
            VehicleImage.filename.like(f'studio_{image_id}_%')
        ).first()

        if not already_in_gallery:
            # Rename file to include studio tag for dedup tracking
            tagged_dest = os.path.join(upload_folder, studio_tag_fname)
            os.rename(dest_path, tagged_dest)
            new_fname = studio_tag_fname

            # Update primary image to tagged name
            vehicle.image_filename = new_fname

            # Add to gallery
            gallery_entry = VehicleImage(
                vehicle_id=int(vehicle_id),
                filename=new_fname,
                sort_order=0  # Studio images go first
            )
            db.session.add(gallery_entry)

        db.session.commit()

        return jsonify({
            'ok':         True,
            'filename':   new_fname,
            'image_url':  f'/static/images/uploads/{new_fname}',
            'vehicle_id': vehicle_id,
        }), 200

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('save-to-inventory failed')
        return jsonify({'error': str(exc)}), 500


@background_bp.route('/api/gallery/<image_id>', methods=['DELETE'])
@_studio_dealer_required
@feature_required('studio')
def delete_gallery(image_id):
    car = StudioImage.query.get(image_id)
    for p in [car.original_path, car.nobg_path, car.processed_path]:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
    db.session.delete(car)
    db.session.commit()
    return jsonify({'ok': True})


# ─── Download ─────────────────────────────────────────────────────────────────

@background_bp.route('/api/download/<image_id>')
@_studio_dealer_required
@feature_required('studio')
def download_image(image_id):
    car  = StudioImage.query.get(image_id)
    path = car.processed_path or car.original_path
    if not path or not os.path.exists(path):
        return jsonify({'error': 'File not found'}), 404
    return send_file(path, as_attachment=True,
                     download_name=f'Caryanams_studio_{car.car_name}.jpg')


# ─── 360° Viewer ──────────────────────────────────────────────────────────────

@background_bp.route('/api/car-360/<image_id>')
@_studio_dealer_required
@feature_required('studio')
def car_360_view(image_id):
    car = StudioImage.query.get(image_id)
    frames = StudioImage.query.filter_by(session_group=car.session_group)\
                 .order_by(StudioImage.frame_order.asc()).all() if car.session_group else [car]
    result = []
    for f in frames:
        url = None
        if f.processed_path and os.path.exists(f.processed_path):
            url = '/static/processed/' + os.path.basename(f.processed_path)
        elif f.nobg_path and os.path.exists(f.nobg_path):
            url = '/static/images/uploads/' + os.path.basename(f.nobg_path)
        elif f.original_path and os.path.exists(f.original_path):
            url = '/static/images/uploads/' + os.path.basename(f.original_path)
        if url:
            result.append({'id': f.id, 'url': url, 'frame_order': f.frame_order,
                           'status': f.status, 'car_name': f.car_name})
    return jsonify({'frames': result, 'total_frames': len(result),
                    'session_group': car.session_group, 'car_name': car.car_name,
                    'is_multi_frame': len(result) > 1})


# ─── Watermark Only ───────────────────────────────────────────────────────────

@background_bp.route('/api/watermark/<image_id>', methods=['POST'])
@_studio_dealer_required
@feature_required('studio')
def watermark_route(image_id):
    car = StudioImage.query.get(image_id)
    src = car.processed_path or car.nobg_path or car.original_path
    img = Image.open(src).convert('RGB')
    W, H    = img.size
    canvas  = img.convert('RGBA')
    wm      = create_watermark_layer(W, H)
    canvas  = Image.alpha_composite(canvas, wm)
    result  = canvas.convert('RGB')
    pf      = _processed_folder()
    out     = os.path.join(pf, f'wm_{car.id}.jpg')
    result.save(out, 'JPEG', quality=92)
    car.processed_path = out
    car.status         = 'completed'
    db.session.commit()
    return jsonify({'processed_url': '/static/processed/' + os.path.basename(out)})


# ─── Resize ───────────────────────────────────────────────────────────────────

@background_bp.route('/api/resize/<image_id>', methods=['POST'])
@_studio_dealer_required
@feature_required('studio')
def resize_route(image_id):
    car  = StudioImage.query.get(image_id)
    if car is None:
        return jsonify({'error': 'Image not found'}), 404
    data = request.json or {}
    w    = int(data.get('width', 1200))
    h    = int(data.get('height', 800))
    src  = car.processed_path or car.nobg_path or car.original_path
    img  = Image.open(src).convert('RGB').resize((w, h), Image.LANCZOS)
    pf   = _processed_folder()
    out  = os.path.join(pf, f'rsz_{car.id}.jpg')
    img.save(out, 'JPEG', quality=92)
    car.processed_path = out
    db.session.commit()
    return jsonify({'processed_url': '/static/processed/' + os.path.basename(out), 'width': w, 'height': h})


# ─── Credit Logs ──────────────────────────────────────────────────────────────

@background_bp.route('/api/credit-logs')
@_studio_dealer_required
@feature_required('studio')
def credit_logs():
    logs = StudioCreditLog.query.order_by(StudioCreditLog.timestamp.desc()).limit(100).all()
    return jsonify([{'action': l.action, 'cost': l.cost,
                     'time': l.timestamp.isoformat()} for l in logs])


# ════════════════════════════════════════════════════════════════
#  MASK EDITOR — Vehicle Image direct edit (plate + BG removal)
#  These routes are called from admin/vehicle_images.html and
#  dealer/inventory_detail.html when user clicks 🎨 Mask Edit.
# ════════════════════════════════════════════════════════════════

@background_bp.route('/api/mask-editor/load-vehicle-image/<int:vi_id>')
@_studio_dealer_required
@feature_required('studio')
def mask_editor_load(vi_id):
    """Return base64 of a VehicleImage so the mask editor can show it."""
    from models import VehicleImage
    vi = VehicleImage.query.get(vi_id)
    if not vi:
        return jsonify({'error': 'Image not found'}), 404
    path = os.path.join(current_app.root_path, 'static', 'images', 'uploads', vi.filename)
    if not os.path.exists(path):
        return jsonify({'error': 'File missing on disk'}), 404
    with open(path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    ext = os.path.splitext(vi.filename)[1].lower().lstrip('.')
    mime = 'image/jpeg' if ext in ('jpg', 'jpeg') else f'image/{ext}'
    return jsonify({
        'ok': True,
        'vi_id': vi_id,
        'vehicle_id': vi.vehicle_id,
        'filename': vi.filename,
        'url': f'/static/images/uploads/{vi.filename}',
        'data_url': f'data:{mime};base64,{b64}'
    })


@background_bp.route('/api/mask-editor/upload-for-edit', methods=['POST'])
@_studio_dealer_required
@feature_required('studio')
def mask_editor_upload():
    """
    Upload a vehicle image file (identified by vi_id) into Studio for editing.
    Creates a temporary StudioImage record and returns its id so the
    plate_remover JS can call /api/detect-plate/<id> and /api/process-car/<id>.
    """
    from models import VehicleImage
    vi_id = request.form.get('vi_id')
    if not vi_id:
        return jsonify({'error': 'vi_id required'}), 400
    vi = VehicleImage.query.get(int(vi_id))
    if not vi:
        return jsonify({'error': 'VehicleImage not found'}), 404

    src_path = os.path.join(current_app.root_path, 'static', 'images', 'uploads', vi.filename)
    if not os.path.exists(src_path):
        return jsonify({'error': 'Source file missing'}), 404

    import shutil
    uid = str(uuid.uuid4())[:12]
    upload_folder = _upload_folder()
    ext   = os.path.splitext(vi.filename)[1] or '.jpg'
    fname = f'medit_{uid}{ext}'
    dest  = os.path.join(upload_folder, fname)
    shutil.copy2(src_path, dest)

    car = StudioImage(
        id=uid, filename=fname,
        car_name=vi.filename,
        original_path=dest,
        nobg_path=None, status='uploaded',
        bg_removal_method='none', bg_removal_quality='standard',
    )
    db.session.add(car)
    db.session.commit()

    return jsonify({
        'ok': True,
        'studio_id': uid,
        'original_url': f'/static/images/uploads/{fname}',
        'vi_id': vi_id,
        'vehicle_id': vi.vehicle_id,
    })


@background_bp.route('/api/mask-editor/save-back', methods=['POST'])
@_studio_dealer_required
@feature_required('studio')
def mask_editor_save_back():
    """
    After processing, copy the studio processed image back to the VehicleImage
    record — REPLACING the original file in-place (same filename in DB).
    """
    from models import VehicleImage, Vehicle
    import shutil
    data = request.get_json(silent=True) or {}
    studio_id = data.get('studio_id')
    vi_id     = data.get('vi_id')

    if not studio_id or not vi_id:
        return jsonify({'error': 'studio_id and vi_id required'}), 400

    car = StudioImage.query.get(studio_id)
    if not car:
        return jsonify({'error': 'Studio record not found'}), 404

    vi = VehicleImage.query.get(int(vi_id))
    if not vi:
        return jsonify({'error': 'VehicleImage not found'}), 404

    src_path = car.processed_path or car.nobg_path
    if not src_path or not os.path.exists(src_path):
        return jsonify({'error': 'No processed image to save. Please process first.'}), 400

    # Overwrite the existing file (keep same filename so DB stays consistent)
    dest_path = os.path.join(current_app.root_path, 'static', 'images', 'uploads', vi.filename)

    # Convert PNG to JPG if target is jpg (preserve format of original)
    ext_dest = os.path.splitext(vi.filename)[1].lower()
    if ext_dest in ('.jpg', '.jpeg'):
        img = Image.open(src_path).convert('RGB')
        img.save(dest_path, 'JPEG', quality=92)
    else:
        shutil.copy2(src_path, dest_path)

    # If this image is the vehicle's primary, update timestamp to bust caches
    vehicle = Vehicle.query.get(vi.vehicle_id)
    if vehicle and vehicle.image_filename == vi.filename:
        # Touch updated_at if field exists
        try:
            # datetime already imported
            vehicle.updated_at = _now_ist()
        except Exception:
            pass
        db.session.commit()

    return jsonify({
        'ok': True,
        'vi_id': vi_id,
        'vehicle_id': vi.vehicle_id,
        'filename': vi.filename,
        'image_url': f'/static/images/uploads/{vi.filename}?t={uuid.uuid4().hex[:8]}',
    })


# ── Plate editor helper routes (called from mask editor JS) ───────────────────

@background_bp.route('/api/detect-plate/<studio_id>')
@_studio_dealer_required
@feature_required('studio')
def studio_detect_plate(studio_id):
    """Detect license plate on a StudioImage and return bounding box."""
    from .utils import detect_number_plate
    car = StudioImage.query.get(studio_id)
    if not car:
        return jsonify({'detected': False, 'message': 'Studio image not found'}), 404
    path = car.original_path
    if not os.path.exists(path):
        return jsonify({'detected': False, 'message': 'File missing'}), 404
    plate = detect_number_plate(path)
    try:
        iw, ih = Image.open(path).size
    except Exception as e:
        current_app.logger.error(f'studio_detect_plate: cannot read image dimensions: {e}')
        return jsonify({'detected': False, 'message': f'Image file is corrupt or unreadable: {str(e)}'}), 400
    if plate:
        x, y, w, h = plate
        return jsonify({'detected': True, 'x': x, 'y': y, 'width': w, 'height': h,
                        'img_width': iw, 'img_height': ih})
    return jsonify({'detected': False, 'img_width': iw, 'img_height': ih,
                    'message': 'Auto-detection failed. Use manual selection.'})


@background_bp.route('/api/process-car/<studio_id>', methods=['POST'])
@_studio_dealer_required
@feature_required('studio')
def studio_process_car(studio_id):
    """One-click: plate remove + BG remove + showroom BG. Returns processed image URL."""
    from .utils import process_plate_and_background
    car = StudioImage.query.get(studio_id)
    if not car:
        return jsonify({'success': False, 'message': 'Studio image not found'}), 404
    data = request.get_json(silent=True) or {}
    mode           = data.get('mode', 'caryanams')
    manual         = data.get('manual')
    quad           = data.get('quad')   # optional 4-point quad for perspective plate warp
    car_size_pct   = int(data.get('car_size_pct', 75))
    image_category = data.get('image_category', 'exterior')
    quality        = data.get('quality', 'ultra')

    # Verify source file exists
    if not car.original_path or not os.path.exists(car.original_path):
        current_app.logger.error(f'studio_process_car: source file missing: {car.original_path}')
        return jsonify({'success': False, 'message': f'Source image file not found on server. Please re-upload.'}), 400

    pf = _processed_folder()
    output_path = os.path.join(pf, f'medit_final_{studio_id}.png')

    try:
        ok, plate_info = process_plate_and_background(
            car.original_path, output_path, mode=mode, manual=manual,
            car_size_pct=car_size_pct, image_category=image_category,
            quad=quad, quality=quality
        )
    except Exception as e:
        current_app.logger.exception(f'studio_process_car: process_plate_and_background raised: {e}')
        return jsonify({'success': False, 'message': f'Processing error: {str(e)}'}), 500

    if ok and os.path.exists(output_path):
        car.processed_path = output_path
        car.status = 'processed'
        db.session.commit()
        with open(output_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()

        if image_category == 'interior':
            msg = '✅ Interior image saved (full-screen, original background preserved)!'
        elif image_category == 'plate_only':
            msg = '✅ Number plate hidden (original background preserved)!'
        elif image_category == 'bg_only':
            msg = '✅ Background removed + Showroom BG applied (plate unchanged)!'
        else:
            msg = '✅ Plate removed + Background removed + Showroom BG applied!'

        return jsonify({
            'success': True,
            'processed_url': f'/static/processed/{os.path.basename(output_path)}',
            'preview_b64': b64,
            'plate': plate_info,
            'image_category': image_category,
            'message': msg
        })

    # ── Detailed failure reason ───────────────────────────────────────────────
    reasons = []
    # Check rembg
    try:
        from rembg import remove as _r
    except ImportError:
        reasons.append('AI background removal (rembg) is not installed')
    # Check opencv fallback
    try:
        import cv2  # noqa
    except ImportError:
        reasons.append('OpenCV (cv2) fallback is also missing')
    # Check static bg
    from .utils import STATIC_BG_PATH
    if not os.path.exists(STATIC_BG_PATH):
        reasons.append(f'Showroom background image is missing on server')
    # Check output
    if not os.path.exists(output_path):
        reasons.append('Output file could not be created — please try Manual Select to mark the plate manually')

    reason_str = ' | '.join(reasons) if reasons else 'Unknown processing error — check server logs'
    current_app.logger.error(f'studio_process_car FAILED for {studio_id}: {reason_str}')
    return jsonify({'success': False, 'message': f'Processing failed: {reason_str}'})


@background_bp.route('/api/download-inline-studio/<studio_id>')
@_studio_dealer_required
@feature_required('studio')
def studio_download_inline(studio_id):
    """Serve processed studio image inline (for canvas operations in mask editor)."""
    from flask import make_response
    car = StudioImage.query.get(studio_id)
    if not car:
        return jsonify({'error': 'not found'}), 404
    path = car.processed_path or car.original_path
    try:
        resp = make_response(send_file(path, mimetype='image/png'))
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Cache-Control'] = 'no-cache'
        return resp
    except Exception as e:
        return jsonify({'error': str(e)}), 500
