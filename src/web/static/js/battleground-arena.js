// One arena on /battleground/{aid}: verdict buttons, status, delete. Every
// action POSTs to the same bridge endpoints the extension's side panel uses.
(function () {
  var shell = document.querySelector('[data-arena]');
  if (!shell) return;
  var aid = shell.getAttribute('data-arena');
  var msg = document.getElementById('bgc-msg');
  // The reject-reason presets ride on this script's tag (data-reasons); read
  // now, since document.currentScript is only set while the script first runs.
  var reasons = JSON.parse(document.currentScript.dataset.reasons);

  function say(text, bad) {
    msg.textContent = text || '';
    msg.className = 'bgc-msg' + (bad ? ' fail' : '');
  }

  function post(path, payload) {
    return fetch(path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload || {})
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error((d && d.error) || ('HTTP ' + r.status));
        return d;
      });
    });
  }

  document.addEventListener('click', function (ev) {
    var t = ev.target;
    if (!t || !t.closest) return;
    var el = t.closest('[data-verdict], [data-arena-status], [data-arena-delete]');
    if (!el) return;

    var verdict = el.getAttribute('data-verdict');
    if (verdict) {
      var payload = {verdict: verdict};
      if (verdict === 'rejected') {
        var note = window.prompt(
          'Why? The agent reads this as a revision brief.\n\n' + reasons.join('\n'),
          reasons[0]
        );
        if (note === null) return;
        if (note.trim()) payload.note = note.trim();
      }
      say('Saving\u2026');
      post('/api/battleground/drafts/' + el.getAttribute('data-draft') + '/verdict', payload)
        .then(function () { window.location.reload(); })
        .catch(function (e) { say(String(e.message || e), true); });
      return;
    }

    var next = el.getAttribute('data-arena-status');
    if (next) {
      say('Saving\u2026');
      post('/api/battleground/arenas/' + aid, {status: next})
        .then(function () { window.location.reload(); })
        .catch(function (e) { say(String(e.message || e), true); });
      return;
    }

    if (el.getAttribute('data-arena-delete')) {
      if (!window.confirm('Delete arena #' + aid + ' and every draft on it? This cannot be undone.')) return;
      say('Deleting\u2026');
      post('/api/battleground/arenas/' + aid + '/delete', {})
        .then(function () { window.location.href = '/battleground'; })
        .catch(function (e) { say(String(e.message || e), true); });
    }
  });
})();
