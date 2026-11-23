// Runs in <head>, synchronously, before first paint: a plain <script src>
// (no defer), loaded after the font preload and before every stylesheet.
// Keep it tiny — every page waits on it.
(function () {
  var d = document, r = d.documentElement;

  // Theme. Default 'dark' must match initTheme() in shell.js, which treats
  // anything but `light` as dark.
  var t = 'dark';
  try { var s = localStorage.getItem('agent-chat.theme'); if (s === 'light' || s === 'dark') t = s; } catch (e) {}
  r.classList.remove('light', 'dark');
  r.classList.add(t);
  if (t === 'light') {
    var m = d.querySelector('meta[name="theme-color"]');
    if (m) m.setAttribute('content', '#fafafa');
  }

  // `js` gates the scroll-reveal styles: content a script hides must only be
  // hidden when a script is there to show it again (see shell.js).
  // `rail-collapsed` is restored here so the sidebar can't paint open and
  // then snap shut on DOMContentLoaded.
  r.classList.add('js');
  try { if (localStorage.getItem('ab-rail') === '0') r.classList.add('rail-collapsed'); } catch (_) {}

  // The web-font stylesheet must not block first paint (audit RT-41). The page
  // preloads it; inserting the stylesheet from script makes it non-blocking.
  // (Was an inline onload= handler, which a nonce CSP refuses.)
  var pre = d.querySelector('link[rel="preload"][as="style"][data-font-css]');
  if (pre) {
    var l = d.createElement('link');
    l.rel = 'stylesheet';
    l.href = pre.href;
    d.head.appendChild(l);
  }

  // Image fallbacks, declared in markup instead of inline onerror= handlers.
  // `error` doesn't bubble, so listen in the capture phase — attached here,
  // before <body> parses, so no image can fail before the listener exists.
  //   data-fallback="<url>"  swap to that url once (+ data-fallback-class on
  //                          the parent, e.g. the explorer's is-avatar)
  //   data-on-error="hide"   display:none
  //   data-on-error="remove" drop the element
  d.addEventListener('error', function (e) {
    var img = e.target;
    if (!img || img.tagName !== 'IMG') return;
    // Same-origin paths only, URI-encoded: a fallback can't become a
    // javascript: or off-site URL.
    var fb = img.getAttribute('data-fallback') || '';
    if (fb) {
      img.removeAttribute('data-fallback');
      if (/^\/(?![\/\\])/.test(fb)) img.src = encodeURI(fb);
      var pc = img.getAttribute('data-fallback-class');   // restyle the frame too
      if (pc && img.parentNode) img.parentNode.classList.add(pc);
      return;
    }
    var how = img.getAttribute('data-on-error');
    if (how === 'hide') img.style.display = 'none';
    else if (how === 'remove') img.remove();
  }, true);

  // <select data-autosubmit> submits its form on change (the explorer's
  // filters). Delegated, so it covers markup parsed after this runs.
  d.addEventListener('change', function (e) {
    var el = e.target;
    if (el && el.form && el.hasAttribute && el.hasAttribute('data-autosubmit')) el.form.submit();
  });
})();
