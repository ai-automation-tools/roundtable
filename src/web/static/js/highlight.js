// highlight.js, fetched (integrity-checked) the first time a code block is on
// the page — not in <head>, where it blocked first paint (audit RT-41).
// The CDN script carries this page's CSP nonce, read off our own tag, so the
// policy needn't allowlist all of cdnjs.
window.__hl = (function () {
  var base = 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.10.0/', wait = null;
  var nonce = document.currentScript ? document.currentScript.nonce : '';
  function tag(name, attrs) {
    var el = document.createElement(name);
    for (var k in attrs) el[k] = attrs[k];
    el.crossOrigin = 'anonymous';
    document.head.appendChild(el);
    return el;
  }
  function load() {
    if (!wait) {
      tag('link', { rel: 'stylesheet', href: base + 'styles/github-dark.min.css',
                    integrity: 'sha512-rO+olRTkcf304DQBxSWxln8JXCzTHlKnIdnMUwYvQa9/Jd4cQaNkItIUj6Z4nvW1dqK0SKXLbn9h4KwZTNtAyw==' });
      wait = new Promise(function (ok, fail) {
        var s = tag('script', { src: base + 'highlight.min.js', integrity: 'sha512-6yoqbrcLAHDWAdQmiRlHG4+m0g/CT/V9AGyxabG8j7Jk8j3r3K6due7oqpiRMZqcYe9WM2gPcaNNxnl2ux+3tA==',
                                nonce: nonce });
        s.onload = ok; s.onerror = fail;
      });
    }
    return wait;
  }
  return function (root) {
    var codes = (root || document).querySelectorAll('pre code');
    if (!codes.length) return;
    load().then(function () {
      codes.forEach(function (el) { window.hljs.highlightElement(el); });
    }).catch(function () {});  // no CDN: code stays plain, still readable
  };
})();
