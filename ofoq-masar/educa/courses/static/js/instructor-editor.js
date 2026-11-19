(() => {
  const dialog = document.querySelector('[data-content-editor-dialog]');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const body = dialog.querySelector('[data-editor-body]');
  const title = dialog.querySelector('#teacher-editor-title');
  let opener = null, controller = null, saving = false;
  const showError = message => {
    let error = body.querySelector('[data-editor-error]');
    if (!error) { error = document.createElement('p'); error.className = 'teacher-editor-error'; error.setAttribute('role', 'alert'); body.prepend(error); }
    error.hidden = false;
    error.textContent = message;
  };
  document.addEventListener('click', async event => {
    const link = event.target.closest('[data-content-editor]');
    if (!link) return;
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (dialog.open) return;
    if (window.MasarCurriculum?.isBusy()) { window.appAlerts?.show('انتظر انتهاء حفظ التغيير الحالي', 'error'); return; }
    opener = link;
    title.textContent = link.dataset.editorTitle || 'إعداد المحتوى';
    body.replaceChildren();
    const loading = document.createElement('p');
    loading.className = 'teacher-editor-loading'; loading.textContent = 'جارٍ تحميل النموذج'; body.append(loading);
    controller = new AbortController();
    const requestController = controller;
    dialog.showModal(); document.body.classList.add('teacher-dialog-open');
    try {
      const response = await fetch(link.href, { credentials: 'same-origin', redirect: 'error', signal: requestController.signal, headers: { 'X-Editor-Dialog': '1' } });
      if (!response.ok) throw new Error('تعذّر فتح النموذج، تحقّق من الجلسة وصلاحية تعديل النسخة');
      const html = await response.text();
      if (!dialog.open || controller !== requestController) return;
      body.innerHTML = html;
      const form = body.querySelector('[data-content-editor-form]');
      if (!form) { body.replaceChildren(); throw new Error('تعذّر تحميل النموذج، حدّث الصفحة ثم أعد المحاولة'); }
      window.initializeMasarTeacherFields?.(body);
      form.querySelector('input:not([type=hidden]):not([type=file]),select,textarea')?.focus();
    } catch (error) {
      if (error.name !== 'AbortError' && dialog.open && controller === requestController) { body.replaceChildren(); showError(error instanceof TypeError ? 'تعذّر الاتصال، أغلق النافذة وأعد المحاولة' : error.message); }
    }
  });
  dialog.addEventListener('click', event => {
    if (event.target.closest('[data-editor-close]') && !saving) dialog.close();
  });
  dialog.addEventListener('cancel', event => { if (saving) event.preventDefault(); });
  dialog.addEventListener('close', () => {
    controller?.abort(); controller = null;
    body.querySelector('form')?.reset();
    body.replaceChildren(); document.body.classList.remove('teacher-dialog-open');
    if (opener?.isConnected) opener.focus();
  });
  dialog.addEventListener('submit', async event => {
    const form = event.target.closest('[data-content-editor-form]');
    if (!form) return;
    event.preventDefault(); if (saving) return;
    saving = true;
    const data = new FormData(form);
    const buttons = dialog.querySelectorAll('button');
    buttons.forEach(button => { button.disabled = true; });
    form.setAttribute('aria-busy', 'true');
    form.querySelectorAll('[data-editor-field-error]').forEach(error => error.remove());
    form.querySelectorAll('[aria-invalid]').forEach(field => field.removeAttribute('aria-invalid'));
    const alert = form.querySelector('[data-editor-error]');
    alert.hidden = true;
    try {
      const response = await fetch(form.action, { method: 'POST', credentials: 'same-origin', redirect: 'error', headers: { 'X-Editor-Dialog': '1', 'Accept': 'application/json' }, body: data });
      const result = await response.json().catch(() => null);
      if (response.status === 422 && result?.errors) {
        showError('راجع الحقول الموضّحة أدناه');
        for (const [name, errors] of Object.entries(result.errors)) {
          const field = form.elements.namedItem(name);
          if (!field?.closest) { alert.textContent += ' — ' + errors.map(error => error.message).join('، '); continue; }
          const wrapper = field.closest('.teacher-field');
          const list = document.createElement('ul'); list.className = 'errorlist'; list.dataset.editorFieldError = '';
          errors.forEach(error => { const item = document.createElement('li'); item.textContent = error.message; list.append(item); });
          wrapper.append(list); field.setAttribute('aria-invalid', 'true');
        }
        form.querySelector('[aria-invalid=true]')?.focus();
        return;
      }
      const assessmentList = document.querySelector('.assessment-list');
      if (response.ok && result?.assessment_html && assessmentList) {
        const cardId = 'assessment-version-' + result.assessment_version_id;
        if (result.assessment_updated) {
          const card = document.getElementById(cardId);
          if (!card || !assessmentList.contains(card)) throw new Error('تم الحفظ، لكن تعذّر تحديث البطاقة المعروضة');
          card.outerHTML = result.assessment_html;
        } else {
          assessmentList.querySelector('.student-empty')?.remove();
          assessmentList.insertAdjacentHTML('beforeend', result.assessment_html);
        }
        dialog.close();
        if (window.MasarCurriculum && document.querySelector('[data-curriculum-page]')) {
          await window.MasarCurriculum.refreshSaved(window.location.href,result.message);
        } else window.appAlerts?.show(result.message, 'success');
        if (result.assessment_updated) document.getElementById(cardId)?.querySelector('[data-content-editor]')?.focus();
        return;
      }
      if (!response.ok || !result?.redirect_url) throw new Error('تعذّر الحفظ، تحقّق من الجلسة وصلاحية تعديل النسخة');
      const destination = new URL(result.redirect_url, window.location.origin);
      if (destination.origin !== window.location.origin) throw new Error('تعذّر التحقق من وجهة العودة');
      if (window.MasarCurriculum && document.querySelector('[data-curriculum-page]')) {
        await window.MasarCurriculum.refreshSaved(destination.href, 'تم حفظ التغييرات');
        dialog.close();
        return;
      }
      window.location.assign(destination.href);
    } catch (error) {
      showError(error instanceof TypeError ? 'تعذّر الاتصال، بقيت مدخلاتك هنا، تحقّق من المنهج قبل إعادة المحاولة' : error.message);
    } finally {
      saving = false; buttons.forEach(button => { button.disabled = false; }); form.removeAttribute('aria-busy');
    }
  });
})();
