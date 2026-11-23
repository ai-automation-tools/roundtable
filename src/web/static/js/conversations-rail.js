// The /conversations rail: search, filter chips, agent filter, sort, collapse,
// resize, delete. Loaded on the index, a transcript and the not-found page.
(function() {
  const root = document.querySelector('.cv2');
  if (!root) return;
  const LSORT = 'agentchat.cv.sort', LRAIL = 'agentchat.cv.rail';
  const list = root.querySelector('.cv-list');
  const search = document.getElementById('cv-search');
  const noMatch = document.getElementById('cv-nomatch');
  const sortSel = document.getElementById('cv-sort');
  const agentSel = document.getElementById('cv-agent');
  const items = () => [...root.querySelectorAll('.cv-item')];
  let activeFilter = 'all';

  function applyFilters() {
    const q = (search && search.value.trim().toLowerCase()) || '';
    const ag = (agentSel && agentSel.value) || '';
    let shown = 0;
    items().forEach(it => {
      const qHit = !q || (it.dataset.search || '').includes(q);
      const fHit =
        activeFilter === 'all' ||
        (activeFilter === 'active' && it.dataset.status === 'active') ||
        (activeFilter === 'complete' && it.dataset.status !== 'active') ||
        (activeFilter.startsWith('type:') &&
          (it.dataset.convType || 'debate') === activeFilter.slice(5)) ||
        (activeFilter === 'multi' && Number(it.dataset.participantCount || '0') >= 3);
      const aHit = !ag || (it.dataset.participants || '').split('|').includes(ag);
      const vis = qHit && fHit && aHit;
      it.style.display = vis ? '' : 'none';
      if (vis) shown++;
    });
    if (noMatch) noMatch.style.display = shown === 0 ? 'block' : 'none';
  }

  function applySort() {
    if (!list || !sortSel) return;
    const mode = sortSel.value;
    const arr = items();
    const num = (it, k) => Number(it.dataset[k] || 0);
    arr.sort((a, b) => {
      if (mode === 'oldest') return num(a, 'id') - num(b, 'id');
      if (mode === 'msgs') return num(b, 'msgs') - num(a, 'msgs');
      if (mode === 'updated') {
        const ua = a.dataset.updated || '', ub = b.dataset.updated || '';
        return ua < ub ? 1 : ua > ub ? -1 : 0;
      }
      return num(b, 'id') - num(a, 'id');   /* newest (default) */
    });
    arr.forEach(it => list.insertBefore(it, noMatch));
    try { localStorage.setItem(LSORT, mode); } catch (e) {}
  }

  if (search) search.addEventListener('input', applyFilters);
  if (agentSel) agentSel.addEventListener('change', applyFilters);
  if (sortSel) sortSel.addEventListener('change', applySort);
  root.querySelectorAll('.cv-fchip[data-filter]').forEach(btn => {
    btn.addEventListener('click', () => {
      root.querySelectorAll('.cv-fchip[data-filter]').forEach(b => b.classList.toggle('active', b === btn));
      activeFilter = btn.dataset.filter || 'all';
      applyFilters();
    });
  });

  // Collapse / expand the rail; persisted per-browser.
  const railBtn = document.getElementById('cv-rail-toggle');
  const openBtn = document.getElementById('cv-rail-open');
  function setRail(hidden) {
    root.classList.toggle('rail-hidden', hidden);
    try { localStorage.setItem(LRAIL, hidden ? '1' : '0'); } catch (e) {}
  }
  if (railBtn) railBtn.addEventListener('click', () => setRail(true));
  if (openBtn) openBtn.addEventListener('click', () => setRail(false));
  try { if (localStorage.getItem(LRAIL) === '1') setRail(true); } catch (e) {}

  // Drag the rail's right edge to resize; width persisted per-browser.
  const LWID = 'agentchat.cv.railw', RAIL_MIN = 236, RAIL_MAX = 560, RAIL_DEF = 320;
  const resizer = document.getElementById('cv-resizer');
  const setRailW = (w) => root.style.setProperty('--cv-rail-w', Math.round(w) + 'px');
  try { const w = parseInt(localStorage.getItem(LWID) || '', 10); if (w) setRailW(w); } catch (e) {}
  if (resizer) {
    let dragging = false;
    const onMove = (e) => {
      if (!dragging) return;
      const left = root.getBoundingClientRect().left;
      setRailW(Math.max(RAIL_MIN, Math.min(RAIL_MAX, e.clientX - left)));
    };
    const onUp = () => {
      if (!dragging) return;
      dragging = false;
      root.classList.remove('cv-resizing');
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      const cur = parseInt(root.style.getPropertyValue('--cv-rail-w'), 10);
      try { if (cur) localStorage.setItem(LWID, String(cur)); } catch (e) {}
    };
    resizer.addEventListener('mousedown', (e) => {
      e.preventDefault();
      dragging = true;
      root.classList.add('cv-resizing');
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
    resizer.addEventListener('dblclick', () => {
      setRailW(RAIL_DEF);
      try { localStorage.setItem(LWID, String(RAIL_DEF)); } catch (e) {}
    });
  }

  // Hover-(i) details popover — a single fixed element, positioned by JS so
  // the list's overflow can't clip it. Reads the item's data-* attributes.
  const tip = document.getElementById('cv-tip');
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
  ));
  function showTip(btn) {
    const it = btn.closest('.cv-item');
    if (!it || !tip) return;
    const status = it.dataset.status || '';
    const parts = (it.dataset.participants || '').split('|').filter(Boolean);
    const cast = it.dataset.cast || parts.join(', ') || '—';
    const row = (k, v) => '<div class="cv-tip-row"><span class="cv-tip-k">' + k +
      '</span><span class="cv-tip-v">' + esc(v) + '</span></div>';
    tip.innerHTML =
      '<div class="cv-tip-h">#' + esc(it.dataset.id) +
      ' <span class="cv-tip-st ' + esc(status) + '">' + esc(status || 'unknown') + '</span></div>' +
      row('Messages', it.dataset.msgs || '0') +
      row('Cast', cast) +
      row('Agents', parts.length || '—') +
      (it.dataset.date ? row('Updated', it.dataset.date) : '');
    tip.classList.add('show');
    const r = btn.getBoundingClientRect();
    const tw = tip.offsetWidth, th = tip.offsetHeight, gap = 8;
    let x = r.right + gap;
    if (x + tw > window.innerWidth - 8) x = r.left - tw - gap;
    let y = r.top + r.height / 2 - th / 2;
    y = Math.max(8, Math.min(y, window.innerHeight - th - 8));
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  }
  const hideTip = () => { if (tip) tip.classList.remove('show'); };
  root.querySelectorAll('.cv-info').forEach(btn => {
    btn.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); });
    btn.addEventListener('mouseenter', () => showTip(btn));
    btn.addEventListener('mouseleave', hideTip);
  });
  if (list) list.addEventListener('scroll', hideTip, { passive: true });

  root.querySelectorAll('.cv-del').forEach(btn => {
    btn.addEventListener('click', async (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      const cid = btn.dataset.cid;
      const topic = btn.dataset.topic || '(untitled)';
      const msgs = btn.dataset.msgCount || '0';
      if (!confirm('Permanently delete conversation #' + cid + '?\n\nTopic: ' + topic +
                   '\nMessages: ' + msgs + '\n\nThis deletes the row and all its messages. ' +
                   'The local sidecar applies the deletion within ~5s. This cannot be undone.')) return;
      btn.disabled = true;
      try {
        const res = await fetch('/api/conversations/' + cid + '/delete', { method: 'POST' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const item = btn.closest('.cv-item');
        if (item && item.classList.contains('active')) { location.href = '/conversations'; return; }
        if (item) item.remove();
      } catch (err) { alert('Delete failed: ' + err.message); btn.disabled = false; }
    });
  });

  try {
    const s = localStorage.getItem(LSORT);
    if (s && sortSel) sortSel.value = s;
  } catch (e) {}
  applySort();
  applyFilters();
})();
