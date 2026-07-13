// admin/menu.js — admin menu (phase-2 U6 carve).

export const AdminMenu = (function () {
  const trigger = () => document.getElementById('admin-trigger');
  const menu = () => document.getElementById('admin-menu');

  function open() {
    menu().hidden = false;
    trigger().setAttribute('aria-expanded', 'true');
    document.addEventListener('click', onOutsideClick, true);
    document.addEventListener('keydown', onKeydown);
    // Focus first menu item for keyboard users.
    const first = menu().querySelector('.admin-menu-item');
    if (first) first.focus();
  }

  function close() {
    menu().hidden = true;
    trigger().setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', onOutsideClick, true);
    document.removeEventListener('keydown', onKeydown);
  }

  function toggle(_el) {
    if (menu().hidden) open(); else close();
  }

  function onOutsideClick(e) {
    if (!menu().contains(e.target) && !trigger().contains(e.target)) close();
  }

  function onKeydown(e) {
    if (e.key === 'Escape') { close(); trigger().focus(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const items = Array.from(menu().querySelectorAll('.admin-menu-item'));
      const i = items.indexOf(document.activeElement);
      const next = e.key === 'ArrowDown'
        ? items[(i + 1) % items.length]
        : items[(i - 1 + items.length) % items.length];
      next.focus();
    }
  }

  function select(panelId) {
    close();
    showPanel(panelId);
  }

  function showPanel(panelId) {
    // Hide every .tab-content (operational + admin).
    document.querySelectorAll('.tab-content').forEach(t => {
      t.classList.remove('active');
      t.style.display = '';
    });
    // De-active every .tab-btn.
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));

    const target = document.getElementById('tab-' + panelId);
    if (target) {
      target.classList.add('active');
      target.style.display = 'block';
    }
    trigger().classList.add('active');

    // Notify panels so they can lazy-load.
    window.dispatchEvent(new CustomEvent('adminPanelActivated', {detail: {panel: panelId}}));
  }

  // Reset Admin trigger active state when an operational tab is chosen.
  document.addEventListener('click', function (e) {
    if (e.target.classList.contains('tab-btn') && e.target.id !== 'admin-trigger') {
      trigger().classList.remove('active');
    }
  }, true);

  return { toggle, select, open, close, showPanel };
})();
