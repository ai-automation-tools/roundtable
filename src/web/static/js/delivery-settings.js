// Settings > Delivery: the folder / command sink form and its save.
(function() {
  const form = document.getElementById('dl-form');
  const errorPanel = document.getElementById('dl-error');
  const msg = document.getElementById('dl-msg');
  const saveBtn = form.querySelector('button[type=submit]');

  function events(name) {
    return Array.from(form.querySelectorAll('input[data-events=' + name + ']:checked'))
      .map(b => b.value);
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => (
      {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
    ));
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    errorPanel.classList.add('hidden');
    msg.className = 'su-seats-msg';
    msg.textContent = 'Saving\u2026';
    saveBtn.disabled = true;
    const payload = {
      folder: {
        enabled: document.getElementById('dl-folder-enabled').checked,
        path: document.getElementById('dl-folder-path').value.trim(),
        include_result: document.getElementById('dl-folder-result').checked,
        scope: (form.querySelector('input[name=dl-scope]:checked') || {}).value || 'all',
        events: events('folder'),
      },
      command: {
        enabled: document.getElementById('dl-cmd-enabled').checked,
        argv: document.getElementById('dl-cmd-argv').value.trim(),
        timeout: parseInt(document.getElementById('dl-cmd-timeout').value, 10) || 120,
        events: events('command'),
      },
    };
    try {
      const res = await fetch('/api/settings/delivery', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.ok) {
        msg.className = 'su-seats-msg ok';
        msg.textContent = 'Saved \u2713';
      } else {
        msg.textContent = '';
        errorPanel.innerHTML = '<h2>Not saved</h2><p>' +
          esc(data.error || 'Unknown error') + '</p>';
        errorPanel.classList.remove('hidden');
      }
    } catch (err) {
      msg.textContent = '';
      errorPanel.innerHTML = '<h2>Network error</h2><p>' + esc(String(err)) + '</p>';
      errorPanel.classList.remove('hidden');
    } finally {
      saveBtn.disabled = false;
    }
  });
})();
