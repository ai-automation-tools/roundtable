// Settings > CLI tools: the ticklist, re-probe, seat creation, save. The
// per-tool seat cap arrives as data-max-seats on this script's own tag.
(function() {
  const MAX_SEATS = Number(document.currentScript.dataset.maxSeats);
  const form = document.getElementById('su-form');
  const submitBtn = form.querySelector('button[type=submit]');
  const errorPanel = document.getElementById('su-error');
  const planBox = document.getElementById('su-plan');
  const boxes = Array.from(form.querySelectorAll('input[name=cli]'));

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => (
      {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
    ));
  }

  // Same round-robin as orchestrator.availability.plan_seats — one seat per
  // tool, then a second on each. Mirrored here only to preview the plan; the
  // server plans for real when a conversation is seeded.
  function planSeats(clis, count) {
    const out = [];
    let idx = 1;
    while (out.length < count && idx <= MAX_SEATS) {
      for (const c of clis) {
        if (out.length >= count) break;
        out.push(idx === 1 ? c : c + '-' + idx);
      }
      idx++;
    }
    return out;
  }

  function chosen() { return boxes.filter(b => b.checked).map(b => b.value); }

  function renderPlan() {
    const clis = chosen();
    if (!clis.length) {
      planBox.innerHTML = '<p class="su-plan-none">No CLIs ticked. With none, there\'s ' +
        'nothing to seed a conversation with &mdash; install one and come back, or tick ' +
        'the one you already have.</p>';
      return;
    }
    const two = planSeats(clis, 2);
    const three = planSeats(clis, 3);
    const extra = two.concat(three).filter((s, i, a) =>
      a.indexOf(s) === i && /-[2-9]$/.test(s));
    let html = '<p class="su-plan-lead"><strong>' + clis.length + '</strong> CLI' +
      (clis.length === 1 ? '' : 's') + ' available.</p>' +
      '<ul class="su-plan-list">' +
      '<li><span class="su-plan-k">2-agent debate</span>' +
        '<span class="su-seatline">' + two.map(s => '<code>' + esc(s) + '</code>').join(
          ' <span class="su-vs">vs</span> ') + '</span></li>' +
      '<li><span class="su-plan-k">3-agent debate</span>' +
        '<span class="su-seatline">' + three.map(s => '<code>' + esc(s) + '</code>').join(
          ' <span class="su-vs">&middot;</span> ') + '</span></li>' +
      '</ul>';
    if (clis.length === 1) {
      html += '<p class="su-plan-note">One tool is fine: seat 1 keeps the bare id and ' +
        'each extra seat gets its own config folder passing its own <code>--agent-id</code>. ' +
        'Two instances of the same CLI, two personas, one debate.</p>';
    }
    if (extra.length) {
      html += '<div class="su-seats" id="su-seats" data-seats="' +
        esc(extra.join(',')) + '">' +
        '<p>Those runs need seat folders that don\'t exist yet: ' +
        extra.map(s => '<code>' + esc(s) + '</code>').join(', ') + '. ' +
        'Each is a copy of seat 1\'s MCP config with the agent id rewritten.</p>' +
        '<button type="button" class="btn su-mkseats">Create the missing seat folders</button>' +
        '<span class="su-seats-msg"></span></div>';
    }
    planBox.innerHTML = html;
    // Only offer creation for seats that are genuinely absent.
    const box = document.getElementById('su-seats');
    if (box) refreshSeats(box);
  }

  async function refreshSeats(box) {
    const want = box.dataset.seats.split(',').filter(Boolean);
    try {
      const res = await fetch('/api/setup');
      const data = await res.json();
      const missing = want.filter(s => (data.missing_seats || []).includes(s) ||
                                        !(data.existing_seats || []).includes(s));
      if (!missing.length) { box.remove(); return; }
      box.dataset.seats = missing.join(',');
    } catch (_) { /* leave the button; the POST reports the real outcome */ }
  }

  planBox.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('.su-mkseats');
    if (!btn) return;
    const box = btn.closest('.su-seats');
    const msg = box.querySelector('.su-seats-msg');
    btn.disabled = true;
    msg.textContent = 'Creating\u2026';
    try {
      const res = await fetch('/api/setup/seats', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({seats: box.dataset.seats.split(',').filter(Boolean)}),
      });
      const data = await res.json();
      if (data.ok) {
        msg.className = 'su-seats-msg ok';
        msg.textContent = 'Created: ' + (data.created || []).join(', ');
        if (data.notes && data.notes.length) {
          const p = document.createElement('p');
          p.className = 'su-plan-note';
          p.textContent = data.notes.join(' ');
          box.appendChild(p);
        }
        btn.remove();
      } else {
        msg.className = 'su-seats-msg fail';
        msg.textContent = data.error || 'Could not create the seats.';
        btn.disabled = false;
      }
    } catch (err) {
      msg.className = 'su-seats-msg fail';
      msg.textContent = String(err);
      btn.disabled = false;
    }
  });

  boxes.forEach(b => b.addEventListener('change', renderPlan));
  renderPlan();

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    submitBtn.disabled = true;
    submitBtn.textContent = 'Saving\u2026';
    errorPanel.classList.add('hidden');
    try {
      const res = await fetch('/api/setup', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({available: chosen()}),
      });
      const data = await res.json();
      if (data.ok) {
        submitBtn.textContent = 'Saved \u2713';
        setTimeout(() => {
          submitBtn.disabled = false;
          submitBtn.textContent = 'Save my CLI setup';
        }, 1600);
        return;
      }
      errorPanel.innerHTML = '<h2>Not saved</h2><p>' + esc(data.error || 'Unknown error') + '</p>';
      errorPanel.classList.remove('hidden');
    } catch (err) {
      errorPanel.innerHTML = '<h2>Network error</h2><p>' + esc(String(err)) + '</p>';
      errorPanel.classList.remove('hidden');
    } finally {
      if (submitBtn.textContent === 'Saving\u2026') {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Save my CLI setup';
      }
    }
  });
})();
