(function () {
  'use strict';
  var d = document;
  // The repo URL rides on this script's own tag (data-github) rather than an
  // inline window.__AB_LINKS assignment, which a nonce CSP would need to cover.
  var me = d.currentScript;
  var LINKS = me && me.dataset.github ? { github: me.dataset.github } : {};

  // Everything below queries the whole document, but this script is emitted
  // with the topbar — i.e. BEFORE <main> is parsed. Running inline meant
  // querySelectorAll('.reveal') matched nothing and the observer watched
  // nothing, leaving six homepage sections invisible. Wait for the DOM.
  function ready(fn) {
    if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', fn);
    else fn();
  }
  // Each feature is wired independently: one missing element (or one throw)
  // must not take the rest of the chrome down with it. The palette used to
  // `return` early on no #cmdk, which would now also skip the reveals and the
  // sidebar toggle below it.
  ready(function () {
    [initTheme, initPill, initPalette, initReveals, initRail, initSpot, initFocus].forEach(function (fn) {
      try { fn(); } catch (e) { if (window.console) console.error('[agent-chat] ' + fn.name, e); }
    });
  });

  // [data-focus-on-load] takes focus once the page is parsed — the explorer's
  // result count after a search, so a screen reader announces it (audit RT-42).
  function initFocus() {
    var el = d.querySelector('[data-focus-on-load]');
    if (el) el.focus({ preventScroll: true });
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* ================= shared data cache =================
     One /api/conversations response feeds BOTH the topbar live count and the
     palette's conversation index — fetching it twice on the same page would
     be pure waste. */
  var cache = { convs: null, personas: null };

  function fetchConvs(force) {
    if (!force && cache.convs) return Promise.resolve(cache.convs);
    // Just the four fields used here; the full rows are ~13 KB each (RT-41).
    return fetch('/api/conversations?fields=id,topic,status,participants',
                 { headers: { accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (j) { cache.convs = Array.isArray(j) ? j : []; return cache.convs; })
      .catch(function () { return cache.convs || []; });
  }
  function fetchPersonas() {
    if (cache.personas) return Promise.resolve(cache.personas);
    return fetch('/api/personas', { headers: { accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (j) { cache.personas = Array.isArray(j) ? j : []; return cache.personas; })
      .catch(function () { return []; });
  }

  /* ================= live pill =================
     The homepage used to render an `active` count server-side that went stale
     the moment a debate ended. Now every page carries the pill and polls, so
     it stays true without a refresh. Paused while the tab is hidden. */
  var pill = null;
  function paintPill(convs) {
    if (!pill) return;
    var n = 0;
    for (var i = 0; i < convs.length; i++) if (convs[i].status === 'active') n++;
    var txt = pill.querySelector('.live-txt');
    pill.className = 'live-pill' + (n ? '' : ' idle');
    if (txt) txt.textContent = n ? n + (n === 1 ? ' debate live' : ' debates live') : 'system online';
    pill.title = n ? n + ' active conversation' + (n === 1 ? '' : 's') + ' — open the inbox' : 'No debates running right now';
  }
  function initPill() {
    pill = d.getElementById('ab-live');
    if (!pill) return;
    fetchConvs(true).then(paintPill);
    setInterval(function () { if (!d.hidden) fetchConvs(true).then(paintPill); }, 30000);
  }

  /* ================= command palette ================= */
  var root = null, input = null, list = null, count = null;
  var items = [], sel = 0, built = false, lastFocus = null;

  var ICO = {
    home: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    orch: '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
    pers: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>',
    extn: '<path d="M10 3.5a2 2 0 1 1 4 0V5h3a1 1 0 0 1 1 1v3h1.5a2 2 0 1 1 0 4H18v3a1 1 0 0 1-1 1h-3v1.5a2 2 0 1 1-4 0V17H7a1 1 0 0 1-1-1v-3H4.5a2 2 0 1 1 0-4H6V6a1 1 0 0 1 1-1h3z"/>',
    arena: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.4"/><line x1="12" y1="1.5" x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="22.5"/><line x1="1.5" y1="12" x2="5" y2="12"/><line x1="19" y1="12" x2="22.5" y2="12"/>',
    setup: '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
    reg: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    gh: '<path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/>'
  };

  function svg(name) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICO[name] || ICO.chat) + '</svg>';
  }

  var PAGES = [
    { kind: 'Pages', title: 'Home', sub: 'Landing page, live counters, featured debates', url: '/', ico: 'home' },
    { kind: 'Pages', title: 'Conversations', sub: 'Browse every debate transcript', url: '/conversations', ico: 'chat' },
    { kind: 'Pages', title: 'Orchestrate', sub: 'Seed and launch a new debate', url: '/orchestrate', ico: 'orch' },
    { kind: 'Pages', title: 'Personas', sub: 'Browse the cast, read and download cards', url: '/personas', ico: 'pers' },
    { kind: 'Pages', title: 'Manage personas', sub: 'Create, edit, import debater cards', url: '/personas/manage', ico: 'pers' },
    { kind: 'Pages', title: 'Browser extension', sub: 'What AgentBattleground is and how to install it', url: '/extension', ico: 'extn' },
    { kind: 'Pages', title: 'Battleground', sub: 'Captured arenas, drafts, and verdicts', url: '/battleground', ico: 'arena' },
    { kind: 'Pages', title: 'CLI setup', sub: 'Which CLI tools this machine has', url: '/setup', ico: 'setup' },
    { kind: 'Pages', title: 'GitHub repository', sub: 'ai-automation-tools/roundtable', url: LINKS.github, ico: 'gh', ext: true }
  ];

  function initials(name) {
    var parts = String(name || '').split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  function pad(n) { return ('000' + n).slice(-3); }

  function build() {
    if (built) return Promise.resolve(items);
    built = true;
    return Promise.all([fetchConvs(false), fetchPersonas()]).then(function (res) {
      var convs = res[0] || [], personas = res[1] || [];
      items = PAGES.filter(function (p) { return !!p.url; });
      convs.forEach(function (c) {
        var who = Array.isArray(c.participants) ? c.participants.join(' · ') : '';
        items.push({
          kind: 'Conversations',
          title: c.topic || '(untitled)',
          sub: '#' + pad(c.id) + '  ' + (c.status || '') + (who ? '  ' + who : ''),
          url: '/conversations/' + c.id,
          badge: '#' + c.id,
          live: c.status === 'active'
        });
      });
      personas.forEach(function (p) {
        items.push({
          kind: 'Personas',
          title: p.name || p.slug,
          sub: p.group || '',
          url: '/personas/' + encodeURIComponent(p.slug) + '?group=' + encodeURIComponent(p.group || ''),
          badge: initials(p.name || p.slug)
        });
      });
      return items;
    });
  }

  /* Subsequence fuzzy match. Scores contiguous runs and word-start hits so
     "gord" puts "Gordon Ramsay" above "Good Gardening", and shorter titles win
     ties. Returns null when q isn't a subsequence of text at all.

     A bare subsequence test is far too generous on prose: "ramsay" happily
     matched "B-r-ain Computer Interf-a-ces ... neur-a-l ... technolog-y" by
     picking letters out of a whole sentence. So a match must ALSO be dense —
     the letters have to sit close together — unless every hit lands on a word
     start, which is what makes real acronym queries ("bci") still work. */
  var WORD_START = /[\s\-_\/·#:]/;
  function fuzzy(q, text) {
    if (!q) return { score: 0, hits: [] };
    var t = String(text).toLowerCase(), ql = q.toLowerCase();
    var ti = 0, score = 0, run = 0, hits = [], starts = 0;
    for (var i = 0; i < ql.length; i++) {
      var found = -1;
      for (var j = ti; j < t.length; j++) { if (t[j] === ql[i]) { found = j; break; } }
      if (found < 0) return null;
      hits.push(found);
      if (found === ti && i > 0) { run++; score += 6 + run * 3; } else { run = 0; score += 1; }
      if (found === 0 || WORD_START.test(t[found - 1] || '')) { score += 8; starts++; }
      ti = found + 1;
    }
    var spread = hits[hits.length - 1] - hits[0] + 1;
    if (ql.length / spread < 0.3 && starts < ql.length) return null;
    return { score: score - Math.min(t.length * 0.05, 8), hits: hits };
  }

  function hl(text, hits) {
    var set = {}, out = '', i;
    for (i = 0; i < (hits || []).length; i++) set[hits[i]] = 1;
    for (i = 0; i < text.length; i++) out += set[i] ? '<mark>' + esc(text[i]) + '</mark>' : esc(text[i]);
    return out;
  }

  function score(q) {
    var out = [];
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      var m = fuzzy(q, it.title);
      var via = 'title';
      if (!m) { m = fuzzy(q, it.sub || ''); via = 'sub'; }
      if (!m) continue;
      out.push({ it: it, s: m.score + (via === 'title' ? 12 : 0), hits: via === 'title' ? m.hits : [] });
    }
    out.sort(function (a, b) { return b.s - a.s; });
    return out.slice(0, 40);
  }

  var rows = [];
  function render() {
    var q = (input.value || '').trim();
    var hits = score(q);
    rows = [];
    if (!hits.length) {
      list.innerHTML = '<li class="cmdk-empty">Nothing matches &ldquo;' + esc(q) + '&rdquo;</li>';
      count.textContent = '';
      return;
    }
    var html = '', group = null, n = 0;
    hits.forEach(function (h) {
      if (h.it.kind !== group) { group = h.it.kind; html += '<li class="cmdk-group">' + esc(group) + '</li>'; }
      var ico = h.it.ico ? svg(h.it.ico) : esc(h.it.badge || '');
      html += '<li class="cmdk-item" role="option" data-i="' + n + '" aria-selected="false">' +
        '<span class="cmdk-ico">' + ico + '</span>' +
        '<span class="cmdk-body"><span class="cmdk-title">' + hl(String(h.it.title), h.hits) +
        (h.it.live ? ' <span class="live-pill" style="margin-left:4px"><span class="dot"></span></span>' : '') +
        '</span>' + (h.it.sub ? '<span class="cmdk-sub">' + esc(h.it.sub) + '</span>' : '') + '</span>' +
        '<span class="cmdk-go">' + (h.it.ext ? '&#8599;' : '&#8629;') + '</span></li>';
      rows.push(h.it);
      n++;
    });
    list.innerHTML = html;
    count.textContent = rows.length + (rows.length === 1 ? ' result' : ' results');
    sel = 0;
    paintSel();
  }

  function paintSel() {
    var els = list.querySelectorAll('.cmdk-item');
    for (var i = 0; i < els.length; i++) {
      var on = i === sel;
      els[i].setAttribute('aria-selected', on ? 'true' : 'false');
      if (on) {
        els[i].scrollIntoView({ block: 'nearest' });
        input.setAttribute('aria-activedescendant', 'cmdk-opt-' + i);
      }
    }
  }

  function go(i) {
    var it = rows[i];
    if (!it) return;
    close();
    if (it.ext) window.open(it.url, '_blank', 'noopener');
    else window.location.href = it.url;
  }

  function open() {
    if (!root.hidden) return;
    lastFocus = d.activeElement;
    root.hidden = false;
    input.value = '';
    list.innerHTML = '<li class="cmdk-empty">Loading&hellip;</li>';
    d.documentElement.style.overflow = 'hidden';
    input.focus();
    build().then(render);
  }
  function close() {
    if (root.hidden) return;
    root.hidden = true;
    d.documentElement.style.overflow = '';
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  function initPalette() {
    root = d.getElementById('cmdk');
    if (!root) return;
    input = d.getElementById('cmdk-input');
    list = d.getElementById('cmdk-list');
    count = d.getElementById('cmdk-count');
    if (!input || !list || !count) return;

    // The shortcut is Cmd+K on a Mac and Ctrl+K everywhere else (the handler
    // below accepts either). Render whichever one the reader actually has.
    if (/Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent || '')) {
      Array.prototype.forEach.call(d.querySelectorAll('.cmdk-trigger kbd'), function (k) {
        k.textContent = '⌘ K';
      });
      Array.prototype.forEach.call(d.querySelectorAll('[data-cmdk-open]'), function (b) {
        b.setAttribute('aria-label', 'Search (Command K)');
      });
    }

    d.addEventListener('keydown', onKey);
    input.addEventListener('input', render);
    list.addEventListener('click', function (e) {
      var li = e.target.closest && e.target.closest('.cmdk-item');
      if (li) go(parseInt(li.dataset.i, 10));
    });
    list.addEventListener('mousemove', function (e) {
      var li = e.target.closest && e.target.closest('.cmdk-item');
      if (li) { var i = parseInt(li.dataset.i, 10); if (i !== sel) { sel = i; paintSel(); } }
    });
    Array.prototype.forEach.call(d.querySelectorAll('[data-cmdk-open]'), function (b) {
      b.addEventListener('click', open);
    });
    Array.prototype.forEach.call(d.querySelectorAll('[data-cmdk-close]'), function (b) {
      b.addEventListener('click', close);
    });
  }

  function onKey(e) {
    var mod = e.metaKey || e.ctrlKey;
    if (mod && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); root.hidden ? open() : close(); return; }
    if (root.hidden) {
      // Bare "/" opens search too — but not while the operator is typing in
      // the persona search box, the rail filter, or any other field.
      var t = e.target, tag = t && t.tagName;
      if (e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey &&
          tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT' && !(t && t.isContentEditable)) {
        e.preventDefault(); open();
      }
      return;
    }
    if (e.key === 'Escape') { e.preventDefault(); close(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); if (rows.length) { sel = (sel + 1) % rows.length; paintSel(); } }
    else if (e.key === 'ArrowUp') { e.preventDefault(); if (rows.length) { sel = (sel - 1 + rows.length) % rows.length; paintSel(); } }
    else if (e.key === 'Enter') { e.preventDefault(); go(sel); }
    else if (e.key === 'Tab') { e.preventDefault(); input.focus(); }  // keep focus trapped
  }

  /* ================= scroll reveals ================= */
  function initReveals() {
    var reveals = d.querySelectorAll('.reveal');
    if (!reveals.length) return;
    if (!('IntersectionObserver' in window)) {
      Array.prototype.forEach.call(reveals, function (el) { el.classList.add('seen'); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('seen'); io.unobserve(en.target); }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.04 });
    Array.prototype.forEach.call(reveals, function (el) { io.observe(el); });
  }

  /* ================= spotlight =================
     Cards marked .spot draw a ring where the pointer is (css/topbar.css). One
     delegated listener for the whole document: two custom properties on the
     card, no per-card handlers, nothing to re-bind when SSE appends a row. */
  function initSpot() {
    if (window.matchMedia && window.matchMedia('(hover: none)').matches) return;
    d.addEventListener('pointermove', function (e) {
      var el = e.target && e.target.closest ? e.target.closest('.spot') : null;
      if (!el) return;
      var r = el.getBoundingClientRect();
      el.style.setProperty('--mx', (e.clientX - r.left) + 'px');
      el.style.setProperty('--my', (e.clientY - r.top) + 'px');
    }, { passive: true });
  }

  /* ================= sidebar collapse =================
     The state itself is applied by js/boot.js before first paint (so the rail
     can't flash open and snap shut); this only wires the toggle. */
  function initRail() {
    var railToggle = d.getElementById('rail-toggle');
    if (!railToggle) return;
    var html = d.documentElement;
    function syncRail() {
      var collapsed = html.classList.contains('rail-collapsed');
      railToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      var name = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
      railToggle.setAttribute('aria-label', name);
      railToggle.setAttribute('title', name);
    }
    railToggle.addEventListener('click', function () {
      var collapsed = html.classList.toggle('rail-collapsed');
      try { localStorage.setItem('ab-rail', collapsed ? '0' : '1'); } catch (e) {}
      syncRail();
    });
    syncRail();
  }

  /* ================= theme switch =================
     js/boot.js already put `dark` or `light` on <html> before first paint;
     this wires the pill. Anything but `light` reads as dark — the same default
     js/boot.js falls back to, and the two must agree. */
  function initTheme() {
    var btns = d.querySelectorAll('[data-theme-set]');
    if (!btns.length) return;
    var html = d.documentElement;
    function sync() {
      var t = html.classList.contains('light') ? 'light' : 'dark';
      Array.prototype.forEach.call(btns, function (b) {
        b.setAttribute('aria-pressed', b.getAttribute('data-theme-set') === t ? 'true' : 'false');
      });
      var meta = d.querySelector('meta[name="theme-color"]');
      if (meta) meta.setAttribute('content', t === 'light' ? '#fafafa' : '#060606');
    }
    Array.prototype.forEach.call(btns, function (b) {
      b.addEventListener('click', function () {
        var t = b.getAttribute('data-theme-set') === 'light' ? 'light' : 'dark';
        html.classList.remove('light', 'dark');
        html.classList.add(t);
        try { localStorage.setItem('agent-chat.theme', t); } catch (e) {}
        sync();
      });
    });
    sync();
  }
})();
