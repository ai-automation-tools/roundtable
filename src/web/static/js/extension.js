// /extension: ask this instance's bridge whether the extension can reach it.
(function () {
  var box = document.getElementById('xt-bridge');
  var txt = document.getElementById('xt-bridge-txt');
  if (!box || !txt) return;
  fetch('/api/battleground/healthz').then(function (r) { return r.json(); }).then(function (d) {
    if (d && d.ok && d.token_configured) {
      box.className = 'xt-bridge up';
      txt.textContent = 'Bridge is up on this instance. The extension can create arenas here once its id is in AGENT_CHAT_EXTENSION_IDS and the panel\u2019s Settings carry the bridge token.';
    } else if (d && d.ok) {
      box.className = 'xt-bridge down';
      txt.textContent = 'Bridge is up, but no bridge token is set, so it refuses the extension. Add AGENT_CHAT_BATTLEGROUND_TOKEN to the repo\u2019s .env.';
    } else {
      box.className = 'xt-bridge down';
      txt.textContent = 'Bridge is not answering: ' + ((d && d.error) || 'unknown error')
        + '. The extension will not be able to open an arena until this server can read its database.';
    }
  }).catch(function (e) {
    box.className = 'xt-bridge down';
    txt.textContent = 'Bridge check failed: ' + e;
  });
})();
