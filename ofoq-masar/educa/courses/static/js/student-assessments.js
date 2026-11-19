(() => {
  document.querySelectorAll('[data-assessment-start]').forEach(form => form.addEventListener('submit', () => {
    form.querySelector('button[type="submit"]').disabled = true;
  }));
  const form = document.querySelector('[data-assessment-form]');
  const dialog = document.querySelector('[data-assessment-confirm]');
  if (!form || !dialog || typeof dialog.showModal !== 'function' || !window.fetch || !window.AbortController) return;
  const questions = [...form.querySelectorAll('[data-assessment-question]')];
  const saveButton = form.querySelector('[data-assessment-save]');
  const submitButton = form.querySelector('[data-assessment-submit]');
  const recoverButton = form.querySelector('[data-assessment-recover]');
  const status = form.querySelector('[data-save-status]');
  const errorBox = form.querySelector('[data-request-error]');
  const login = form.querySelector('[data-assessment-login]');
  const csrfInput = form.querySelector('[name="csrfmiddlewaretoken"]');
  let csrf = csrfInput.value;
  let saved;
  try { saved = JSON.parse(document.getElementById('assessment-confirmed-answers').textContent); }
  catch { return; }
  const fingerprint = rows => JSON.stringify(rows.map(row => [row.question_key, row.option_key || '']));
  const choices = () => questions.map(question => ({question_key:question.dataset.assessmentQuestion,
    option_key:question.querySelector('input[type="radio"]:checked')?.value || ''}));
  let confirmed = fingerprint(saved), busy = null, uncertain = false, blocked = false, submitted = false, sequence = 0;
  let notice = null;
  const autoSave = form.dataset.assessmentAutosave === 'true';
  let autosaveTimer = null;
  const cancelAutosave = () => { clearTimeout(autosaveTimer); autosaveTimer = null; };
  const scheduleSave = (delay = 450) => {
    cancelAutosave();
    if (!autoSave || blocked || uncertain || submitted || !dirty()) return;
    autosaveTimer = setTimeout(() => { autosaveTimer = null; save(); }, delay);
  };
  const dirty = () => fingerprint(choices()) !== confirmed;
  const announce = message => { status.textContent = message; };
  const controls = () => {
    saveButton.disabled = submitButton.disabled = Boolean(busy || uncertain || blocked);
    recoverButton.disabled = Boolean(busy);
    questions.forEach(question => {
      question.disabled = busy === 'submit' || uncertain || blocked;
    });
    form.setAttribute('aria-busy', busy ? 'true' : 'false');
    form.querySelector('[data-answered-count]').textContent = String(choices().filter(row => row.option_key).length);
  };
  const clearError = () => { errorBox.hidden = true; login.hidden = true; notice?.dismiss(); notice = null; };
  const error = (message, action) => {
    errorBox.textContent = message; errorBox.hidden = Boolean(window.appAlerts);
    notice?.dismiss();
    if (window.appAlerts) notice = window.appAlerts.show(message, 'error', action);
  };
  const sessionExpired = () => {
    blocked = true; login.hidden = false;
    announce('انتهت الجلسة · لا يمكن تأكيد حفظ التغييرات');
    error('سجّل الدخول مجددًا في تبويب جديد، ثم تحقّق من حالة المحاولة. اختياراتك باقية هنا');
    recoverButton.hidden = false;
  };
  const navigateResult = () => {
    submitted = true; uncertain = false; confirmed = fingerprint(choices());
    window.location.assign(form.dataset.resultUrl);
  };
  const request = async (url, rows, id) => {
    const controller = new window.AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await window.fetch(url, {method:rows === undefined ? 'GET' : 'POST',
        credentials:'same-origin', headers:{Accept:'application/json', ...(rows === undefined ? {} : {'Content-Type':'application/json','X-CSRFToken':csrf})},
        ...(rows === undefined ? {} : {body:JSON.stringify({answers:rows})}), signal:controller.signal});
      if (id !== sequence) return null;
      const freshToken = response.headers?.get('X-CSRFToken');
      if (freshToken) csrf = csrfInput.value = freshToken;
      if (response.redirected || response.status === 401) { sessionExpired(); return null; }
      if (response.status === 403) {
        // CSRF middleware can reject an expired session before the JSON view runs.
        const check = await window.fetch(form.dataset.readUrl, {credentials:'same-origin',headers:{Accept:'application/json'},signal:controller.signal});
        if (check.redirected || check.status === 401) { sessionExpired(); return null; }
        const token = check.headers?.get('X-CSRFToken');
        if (token) csrf = csrfInput.value = token;
        throw Object.assign(new Error('تعذّر التحقق من الطلب؛ تم تحديث حماية الجلسة، أعد المحاولة'), {status:403});
      }
      const data = await response.json();
      if (!response.ok) throw Object.assign(new Error(data.detail || 'تعذّر تنفيذ الطلب'), {status:response.status,code:data.error});
      const expectedId = form.dataset.readUrl.match(/attempts\/(\d+)\//)?.[1];
      if (data.attempt_id === undefined || (expectedId && String(data.attempt_id) !== expectedId)
          || !['in_progress','submitted'].includes(data.status)) throw new Error('استجابة غير متوقعة؛ تحقّق من حالة المحاولة');
      return data;
    } finally { clearTimeout(timer); }
  };
  const recover = async () => {
    if (busy) return;
    let recoveredActive = false;
    busy = 'read'; const id = ++sequence; controls(); clearError();
    try {
      const data = await request(form.dataset.readUrl, undefined, id);
      if (!data || id !== sequence) return;
      if (data.status === 'submitted') { navigateResult(); return; }
      if (!Array.isArray(data.questions)) throw new Error('تعذّر قراءة حالة المحاولة');
      confirmed = fingerprint(data.questions.map(row => ({question_key:row.question_key,option_key:row.selected_option_key})));
      uncertain = blocked = false; recoverButton.hidden = true;
      recoveredActive = true;
      announce(dirty() ? 'تغييرات غير محفوظة · يمكنك حفظها أو إعادة التسليم' : 'تم تحميل حالة المحاولة المحفوظة');
      // Never replace the student's current choices with older server selections.
    } catch (failure) {
      announce('تعذّر التحقق من الحالة');
      if (failure.status === 404) {
        blocked = true;
        error('المحاولة لم تعد متاحة لحسابك. لم نغيّر اختياراتك المعروضة هنا');
      } else error('تعذّر التحقق من حالة المحاولة. اختياراتك باقية؛ أعد المحاولة', {label:'إعادة التحقق',run:recover});
    } finally { if (id === sequence) { busy = null; controls(); if (recoveredActive) scheduleSave(); } }
  };
  const save = async () => {
    if (busy || uncertain || blocked) return;
    cancelAutosave();
    let succeeded = false;
    const sent = choices(), id = ++sequence; busy = 'save'; controls(); clearError(); announce('جارٍ الحفظ');
    try {
      const data = await request(form.dataset.saveUrl, sent, id);
      if (!data || id !== sequence) return;
      if (data.status === 'submitted') { navigateResult(); return; }
      confirmed = fingerprint(sent);
      succeeded = true;
      if (autoSave) saveButton.hidden = true;
      announce(dirty() ? 'تغييرات غير محفوظة' : 'تم الحفظ');
    } catch (failure) {
      if (id !== sequence) return;
      announce('تعذر الحفظ');
      if (failure.code === 'attempt_submitted') { uncertain = true; recoverButton.hidden = false; }
      if (failure.code === 'prerequisites_not_met') { blocked = true; recoverButton.hidden = false; }
      if (failure.status === 404) blocked = true;
      if (autoSave && !window.appAlerts && !blocked && !uncertain) saveButton.hidden = false;
      if (failure.code === 'prerequisites_not_met') error(failure.message + ' · اختياراتك باقية هنا');
      else error('تعذّر حفظ الإجابات. اختياراتك باقية؛ أعد المحاولة', {label:'إعادة المحاولة',run:save});
    } finally {
      if (id === sequence) {
        busy = null; controls();
        if (succeeded && dirty()) scheduleSave(0);
      }
    }
  };
  const submit = async () => {
    if (busy || uncertain || blocked) return;
    cancelAutosave();
    const sent = choices(), id = ++sequence; busy = 'submit'; controls(); clearError(); announce('جارٍ تسليم المحاولة');
    try {
      const data = await request(form.dataset.submitUrl, sent, id);
      if (!data || id !== sequence) return;
      if (data.status !== 'submitted' || !data.result) throw new Error('تعذّر تأكيد نتيجة التسليم');
      navigateResult();
    } catch (failure) {
      if (id !== sequence) return;
      if (!failure.status || failure.code === 'attempt_submitted' || failure.status >= 500) {
        uncertain = true; recoverButton.hidden = false;
        announce('تعذّر التأكد من التسليم');
        error('قد يكون التسليم وصل إلى الخادم. تحقّق من الحالة قبل إعادة الإرسال', {label:'التحقق من الحالة',run:recover});
      } else {
        announce('تعذّر تسليم المحاولة');
        if (failure.status === 404) blocked = true;
        if (failure.code === 'prerequisites_not_met') { blocked = true; recoverButton.hidden = false; }
        error(failure.message + ' · اختياراتك باقية، ويمكن إعادة المحاولة');
      }
    } finally { if (id === sequence) { busy = null; controls(); } }
  };
  form.addEventListener('change', () => { controls(); announce(dirty() ? 'تغييرات غير محفوظة' : 'تم الحفظ'); scheduleSave(); });
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (busy || uncertain || blocked) return;
    if (!event.submitter || event.submitter.value === 'save') { save(); return; }
    cancelAutosave();
    dialog.querySelector('[data-unanswered-count]').textContent = String(choices().filter(row => !row.option_key).length);
    dialog.showModal();
  });
  dialog.querySelectorAll('[data-assessment-cancel]').forEach(button => button.addEventListener('click', () => dialog.close()));
  dialog.addEventListener('close', () => { submitButton.focus(); scheduleSave(); });
  dialog.querySelector('[data-assessment-confirm-submit]').addEventListener('click', () => { dialog.close(); submit(); });
  recoverButton.addEventListener('click', recover);
  window.addEventListener('beforeunload', event => {
    if (!submitted && (dirty() || uncertain || busy === 'submit')) { event.preventDefault(); event.returnValue = ''; }
  });
  if (autoSave) saveButton.hidden = true;
  controls();
  if (autoSave && dirty()) scheduleSave();
})();
