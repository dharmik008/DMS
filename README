# Caryanams DMS — Unified Platform
**Dealer Management System** + **Caryanams Studio** (AI Background Removal)

## 🚀 Quick Start

```bash
pip install -r requirements.txt
python app.py
```

Visit: http://localhost:5000

---

## 📁 Project Structure

```
├── app.py                  Main Flask app (factory pattern)
├── requirements.txt        All dependencies
│
├── auth/routes.py          Blueprint: /auth
├── dealer/routes.py        Blueprint: /dealer
├── user/routes.py          Blueprint: /
├── background/             ← NEW: Caryanams Studio
│   ├── __init__.py
│   ├── routes.py           Blueprint: /studio
│   └── utils.py            AI image processing logic
│
├── templates/
│   ├── dealer/
│   │   ├── base.html       Sidebar (Studio link added)
│   │   ├── dashboard.html  Dashboard (Studio CTA added)
│   │   └── vehicle_form.html (Studio button added)
│   └── background/
│       └── remove.html     ← NEW: Studio UI
│
└── static/
    ├── images/uploads/     DMS vehicle images
    ├── processed/          ← NEW: Studio output images
    └── custom_bgs/         ← NEW: ba1_studio.jpg + custom BGs
```

---

## 🎨 Studio Routes

| URL | Description |
|-----|-------------|
| `/studio/` | Studio main page |
| `/studio/api/upload` | Upload car images (POST) |
| `/studio/api/remove-bg/<id>` | Remove background (POST) |
| `/studio/api/remove-bg-batch` | Batch remove (POST) |
| `/studio/api/apply-bg/<id>` | Apply background (POST) |
| `/studio/api/apply-to-all` | Apply BG to all images (POST) |
| `/studio/api/upload-bg-image` | Upload custom BG (POST) |
| `/studio/api/download/<id>` | Download processed image |
| `/studio/api/gallery` | Gallery list (GET) |
| `/studio/api/car-360/<id>` | 360° frame data (GET) |

---

## 🧩 Dependencies

### DMS Core
- Flask, Flask-SQLAlchemy, Flask-Login

### Caryanams Studio
- **rembg** — AI background removal (u2net / isnet models)
- **opencv-python-headless** — GrabCut fallback
- **Pillow** — Image compositing, watermark, shadow
- **numpy** — Pixel-level operations

---

## 📌 Notes

- Both modules share ONE SQLite database (`Caryanams.db`)
- Studio uses separate tables: `studio_image`, `studio_credit_log`
- `UPLOAD_FOLDER` from DMS config is reused for original uploads
- Processed images go to `static/processed/`
- Place `ba1_studio.jpg` in `static/custom_bgs/` for studio background
- First run will download AI models (~170MB for u2net)
