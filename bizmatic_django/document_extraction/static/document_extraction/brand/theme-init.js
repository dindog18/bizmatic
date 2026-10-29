/* Apply the local display preference before paint. No account or server setting changes. */
(() => {
  'use strict';
  try {
    const theme = localStorage.getItem('bizmatic.theme');
    if (theme === 'dark' || theme === 'light') document.documentElement.dataset.bsTheme = theme;
  } catch (_) { /* Storage can be unavailable; the default light theme still works. */ }
})();
