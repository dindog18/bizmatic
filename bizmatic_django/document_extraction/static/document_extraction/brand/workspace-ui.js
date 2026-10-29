/* Shared presentation enhancements. Record actions remain owned by each workspace. */
(() => {
  'use strict';
  const themeButton = document.querySelector('[data-theme-toggle]');
  function updateThemeButton() {
    const dark = document.documentElement.dataset.bsTheme === 'dark';
    themeButton?.setAttribute('aria-pressed', String(dark));
    themeButton?.setAttribute('aria-label', `Switch to ${dark ? 'light' : 'dark'} theme`);
    if (themeButton) themeButton.title = `Switch to ${dark ? 'light' : 'dark'} theme`;
  }
  themeButton?.addEventListener('click', () => {
    const theme = document.documentElement.dataset.bsTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.bsTheme = theme;
    try { localStorage.setItem('bizmatic.theme', theme); } catch (_) { /* Optional preference. */ }
    updateThemeButton();
  });
  updateThemeButton();

  // Bootstrap owns opening/closing; restore focus after Escape and close on navigation.
  const menu = document.getElementById('navbarVerticalCollapse');
  const menuButton = document.querySelector('[aria-controls="navbarVerticalCollapse"]');
  function closeMenu() {
    if (menu?.classList.contains('show')) bootstrap.Collapse.getOrCreateInstance(menu, {toggle: false}).hide();
  }
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu?.classList.contains('show') && window.innerWidth < 1200) {
      closeMenu(); menuButton?.focus();
    }
  });
  menu?.addEventListener('click', event => {
    if (event.target.closest('a') && window.innerWidth < 1200) closeMenu();
  });
  document.addEventListener('click', event => {
    if (window.innerWidth < 1200 && !event.target.closest('.navbar-vertical, [aria-controls="navbarVerticalCollapse"]')) closeMenu();
  });

  // Keep real table semantics and source order. Only simple record registers stack on mobile;
  // line-item, schema and reconciliation comparisons retain keyboard-scrollable tables.
  function enhanceTables() {
    document.querySelectorAll('#page-content .table-responsive').forEach(region => {
      const table = region.querySelector('table');
      if (!table) return;
      region.tabIndex = 0;
      region.setAttribute('role', 'region');
      region.setAttribute('aria-label', table.caption?.textContent.trim() || 'Data table; scroll horizontally for more columns');
    });
    document.querySelectorAll('#register-table table, .document-table, [data-record-table]').forEach(table => {
      if (table.dataset.mobileReady) return;
      table.dataset.mobileReady = 'true';
      table.classList.add('biz-record-table');
      table.setAttribute('role', 'table');
      const headers = Array.from(table.querySelectorAll('thead th'));
      table.querySelectorAll('thead, tbody').forEach(group => group.setAttribute('role', 'rowgroup'));
      table.querySelectorAll('tr').forEach(row => row.setAttribute('role', 'row'));
      headers.forEach(header => header.setAttribute('role', 'columnheader'));
      table.querySelectorAll('tbody tr').forEach(row => {
        Array.from(row.cells).forEach((cell, index) => {
          cell.dataset.label = headers[index]?.textContent.trim() || 'Actions';
          cell.setAttribute('role', 'cell');
          if (cell.colSpan > 1) cell.classList.add('biz-table-empty');
        });
      });
    });
  }
  let scheduled = false;
  const observer = new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => { scheduled = false; enhanceTables(); });
  });
  const content = document.getElementById('page-content');
  if (content) observer.observe(content, {childList: true, subtree: true});
  enhanceTables();
})();
