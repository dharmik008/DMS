"""
utils/image_utils.py — Caryanams Image Processing Pipeline
============================================================

save_uploaded_image() — FAST plain save for ALL uploads (vehicle + KYC + logo).
  - NO background removal at upload time (rembg removed from upload pipeline)
  - Background removal happens ONLY in Mask Editor (studio/api/process-car)
  - vehicle_mode=True: resize to max 1920x1080 if larger, stamp logo, save as JPEG 92
  - vehicle_mode=False: plain save (KYC docs, logos, etc.)

Format rules:
  .webp  → convert to .jpg
  .png   → keep as .png  (unless vehicle_mode=True, then → .jpg)
  .jpg / .jpeg → .jpg
"""

import os
import io
import uuid
import logging
from PIL import Image

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

# ─── HD canvas settings ───────────────────────────────────────────────────────
HD_W   = 1920
HD_H   = 1080
PAD    = 0.05          # 5 % padding on each side
QUALITY = 92

# ─── Logo path (relative to this file: ../../static/images/logo.png) ─────────
def _logo_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'static', 'images', 'logo.png')


def get_safe_extension(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    if ext == 'webp':
        return 'jpg'
    if ext == 'png':
        return 'png'
    if ext in ('jpg', 'jpeg'):
        return 'jpg'
    return 'jpg'


def is_allowed_image(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext in ALLOWED_EXTENSIONS


# ─── Background removal ───────────────────────────────────────────────────────

def _remove_background(img: Image.Image) -> Image.Image:
    """Try rembg AI removal. Falls back to returning the RGBA image as-is."""
    try:
        from rembg import remove as rembg_remove
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        result = rembg_remove(buf.getvalue())
        return Image.open(io.BytesIO(result)).convert('RGBA')
    except ImportError:
        logger.info('[image_utils] rembg not installed — skipping BG removal')
    except Exception as e:
        logger.warning(f'[image_utils] rembg failed: {e}')
    return img.convert('RGBA')


# ─── White canvas composer ────────────────────────────────────────────────────

def _place_on_white_hd(fg: Image.Image) -> Image.Image:
    """
    Composite RGBA foreground onto a 1920×1080 white canvas.
    Car is centred with PAD% padding on all sides — nothing ever gets cropped.
    """
    # Crop transparent border
    bbox = fg.getbbox() if fg.mode == 'RGBA' else None
    if bbox:
        fg = fg.crop(bbox)

    fw, fh = fg.size
    avail_w = int(HD_W * (1 - 2 * PAD))
    avail_h = int(HD_H * (1 - 2 * PAD))
    scale   = min(avail_w / fw, avail_h / fh, 1.0)   # never upscale beyond original
    nw, nh  = max(1, int(fw * scale)), max(1, int(fh * scale))
    fg_rs   = fg.resize((nw, nh), Image.LANCZOS)

    canvas  = Image.new('RGBA', (HD_W, HD_H), (255, 255, 255, 255))
    px      = (HD_W - nw) // 2
    py      = (HD_H - nh) // 2
    mask    = fg_rs.split()[3] if fg_rs.mode == 'RGBA' else None
    canvas.paste(fg_rs, (px, py), mask)
    return canvas.convert('RGB')


# ─── Logo stamp ───────────────────────────────────────────────────────────────

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

        # 70 % opacity
        r, g, b, a = logo_rs.split()
        a = a.point(lambda x: int(x * 0.70))
        logo_rs = Image.merge('RGBA', (r, g, b, a))

        margin = int(canvas.width * 0.015)
        px = canvas.width  - logo_rs.width  - margin
        py = canvas.height - logo_rs.height - margin
        base = canvas.convert('RGBA')
        base.paste(logo_rs, (px, py), logo_rs)
        return base.convert('RGB')
    except Exception as e:
        logger.warning(f'[image_utils] logo stamp failed: {e}')
        return canvas


# ─── Full vehicle pipeline (NO background removal — fast save) ───────────────

def _process_vehicle_image(file_obj) -> bytes:
    """
    Fast pipeline: resize to max HD if needed, stamp logo, save as JPEG.
    NO background removal here — that happens only in Mask Editor.
    """
    raw = file_obj.read()
    file_obj.seek(0)

    img = Image.open(io.BytesIO(raw)).convert('RGB')

    # Resize down if larger than HD (never upscale)
    if img.width > HD_W or img.height > HD_H:
        img.thumbnail((HD_W, HD_H), Image.LANCZOS)

    # Stamp logo
    img = _stamp_logo(img)

    out = io.BytesIO()
    img.save(out, 'JPEG', quality=QUALITY, optimize=True)
    return out.getvalue()


# ─── Main public function ─────────────────────────────────────────────────────

def save_uploaded_image(
    file_obj,
    upload_folder: str,
    base_name: str,
    vehicle_mode: bool = True,   # True = HD + white bg + logo pipeline
) -> str:
    """
    Save a werkzeug FileStorage to upload_folder.

    vehicle_mode=True  (default) — full pipeline: BG removal, white HD canvas, logo
    vehicle_mode=False           — plain save (KYC docs, logos, etc.)

    Returns final filename (e.g. 'abc123.jpg').
    """
    os.makedirs(upload_folder, exist_ok=True)
    original_name = file_obj.filename or ''
    orig_ext = os.path.splitext(original_name)[1].lower().lstrip('.')

    if vehicle_mode:
        # Always output as .jpg for vehicle images
        final_filename = f'{base_name}.jpg'
        dest_path = os.path.join(upload_folder, final_filename)
        try:
            processed = _process_vehicle_image(file_obj)
            with open(dest_path, 'wb') as f:
                f.write(processed)
            logger.info(f'[save_uploaded_image] vehicle HD saved: {final_filename}')
            return final_filename
        except Exception as e:
            logger.error(f'[save_uploaded_image] vehicle pipeline failed: {e}', exc_info=True)
            # Fallback: plain save
            file_obj.seek(0)

    # ── Plain save (KYC / logos / fallback) ──────────────────────────────────
    ext = get_safe_extension(original_name)
    final_filename = f'{base_name}.{ext}'
    dest_path = os.path.join(upload_folder, final_filename)

    if orig_ext == 'webp':
        img = Image.open(file_obj)
        if img.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGB', img.size, (255, 255, 255))
            img = img.convert('RGBA')
            bg.paste(img, mask=img.split()[3])
            bg.save(dest_path, 'JPEG', quality=QUALITY)
        else:
            img.convert('RGB').save(dest_path, 'JPEG', quality=QUALITY)
    else:
        file_obj.seek(0)
        file_obj.save(dest_path)

    return final_filename
