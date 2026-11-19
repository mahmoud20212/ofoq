(() => {
  const initializeFields = (root) => {
  root.querySelectorAll('[data-upload]').forEach(wrapper => {
    const input = wrapper.querySelector('input[type=file]');
    const preview = wrapper.querySelector('[data-upload-preview]');
    const name = wrapper.querySelector('[data-upload-name]');
    let url = null;
    let isImage = input.hasAttribute('data-image-upload');
    wrapper.setUploadKind = image => {
      if (image === isImage) return;
      isImage = image;
      if (url) { URL.revokeObjectURL(url); url = null; }
      input.value = '';
      input.accept = image ? 'image/*' : '.pdf,.txt,.zip,.py,.ipynb,.csv,.json,.docx,.pptx,.xlsx';
      const icon = wrapper.querySelector(image ? '[data-upload-image-icon]' : '[data-upload-file-icon]');
      preview.replaceChildren(icon.content.cloneNode(true));
      wrapper.querySelector('[data-upload-title]').textContent = image ? 'صورة المحتوى' : 'ملف المحتوى';
      wrapper.querySelector('.teacher-upload-picker label').textContent = image ? 'اختيار الصورة' : 'اختيار الملف';
      name.textContent = image ? 'اختر صورة واضحة بتنسيق PNG أو JPG أو WebP' : 'اختر ملف المحتوى من جهازك';
    };
    input.addEventListener('change', () => {
      if (url) { URL.revokeObjectURL(url); url = null; }
      const file = input.files?.[0];
      if (!file) return;
      name.textContent = file.name;
      const clear = wrapper.querySelector('input[type=checkbox]');
      if (clear) clear.checked = false;
      if (isImage && file.type.startsWith('image/')) {
        url = URL.createObjectURL(file);
        const image = document.createElement('img');
        image.src = url;
        image.alt = 'معاينة الصورة المختارة';
        preview.replaceChildren(image);
      }
    });
    input.form?.addEventListener('reset', () => { if (url) URL.revokeObjectURL(url); });
  });
  const noExperience = root.querySelector('[data-no-experience]');
  const requirements = root.querySelector('[name="requirements"]');
  if (noExperience && requirements) {
    let previous = requirements.value === 'لا تحتاج خبرة سابقة' ? '' : requirements.value;
    const syncRequirements = () => {
      requirements.disabled = noExperience.checked;
      requirements.required = !noExperience.checked;
      requirements.value = noExperience.checked ? 'لا تحتاج خبرة سابقة' : previous;
    };
    noExperience.addEventListener('change', () => {
      if (noExperience.checked) previous = requirements.value;
      syncRequirements();
    });
    syncRequirements();
  }
  const paid = root.querySelector('[data-paid]');
  const priceField = root.querySelector('[data-field="price"]');
  const price = root.querySelector('[data-price]');
  if (paid && priceField && price) {
    const sync = () => {
      priceField.hidden = !paid.checked;
      price.required = paid.checked;
      if (!paid.checked) price.value = '';
      const status = root.querySelector('[data-pricing-status]');
      if (status) status.textContent = paid.checked ? 'حدّد السعر بالدولار' : 'الدورة مجانية';
    };
    paid.addEventListener('change', sync); sync();
  }
  const kind = root.querySelector('[data-lesson-kind]');
  if (kind) {
    const sync = () => {
      if (['image', 'file'].includes(kind.value)) root.querySelector('[data-field="file"] [data-upload]')?.setUploadKind?.(kind.value === 'image');
      for (const field of ['text', 'url', 'file']) {
        const wrapper = root.querySelector(`[data-field="${field}"]`);
        if (wrapper) wrapper.hidden = field === 'text' ? kind.value !== 'text' : field === 'url' ? kind.value !== 'video' : !['image', 'file'].includes(kind.value);
      }
    };
    kind.addEventListener('change', sync); sync();
  }
  };
  window.initializeMasarTeacherFields = initializeFields;
  initializeFields(document);
  document.querySelectorAll('.teacher-setup-steps [aria-disabled="true"]').forEach(step => {
    const explain = () => {
      const nav = step.closest('nav');
      let note = nav.querySelector('[data-step-requirements]');
      if (!note) {
        note = document.createElement('p');
        note.dataset.stepRequirements = '';
        note.className = 'teacher-note';
        note.setAttribute('role', 'status');
        nav.append(note);
      }
      note.textContent = step.title;
    };
    step.addEventListener('click', explain);
    step.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); explain(); }
    });
  });
  const dialog = document.querySelector('.teacher-action-dialog');
  if (dialog && typeof dialog.showModal === 'function') {
    const form = dialog.querySelector('[data-action-form]');
    const submit = dialog.querySelector('[data-action-submit]');
    const title = dialog.querySelector('#teacher-action-title');
    const description = dialog.querySelector('#teacher-action-description');
    const confirmation = form.querySelector('.teacher-confirm-checkbox');
    const checkbox = confirmation.querySelector('input');
    let opener = null;
    const open = (trigger, action, heading, message, destructive, requireCheckbox = true, submitLabel = heading) => {
      if (dialog.open) return;
      opener = trigger?.closest('[data-course-more]')?.querySelector('summary') || trigger;
      document.querySelectorAll('[data-course-more][open]').forEach(menu => { menu.open = false; });
      form.reset();
      confirmation.hidden = !requireCheckbox;
      checkbox.required = requireCheckbox;
      checkbox.checked = !requireCheckbox;
      form.action = action;
      title.textContent = heading;
      description.textContent = message;
      const item = dialog.querySelector('[data-action-item]');
      if (item) {
        item.textContent = trigger?.dataset.actionItem || '';
        item.hidden = !item.textContent;
      }
      submit.textContent = submitLabel;
      submit.className = destructive ? 'teacher-danger-button' : 'button small';
      submit.disabled = false;
      dialog.showModal();
      document.body.classList.add('teacher-dialog-open');
    };
    document.addEventListener('click', event => {
      const link = event.target.closest('[data-course-action]');
      if (!link) return;
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      open(link, link.href, link.dataset.actionTitle, link.dataset.actionDescription, link.dataset.courseAction === 'delete');
    });
    document.addEventListener('submit', event => {
      const source = event.target.closest('[data-confirm-delete]');
      if (!source) return;
      event.preventDefault();
      open(event.submitter, source.action, source.dataset.actionTitle || 'حذف العنصر', 'سيُحذف هذا العنصر من المسودة فقط. لن يتغيّر المحتوى المنشور قبل اعتماد النسخة.', true);
    });
    document.querySelectorAll('[data-confirm-action]').forEach(source => source.addEventListener('submit', event => {
      event.preventDefault();
      open(event.submitter, source.action, source.dataset.actionTitle, source.dataset.actionDescription, source.dataset.destructive === 'true', false, source.dataset.confirmLabel);
    }));
    dialog.querySelectorAll('[data-action-close]').forEach(button => button.addEventListener('click', () => dialog.close()));
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const bounds = dialog.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
    });
    dialog.addEventListener('close', () => {
      document.body.classList.remove('teacher-dialog-open');
      form.reset();
      if (opener?.isConnected) opener.focus();
    });
    form.addEventListener('submit', () => { submit.disabled = true; });
  }
  document.querySelectorAll('[data-course-more]').forEach(menu => {
    menu.addEventListener('keydown', event => {
      if (event.key === 'Escape' && menu.open) { menu.open = false; menu.querySelector('summary').focus(); }
    });
    document.addEventListener('click', event => {
      if (menu.open && !menu.contains(event.target)) menu.open = false;
    });
  });
})();
