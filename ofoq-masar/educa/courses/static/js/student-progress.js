(() => {
  // Keep the native progress value authoritative; animate only its decorative fill.
  const fills = new WeakMap();
  const updateBar = (bar, percentage) => {
    let fill = fills.get(bar);
    if (!fill && bar.tagName === 'PROGRESS' && typeof document.createElement === 'function') {
      const track = document.createElement('span');
      track.className = 'student-progress-track';
      track.setAttribute('aria-hidden', 'true');
      fill = document.createElement('span');
      fill.className = 'student-progress-fill';
      fill.style.width = `${Number(bar.value)}%`;
      track.append(fill);
      bar.after(track);
      bar.classList.add('student-progress-native');
      fills.set(bar, fill);
      // Establish the starting width before applying the new server value.
      track.getBoundingClientRect();
    }
    bar.value = percentage;
    bar.textContent = `${percentage}%`;
    if (fill) fill.style.width = `${percentage}%`;
  };
  document.querySelectorAll('[data-progress-bar]').forEach(bar => {
    if (bar.tagName === 'PROGRESS') updateBar(bar, Number(bar.value));
  });
  const forms = Array.from(document.querySelectorAll('[data-completion-form]'));
  const saving = new Set();
  let queue = Promise.resolve();
  let errorNotice = null;
  forms.forEach(form => {
    const checkbox = form.querySelector('[data-completion-checkbox]');
    const message = form.querySelector('[data-progress-message]') || document.querySelector('[data-learning-feedback]');
    const login = form.querySelector('[data-progress-login]') || document.querySelector('[data-learning-login]');
    const announce = (text, error = false, action = null) => {
      const useToast = error && typeof window !== 'undefined' && typeof window.appAlerts?.show === 'function';
      if (useToast) {
        errorNotice?.dismiss();
        errorNotice = window.appAlerts.show(text, 'error', action);
      }
      if (!message) return;
      message.setAttribute('data-quiet-success', String(!error || useToast));
      if (useToast) { message.textContent = ''; return; }
      message.setAttribute('role', error ? 'alert' : 'status');
      message.setAttribute('aria-live', error ? 'assertive' : 'polite');
      message.textContent = text;
    };
    const submit = event => {
      // Leave the native POST fallback intact on browsers without fetch.
      if (typeof fetch !== 'function' || typeof AbortController !== 'function') return;
      event.preventDefault();
      const key = `${form.dataset.courseId}:${form.dataset.contentId}`;
      if (saving.has(key)) return;
      saving.add(key);
      const peers = forms.filter(other => other.dataset.courseId === form.dataset.courseId && other.dataset.contentId === form.dataset.contentId);
      const desired = checkbox ? checkbox.checked : form.dataset.completed !== 'true';
      peers.forEach(other => {
        other.setAttribute('aria-busy', 'true');
        other.querySelectorAll('button, [data-completion-checkbox]').forEach(control => { control.disabled = true; });
      });
      if (message) message.textContent = '';
      if (login) login.hidden = true;
      const run = async () => {
      errorNotice?.dismiss();
      errorNotice = null;
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 15000);
      try {
        const response = await fetch(desired ? form.dataset.completeUrl : form.dataset.incompleteUrl, {
          method: 'POST', credentials: 'same-origin', body: new FormData(form),
          headers: { Accept: 'application/json' }, signal: controller.signal,
        });
        if (response.status === 401 || response.redirected) {
          const toastsAvailable = typeof window !== 'undefined' && typeof window.appAlerts?.show === 'function';
          if (login) login.hidden = toastsAvailable;
          announce('انتهت جلستك. سجّل الدخول مجددًا لحفظ التغيير', true, login ? {
            label: 'تسجيل الدخول مجددًا', run: () => window.location.assign(login.href),
          } : null);
          return;
        }
        if (response.status === 403) throw new Error('session');
        if (!response.ok) throw new Error('request');
        const body = await response.json();
        const progress = body.progress;
        if (typeof body.completed !== 'boolean' || body.course_id !== Number(form.dataset.courseId) || body.content_id !== Number(form.dataset.contentId) ||
            !progress || !Number.isInteger(progress.available_content_count) || !Number.isInteger(progress.completed_content_count) ||
            !Number.isInteger(progress.completion_percentage) || progress.available_content_count < 1 || progress.completed_content_count < 0 ||
            progress.completed_content_count > progress.available_content_count || progress.completion_percentage < 0 || progress.completion_percentage > 100) throw new Error('response');
        peers.forEach(other => {
          other.dataset.completed = String(body.completed);
          other.action = body.completed ? other.dataset.incompleteUrl : other.dataset.completeUrl;
          const toggle = other.querySelector('[data-completion-checkbox]');
          const action = other.querySelector('[data-completion-button]');
          const text = other.querySelector('[data-completion-label]');
          const status = other.querySelector('[data-completion-state]');
          if (toggle) toggle.checked = body.completed;
          if (action) { action.setAttribute('aria-pressed', String(body.completed)); action.setAttribute('aria-label', body.completed ? 'مكتمل' : 'تحديد المحتوى كمكتمل'); action.classList.toggle('is-completed', body.completed); }
          if (status) status.textContent = body.completed ? 'هذا المحتوى مكتمل' : 'لم تحدّد هذا المحتوى كمكتمل';
          if (text) text.textContent = body.completed ? 'مكتمل' : 'تحديد كمكتمل';
        });
        document.querySelectorAll('[data-course-progress]').forEach(panel => {
          if (panel.dataset.courseProgress !== form.dataset.courseId) return;
          panel.querySelector('[data-progress-count]').textContent = `أكملت ${progress.completed_content_count} من ${progress.available_content_count}`;
          panel.querySelector('[data-progress-percent]').textContent = `${progress.completion_percentage}%`;
          const bar = panel.querySelector('[data-progress-bar]');
          updateBar(bar, progress.completion_percentage);
        });
        if (Array.isArray(body.assessment_states)) {
          body.assessment_states.forEach(test => {
            document.querySelectorAll('[data-assessment-row]').forEach(row => {
              if (String(row.dataset.assessmentRow) !== String(test.id)) return;
              row.querySelectorAll('[data-assessment-lock]').forEach(lock => { lock.hidden = test.is_unlocked; });
              row.querySelectorAll('[data-assessment-state-label]').forEach(label => { label.textContent = test.is_unlocked ? test.state_label : 'مقفل'; });
            });
          });
        }
        announce(`${body.completed ? 'تم تحديد المحتوى كمكتمل' : 'تم إلغاء الإكمال'}. ${progress.completed_content_count} من ${progress.available_content_count}، التقدّم ${progress.completion_percentage}%`);
      } catch (error) {
        announce(error.message === 'session' ? 'تعذّر حفظ التغيير. أعد تحميل الصفحة لتجديد الجلسة' : 'تعذّر حفظ التغيير. تحقق من اتصالك وأعد المحاولة', true, {
          label: error.message === 'session' ? 'إعادة تحميل الصفحة' : 'إعادة المحاولة',
          run: () => {
            if (error.message === 'session') { window.location.reload(); return; }
            if (checkbox) checkbox.checked = desired;
            return submit({ preventDefault() {} });
          },
        });
      } finally {
        clearTimeout(timeout);
        peers.forEach(other => {
          const toggle = other.querySelector('[data-completion-checkbox]');
          if (toggle) toggle.checked = other.dataset.completed === 'true';
          other.querySelectorAll('button, [data-completion-checkbox]').forEach(control => { control.disabled = false; });
          other.removeAttribute('aria-busy');
        });
        saving.delete(key);
      }
      };
      queue = queue.then(run, run);
      return queue;
    };
    form.addEventListener('submit', submit);
    if (checkbox) checkbox.addEventListener('change', submit);
  });
  document.querySelectorAll('[data-learning-image]').forEach(image => {
    const showError = () => {
      image.hidden = true;
      const error = image.parentElement.querySelector('[data-media-error]');
      if (error) error.hidden = false;
    };
    image.addEventListener('error', showError);
    if (image.complete && image.naturalWidth === 0) showError();
  });
})();
