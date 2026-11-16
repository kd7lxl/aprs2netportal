/*
 * Follow the browser's light/dark preference with Bootstrap's colour modes.
 * Loaded from <head> without defer, so that the theme is set before the
 * first paint.
 */
(function () {
  'use strict';

  var query = window.matchMedia('(prefers-color-scheme: dark)');

  function apply() {
    document.documentElement.setAttribute(
      'data-bs-theme', query.matches ? 'dark' : 'light');
  }

  apply();
  if (query.addEventListener) {
    query.addEventListener('change', apply);
  }
})();
