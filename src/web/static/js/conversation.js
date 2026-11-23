// One conversation's transcript reader: live updates over SSE, the progress
// bar, Stop / Delete / close-windows, the prompt dialogs. Its per-page values
// (id, last message id, cast, avatars, live or not) come from the #cv-data
// JSON block rendered by web/render/conversations.py.
(function() {
  const DATA = JSON.parse(document.getElementById('cv-data').textContent);
  const cid = DATA.cid;
  let lastId = DATA.lastId;
  const PERSONAS = DATA.personas;
  const AGENT_VISUALS = DATA.visuals;
  const transcript = document.getElementById('transcript');
  const pill = document.getElementById('cv-pill');
  const turnBadge = document.getElementById('turn-badge');
  // "quiet for N" — elapsed since the last message, ticking locally.
  // Deliberately not a health check: it reports, the operator judges.
  const quietBadge = document.getElementById('quiet-badge');
  let quietSince = quietBadge
    ? Date.parse(quietBadge.dataset.last.replace(' ', 'T')) : 0;
  const quietBar = quietBadge ? (parseInt(quietBadge.dataset.bar, 10) || 240) : 240;
  function humanGap(sec) {
    if (sec < 90) return Math.round(sec) + 's';
    if (sec < 5400) return Math.round(sec / 60) + ' min';
    return (sec / 3600).toFixed(1) + ' h';
  }
  function tickQuiet() {
    if (!quietBadge || !quietSince) return;
    const sec = (Date.now() - quietSince) / 1000;
    if (sec < 60) { quietBadge.hidden = true; return; }
    quietBadge.hidden = false;
    const over = sec >= quietBar;
    quietBadge.classList.toggle('is-stale', over);
    quietBadge.querySelector('.cv-quiet-txt').textContent =
      'quiet ' + humanGap(sec);
    quietBadge.title = over
      ? 'No message for ' + humanGap(sec) + ', longer than usual for this '
        + 'conversation. An agent may be composing a long reply — or may be '
        + 'waiting on a prompt in its own window. Check the CLI window before '
        + 'assuming it is stuck.'
      : 'Time since the last message.';
  }
  tickQuiet();
  setInterval(tickQuiet, 15000);
  const stopBtn = document.getElementById('stop-btn');
  const nextSteps = document.getElementById('next-steps');
  // Wire the "Copy prompt" buttons in the Next-steps panel.
  if (nextSteps) {
    nextSteps.querySelectorAll('.ns-copy').forEach(btn => {
      btn.addEventListener('click', async () => {
        const prompt = btn.dataset.prompt || '';
        try {
          await navigator.clipboard.writeText(prompt);
          const orig = btn.textContent;
          btn.textContent = 'Copied!';
          btn.disabled = true;
          setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 1500);
        } catch (err) {
          alert('Copy failed: ' + err.message);
        }
      });
    });
  }
  // --- media-prompt modal -----------------------------------------
  // The button fetches the prompt rather than carrying it in a data-
  // attribute: they run ~9KB each and would sit in the HTML of every
  // conversation page whether or not anyone opens one.
  const pmModal = document.getElementById('cv-pm');
  const pmTitle = document.getElementById('cv-pm-title');
  const pmSub = document.getElementById('cv-pm-sub');
  const pmText = document.getElementById('cv-pm-text');
  const pmCopy = document.getElementById('cv-pm-copy');
  const pmDl = document.getElementById('cv-pm-dl');
  const PM_META = {
    images: {
      title: 'Image prompt',
      sub: 'Copy this and paste it into an image tool (ChatGPT, Gemini, Midjourney, a CLI agent). It asks for a cover, a team shot, and one portrait per character — already filled in with this cast.',
    },
    audio: {
      title: 'Audio prompt',
      sub: 'Copy this and paste it into a CLI agent with text-to-speech. It fetches this transcript and renders one voiced MP3 — already filled in with this cast.',
    },
  };
  function pmClose() {
    if (pmModal) pmModal.classList.add('hidden');
  }
  if (pmModal) {
    pmModal.addEventListener('click', (e) => {
      if (e.target === pmModal || e.target.closest('[data-pm-close]')) pmClose();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !pmModal.classList.contains('hidden')) pmClose();
    });
  }
  // --- Actions help popover ---
  // One "?" for the pane. Click toggles; click-outside and Escape
  // close. aria-expanded is the single source of truth for open state,
  // so the CSS lit-state and the assistive-tech state can't disagree.
  const ahBtn = document.getElementById('cv-ahelp-btn');
  const ahPop = document.getElementById('cv-ahelp-pop');
  if (ahBtn && ahPop) {
    const ahSet = (open) => {
      ahPop.hidden = !open;
      ahBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    };
    ahBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      ahSet(ahPop.hidden);
    });
    document.addEventListener('click', (e) => {
      if (!ahPop.hidden && !ahPop.contains(e.target)) ahSet(false);
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !ahPop.hidden) { ahSet(false); ahBtn.focus(); }
    });
  }
  document.querySelectorAll('.cv-prompt-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const kind = btn.dataset.kind;
      const meta = PM_META[kind] || { title: 'Prompt', sub: '' };
      const url = '/api/conversations/' + cid + '/prompts/' + kind + '.md';
      if (!pmModal) return;
      pmTitle.textContent = meta.title;
      pmSub.textContent = meta.sub;
      pmText.value = 'Loading…';
      pmDl.href = url + '?download=1';
      pmModal.classList.remove('hidden');
      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        pmText.value = await res.text();
      } catch (err) {
        pmText.value = 'Could not build the prompt: ' + err.message;
      }
    });
  });
  if (pmCopy) {
    pmCopy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(pmText.value);
        const orig = pmCopy.textContent;
        pmCopy.textContent = 'Copied!';
        setTimeout(() => { pmCopy.textContent = orig; }, 1500);
      } catch (err) {
        // Clipboard is blocked outside a secure context (plain http on
        // a LAN address). Selecting the text still lets them copy it.
        pmText.select();
        alert('Copy failed: ' + err.message + '\nThe text is selected — press Ctrl+C.');
      }
    });
  }

  if (stopBtn) {
    stopBtn.addEventListener('click', async () => {
      if (!confirm('End this conversation? Both agents will see status="complete" on their next call. This cannot be undone.')) return;
      stopBtn.disabled = true;
      stopBtn.textContent = 'Stopping…';
      try {
        const res = await fetch('/api/conversations/' + cid + '/stop', { method: 'POST' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        // A stopped run reaches an agent only at its next MCP call; one
        // mid-tool-call keeps going. Offer to close the windows this app
        // opened for it (audit RT-21).
        const info = await res.json().catch(() => ({}));
        const n = info.seat_windows || 0;
        if (n && confirm('Also close the ' + n + ' CLI window' + (n === 1 ? '' : 's') +
                         ' this app opened for it? Anything unsaved in them is lost.')) {
          await fetch('/api/conversations/' + cid + '/close-windows', { method: 'POST' });
        }
        // Server flipped status='complete'. The SSE stream will emit
        // 'event: complete' on its next tick; the pill flips there.
      } catch (err) {
        alert('Stop failed: ' + err.message);
        stopBtn.disabled = false;
        stopBtn.textContent = 'Stop';
      }
    });
  }
  const deleteBtn = document.getElementById('delete-btn');
  if (deleteBtn) {
    deleteBtn.addEventListener('click', async () => {
      const topic = deleteBtn.dataset.topic || '(untitled)';
      const msgs = deleteBtn.dataset.msgCount || '0';
      if (!confirm('Permanently delete conversation #' + cid + '?\n\nTopic: ' + topic +
                   '\nMessages: ' + msgs + '\n\nThis deletes the row and all its messages. ' +
                   'The local sidecar applies the deletion within ~5s. This cannot be undone.')) return;
      deleteBtn.disabled = true;
      try {
        const res = await fetch('/api/conversations/' + cid + '/delete', { method: 'POST' });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        location.href = '/conversations';
      } catch (err) {
        alert('Delete failed: ' + err.message);
        deleteBtn.disabled = false;
      }
    });
  }
  // Syntax-highlight code blocks in the server-rendered HTML.
  // Re-run after each SSE message append below.
  if (window.__hl) window.__hl(document.getElementById('transcript'));

  // --- scroll progress + jump-to-latest ---------------------------
  // .cv-main is the scroller; the window itself never scrolls on this
  // page, so every measurement below is against the pane. Wired up for
  // complete conversations too (the rail is just as useful reading an
  // archived debate) — hence it sits above the is_active early-return.
  const cvMain = document.getElementById('cv-main');
  const progBar = document.querySelector('#cv-prog i');
  const jumpWrap = document.getElementById('cv-jumpwrap');
  const jumpBtn = document.getElementById('cv-jump');
  const jumpN = document.getElementById('cv-jump-n');
  const NEAR = 120;  // px of slack that still counts as "at the bottom"
  let unread = 0;
  function atBottom() {
    if (!cvMain) return true;
    return cvMain.scrollHeight - cvMain.scrollTop - cvMain.clientHeight <= NEAR;
  }
  function paintProgress() {
    if (!progBar || !cvMain) return;
    const max = cvMain.scrollHeight - cvMain.clientHeight;
    const p = max > 0 ? Math.min(1, Math.max(0, cvMain.scrollTop / max)) : 0;
    progBar.style.transform = 'scaleX(' + p + ')';
  }
  function paintJump() {
    if (!jumpWrap) return;
    jumpWrap.classList.toggle('show', unread > 0 && !atBottom());
    if (jumpN) { jumpN.hidden = unread < 1; jumpN.textContent = unread; }
  }
  function toBottom(smooth) {
    if (!cvMain) return;
    cvMain.scrollTo({ top: cvMain.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    unread = 0;
    paintJump();
  }
  if (cvMain) {
    cvMain.addEventListener('scroll', () => {
      paintProgress();
      if (atBottom()) unread = 0;
      paintJump();
    }, { passive: true });
    window.addEventListener('resize', paintProgress, { passive: true });
    paintProgress();
  }
  if (jumpBtn) jumpBtn.addEventListener('click', () => toBottom(true));

  if (!DATA.active) return;
  const es = new EventSource('/api/conversations/' + cid + '/stream?since=' + lastId);
  es.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id <= lastId) return;
    // Measure BEFORE the DOM grows, or the new message's own height
    // pushes us out of the "at the bottom" window and we never stick.
    const stick = atBottom();
    lastId = m.id;
    const tmp = document.createElement('div');
    tmp.innerHTML = renderMsg(m);
    const node = tmp.firstElementChild;
    transcript.appendChild(node);
    if (window.__hl) window.__hl(node);
    // First real message — hide the "Next: launch each CLI" panel.
    if (nextSteps && nextSteps.parentNode) {
      nextSteps.remove();
    }
    // Follow the tail only if the reader was already at it. This used
    // to scroll unconditionally, which yanked the viewport away from
    // anyone reading earlier in the debate every time an agent replied.
    if (stick) {
      toBottom(false);
    } else {
      unread++;
      paintJump();
    }
    paintProgress();
  });
  es.addEventListener('turn', (ev) => {
    if (!turnBadge) return;
    try {
      const d = JSON.parse(ev.data);
      const who = d.current_turn;
      const label = who
        ? (PERSONAS[who] ? PERSONAS[who] + ' (' + who + ') is up' : who + ' is up')
        : 'waiting…';
      turnBadge.querySelector('.cv-turn-txt').textContent = label;
    } catch (e) {}
  });
  es.addEventListener('complete', () => {
    es.close();
    if (pill) {
      pill.classList.remove('is-active');
      pill.querySelector('.cv-pill-txt').textContent = 'complete';
    }
    if (turnBadge) turnBadge.remove();
    if (quietBadge) quietBadge.remove();
    if (stopBtn) stopBtn.remove();
  });
  function demoteEarlierResults() {
    // A new result supersedes every earlier one. Same last-wins rule
    // the server render and the export use (export.final_result);
    // applied here so a live run agrees with a reload.
    document.querySelectorAll('.msg.signal-result:not(.signal-superseded)')
      .forEach(el => {
        el.classList.add('signal-superseded');
        const badge = el.querySelector('.msg-head .signal');
        if (badge) {
          badge.className = 'signal superseded';
          badge.textContent = 'superseded draft';
        }
        const body = el.querySelector(':scope > .msg-body');
        if (body && !el.querySelector('.msg-superseded')) {
          const d = document.createElement('details');
          d.className = 'msg-superseded';
          const sum = document.createElement('summary');
          sum.textContent =
            'Superseded draft — a later result replaced this. Show it.';
          d.appendChild(sum);
          body.replaceWith(d);
          d.appendChild(body);
        }
      });
  }
  function renderMsg(m) {
    if (m.signal === 'result') demoteEarlierResults();
    quietSince = Date.now();
    if (quietBadge) quietBadge.hidden = true;
    // m.content_html is server-rendered safe HTML (markdown-it-py
    // with html=False + URL-scheme validator + target=_blank patch).
    // No client-side escaping — the server already did it.
    const senderClass = 'sender-' + esc(m.sender || '');
    const signalClass = m.signal ? 'signal-' + esc(m.signal) : '';
    const signalBadge = m.signal
      ? '<span class="signal ' + esc(m.signal) + '">' + esc(m.signal) + '</span>'
      : '';
    const pname = PERSONAS[m.sender];
    const visual = AGENT_VISUALS[m.sender] || AGENT_VISUALS.system ||
      { initials: String(m.sender || 'AI').slice(0, 2).toUpperCase(), style: '--cv-ink:#10b981;--cv-ink-2:#38bdf8;', avatar: '/avatars/' + encodeURIComponent(String(m.sender || '')) };
    const avatarUrl = visual.avatar || '';
    const avatar = avatarUrl
      ? '<span class="msg-avatar avatar-has-img" style="' + esc(visual.style) + '" role="img">' +
          '<img class="avatar-img" src="' + esc(avatarUrl) + '" alt="" loading="lazy" ' +
          'data-on-error="hide">' + esc(visual.initials || 'AI') + '</span>'
      : '<span class="msg-avatar" style="' + esc(visual.style) +
          '" aria-hidden="true">' + esc(visual.initials || 'AI') + '</span>';
    const who = pname
      ? esc(pname) + ' <span class="who-cli">' + esc(m.sender) + '</span>'
      : esc(m.sender);
    const hid = 'm' + esc(m.id) + '-who';
    return '<article class="msg ' + senderClass + ' ' + signalClass + '" data-id="' + esc(m.id) +
      '" aria-labelledby="' + hid + '">' +
      '<div class="msg-head">' + avatar + '<h3 class="who" id="' + hid + '">' + who + '</h3>' +
      '<span class="time">' + esc(fmtTime(m.created_at)) + '</span>' + signalBadge + '</div>' +
      '<div class="msg-body">' + (m.content_html || '') + '</div></article>';
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, c => (
      {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
    ));
  }
  function fmtTime(ts) {
    return String(ts).replace('T', ' ').split('+')[0].split('.')[0];
  }
})();
