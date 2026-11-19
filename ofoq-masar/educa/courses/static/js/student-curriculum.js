(() => {
  const workspace = document.querySelector('[data-learning-workspace]');
  if (!workspace) return;
  const panel = document.getElementById('learning-curriculum');
  const dialog = document.querySelector('[data-curriculum-dialog]');
  const opener = document.querySelector('[data-open-curriculum]');
  if (!panel || !dialog || !opener || typeof dialog.showModal !== 'function') return;
  const marker = document.createComment('curriculum');
  panel.before(marker);
  const mobile = window.matchMedia('(max-width: 1100px)');
  const unitAnimations = new WeakMap();
  panel.querySelectorAll('.learning-unit').forEach(unit => {
    const summary = unit.querySelector?.('summary');
    const list = unit.querySelector?.('ul');
    if (!summary || !list) return;
    summary.addEventListener('click', event => {
      event.preventDefault();
      const previous = unitAnimations.get(unit);
      const targetOpen = !(previous ? previous.targetOpen : unit.open);
      const from = unit.open ? list.getBoundingClientRect().height : 0;
      const fromMargin = unit.open && typeof window.getComputedStyle === 'function' ? window.getComputedStyle(list).marginBottom : (unit.open ? '8px' : '0px');
      previous?.animation.cancel();
      unit.dataset.expanded = String(targetOpen);
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || typeof list.animate !== 'function') {
        unit.open = targetOpen;
        list.style.overflow = '';
        unitAnimations.delete(unit);
        return;
      }
      unit.open = true;
      const to = targetOpen ? list.scrollHeight : 0;
      list.style.overflow = 'hidden';
      const animation = list.animate([
        {height:`${from}px`,marginBottom:fromMargin},
        {height:`${to}px`,marginBottom:targetOpen ? '8px' : '0px'},
      ], {duration:targetOpen ? 200 : 160,easing:'cubic-bezier(.25,.65,.35,1)',fill:'both'});
      unitAnimations.set(unit, {animation,targetOpen});
      animation.onfinish = () => {
        if (unitAnimations.get(unit)?.animation !== animation) return;
        unit.open = targetOpen;
        animation.cancel();
        list.style.overflow = '';
        unitAnimations.delete(unit);
      };
    });
  });
  const revealCurrent = () => {
    const row = panel.querySelector('[data-current-content]');
    const scroll = panel.querySelector('[data-curriculum-scroll]');
    if (!row || !scroll) return;
    const unit = row.closest('details');
    if (unit) {
      unitAnimations.get(unit)?.animation.cancel();
      unitAnimations.delete(unit);
      unit.open = true;
      unit.dataset.expanded = 'true';
      const list = unit.querySelector('ul');
      if (list) list.style.overflow = '';
    }
    const item = row.getBoundingClientRect();
    const bounds = scroll.getBoundingClientRect();
    if (item.bottom > bounds.bottom) scroll.scrollTop += item.bottom - bounds.bottom + 12;
    if (item.top < bounds.top) scroll.scrollTop -= bounds.top - item.top + 12;
  };
  const layout = () => {
    if (dialog.open) dialog.close();
    if (mobile.matches) dialog.append(panel);
    else marker.after(panel);
    requestAnimationFrame(revealCurrent);
  };
  opener.addEventListener('click', () => {
    dialog.showModal();
    opener.setAttribute('aria-expanded', 'true');
    requestAnimationFrame(revealCurrent);
  });
  panel.querySelector('[data-curriculum-close]').addEventListener('click', () => dialog.close());
  panel.querySelectorAll('[data-curriculum-link]').forEach(link => link.addEventListener('click', () => { if (dialog.open) dialog.close(); }));
  dialog.addEventListener('close', () => {
    opener.setAttribute('aria-expanded', 'false');
    if (mobile.matches) opener.focus();
  });
  mobile.addEventListener('change', layout);
  const help = document.getElementById('learning-help-dialog');
  const helpTrigger = panel.querySelector('[data-open-help]');
  if (help && typeof help.showModal === 'function' && helpTrigger) {
    helpTrigger.addEventListener('click', event => { event.preventDefault(); help.showModal(); });
    help.querySelector('[data-close-help]').addEventListener('click', () => help.close());
    help.addEventListener('close', () => helpTrigger.focus());
    help.querySelector('[data-help-comments]')?.addEventListener('click', () => {
      help.close();
      if (dialog.open) dialog.close();
      requestAnimationFrame(() => {
        const comments = document.getElementById('lesson-comments-title');
        if (comments) { comments.tabIndex = -1; comments.focus(); }
      });
    });
  }
  document.body.classList.add('learning-ui-ready');
  layout();
})();
