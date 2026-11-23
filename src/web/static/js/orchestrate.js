// The /orchestrate form: the chair engine (one row per chair, seat ids derived
// from chair order), presets, formats, custom persona cards, the brief picker,
// preflight + launch. Server values come from the #orch-data JSON block
// rendered by web/render/orchestrate.py.
(function() {
  const DATA = JSON.parse(document.getElementById('orch-data').textContent);
  const presetDefaults = DATA.presets;
  const convTypes = DATA.convTypes;
  const form = document.getElementById('orch-form');
  const submitBtn = form.querySelector('button[type=submit]');
  const errorPanel = document.getElementById('orch-error');
  const presetRadios = form.querySelectorAll('input[name=preset]');
  const presetCards = form.querySelectorAll('.orch-preset');
  const presetSection = document.getElementById('orch-preset-section');
  const presetLabel = document.getElementById('orch-preset-label');
  const presetGrid = document.getElementById('orch-preset-grid');
  const maxTurns = form.querySelector('input[name=max_turns]');
  const firstSelect = form.querySelector('select[name=first]');
  // The chair row is a server-rendered <template>: its option lists, icon and
  // accept list are markup, so they are cloned, never assembled as a string.
  const chairTpl = document.getElementById('orch-chair-tpl');
  const MAX_SEATS_PER_CLI = DATA.maxSeatsPerCli;
  const seatsBox = document.getElementById('orch-seats');
  const addSeatBtn = document.getElementById('orch-add-seat');
  const modSeatId = document.getElementById('orch-mod-seat-id');
  const castRandomBtn = document.getElementById('orch-cast-random');
  const spawnToggle = form.querySelector('input[name=spawn]');
  const skipToggle = form.querySelector('input[name=skip_permissions]');
  const deliverToggle = form.querySelector('input[name=deliver_locally]');
  const publishToggle = form.querySelector('input[name=publish]');
  const modEnable = form.querySelector('input[name=mod_enable]');
  const modFields = document.getElementById('orch-mod-fields');
  const modCli = form.querySelector('select[name=mod_cli]');
  const modPersona = form.querySelector('select[name=mod_persona]');
  const typeRadios = form.querySelectorAll('input[name=conv_type]');
  const guideLink = document.getElementById('orch-guide-link');
  const partsLabel = document.getElementById('orch-participants-label');
  const leadLabel = document.getElementById('orch-lead-label');
  const leadHint = document.getElementById('orch-lead-hint');
  const modToggle = document.getElementById('orch-mod-toggle');
  const leadSection = document.getElementById('orch-lead-section');
  const firstLabel = document.getElementById('orch-first-label');
  const firstHint = document.getElementById('orch-first-hint');
  const modToggleText = document.getElementById('orch-mod-toggle-text');
  const modPersonaLabel = document.getElementById('orch-mod-persona-label');
  const extraSection = document.getElementById('orch-extra-section');
  const extraRows = document.getElementById('orch-extra-rows');
  // role -> cli, kept OUTSIDE the DOM so a pick survives the rebuild that
  // happens whenever the seat list or the format changes. Filtered against the
  // current type + checked seats on submit, so a stale entry can't be posted.
  const extraPicks = {};

  function currentType() {
    const picked = Array.from(typeRadios).find(r => r.checked);
    return convTypes[picked ? picked.value : ''] ? picked.value : 'debate';
  }

  // Re-label the form for the chosen format and force the lead seat on for a
  // type that requires one (a podcast without a host is not a podcast). The
  // server re-validates all of this — see orchestrator/conv_types.py.
  // A URL from the page's data, accepted only as a same-origin path or an
  // https URL, and URI-encoded — so no value can become a javascript: link.
  function safeUrl(u) {
    u = String(u || '');
    return /^(\/(?![\/\\])|https:\/\/)/.test(u) ? encodeURI(u) : '';
  }
  // "Label<em class="mark">note</em>", built from text — #orch-data values
  // never go through innerHTML.
  function setLabel(el, text, note, live) {
    el.textContent = text;
    const em = document.createElement('em');
    em.className = 'mark' + (live ? ' is-live' : '');
    em.textContent = note;
    el.appendChild(em);
  }

  function updateConvType() {
    const key = currentType();
    const t = convTypes[key];
    if (!t) return;
    // A lead that is one of the members is picked from these checkboxes, so
    // the range quoted here is the WHOLE room, not members-besides-the-lead.
    const lo = t.leadNeedsOwnSeat ? t.minMembers : t.minParticipants;
    const hi = t.leadNeedsOwnSeat ? t.maxMembers : t.maxParticipants;
    if (partsLabel) {
      setLabel(partsLabel, t.membersLabel, lo + '–' + hi + ' seats', false);
    }
    if (firstLabel) firstLabel.textContent = t.firstLabel || 'First speaker';
    if (firstHint) {
      firstHint.textContent = t.firstHint || '';
      firstHint.style.display = t.firstHint ? '' : 'none';
    }
    if (leadLabel) {
      setLabel(leadLabel, t.leadLabel, t.leadRequired ? 'required' : 'optional', t.leadRequired);
    }
    if (modToggleText) modToggleText.textContent = 'Add a ' + t.leadLabel.toLowerCase();
    if (modPersonaLabel) modPersonaLabel.textContent = t.leadLabel + ' persona';
    if (guideLink && t.guideUrl) {
      guideLink.href = safeUrl(t.guideUrl);
      guideLink.textContent = t.guideLabel + ' \u2197';
    }
    // One server-rendered hint per type; show this type's.
    if (leadHint) leadHint.querySelectorAll('[data-type]').forEach(el => {
      el.hidden = el.dataset.type !== key;
    });
    // A lead that is one of the members has no separate seat to configure:
    // hide the section AND clear the toggle so the submit handler sends
    // moderator:null. Left checked-but-hidden it would post an unseen seat.
    if (leadSection) leadSection.style.display = t.leadNeedsOwnSeat ? '' : 'none';
    if (modEnable && !t.leadNeedsOwnSeat) {
      modEnable.checked = false;
      modEnable.disabled = true;
    } else if (modEnable && t.leadRequired) {
      // Required: the seat is not a choice, so a disabled ticked box is noise.
      // Hide it and let the fields below stand on their own.
      modEnable.checked = true;
      modEnable.disabled = true;
      if (modToggle) modToggle.style.display = 'none';
    } else if (modEnable) {
      modEnable.disabled = false;
      if (modToggle) modToggle.style.display = '';
    }
    // Sub-types belong to a format, so show only the ones this format offers.
    // Cards are never rebuilt, just hidden — a selection that is still on
    // offer survives the switch. The server accepts any preset with any type
    // (presets.for_types is advisory), so this only shapes the picker.
    const offered = t.presets || [];
    let stillOffered = false;
    presetCards.forEach(card => {
      const name = card.dataset.preset;
      const show = name === '' || offered.includes(name);
      card.style.display = show ? '' : 'none';
      const radio = card.querySelector('input');
      if (radio) {
        radio.disabled = !show;
        if (radio.checked && !show) radio.checked = false;
        if (radio.checked && show) stillOffered = true;
      }
    });
    // Only one sub-type on offer means there is nothing to choose — hide the
    // whole section rather than showing a single radio next to "None".
    if (presetSection) presetSection.style.display = offered.length > 1 ? '' : 'none';
    if (presetLabel) presetLabel.textContent = offered.length > 1 ? 'Sub-type' : 'Preset';
    if (!stillOffered) selectPreset(t.defaultPreset && offered.includes(t.defaultPreset)
                                    ? t.defaultPreset : '');
    updateModerator();
    fitChairsToType();
    renderSeatIds();
    updateFirstSpeaker();
    updateExtraSeats();
  }

  // The host picks a TOOL like every other chair. It still needs a seat of its
  // own, but that is a seat NUMBER (roomSeats() hands it 'claude-code' and the
  // first guest on the same tool 'claude-code-2'), so hosting on the tool the
  // guests use is no longer a conflict to explain away.
  function updateModerator() {
    const on = !!(modEnable && modEnable.checked);
    if (modFields) modFields.style.display = on ? 'flex' : 'none';
    if (!modCli) return;
    modCli.disabled = !on;
    if (modPersona) modPersona.disabled = !on;
  }

  // --- chairs -------------------------------------------------------------
  // A chair is a row: which TOOL it runs on, and who it plays. Its seat id is
  // derived, never typed — the second chair on a tool is 'claude-code-2'. That
  // is the whole reason this replaced a grid of seat checkboxes: an operator
  // with one CLI could not express "all the chairs on Claude Code", and the
  // seat numbers were theirs to keep track of.
  let chairSeq = 0;

  function chairRows() {
    return seatsBox ? Array.from(seatsBox.querySelectorAll('.orch-seat')) : [];
  }

  function addChair(tool, persona) {
    if (!seatsBox || !chairTpl) return null;
    const id = 'c' + (++chairSeq);
    const row = chairTpl.content.firstElementChild.cloneNode(true);
    row.dataset.chair = id;
    row.querySelector('.orch-persona-custom').dataset.chair = id;
    row.querySelector('.orch-persona-file').dataset.chair = id;
    seatsBox.appendChild(row);
    const toolSel = row.querySelector('.seat-tool');
    if (tool && Array.from(toolSel.options).some(o => o.value === tool)) toolSel.value = tool;
    const personaSel = row.querySelector('.seat-persona');
    // Only a slug the roster offers — assigning an unknown value blanks the select.
    if (persona && Array.from(personaSel.options).some(o => o.value === persona)) personaSel.value = persona;
    toolSel.addEventListener('change', seatsChanged);
    personaSel.addEventListener('change', () => {
      if (personaSel.value !== '__custom__' && customPersonas[id]) clearCustom(id);
      updateRecap();
    });
    row.querySelector('.seat-del').addEventListener('click', () => removeChair(id));
    row.querySelector('.orch-persona-custom').addEventListener('click', () => {
      if (customPersonas[id]) { clearCustom(id); return; }
      row.querySelector('.orch-persona-file').click();
    });
    row.querySelector('.orch-persona-file').addEventListener('change', (ev) =>
      readPersonaCard(ev.target, id));
    return row;
  }

  function removeChair(id) {
    const row = chairRows().find(r => r.dataset.chair === id);
    if (!row) return;
    delete customPersonas[id];
    row.remove();
    seatsChanged();
  }

  function moderatorOn() {
    const t = convTypes[currentType()] || {};
    return !!(modEnable && modEnable.checked && t.leadNeedsOwnSeat);
  }

  // Seat ids for the whole room, in the order the server seeds them: the host
  // first when it holds its own seat, then the chairs top to bottom. Two chairs
  // on one tool become 'codex' and 'codex-2'.
  function roomSeats() {
    const t = convTypes[currentType()] || {};
    const counts = {};
    const next = (tool) => {
      counts[tool] = (counts[tool] || 0) + 1;
      return counts[tool] === 1 ? tool : tool + '-' + counts[tool];
    };
    const out = { host: null, chairs: [], overflow: [] };
    if (moderatorOn() && modCli && modCli.value) out.host = next(modCli.value);
    chairRows().forEach(r => {
      const tool = r.querySelector('.seat-tool').value;
      out.chairs.push(next(tool));
      if (counts[tool] > MAX_SEATS_PER_CLI && out.overflow.indexOf(tool) === -1) {
        out.overflow.push(tool);
      }
    });
    return out;
  }

  // Just the participant seats — what every other consumer used to read off the
  // checkbox list.
  function selectedSeats() { return roomSeats().chairs; }

  // Re-label the rows and repaint every derived seat id. Called for anything
  // that can change one: a tool swap, an add/remove, the host, the format.
  function renderSeatIds() {
    const t = convTypes[currentType()] || {};
    const room = roomSeats();
    const one = (t.membersLabel || 'Participants').replace(/s$/, '');
    chairRows().forEach((row, i) => {
      row.querySelector('.seat-n').textContent = one + ' ' + (i + 1);
      const idCell = row.querySelector('.seat-id');
      const seat = room.chairs[i];
      // Only worth saying when it isn't just the tool name: a second chair on
      // the same tool is the one case an operator has to be told about.
      const extra = seat && seat !== row.querySelector('.seat-tool').value;
      idCell.textContent = extra ? 'runs as ' + seat : '';
      idCell.classList.toggle('is-extra', !!extra);
    });
    if (modSeatId) {
      const extra = room.host && modCli && room.host !== modCli.value;
      modSeatId.textContent = extra ? 'runs as ' + room.host : '';
      modSeatId.classList.toggle('is-extra', !!extra);
    }
    const lo = t.leadNeedsOwnSeat ? t.minMembers : t.minParticipants;
    const hi = t.leadNeedsOwnSeat ? t.maxMembers : t.maxParticipants;
    const n = chairRows().length;
    if (addSeatBtn) {
      addSeatBtn.disabled = n >= hi;
      addSeatBtn.textContent = n >= hi ? 'Maximum seats' : '+ Add a seat';
    }
    chairRows().forEach(row => { row.querySelector('.seat-del').disabled = n <= lo; });
  }

  function seatsChanged() {
    renderSeatIds();
    updateFirstSpeaker();
    updateExtraSeats();
    updateRecap();
  }

  // Grow or shrink the chair list to fit the format just picked.
  function fitChairsToType() {
    const t = convTypes[currentType()] || {};
    const lo = t.leadNeedsOwnSeat ? t.minMembers : t.minParticipants;
    const hi = t.leadNeedsOwnSeat ? t.maxMembers : t.maxParticipants;
    while (chairRows().length > hi) {
      const last = chairRows()[chairRows().length - 1];
      delete customPersonas[last.dataset.chair];
      last.remove();
    }
    while (chairRows().length < lo) addChair(null, null);
  }

  // The error panel lives at the foot of the form, which is off-screen for a
  // failure raised while picking a persona seven sections up. Bring it along.
  function showError(title, lines) {
    if (!errorPanel) return;
    errorPanel.innerHTML = '<h2>' + escapeHtml(title) + '</h2><ul>' +
      (lines || []).map(l => '<li>' + escapeHtml(l) + '</li>').join('') + '</ul>';
    errorPanel.classList.remove('hidden');
    errorPanel.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  // Persona cards uploaded for THIS RUN ONLY: {chair: {filename, text}}.
  // Read with FileReader like the Brief; the text rides the launch payload and
  // is parsed server-side into a persona body with no slug. Nothing is written
  // to the registry, so a one-off card never appears in /personas or on the
  // mirror — /personas' importer is the place that saves one.
  const customPersonas = {};

  function chairRowFor(chair) {
    return chairRows().find(r => r.dataset.chair === chair);
  }

  function personaSelectFor(chair) {
    const row = chairRowFor(chair);
    return row ? row.querySelector('.seat-persona') : null;
  }

  // The select is the one place a seat's persona is stated, so a loaded card
  // has to become an option in it rather than a badge parked alongside — with
  // the file name on it, since "custom" alone does not say which card.
  function setCustomOption(chair, filename) {
    const sel = personaSelectFor(chair);
    if (!sel) return;
    let opt = sel.querySelector('option[value="__custom__"]');
    if (!opt) {
      opt = document.createElement('option');
      opt.value = '__custom__';
      sel.insertBefore(opt, sel.firstChild);
    }
    opt.textContent = 'custom: ' + filename;
    sel.value = '__custom__';
    const row = chairRowFor(chair);
    if (row) row.classList.add('has-custom');
    updateRecap();
  }

  function clearCustom(chair) {
    delete customPersonas[chair];
    const sel = personaSelectFor(chair);
    const opt = sel && sel.querySelector('option[value="__custom__"]');
    if (opt) opt.remove();
    if (sel) sel.value = '__none__';
    const row = chairRowFor(chair);
    if (row) row.classList.remove('has-custom');
    updateRecap();
  }

  // Read one persona card off a chair's file input. Wired in addChair(), since
  // rows come and go — a document-wide listener would miss every row added
  // after load.
  function readPersonaCard(input, chair) {
    const file = input.files && input.files[0];
    input.value = '';
    if (!file) return;
    if (file.size > DATA.personaMax) {
      showError('Persona card too large',
        [file.name + ' is ' + Math.round(file.size / 1024) + ' KB — the limit is '
         + Math.round(DATA.personaMax / 1024) + ' KB.']);
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => showError('Could not read that file', [file.name]);
    reader.onload = () => {
      const text = String(reader.result || '').trim();
      if (!text) {
        showError('That persona card is empty', [file.name + ' has no content.']);
        return;
      }
      customPersonas[chair] = { filename: file.name, text: text };
      setCustomOption(chair, file.name);
    };
    reader.readAsText(file);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => (
      {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
    ));
  }

  // The seat that will hold the lead role, for a type whose lead is one of the
  // members. Excluded from every extra-seat dropdown: a facilitator that is
  // also the skeptic is one seat doing two jobs, and the server refuses it.
  // Types whose lead runs on its own seat can't clash — that seat is never a
  // checked participant.
  function effectiveLeadSeat() {
    const t = convTypes[currentType()] || {};
    if (!t.leadRequired || t.leadNeedsOwnSeat) return null;
    const checked = selectedSeats();
    const first = firstSelect ? firstSelect.value : '';
    return (first && checked.includes(first)) ? first : (checked[0] || null);
  }

  // One dropdown per extra-role SLOT (a role with maxCount 2 gets two), built
  // from convTypes[...].extraRoles so a new one needs no edit here. Picks live
  // in `extraPicks`, not the DOM, because this markup is thrown away and
  // rebuilt every time the seat list or the format changes.
  function updateExtraSeats() {
    if (!extraRows || !extraSection) return;
    const t = convTypes[currentType()] || {};
    const offered = t.extraRoles || [];
    extraSection.style.display = offered.length ? '' : 'none';
    if (!offered.length) { extraRows.innerHTML = ''; return; }
    const lead = effectiveLeadSeat();
    const seats = selectedSeats().filter(c => c !== lead);
    let html = '';
    offered.forEach(e => {
      const slots = Math.max(1, e.maxCount || 1);
      for (let i = 0; i < slots; i++) {
        const key = e.role + '#' + i;
        const label = slots > 1 ? e.label + ' ' + (i + 1) : e.label;
        let opts = '<option value="">(none)</option>';
        seats.forEach(s => {
          opts += '<option value="' + escapeHtml(s) + '">' + escapeHtml(s) + '</option>';
        });
        html += '<label class="orch-persona-row">' +
                '<span class="cli-name">' + escapeHtml(label) + '</span>' +
                '<select data-extra-key="' + escapeHtml(key) +
                '" data-extra-role="' + escapeHtml(e.role) + '">' + opts + '</select>' +
                '</label>';
      }
      if (e.hint) html += '<p class="hint">' + escapeHtml(e.hint) + '</p>';
    });
    extraRows.innerHTML = html;
    extraRows.querySelectorAll('select[data-extra-key]').forEach(sel => {
      const key = sel.dataset.extraKey;
      const prev = extraPicks[key];
      if (prev && seats.indexOf(prev) !== -1) { sel.value = prev; }
      else { delete extraPicks[key]; }
      sel.addEventListener('change', () => {
        if (sel.value) extraPicks[key] = sel.value; else delete extraPicks[key];
        updateRecap();
      });
    });
  }

  // {cli: role} for the seats currently marked, dropping anything the current
  // format or seat selection has invalidated. This is what the POST carries.
  function extraRolePayload() {
    const t = convTypes[currentType()] || {};
    const offered = (t.extraRoles || []).map(e => e.role);
    const lead = effectiveLeadSeat();
    const checked = selectedSeats();
    const out = {};
    Object.keys(extraPicks).forEach(key => {
      const role = key.split('#')[0];
      const cli = extraPicks[key];
      if (offered.indexOf(role) === -1) return;
      if (cli === lead || checked.indexOf(cli) === -1) return;
      out[cli] = role;
    });
    return out;
  }

  function updateFirstSpeaker() {
    const selected = selectedSeats();
    const current = firstSelect.value;
    firstSelect.innerHTML = '<option value="">(first selected)</option>' +
      selected.map(s => `<option value="${s}">${s}</option>`).join('');
    if (selected.includes(current)) firstSelect.value = current;
  }

  // Check one sub-type and pull its mode/turn defaults across.
  function selectPreset(name) {
    presetRadios.forEach(r => { r.checked = (r.value === name); });
    const d = presetDefaults[name];
    if (d && maxTurns) maxTurns.value = d.max_turns;
  }

  function currentPreset() {
    const picked = Array.from(presetRadios).find(r => r.checked && !r.disabled);
    return picked ? picked.value : '';
  }

  presetRadios.forEach(r => r.addEventListener('change', () => {
    const d = presetDefaults[r.value];
    if (d && maxTurns) maxTurns.value = d.max_turns;
  }));

  // --- sub-type help ------------------------------------------------------
  // The tooltip is pure CSS (:hover / :focus-visible on the "?"), so nothing
  // here shows or hides it. This exists only because the "?" sits inside the
  // card's <label>: without it a stray click on the help button would tick the
  // radio behind it, and reading about a sub-type must not select it.
  // Delegated from the grid so it survives a future re-render of the cards.
  if (presetGrid) {
    presetGrid.addEventListener('click', (ev) => {
      if (!ev.target.closest('.orch-preset-help')) return;
      ev.preventDefault();
      ev.stopPropagation();
    });
  }
  // One line in the sticky bar saying what the button will actually commit.
  // The form has nine sections and the launch is not idempotent, so "what am
  // I about to start" was worth answering on screen rather than by scrolling.
  const recap = document.getElementById('orch-recap');
  function updateRecap() {
    if (!recap) return;
    const t = convTypes[currentType()] || {};
    const seats = selectedSeats();
    const modOn = moderatorOn();
    const total = seats.length + (modOn && t.leadNeedsOwnSeat ? 1 : 0);
    const preset = currentPreset();
    // [bold, rest] pairs, built as nodes: the turn count is whatever was typed.
    const parts = [
      [t.label || currentType(), preset && preset !== currentType() ? ' · ' + preset : ''],
      [String(total), ' seat' + (total === 1 ? '' : 's') +
        (seats.length ? ' — ' + seats.join(', ')
                      + (modOn && t.leadNeedsOwnSeat ? ' + lead' : '') : '')],
      [maxTurns && maxTurns.value ? maxTurns.value : '?', ' turns each'],
    ];
    const extras = extraRolePayload();
    Object.keys(extras).forEach(cli => {
      parts.push([String(extras[cli]), ' ' + cli]);
    });
    recap.textContent = '';
    parts.forEach(([bold, rest], i) => {
      if (i) {
        const sep = document.createElement('span');
        sep.className = 'sep';
        sep.textContent = '/';
        recap.appendChild(sep);
      }
      const b = document.createElement('b');
      b.textContent = bold;
      recap.append(b, rest);
    });
    updateSkipWarn();
  }

  // Every persona change already routes through updateRecap(), so the warning
  // rides it rather than hooking each add/clear/remove path separately.
  // Looked up per call, not hoisted into a const: updateRecap() can run before
  // this line does, and a const read there is a TDZ ReferenceError.
  function updateSkipWarn() {
    const skipWarn = document.getElementById('orch-skip-warn');
    if (!skipWarn) return;
    const on = !!(skipToggle && skipToggle.checked) && Object.keys(customPersonas).length > 0;
    skipWarn.style.display = on ? '' : 'none';
  }
  if (skipToggle) skipToggle.addEventListener('change', updateSkipWarn);

  if (addSeatBtn) addSeatBtn.addEventListener('click', () => {
    addChair(null, null);
    seatsChanged();
  });
  if (modCli) modCli.addEventListener('change', seatsChanged);
  // Changing who speaks first changes who facilitates, which changes who is
  // eligible to be the skeptic.
  if (firstSelect) firstSelect.addEventListener('change', () => {
    updateExtraSeats();
    updateRecap();
  });
  typeRadios.forEach(r => r.addEventListener('change', () => {
    updateConvType();
    updateRecap();
  }));
  presetRadios.forEach(r => r.addEventListener('change', updateRecap));
  if (maxTurns) maxTurns.addEventListener('input', updateRecap);
  if (modEnable) modEnable.addEventListener('change', () => {
    updateModerator();
    renderSeatIds();
    updateRecap();
  });
  // Two chairs is every format's minimum, and the historical default pair when
  // this machine has both tools. ?persona=<slug> (the persona explorer's "Use in
  // a debate") seats that persona in the first chair.
  addChair('claude-code', new URLSearchParams(location.search).get('persona'));
  addChair('codex', null);
  // Default the host onto a tool no chair is using, when there is one. Sharing
  // a tool is fine now — the host just becomes 'claude-code-2' — but a default
  // that silently renumbers Guest 1 reads as a mistake rather than a choice.
  if (modCli) {
    const inUse = chairRows().map(r => r.querySelector('.seat-tool').value);
    const free = Array.from(modCli.options).map(o => o.value)
                      .find(v => inUse.indexOf(v) === -1);
    if (free) modCli.value = free;
  }
  updateFirstSpeaker();
  updateConvType();   // calls fitChairsToType() + updateExtraSeats()
  updateRecap();

  // "Cast all selected randomly" — set every visible persona select to random.
  if (castRandomBtn) {
    castRandomBtn.addEventListener('click', () => {
      chairRows().forEach(row => {
        const sel = row.querySelector('.seat-persona');
        if (sel && sel.value !== '__custom__') sel.value = '__random__';
      });
      updateRecap();
    });
  }

  // Topic is a <textarea> so a pasted brief keeps its shape while you edit it,
  // but it used to be an <input>, where Enter submitted. Keep that: Enter
  // submits, Shift+Enter takes a newline — the convention every chat box uses.
  // (Seeding collapses whitespace anyway, so a newline never reaches the DB.)
  const topicBox = form.querySelector('textarea[name=topic]');
  const topicCount = document.getElementById('orch-topic-count');
  if (topicBox) {
    topicBox.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' && !ev.shiftKey) {
        ev.preventDefault();
        form.requestSubmit();
      }
    });
    // The counter turns amber near the cap. `maxlength` already stops typing
    // past it, but a paste is silently truncated by the browser — the count
    // is the only sign that happened.
    const countTopic = () => {
      if (!topicCount) return;
      topicCount.textContent = topicBox.value.length;
      topicCount.parentElement.classList.toggle(
        'is-near', topicBox.value.length > DATA.topicMax * 0.8);
    };
    topicBox.addEventListener('input', countTopic);
    countTopic();
  }

  // Brief file picker. Read in the browser and dropped into the textarea, so
  // the operator can edit it before launching and the POST body stays the same
  // JSON `kickoff` string it always was — no upload route, nothing stored.
  const briefFile = document.getElementById('orch-brief-file');
  const briefBox = document.getElementById('orch-brief');
  const briefName = document.getElementById('orch-brief-file-name');
  if (briefFile && briefBox) {
    briefFile.addEventListener('change', () => {
      const file = briefFile.files && briefFile.files[0];
      if (!file) return;
      if (file.size > DATA.briefMax) {
        briefName.textContent = file.name + ' is ' + Math.round(file.size / 1024) +
          ' KB — the limit is ' + Math.round(DATA.briefMax / 1024) + ' KB.';
        briefName.classList.add('is-bad');
        briefFile.value = '';
        return;
      }
      const reader = new FileReader();
      reader.onerror = () => {
        briefName.textContent = 'Could not read ' + file.name + '.';
        briefName.classList.add('is-bad');
      };
      reader.onload = () => {
        briefBox.value = String(reader.result || '');
        // The panel is collapsed by default; a loaded file has to be visible,
        // or "Attach a file" looks like it did nothing.
        const panel = document.getElementById('orch-brief-details');
        if (panel) panel.open = true;
        briefName.classList.remove('is-bad');
        briefName.textContent = 'Loaded ' + file.name + ' (' +
          briefBox.value.length.toLocaleString() + ' characters) — edit below if you like.';
        briefBox.dispatchEvent(new Event('input'));
      };
      reader.readAsText(file);
    });
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    submitBtn.disabled = true;
    submitBtn.textContent = 'Running preflight…';
    // Set on the success path. `window.location.href` does not stop this
    // script or unload the page synchronously, so without this the `finally`
    // below re-enabled the button for the whole teardown-and-navigate window
    // — and a second click in that gap seeded a SECOND conversation and
    // spawned a second set of CLI windows. That is exactly what happened to
    // runs #55/#56 (seeded 219ms apart, four terminals). A launch is not
    // idempotent: the button stays dead once it has worked.
    let navigating = false;
    errorPanel.classList.add('hidden');
    errorPanel.innerHTML = '';

    const fd = new FormData(form);
    // Seat ids are derived from the chairs, so this is also where a chair list
    // that asks one tool for more seats than it can hold is caught.
    const room = roomSeats();
    if (room.overflow.length) {
      showError('Too many seats on one tool',
        room.overflow.map(t => t + ' can hold at most ' + MAX_SEATS_PER_CLI +
                               ' seats — move a chair to another tool.'));
      submitBtn.disabled = false;
      submitBtn.textContent = 'Run preflight + start conversation';
      return;
    }
    const participants = room.chairs;
    const personas = {};
    const personaCustom = {};
    const models = {};
    chairRows().forEach((row, i) => {
      const seat = participants[i];
      const model = (row.querySelector('.seat-model')?.value || '').trim();
      if (model) models[seat] = model;
      const sel = row.querySelector('.seat-persona');
      if (!sel) return;
      personas[seat] = sel.value;
      const chair = row.dataset.chair;
      if (sel.value === '__custom__' && customPersonas[chair]) {
        personaCustom[seat] = customPersonas[chair];
      }
    });
    const payload = {
      topic: (fd.get('topic') || '').trim(),
      conv_type: currentType(),
      participants: participants,
      preset: currentPreset() || null,
      max_turns: parseInt(fd.get('max_turns'), 10) || null,
      max_minutes: parseInt(fd.get('max_minutes'), 10) || null,
      first: fd.get('first') || null,
      kickoff: (fd.get('kickoff') || '').trim() || null,
      personas: personas,
      persona_custom: personaCustom,
      models: models,
      roles: extraRolePayload(),
      spawn: !!(spawnToggle && spawnToggle.checked),
      skip_permissions: !!(skipToggle && skipToggle.checked),
      // Absent (delivery off) or disabled (scope: all) both send false;
      // the server ignores it in the second case anyway.
      deliver_locally: !!(deliverToggle && !deliverToggle.disabled && deliverToggle.checked),
      publish: !!(publishToggle && publishToggle.checked),
      moderator: (moderatorOn() && room.host)
        ? { cli: room.host, persona: (modPersona ? modPersona.value : '__none__') }
        : null,
    };

    try {
      const res = await fetch('/api/orchestrate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.ok) {
        // If spawning couldn't happen (hosted / non-Windows / no pwsh), don't
        // silently redirect — the operator would wonder why no windows opened.
        const sp = data.spawn || {};
        if (sp.status === 'unavailable' || sp.status === 'error') {
          let note = '<h2>Conversation #' + data.conversation_id + ' seeded — but agents were not spawned</h2>';
          note += '<p>' + escapeHtml(sp.detail || 'spawn unavailable') + '</p>';
          if (sp.manual) note += '<p>Launch them yourself: <code>' + escapeHtml(sp.manual) + '</code></p>';
          note += '<p><a href="/conversations/' + data.conversation_id + '">Open the conversation &rarr;</a></p>';
          errorPanel.innerHTML = note;
          errorPanel.classList.remove('hidden');
          submitBtn.disabled = false;
          submitBtn.textContent = 'Run preflight + start conversation';
          return;
        }
        navigating = true;
        submitBtn.textContent = 'Opening conversation…';
        window.location.href = '/conversations/' + data.conversation_id;
        return;
      }
      let parts = ['<h2>Aborted — ' + escapeHtml(data.kind || 'error') + '</h2><ul>'];
      if (data.kind === 'preflight_failed' && Array.isArray(data.preflight)) {
        for (const r of data.preflight) {
          if (!r.ok) {
            for (const f of r.failures) {
              parts.push('<li><span class="code">' + escapeHtml(r.cli) + '/' + escapeHtml(f.code) + '</span>' + escapeHtml(f.detail) + '</li>');
            }
          }
        }
      } else {
        parts.push('<li>' + escapeHtml(data.error || 'Unknown error') + '</li>');
      }
      parts.push('</ul>');
      if (data.log_path) {
        parts.push('<p style="margin: 8px 0 0 0; font-size: 12px;">Full log: <code>' + escapeHtml(data.log_path) + '</code></p>');
      }
      errorPanel.innerHTML = parts.join('');
      errorPanel.classList.remove('hidden');
    } catch (err) {
      errorPanel.innerHTML = '<h2>Network error</h2><p>' + escapeHtml(String(err)) + '</p>';
      errorPanel.classList.remove('hidden');
    } finally {
      // Only when the run did NOT start — see `navigating` above.
      if (!navigating) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Run preflight + start conversation';
      }
    }
  });
})();
