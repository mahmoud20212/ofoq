(() => {
  const iconSprite = document.documentElement.dataset.iconSprite ||
    new URL('../vendor/lucide/masar-icons.svg', document.currentScript.src).href;
  function initialize(alert) {
    const persistent = alert.dataset.alertLevel === 'error' || alert.dataset.alertLevel === 'warning';
    let remaining = alert.querySelector('a, [data-alert-action]') ? 10000 : 6000;
    let timer = null, started = 0, hovered = false, closing = false;
    const pause = () => {
      if (timer !== null) { clearTimeout(timer); timer = null; remaining -= performance.now() - started; }
    };
    const visibility = () => document.hidden ? pause() : resume();
    const dismiss = () => {
      if (closing) return;
      closing = true; pause();
      document.removeEventListener('visibilitychange', visibility);
      alert.classList.add('is-leaving');
      setTimeout(() => {
        const stack = alert.parentElement;
        alert.remove();
        if (stack && !stack.querySelector('.app-alert')) stack.remove();
      }, window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 160);
    };
    const resume = () => {
      if (persistent || closing || timer !== null || hovered || document.hidden || alert.contains(document.activeElement)) return;
      started = performance.now(); timer = setTimeout(dismiss, Math.max(0, remaining));
    };
    alert.querySelector('[data-alert-close]')?.addEventListener('click', dismiss);
    alert.addEventListener('mouseenter', () => { hovered = true; pause(); });
    alert.addEventListener('mouseleave', () => { hovered = false; resume(); });
    alert.addEventListener('focusin', pause);
    alert.addEventListener('focusout', () => setTimeout(resume, 0));
    document.addEventListener('visibilitychange', visibility);
    resume();
  }
  window.appAlerts = {
    show(message, level = 'success', action = null) {
      let stack = document.querySelector('.app-alert-stack');
      if (!stack) { stack = document.createElement('div'); stack.className = 'app-alert-stack'; stack.setAttribute('aria-label', 'التنبيهات'); document.body.append(stack); }
      const alert = document.createElement('div'); alert.className = `app-alert app-alert--${level}`; alert.dataset.alertLevel = level;
      alert.setAttribute('role', level === 'error' ? 'alert' : 'status'); alert.setAttribute('aria-atomic', 'true');
      const symbol = document.createElement('span'); symbol.className = 'app-alert-symbol'; symbol.setAttribute('aria-hidden', 'true');
      const icon = level === 'error' ? 'circle-xmark' : level === 'warning' ? 'triangle-exclamation' : level === 'info' ? 'circle-info' : 'circle-check';
      symbol.innerHTML = `<svg class="icon lucide-icon" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><use href="${iconSprite}#${icon}" width="24" height="24"/></svg>`;
      const content = document.createElement('div'); const text = document.createElement('p'); text.textContent = message; content.append(text);
      let actionButton;
      if (action) { actionButton = document.createElement('button'); actionButton.type = 'button'; actionButton.dataset.alertAction = ''; actionButton.textContent = action.label; actionButton.addEventListener('click', async () => { actionButton.disabled = true; try { await action.run(); } finally { actionButton.disabled = false; } }); content.append(actionButton); }
      const close = document.createElement('button'); close.type = 'button'; close.dataset.alertClose = ''; close.setAttribute('aria-label', 'إغلاق التنبيه'); close.innerHTML = `<svg class="icon lucide-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><use href="${iconSprite}#xmark" width="24" height="24"/></svg>`;
      alert.append(symbol, content, close); stack.append(alert); initialize(alert);
      return { actionButton, dismiss: () => close.click() };
    }
  };
  document.querySelectorAll('.app-alert').forEach(initialize);
})();
