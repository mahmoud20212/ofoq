(() => {
  const selector = document.querySelector('[data-curriculum-page]') ? '[data-curriculum-page]' :
    document.querySelector('.assessment-list-region') ? '.assessment-list-region' : null;
  if (!selector || !window.fetch || !window.DOMParser) return;
  let busy = false;
  const initialRoot = document.querySelector(selector);
  const revisionId = initialRoot.dataset?.revisionId;
  const tabPaths = [initialRoot.dataset?.contentTabUrl,initialRoot.dataset?.assessmentTabUrl]
    .filter(Boolean).map(value => new URL(value,window.location.href).pathname);
  const isBusy = () => busy || document.querySelector('[data-curriculum-builder][aria-busy="true"]') !== null;
  const notify = (message, error = false, action = null) => window.appAlerts?.show(message, error ? 'error' : 'success', action);
  const localURL = value => {
    const url = new URL(value, window.location.href);
    if (url.origin !== window.location.origin || !(tabPaths.length ? tabPaths.includes(url.pathname) : url.pathname === window.location.pathname)) throw new Error('تعذّر التحقق من وجهة المنهج');
    return url;
  };
  const refresh = async (value, {push = false} = {}) => {
    if (isBusy()) throw new Error('انتظر انتهاء حفظ التغيير الحالي');
    const url = localURL(value), root = document.querySelector(selector);
    busy = true; root.setAttribute('aria-busy', 'true'); root.inert = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(url.href, {credentials:'same-origin', redirect:'error', signal:controller.signal});
      if (!response.ok) throw new Error('تعذّر تحميل المنهج، تحقّق من الجلسة والصلاحيات');
      const parsed = new DOMParser().parseFromString(await response.text(), 'text/html');
      const next = parsed.querySelector(selector);
      if (!next || (revisionId && next.dataset.revisionId !== revisionId)) throw new Error('تعذّر التحقق من المنهج، سجّل الدخول مجددًا عند انتهاء الجلسة');
      window.dispatchEvent(new Event('masar:curriculum-before-update'));
      root.replaceChildren(...next.childNodes);
      if (push) window.history.pushState(window.history.state, '', url.href);
      else window.history.replaceState(window.history.state, '', url.href);
      if (parsed.title) document.title = parsed.title;
      window.dispatchEvent(new Event('masar:curriculum-updated'));
    } finally {
      clearTimeout(timer); busy = false; root.inert = false; root.removeAttribute('aria-busy');
    }
  };
  const refreshSaved = async (url, message) => {
    try { await refresh(url); notify(message); return true; }
    catch (_) {
      notify('تم تنفيذ الإجراء، لكن تعذّر تحديث العرض. أعد تحميل المنهج للتحقق دون تكرار الإجراء', true,
        {label:'تحديث المنهج', run:() => refreshSaved(url, 'تم تحديث المنهج')});
      return false;
    }
  };
  window.MasarCurriculum = {refresh, refreshSaved, isBusy};
  document.addEventListener('click', async event => {
    const link = event.target.closest('[data-curriculum-tab], .teacher-builder-module a');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (isBusy()) { notify('انتظر انتهاء حفظ التغيير الحالي', true); return; }
    const switching = link.hasAttribute('data-curriculum-tab');
    if (switching && new URL(link.href).href === window.location.href) return;
    try {
      await refresh(link.href,{push:switching});
      const focus = document.querySelector(switching ? '[data-curriculum-tab][aria-current="page"]' : '.teacher-builder-content h2');
      if (focus?.tagName === 'H2') focus.tabIndex = -1;
      focus?.focus({preventScroll:true});
    }
    catch (error) { notify(error.message || 'تعذّر عرض الوحدة، أعد المحاولة', true); }
  });
  window.addEventListener('popstate', () => {
    if (!tabPaths.length) return;
    let url;
    try { url = localURL(window.location.href); } catch (_) { return; }
    refresh(url.href).catch(() => notify('تعذّر عرض التبويب، أعد المحاولة',true,{label:'إعادة المحاولة',run:()=>refresh(url.href)}));
  });
  document.addEventListener('submit', async event => {
    const form = event.target.closest('[data-action-form]');
    if (!form) return;
    const url = new URL(form.action, window.location.href);
    if (url.origin !== window.location.origin || !url.pathname.startsWith(window.location.pathname) || !url.pathname.endsWith('/delete/')) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (isBusy() || form.dataset.saving === 'true') return;
    form.dataset.saving = 'true';
    const dialog = form.closest('dialog'), buttons = [...dialog.querySelectorAll('button')];
    const preventCancel = e => e.preventDefault();
    dialog.addEventListener('cancel', preventCancel);
    buttons.forEach(button => { button.disabled = true; });
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(url.href, {method:'POST', body:new FormData(form), credentials:'same-origin', redirect:'error', signal:controller.signal,
        headers:{'X-Curriculum-Action':'1', 'Accept':'application/json'}});
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.redirect_url) throw new Error('تعذّر تأكيد الحذف، تحقّق من الجلسة والصلاحيات');
      dialog.close();
      await refreshSaved(result.redirect_url, result.message || 'تم الحذف من نسخة العمل');
    } catch (error) {
      dialog.close();
      notify(error.message || 'لم يصل تأكيد الحذف، تحقّق من المنهج قبل إعادة المحاولة', true,
        {label:'تحديث المنهج', run:() => refreshSaved(window.location.href, 'تم تحديث المنهج')});
    } finally {
      clearTimeout(timer); delete form.dataset.saving;
      buttons.forEach(button => { button.disabled = false; }); dialog.removeEventListener('cancel', preventCancel);
    }
  }, true);
})();
