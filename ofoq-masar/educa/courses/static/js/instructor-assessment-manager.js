(() => {
  const dialog = document.querySelector('[data-assessment-manager-dialog]');
  if (!dialog || typeof dialog.showModal !== 'function' || !window.fetch) return;
  const body = dialog.querySelector('[data-assessment-manager-body]');
  const errorBox = dialog.querySelector('[data-manager-error]');
  const status = dialog.querySelector('[data-manager-status]');
  const closeButton = dialog.querySelector('[data-assessment-manager-close]');
  let opener = null, boundary = '', busy = false, posting = false, changed = false, controller = null;
  const error = message => { errorBox.textContent = message; errorBox.hidden = false; status.textContent = message; };
  const checkedURL = value => {
    const url = new URL(value, window.location.href);
    if (url.origin !== window.location.origin || !url.pathname.startsWith(boundary)) throw new Error('تعذّر التحقق من رابط إدارة الأسئلة');
    return url;
  };
  const readPage = async (value, options = {}) => {
    const url = checkedURL(value);
    const response = await fetch(url.href, {credentials:'same-origin', redirect:'error', signal:controller.signal,
      ...options, headers:{'X-Assessment-Workspace':'1'}});
    if (!response.ok) throw new Error('تعذّر تنفيذ الإجراء، تحقّق من الجلسة وصلاحية تعديل النسخة');
    if (response.headers.get('Content-Type')?.includes('application/json')) {
      const result = await response.json();
      if (!result.workspace_url) throw new Error('تعذّر التحقق من نتيجة الحفظ');
      changed = true;
      const destination = new URL(result.workspace_url, window.location.href);
      if (destination.origin === window.location.origin && destination.pathname === window.location.pathname) {
        dialog.close(); return null;
      }
      const page = await readPage(destination.href);
      status.textContent = 'تم حفظ التغيير';
      return page;
    }
    return response.text();
  };
  const load = async (url, options = {}) => {
    if (busy) return;
    if (window.MasarCurriculum?.isBusy()) { error('انتظر انتهاء حفظ ترتيب الأسئلة'); return; }
    busy = true; posting = options.method === 'POST'; errorBox.hidden = true;
    body.setAttribute('aria-busy','true'); body.inert = true;
    closeButton.disabled = posting;
    status.textContent = posting ? 'جارٍ الحفظ' : 'جارٍ تحميل الأسئلة';
    controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const html = await readPage(url, options);
      if (html !== null && dialog.open) {
        window.dispatchEvent(new Event('masar:curriculum-before-update'));
        body.innerHTML = html;
        window.dispatchEvent(new Event('masar:curriculum-updated'));
        const pageTitle = body.querySelector('[data-manager-page-title]');
        if (pageTitle) dialog.querySelector('#assessment-manager-title').textContent = pageTitle.textContent;
        body.scrollTop = 0;
        // Preview is a separate read-only surface; it does not replace this workspace.
        body.querySelectorAll('a[href*="/preview/"]').forEach(link => {link.target='_blank'; link.rel='noopener';});
        body.querySelectorAll('dialog[data-question-confirm]').forEach(confirmation => confirmation.addEventListener('close', () => {
          const row = confirmation.closest('.assessment-question-row');
          const handle = row?.querySelector('[data-drag-handle]');
          if (handle) handle.disabled = false;
          row?.querySelector('[data-course-action="delete"]')?.focus();
        }));
        window.initializeMasarAssessmentOptions?.(body);
        const focus = body.querySelector('input:not([type=hidden]),textarea,select,h3');
        if (focus?.tagName === 'H3') focus.tabIndex = -1;
        focus?.focus({preventScroll:true});
        if (!posting) status.textContent = 'تم تحميل الأسئلة';
      }
    } catch (failure) {
      if (posting) changed = true;
      if (dialog.open) error(posting ? 'لم يصل تأكيد الحفظ. بقيت مدخلاتك هنا؛ تحقّق من قائمة الأسئلة قبل إعادة الحفظ' : 'تعذّر تحميل الأسئلة، أعد المحاولة أو سجّل الدخول مجددًا');
    } finally {
      clearTimeout(timer); busy = false; posting = false;
      body.inert = false; body.removeAttribute('aria-busy'); closeButton.disabled = false;
    }
  };
  document.addEventListener('click', event => {
    const trigger = event.target.closest('[data-assessment-manager]');
    if (!trigger || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (dialog.open || busy || window.MasarCurriculum?.isBusy()) return;
    opener = trigger; boundary = new URL(trigger.href).pathname;
    changed = false; body.replaceChildren(); dialog.showModal();
    document.body.classList.add('teacher-dialog-open'); load(trigger.href);
  });
  const closeConfirmation = confirmation => {
    confirmation.close();
    const row = confirmation.closest('.assessment-question-row');
    const handle = row?.querySelector('[data-drag-handle]');
    if (handle) handle.disabled = false;
    row?.querySelector('[data-course-action="delete"]')?.focus();
  };
  dialog.addEventListener('click', event => {
    if (event.target.closest('[data-assessment-manager-close]')) { if (!posting) dialog.close(); return; }
    const cancel = event.target.closest('[data-question-delete-cancel]');
    if (cancel) { event.preventDefault(); event.stopPropagation(); if (!busy) closeConfirmation(cancel.closest('[data-question-confirm]')); return; }
    const link = event.target.closest('a');
    if (!link || !body.contains(link) || link.target === '_blank' || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); event.stopPropagation();
    try {
      const url = checkedURL(link.href);
      const confirmation = /\/questions\/\d+\/delete\/$/.test(url.pathname) ? link.closest('.assessment-question-row')?.querySelector('[data-question-confirm]') : null;
      if (confirmation) {
        if (busy || window.MasarCurriculum?.isBusy()) return;
        body.querySelectorAll('dialog[data-question-confirm][open]').forEach(closeConfirmation);
        confirmation.showModal();
        const handle = confirmation.closest('.assessment-question-row').querySelector('[data-drag-handle]');
        if (handle) handle.disabled = true;
        confirmation.querySelector('[data-question-delete-cancel]').focus();
        return;
      }
      load(url.href);
    } catch (failure) { error(failure.message); }
  }, true);
  dialog.addEventListener('submit', event => {
    const form = event.target;
    if (!body.contains(form)) return;
    event.preventDefault(); event.stopPropagation();
    if (busy) return;
    if (form.validateAssessment && event.submitter?.value !== 'add_option' && !form.validateAssessment()) return;
    const data = new FormData(form);
    if (event.submitter?.name) data.append(event.submitter.name,event.submitter.value);
    const confirmation = form.closest?.('dialog[data-question-confirm]');
    if (confirmation) closeConfirmation(confirmation);
    load(form.action,{method:'POST',body:data});
  }, true);
  closeButton.addEventListener('click', () => {if (!posting) dialog.close();});
  window.MasarAssessmentManager = {reload:() => load(boundary)};
  dialog.addEventListener('cancel', event => {
    if (posting) {event.preventDefault();return;}
    const confirmation = body.querySelector('dialog[data-question-confirm][open]');
    if (confirmation) {event.preventDefault();closeConfirmation(confirmation);}
  });
  dialog.addEventListener('close', () => {
    window.dispatchEvent(new Event('masar:curriculum-before-update'));
    controller?.abort(); document.body.classList.remove('teacher-dialog-open');
    body.replaceChildren(); opener?.focus();
    if (changed) window.MasarCurriculum?.refreshSaved(window.location.href,'تم تحديث أسئلة الاختبار');
  });
})();
