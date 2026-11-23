// Settings > Notifications: service picker, per-service scratch, test + save.
// Service metadata and the saved state come from the #nt-data JSON block.
(function() {
  const DATA = JSON.parse(document.getElementById('nt-data').textContent);
  const META = DATA.meta;
  const SAVED = DATA.saved;
  const form = document.getElementById('nt-form');
  const targetIn = document.getElementById('nt-target');
  const serverIn = document.getElementById('nt-server');
  const serverWrap = document.getElementById('nt-server-wrap');
  const tLabel = document.getElementById('nt-target-label');
  const tHint = document.getElementById('nt-target-hint');
  const errorPanel = document.getElementById('nt-error');
  const msg = document.getElementById('nt-msg');
  const testBtn = document.getElementById('nt-test');
  const saveBtn = form.querySelector('button[type=submit]');
  const enabledIn = document.getElementById('nt-enabled');

  // Per-service scratch, so switching radios to compare options and switching
  // back doesn't silently drop the URL you already pasted.
  const scratch = {};
  let current = SAVED.service;
  scratch[SAVED.service] = {target: SAVED.target, server: SAVED.server};
  enabledIn.checked = SAVED.enabled;

  function svc() {
    const el = form.querySelector('input[name=nt-service]:checked');
    return el ? el.value : DATA.defaultService;
  }

  // A URL from the page's data, accepted only as a same-origin path or an
  // https URL, and URI-encoded — so no value can become a javascript: link.
  function safeUrl(u) {
    u = String(u || '');
    return /^(\/(?![\/\\])|https:\/\/)/.test(u) ? encodeURI(u) : '';
  }

  function paint(to) {
    const meta = META[to] || {};
    tLabel.textContent = meta.target_label || 'URL';
    tHint.textContent = meta.target_hint || '';
    const docs = safeUrl(meta.docs);
    if (docs) {
      const a = document.createElement('a');
      a.href = docs;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = 'Docs \u2197';
      tHint.append(' ', a);
    }
    targetIn.placeholder = meta.placeholder || '';
    const saved = scratch[to] || {};
    targetIn.value = saved.target || '';
    if (meta.server) {
      serverWrap.style.display = '';
      serverIn.value = saved.server || meta.server;
    } else {
      serverWrap.style.display = 'none';
      serverIn.value = '';
    }
  }

  form.addEventListener('change', (ev) => {
    if (ev.target.name !== 'nt-service') return;
    scratch[current] = {target: targetIn.value, server: serverIn.value};
    current = ev.target.value;
    paint(current);
  });

  function events() {
    return Array.from(form.querySelectorAll('input[name=nt-event]:checked'))
      .map(b => b.value);
  }

  function payload() {
    return {
      service: svc(),
      target: targetIn.value.trim(),
      server: serverIn.value.trim(),
      events: events(),
      enabled: enabledIn.checked,
    };
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => (
      {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
    ));
  }

  function fail(title, detail) {
    errorPanel.innerHTML = '<h2>' + esc(title) + '</h2><p>' + esc(detail) + '</p>';
    errorPanel.classList.remove('hidden');
  }

  async function send(url, btn, busy, done) {
    errorPanel.classList.add('hidden');
    msg.className = 'su-seats-msg';
    msg.textContent = busy;
    btn.disabled = true;
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload()),
      });
      const data = await res.json();
      if (data.ok) {
        msg.className = 'su-seats-msg ok';
        msg.textContent = done;
        return true;
      }
      msg.textContent = '';
      fail('Not sent', data.error || 'Unknown error');
    } catch (err) {
      msg.textContent = '';
      fail('Network error', String(err));
    } finally {
      btn.disabled = false;
    }
    return false;
  }

  testBtn.addEventListener('click', () => send(
    '/api/notifications/test', testBtn,
    'Sending\u2026', 'Sent \u2713 \u2014 check your device'));

  form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    send('/api/notifications', saveBtn, 'Saving\u2026', 'Saved \u2713');
  });

  paint(current);
})();
