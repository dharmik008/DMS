"""
utils/upload_helpers.py — Caryanams DMS
Secure image upload helpers for KYC documents and vehicle images.

Vehicle images → HD (1920×1080) + white background + Caryanams logo watermark
KYC documents  → plain save (no processing)
"""
import os
import uuid
import logging
from PIL import Image
import io

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
MAX_IMAGE_BYTES    = 15 * 1024 * 1024   # 15 MB


def allowed_image(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def validate_image(file_storage) -> tuple[bool, str]:
    """Return (ok, error_message). Validates extension + size."""
    if not file_storage or not file_storage.filename:
        return False, 'No file provided.'
    if not allowed_image(file_storage.filename):
        return False, f'Invalid format. Allowed: {", ".join(ALLOWED_EXTENSIONS)}.'
    file_storage.stream.seek(0, 2)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_IMAGE_BYTES:
        return False, f'File too large (max 15 MB). Got {size // (1024*1024)} MB.'
    return True, ''


def delete_image(folder: str, filename: str):
    """Safely delete an image file."""
    if not filename:
        return
    path = os.path.join(folder, filename)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception as e:
        logger.warning(f'[delete_image] Could not delete {path}: {e}')


# ─── Internal pipeline (shared with image_utils) ─────────────────────────────

def _logo_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'static', 'images', 'logo.png')


def _remove_background(img: Image.Image) -> Image.Image:
    try:
        from rembg import remove as rembg_remove
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        result = rembg_remove(buf.getvalue())
        return Image.open(io.BytesIO(result)).convert('RGBA')
    except ImportError:
        logger.info('[upload_helpers] rembg not installed — skipping BG removal')
    except Exception as e:
        logger.warning(f'[upload_helpers] rembg failed: {e}')
    return img.convert('RGBA')


def _place_on_white_hd(fg: Image.Image) -> Image.Image:
    HD_W, HD_H, PAD = 1920, 1080, 0.05
    bbox = fg.getbbox() if fg.mode == 'RGBA' else None
    if bbox:
        fg = fg.crop(bbox)
    fw, fh = fg.size
    avail_w = int(HD_W * (1 - 2 * PAD))
    avail_h = int(HD_H * (1 - 2 * PAD))
    scale   = min(avail_w / fw, avail_h / fh, 1.0)
    nw, nh  = max(1, int(fw * scale)), max(1, int(fh * scale))
    fg_rs   = fg.resize((nw, nh), Image.LANCZOS)
    canvas  = Image.new('RGBA', (HD_W, HD_H), (255, 255, 255, 255))
    px, py  = (HD_W - nw) // 2, (HD_H - nh) // 2
    mask    = fg_rs.split()[3] if fg_rs.mode == 'RGBA' else None
    canvas.paste(fg_rs, (px, py), mask)
    return canvas.convert('RGB')


def _stamp_logo(canvas: Image.Image) -> Image.Image:
    lpath = _logo_path()
    if not os.path.isfile(lpath):
        return canvas
    try:
        logo = Image.open(lpath).convert('RGBA')
        lw, lh = logo.size
        target_w = max(80, int(canvas.width * 0.11))
        scale    = target_w / lw
        logo_rs  = logo.resize((int(lw * scale), int(lh * scale)), Image.LANCZOS)
        r, g, b, a = logo_rs.split()
        a = a.point(lambda x: int(x * 0.70))
        logo_rs = Image.merge('RGBA', (r, g, b, a))
        margin  = int(canvas.width * 0.015)
        px = canvas.width  - logo_rs.width  - margin
        py = canvas.height - logo_rs.height - margin
        base = canvas.convert('RGBA')
        base.paste(logo_rs, (px, py), logo_rs)
        return base.convert('RGB')
    except Exception as e:
        logger.warning(f'[upload_helpers] logo stamp failed: {e}')
        return canvas


def _vehicle_pipeline(raw_bytes: bytes) -> bytes:
    img    = Image.open(io.BytesIO(raw_bytes)).convert('RGB')
    canvas = _stamp_logo(img)
    out    = io.BytesIO()
    canvas.save(out, 'JPEG', quality=92, optimize=True)
    return out.getvalue()


# ─── Public API ───────────────────────────────────────────────────────────────

def save_image(
    file_storage,
    folder: str,
    prefix: str = 'img',
    vehicle_mode: bool = True,   # False for KYC docs / logos
) -> str | None:
    """
    Save an uploaded image.

    vehicle_mode=True  → HD + white BG + logo pipeline → always .jpg
    vehicle_mode=False → plain save (KYC, logos)

    Returns filename or None on error.
    """
    os.makedirs(folder, exist_ok=True)
    uid = uuid.uuid4().hex[:8]

    if vehicle_mode:
        filename  = f'{prefix}_{uid}.jpg'
        dest_path = os.path.join(folder, filename)
        try:
            raw = file_storage.stream.read()
            file_storage.stream.seek(0)
            processed = _vehicle_pipeline(raw)
            with open(dest_path, 'wb') as f:
                f.write(processed)
            logger.info(f'[save_image] vehicle HD: {filename}')
            return filename
        except Exception as e:
            logger.error(f'[save_image] vehicle pipeline error: {e}', exc_info=True)
            file_storage.stream.seek(0)
            # Fall through to plain save

    # Plain save (KYC / logos / pipeline fallback)
    orig_name = file_storage.filename or ''
    ext = orig_name.rsplit('.', 1)[-1].lower() if '.' in orig_name else 'jpg'
    if ext == 'webp':
        ext = 'jpg'
    filename  = f'{prefix}_{uid}.{ext}'
    dest_path = os.path.join(folder, filename)
    try:
        img = Image.open(file_storage.stream)
        if img.mode in ('RGBA', 'P', 'LA'):
            bg = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            bg.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        max_dim = 1600
        w, h = img.size
        if max(w, h) > max_dim:
            ratio = max_dim / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        img.save(dest_path, 'JPEG', quality=85, optimize=True)
        return filename
    except Exception as e:
        logger.error(f'[save_image] plain save error: {e}')
        return None
