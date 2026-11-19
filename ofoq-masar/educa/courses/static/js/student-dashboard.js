(() => {
  const iconSprite = document.documentElement.dataset.iconSprite ||
    new URL('../vendor/lucide/masar-icons.svg', document.currentScript.src).href;
  const button = document.querySelector('.student-app .theme-toggle');
  if (!button) return;
  const apply = light => {
    document.documentElement.dataset.theme = light ? 'light' : 'dark';
    button.setAttribute('aria-pressed', String(light));
    button.setAttribute('aria-label', light ? 'تفعيل الوضع الداكن' : 'تفعيل الوضع الفاتح');
    button.innerHTML = light ? `<svg class="icon lucide-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><use href="${iconSprite}#moon" width="24" height="24"/></svg>` : `<svg class="icon lucide-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><use href="${iconSprite}#sun" width="24" height="24"/></svg>`;
    document.querySelector('meta[name="theme-color"]').content = light ? '#f4f5fb' : '#080a12';
  };
  let saved;
  try { saved = localStorage.getItem('ofoq-masar-theme'); } catch (_) {}
  apply(saved ? saved === 'light' : matchMedia('(prefers-color-scheme: light)').matches);
  button.addEventListener('click', () => {
    const light = document.documentElement.dataset.theme !== 'light';
    apply(light);
    try { localStorage.setItem('ofoq-masar-theme', light ? 'light' : 'dark'); } catch (_) {}
  });
  const account = document.querySelector('.account-menu');
  if (account) {
    document.addEventListener('click', event => { if (!account.contains(event.target)) account.open = false; });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && account.open) { account.open = false; account.querySelector('summary').focus(); }
    });
  }
})();
(() => {
  const navigation = document.querySelector('.student-navigation');
  if (navigation) {
    const mobile = window.matchMedia('(max-width: 800px)');
    let animation = null;
    let targetOpen = navigation.open;
    const summary = navigation.querySelector('summary');
    const syncNavigation = () => {
      animation?.cancel(); animation = null;
      navigation.style.overflow = '';
      navigation.open = !mobile.matches;
      targetOpen = navigation.open;
    };
    summary.addEventListener('click', event => {
      if (!mobile.matches) return;
      event.preventDefault();
      targetOpen = !targetOpen;
      const from = navigation.getBoundingClientRect().height;
      animation?.cancel();
      if (matchMedia('(prefers-reduced-motion: reduce)').matches || !navigation.animate) {
        navigation.open = targetOpen; navigation.style.overflow = ''; return;
      }
      navigation.open = true;
      const to = targetOpen ? navigation.scrollHeight : summary.getBoundingClientRect().height;
      navigation.style.overflow = 'hidden';
      animation = navigation.animate([{height: `${from}px`}, {height: `${to}px`}], {duration: 260, easing: 'cubic-bezier(.2,.7,.2,1)'});
      animation.onfinish = () => {
        navigation.open = targetOpen;
        navigation.style.overflow = '';
        animation = null;
      };
    });
    syncNavigation();
    mobile.addEventListener('change', syncNavigation);
  }
  const dialog = document.querySelector('.student-review-dialog');
  const trigger = document.querySelector('[data-review-open]');
  if (!dialog || !trigger) return;
  trigger.addEventListener('click', () => dialog.showModal());
  dialog.querySelector('[data-review-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  dialog.addEventListener('close', () => trigger.focus());
})();

// Preserve old links to the former units section.
(() => {
  const menus = [...document.querySelectorAll('[data-course-actions]')];
  document.addEventListener('click', event => {
    menus.forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    menus.forEach(menu => { if (menu.open) { menu.open = false; menu.querySelector('summary').focus(); } });
  });
})();

(() => {
  const target = document.querySelector('[data-course-units-url]');
  if (target && window.location.hash === '#course-modules') window.location.replace(target.dataset.courseUnitsUrl);
})();

(() => {
  const button = document.querySelector('.student-sidebar-toggle');
  const sidebar = document.getElementById('student-sidebar');
  if (!button || !sidebar) return;
  sidebar.querySelectorAll('.student-navigation nav a').forEach(link => {
    const label = link.textContent.trim();
    link.title = label;
    link.setAttribute('aria-label', label);
    [...link.childNodes].filter(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim()).forEach(node => {
      const text = document.createElement('span');
      text.className = 'student-nav-label';
      node.replaceWith(text);
      text.append(node);
    });
  });
  const desktop = matchMedia('(min-width: 801px)');
  let collapsed = false;
  const account = sidebar.querySelector('.student-sidebar-account');
  const panel = account?.querySelector('.account-menu-panel');
  let accountFrame = 0;
  const positionAccount = () => {
    const popover = desktop.matches && collapsed && account?.open;
    panel?.classList.toggle('student-rail-account-popover', !!popover);
    if (!popover || !panel) return;
    const anchor = account.querySelector('summary').getBoundingClientRect();
    const edge = sidebar.getBoundingClientRect();
    const bounds = panel.getBoundingClientRect();
    const width = bounds.width;
    const rtl = getComputedStyle(sidebar).direction === 'rtl';
    const left = Math.max(12, Math.min(innerWidth - width - 12, rtl ? edge.left - width - 12 : edge.right + 12));
    const top = Math.max(12, Math.min(anchor.bottom - bounds.height, innerHeight - bounds.height - 12));
    const setPosition = (key, value) => {
      const pixels = `${Math.round(value)}px`;
      if (panel.style.getPropertyValue(key) !== pixels) panel.style.setProperty(key, pixels);
    };
    setPosition('--account-popover-left', left);
    setPosition('--account-popover-top', top);
  };
  const scheduleAccountPosition = () => {
    if (accountFrame || !desktop.matches || !collapsed || !account?.open) return;
    accountFrame = requestAnimationFrame(() => { accountFrame = 0; positionAccount(); });
  };
  account?.querySelector('summary').addEventListener('click', event => {
    if (!desktop.matches) return;
    event.preventDefault();
    // Position in the same task as opening, before the browser paints the menu.
    account.open = !account.open;
    positionAccount();
  });
  account?.addEventListener('toggle', positionAccount);
  window.addEventListener('resize', scheduleAccountPosition);
  window.addEventListener('scroll', event => {
    if (panel?.contains(event.target)) return;
    scheduleAccountPosition();
  }, {capture: true, passive: true});
  const learningMode = document.body.classList.contains('student-learning-mode');
  if (learningMode) collapsed = true;
  else try { collapsed = localStorage.getItem('ofoq-masar-sidebar-collapsed') === 'true'; } catch (_) {}
  const apply = () => {
    const hide = desktop.matches && collapsed;
    sidebar.hidden = false;
    document.body.classList.toggle('is-sidebar-collapsed', hide);
    button.hidden = !desktop.matches;
    button.setAttribute('aria-expanded', String(!hide));
    const label = hide ? 'توسيع القائمة الجانبية' : 'طي القائمة الجانبية';
    button.setAttribute('aria-label', label);
    button.title = label;
    positionAccount();
  };
  button.addEventListener('click', () => {
    sidebar.querySelectorAll('.account-menu[open]').forEach(menu => menu.open = false);
    collapsed = !collapsed;
    apply();
    if (!learningMode) try { localStorage.setItem('ofoq-masar-sidebar-collapsed', String(collapsed)); } catch (_) {}
  });
  desktop.addEventListener('change', apply);
  apply();
})();

(() => {
  const name = document.querySelector('.student-account-name');
  const text = name?.querySelector('.student-account-name-text');
  if (!text) return;
  const measure = () => {
    const overflow = Math.max(0, text.offsetWidth - name.clientWidth);
    name.classList.toggle('is-overflowing', overflow > 1);
    const direction = getComputedStyle(name).direction === 'rtl' ? 1 : -1;
    name.style.setProperty('--name-scroll-distance', `${direction * overflow}px`);
    name.style.setProperty('--name-scroll-duration', `${Math.max(1.5, overflow / 60 + 0.6)}s`);
  };
  new ResizeObserver(measure).observe(name);
  if (document.fonts) document.fonts.ready.then(measure);
  measure();
})();
