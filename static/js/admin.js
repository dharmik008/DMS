// ── Theme ────────────────────────────────────────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem('autodms_theme') || 'dark';
  applyTheme(saved, false);
}

function applyTheme(mode, notify) {
  if (mode === 'light') {
    document.body.classList.add('light-mode');
  } else {
    document.body.classList.remove('light-mode');
  }
  localStorage.setItem('autodms_theme', mode);
  const btn = document.getElementById('themeToggle');
  if (btn) btn.textContent = mode === 'light' ? '🌙' : '☀️';
  if (notify) showToast(mode === 'light' ? '☀️ Light mode enabled' : '🌙 Dark mode enabled', 'info');
}

function toggleTheme() {
  const current = localStorage.getItem('autodms_theme') || 'dark';
  applyTheme(current === 'dark' ? 'light' : 'dark', true);
}

// ── Sidebar Toggle ───────────────────────────────────────────────────────────
function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.body.classList.toggle('sidebar-open');
}

// ── Tabs ─────────────────────────────────────────────────────────────────────
function initTabs(containerSelector) {
  const containers = document.querySelectorAll(containerSelector || '.tabs-container');
  containers.forEach(container => {
    const buttons = container.querySelectorAll('.tab-btn');
    const panes   = container.querySelectorAll('.tab-pane');
    buttons.forEach((btn, i) => {
      btn.addEventListener('click', () => {
        buttons.forEach(b => b.classList.remove('active'));
        panes.forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        panes[i].classList.add('active');
      });
    });
    if (buttons.length) buttons[0].classList.add('active');
    if (panes.length)   panes[0].classList.add('active');
  });
}

// ── Settings Nav ─────────────────────────────────────────────────────────────
function initSettingsNav() {
  const items    = document.querySelectorAll('.settings-nav-item');
  const sections = document.querySelectorAll('.settings-section');
  items.forEach((item, i) => {
    item.addEventListener('click', () => {
      items.forEach(it => it.classList.remove('active'));
      sections.forEach(s  => s.classList.remove('active'));
      item.classList.add('active');
      sections[i] && sections[i].classList.add('active');
    });
  });
  if (items.length)    items[0].classList.add('active');
  if (sections.length) sections[0].classList.add('active');
}

// ── Table Search ──────────────────────────────────────────────────────────────
function initTableSearch(inputId, tableId) {
  const input = document.getElementById(inputId);
  const table = document.getElementById(tableId);
  if (!input || !table) return;
  input.addEventListener('input', () => {
    const q = input.value.toLowerCase();
    Array.from(table.querySelectorAll('tbody tr')).forEach(row => {
      row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  });
}

// ── Number Format ─────────────────────────────────────────────────────────────
function formatINR(n) {
  return '₹' + n.toLocaleString('en-IN');
}

// ── Toast Notifications ───────────────────────────────────────────────────────
let toastContainer = null;
function getToastContainer() {
  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.className = 'toast-container';
    document.body.appendChild(toastContainer);
  }
  return toastContainer;
}

function showToast(message, type = 'info', duration = 3500) {
  const icons = { success: '✅', error: '❌', info: 'ℹ️', warn: '⚠️' };
  const container = getToastContainer();
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${icons[type] || 'ℹ️'}</span>
    <span class="toast-msg">${message}</span>
    <button class="toast-close" onclick="dismissToast(this.parentElement)">×</button>
  `;
  container.appendChild(toast);
  setTimeout(() => dismissToast(toast), duration);
  return toast;
}

function dismissToast(toast) {
  if (!toast || toast.classList.contains('hiding')) return;
  toast.classList.add('hiding');
  setTimeout(() => toast.remove(), 300);
}

// ── Modal Helpers ─────────────────────────────────────────────────────────────
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('open');
}
function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('open');
}
// Close modal on overlay click
document.addEventListener('click', (e) => {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.classList.remove('open');
  }
});

// ── KYC Document Preview ──────────────────────────────────────────────────────
function openDocPreview(url, label) {
  const modal   = document.getElementById('docPreviewModal');
  const content = document.getElementById('docPreviewContent');
  const title   = document.getElementById('docPreviewTitle');
  const dlBtn   = document.getElementById('docPreviewDownload');
  if (!modal || !content) return;

  title.textContent = label || 'Document Preview';
  dlBtn.href = url;
  dlBtn.download = label || 'document';

  const isPdf = url && url.toLowerCase().endsWith('.pdf');
  if (isPdf) {
    content.innerHTML = `<iframe class="doc-preview-pdf" src="${url}"></iframe>`;
  } else if (url) {
    content.innerHTML = `<img class="doc-preview-img" src="${url}" alt="${label}" id="previewImg">`;
  } else {
    content.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text-3);">No document uploaded yet.</div>`;
    dlBtn.style.display = 'none';
  }
  modal.classList.add('open');
}

// ── KYC Approve / Reject Actions ──────────────────────────────────────────────
function approveKyc(dealerId) {
  if (!confirm('Approve KYC for this dealer? This will activate the dealer account.')) return;
  fetch(`/admin/dealer/approve-kyc/${dealerId}`, { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        showToast('KYC approved! Dealer is now active.', 'success');
        setTimeout(() => location.reload(), 1200);
      } else {
        showToast(data.message || 'Error approving KYC', 'error');
      }
    })
    .catch(() => showToast('Network error. Please try again.', 'error'));
}

function openRejectModal(dealerId) {
  document.getElementById('rejectDealerId').value = dealerId;
  document.getElementById('rejectReason').value = '';
  openModal('rejectKycModal');
}

function submitRejectKyc() {
  const dealerId = document.getElementById('rejectDealerId').value;
  const reason   = document.getElementById('rejectReason').value.trim();
  if (!reason) { showToast('Please enter a rejection reason.', 'warn'); return; }
  fetch(`/admin/dealer/reject-kyc/${dealerId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
    .then(r => r.json())
    .then(data => {
      closeModal('rejectKycModal');
      if (data.success) {
        showToast('KYC rejected and dealer notified.', 'error');
        setTimeout(() => location.reload(), 1200);
      } else {
        showToast(data.message || 'Error rejecting KYC', 'error');
      }
    })
    .catch(() => showToast('Network error. Please try again.', 'error'));
}

// ── KYC Upload (Dealer side) ──────────────────────────────────────────────────
function initKycUploadZones() {
  document.querySelectorAll('.upload-zone').forEach(zone => {
    const input = zone.querySelector('input[type=file]');
    if (!input) return;
    input.addEventListener('change', () => {
      const file = input.files[0];
      if (file) {
        zone.classList.add('has-file');
        let nameEl = zone.querySelector('.file-preview-name');
        if (!nameEl) {
          nameEl = document.createElement('div');
          nameEl.className = 'file-preview-name';
          zone.appendChild(nameEl);
        }
        nameEl.textContent = '✓ ' + file.name;
      }
    });
    ['dragover','dragleave','drop'].forEach(evt => {
      zone.addEventListener(evt, e => {
        e.preventDefault();
        if (evt === 'dragover') zone.classList.add('dragover');
        else zone.classList.remove('dragover');
        if (evt === 'drop' && e.dataTransfer.files.length) {
          input.files = e.dataTransfer.files;
          input.dispatchEvent(new Event('change'));
        }
      });
    });
  });
}

function submitKycUpload(dealerId) {
  const form = document.getElementById('kycUploadForm');
  if (!form) return;

  const required = ['aadhaarFront', 'aadhaarBack', 'panCard'];
  let errors = [];
  required.forEach(field => {
    const input = form.querySelector(`[name="${field}"]`);
    if (!input || !input.files || !input.files.length) {
      errors.push(`${field.replace(/([A-Z])/g, ' $1').trim()} is required.`);
    }
  });
  // Validate file types and sizes
  form.querySelectorAll('input[type=file]').forEach(input => {
    if (!input.files || !input.files.length) return;
    const file = input.files[0];
    const allowed = ['jpg','jpeg','png','pdf'];
    const ext = file.name.split('.').pop().toLowerCase();
    if (!allowed.includes(ext)) errors.push(`${input.name}: Only JPG, PNG, PDF allowed.`);
    if (file.size > 5 * 1024 * 1024) errors.push(`${input.name}: File must be under 5MB.`);
  });

  if (errors.length) {
    errors.forEach(e => showToast(e, 'error'));
    return;
  }

  const fd = new FormData(form);
  fetch(`/dealer/kyc/upload/${dealerId}`, { method: 'POST', body: fd })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        showToast('KYC documents uploaded successfully!', 'success');
        setTimeout(() => location.reload(), 1500);
      } else {
        const msgs = data.errors || [data.message || 'Upload failed'];
        msgs.forEach(e => showToast(e, 'error'));
      }
    })
    .catch(() => showToast('Upload failed. Please try again.', 'error'));
}


// ── Draggable Horizontal Scroll Bar ──────────────────────────────────────────
// Scrolls the HTML element (the true page scroll root).
// Appears only when body.min-width (900 px) > window.innerWidth.
(function () {
  'use strict';

  var bar, track, thumb;
  var isDragging = false;
  var dragStartX  = 0;
  var dragStartSL = 0;
  var arrowTimer  = null;

  // The element we actually scroll is <html>
  function root() { return document.documentElement; }
  function maxSL() { return root().scrollWidth - root().clientWidth; }
  function ratio() { return root().clientWidth / root().scrollWidth; }

  // ── Build DOM ──────────────────────────────────────────────────────────────
  function buildBar() {
    bar = document.createElement('div');
    bar.id = 'hscroll-bar';

    var btnL = document.createElement('div');
    btnL.className = 'hs-arrow';
    btnL.innerHTML = '&#9664;';
    btnL.title = 'Scroll left';

    track = document.createElement('div');
    track.id = 'hscroll-track';

    thumb = document.createElement('div');
    thumb.id = 'hscroll-thumb';
    track.appendChild(thumb);

    var btnR = document.createElement('div');
    btnR.className = 'hs-arrow';
    btnR.innerHTML = '&#9654;';
    btnR.title = 'Scroll right';

    bar.appendChild(btnL);
    bar.appendChild(track);
    bar.appendChild(btnR);
    document.body.appendChild(bar);

    // Arrow hold-to-scroll
    btnL.addEventListener('mousedown',  function () { startArrow(-1); });
    btnR.addEventListener('mousedown',  function () { startArrow( 1); });
    btnL.addEventListener('touchstart', function (e){ e.preventDefault(); startArrow(-1); }, { passive:false });
    btnR.addEventListener('touchstart', function (e){ e.preventDefault(); startArrow( 1); }, { passive:false });
    document.addEventListener('mouseup',   stopArrow);
    document.addEventListener('touchend',  stopArrow);

    // Track click-to-jump
    track.addEventListener('mousedown', onTrackDown);
    track.addEventListener('touchstart', onTrackTouch, { passive:false });

    // Thumb drag
    thumb.addEventListener('mousedown', onThumbDown);
    thumb.addEventListener('touchstart', onThumbTouch, { passive:false });
  }

  // ── Arrow scroll ───────────────────────────────────────────────────────────
  function startArrow(dir) {
    nudge(dir * 120);
    arrowTimer = setInterval(function () { nudge(dir * 120); }, 100);
  }
  function stopArrow() {
    if (arrowTimer) { clearInterval(arrowTimer); arrowTimer = null; }
  }
  function nudge(px) {
    root().scrollLeft = Math.max(0, Math.min(root().scrollLeft + px, maxSL()));
    sync();
  }

  // ── Track click ────────────────────────────────────────────────────────────
  function onTrackDown(e) {
    if (e.target === thumb) return;
    var r = track.getBoundingClientRect();
    var pct = (e.clientX - r.left) / r.width;
    root().scrollLeft = pct * maxSL();
    sync();
  }
  function onTrackTouch(e) {
    if (e.target === thumb) return;
    e.preventDefault();
    var r = track.getBoundingClientRect();
    var pct = (e.touches[0].clientX - r.left) / r.width;
    root().scrollLeft = pct * maxSL();
    sync();
  }

  // ── Thumb drag (mouse) ─────────────────────────────────────────────────────
  function onThumbDown(e) {
    e.preventDefault(); e.stopPropagation();
    isDragging  = true;
    dragStartX  = e.clientX;
    dragStartSL = root().scrollLeft;
    thumb.classList.add('dragging');
    document.addEventListener('mousemove', onDragMove);
    document.addEventListener('mouseup',   onDragUp);
  }
  function onDragMove(e) {
    if (!isDragging) return;
    var tw = track.getBoundingClientRect().width;
    var thW = thumb.offsetWidth;
    var delta = (e.clientX - dragStartX) / (tw - thW);
    root().scrollLeft = dragStartSL + delta * maxSL();
    sync();
  }
  function onDragUp() {
    isDragging = false;
    thumb.classList.remove('dragging');
    document.removeEventListener('mousemove', onDragMove);
    document.removeEventListener('mouseup',   onDragUp);
  }

  // ── Thumb drag (touch) ─────────────────────────────────────────────────────
  function onThumbTouch(e) {
    e.preventDefault(); e.stopPropagation();
    isDragging  = true;
    dragStartX  = e.touches[0].clientX;
    dragStartSL = root().scrollLeft;
    thumb.classList.add('dragging');
    document.addEventListener('touchmove', onTouchMove, { passive:false });
    document.addEventListener('touchend',  onTouchUp);
  }
  function onTouchMove(e) {
    if (!isDragging) return;
    e.preventDefault();
    var tw = track.getBoundingClientRect().width;
    var thW = thumb.offsetWidth;
    var delta = (e.touches[0].clientX - dragStartX) / (tw - thW);
    root().scrollLeft = dragStartSL + delta * maxSL();
    sync();
  }
  function onTouchUp() {
    isDragging = false;
    thumb.classList.remove('dragging');
    document.removeEventListener('touchmove', onTouchMove);
    document.removeEventListener('touchend',  onTouchUp);
  }

  // ── Sync thumb position with scroll ───────────────────────────────────────
  function sync() {
    var max = maxSL();

    if (max <= 2) {          // page fits — hide bar
      bar.classList.remove('visible');
      document.body.classList.remove('hscroll-active');
      return;
    }

    bar.classList.add('visible');
    document.body.classList.add('hscroll-active');

    var thumbPct = ratio() * 100;
    thumb.style.width = Math.max(thumbPct, 5) + '%';   // never narrower than 5%

    var scrolled = root().scrollLeft / max;
    var trackW   = track.offsetWidth;
    var thumbW   = thumb.offsetWidth;
    thumb.style.left = (scrolled * (trackW - thumbW)) + 'px';
  }

  // ── Init ───────────────────────────────────────────────────────────────────
  function init() {
    buildBar();
    // Listen to scroll on BOTH window and html — browsers vary
    window.addEventListener('scroll', sync, { passive:true });
    document.addEventListener('scroll', sync, { passive:true });
    window.addEventListener('resize',  sync);
    // Run once immediately + after a short delay (fonts/images may shift layout)
    sync();
    setTimeout(sync, 300);
    setTimeout(sync, 800);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

// ── On Ready ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initTabs();
  initSettingsNav();
  initKycUploadZones();

  // Auto-dismiss flash messages
  document.querySelectorAll('.flash').forEach(f => {
    setTimeout(() => f.style.opacity = '0', 4000);
    setTimeout(() => f.remove(), 4500);
  });
});
