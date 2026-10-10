/* Shared navigation and account-wide appearance preferences. */
(() => {
  const preferenceKey = 'ai-second-brain-preferences';
  const allowedStyles = ['aurora', 'midnight', 'ocean'];
  const allowedSizes = ['small', 'medium', 'large'];

  window.applyUserPreferences = (preferences, cache = false) => {
    if (!document.body || !preferences) return;
    const normalized = {
      theme: preferences.theme === 'light' ? 'light' : 'dark',
      theme_style: allowedStyles.includes(preferences.theme_style) ? preferences.theme_style : 'aurora',
      font_size: allowedSizes.includes(preferences.font_size) ? preferences.font_size : 'medium',
      notifications: !(preferences.notifications === false || preferences.notifications === 0 || preferences.notifications === '0')
    };
    document.body.classList.remove(
      'theme-light', 'theme-dark',
      'theme-style-aurora', 'theme-style-midnight', 'theme-style-ocean',
      'font-size-small', 'font-size-medium', 'font-size-large'
    );
    document.body.classList.add(
      `theme-${normalized.theme}`,
      `theme-style-${normalized.theme_style}`,
      `font-size-${normalized.font_size}`
    );
    document.body.dataset.remindersEnabled = normalized.notifications ? '1' : '0';
    window.appUserPreferences = normalized;
    if (cache) {
      try { localStorage.setItem(preferenceKey, JSON.stringify(normalized)); } catch (_) {}
    }
    window.dispatchEvent(new CustomEvent('ai-second-brain-preferences-changed', { detail: normalized }));
  };

  try {
    const cached = JSON.parse(localStorage.getItem(preferenceKey) || 'null');
    if (cached) window.applyUserPreferences(cached, false);
  } catch (_) {}

  window.addEventListener('storage', (event) => {
    if (event.key !== preferenceKey || !event.newValue) return;
    try { window.applyUserPreferences(JSON.parse(event.newValue), false); } catch (_) {}
  });

  document.addEventListener('DOMContentLoaded', () => {
    fetch('/api/settings', { headers: { 'Accept': 'application/json' }, cache: 'no-store' })
      .then((response) => response.ok ? response.json() : null)
      .then((preferences) => { if (preferences && preferences.success) window.applyUserPreferences(preferences, true); })
      .catch(() => {});

    if (document.querySelector('.sidebar') || document.querySelector('.app-sidebar')) return;
    const current = window.location.pathname;
    const items = [
      ['/dashboard', 'fa-house', 'Dashboard'], ['/notes', 'fa-note-sticky', 'Notes'], ['/create-note', 'fa-pen-to-square', 'Create Note'],
      ['/pdf-library', 'fa-file-pdf', 'PDF Library'], ['/image-library', 'fa-image', 'Image Library'],
      ['/ai-chat', 'fa-robot', 'AI Chat'], ['/voice-assistant', 'fa-volume-high', 'AI Assistant'],
      ['/reminders', 'fa-bell', 'Reminders'], ['/settings', 'fa-gear', 'Settings'], ['/profile', 'fa-user', 'Profile']
    ];
    const sidebar = document.createElement('aside');
    sidebar.className = 'app-sidebar';
    sidebar.innerHTML = `<a class="app-brand" href="/dashboard"><img class="app-brand-logo" src="/static/images/app-logo-mark.png?v=20261010-pwa-1" alt=""><div>AI SECOND BRAIN<small>Personal knowledge hub</small></div></a><nav>${items.map(([url, icon, label]) => `<a class="${current === url ? 'active' : ''}" href="${url}"><i class="fa-solid ${icon}"></i><span>${label}</span></a>`).join('')}</nav><div class="app-sidebar-footer"><i class="fa-solid fa-circle"></i> System ready</div>`;
    const chatHistoryTools = document.getElementById('aiChatSidebarTools');
    if (current === '/ai-chat' && chatHistoryTools) {
      chatHistoryTools.hidden = false;
      sidebar.insertBefore(chatHistoryTools, sidebar.querySelector('.app-sidebar-footer'));
    }
    document.body.prepend(sidebar);
    document.body.classList.add('app-shell-page');
  });
})();
