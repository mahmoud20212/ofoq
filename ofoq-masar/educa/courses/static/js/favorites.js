(() => {
  const page = document.querySelector('[data-favorites-page]');
  function updateCount() {
    if (!page) return;
    const count = page.querySelectorAll('[data-favorite-card]:not([hidden])').length;
    page.querySelector('[data-favorite-count]').textContent = count;
    page.querySelector('[data-favorites-empty]').hidden = count !== 0;
  }
  async function save(form, action) {
    if (form.querySelector('button').disabled) return;
    const related = [...document.querySelectorAll('[data-favorite-form]')].filter(f => f.dataset.courseId === form.dataset.courseId);
    related.forEach(f => f.querySelector('button').disabled = true);
    try {
      const data = new FormData(form); data.set('action', action);
      const response = await fetch(form.getAttribute('action'), {method: 'POST', body: data, headers: {'X-Requested-With': 'XMLHttpRequest'}, credentials: 'same-origin'});
      const result = await response.json().catch(() => { throw new Error('تعذر تحديث المفضلة. حاول مرة أخرى.'); });
      if (result.login_url) { window.location.assign(result.login_url); return; }
      if (!response.ok) throw new Error(result.error || 'تعذر تحديث المفضلة. حاول مرة أخرى.');
      related.forEach(f => {
        f.elements.action.value = result.saved ? 'remove' : 'add';
        const button = f.querySelector('button');
        button.setAttribute('aria-pressed', String(result.saved));
        button.setAttribute('aria-label', `${result.saved ? 'إزالة من المفضلة' : 'إضافة إلى المفضلة'}: ${button.dataset.courseTitle}`);
        const card = f.closest('[data-favorite-card]'); if (card) card.hidden = !result.saved;
      });
      updateCount();
      let alert;
      const undoAction = page && !result.saved ? {label: 'تراجع', run: async () => { await save(form, 'add'); alert.dismiss(); }} : null;
      alert = window.appAlerts.show(result.saved ? 'تمت إضافة الدورة إلى المفضلة.' : 'تمت إزالة الدورة من المفضلة.', 'success', undoAction);
      if (undoAction) alert.actionButton.focus();
      else if (page) { form.querySelector('button').disabled = false; form.querySelector('button').focus(); }
    } catch (error) { window.appAlerts.show(error.message || 'تعذر تحديث المفضلة. حاول مرة أخرى.', 'error'); }
    finally { related.forEach(f => f.querySelector('button').disabled = false); }
  }
  document.addEventListener('submit', event => {
    const form = event.target.closest('[data-favorite-form]'); if (!form) return;
    event.preventDefault(); save(form, form.elements.action.value);
  });
})();
