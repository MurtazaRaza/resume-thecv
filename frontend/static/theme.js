(function () {
  const STORAGE_KEY = 'cv-theme';

  function systemPrefersDark() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function resolveTheme(stored) {
    if (stored === 'light' || stored === 'dark') return stored;
    return systemPrefersDark() ? 'dark' : 'light';
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const toggle = document.getElementById('theme-toggle');
    if (toggle) {
      const isDark = theme === 'dark';
      toggle.setAttribute('aria-pressed', String(isDark));
      toggle.setAttribute('aria-label', isDark ? 'Switch to light mode' : 'Switch to dark mode');
      toggle.title = isDark ? 'Light mode' : 'Dark mode';
    }
  }

  function getStored() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  }

  function setStored(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* ignore quota / private mode */
    }
  }

  window.__cvTheme = {
    get() {
      return resolveTheme(getStored());
    },
    set(theme) {
      if (theme !== 'light' && theme !== 'dark') return;
      setStored(theme);
      applyTheme(theme);
    },
    toggle() {
      const next = resolveTheme(getStored()) === 'dark' ? 'light' : 'dark';
      setStored(next);
      applyTheme(next);
    },
  };

  applyTheme(resolveTheme(getStored()));

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    const stored = getStored();
    if (stored !== 'light' && stored !== 'dark') {
      applyTheme(resolveTheme(stored));
    }
  });

  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(resolveTheme(getStored()));
    const toggle = document.getElementById('theme-toggle');
    if (toggle) {
      toggle.addEventListener('click', () => window.__cvTheme.toggle());
    }
  });
})();
