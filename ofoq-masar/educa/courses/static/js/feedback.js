(() => {
  document.querySelectorAll('.feedback-rating').forEach(picker => {
    const inputs = [...picker.querySelectorAll('input[type=radio]')];
    const update = () => {
      const value = Number(inputs.find(input => input.checked)?.value || 0);
      inputs.forEach(input => input.closest('label').classList.toggle('is-filled', Number(input.value) <= value));
      picker.querySelector('[data-rating-status]').textContent = value ? `${value} من 5` : 'اختر عدد النجوم';
    };
    picker.addEventListener('change', update); update();
  });
  const invalidReview = document.querySelector('[data-review-invalid]');
  if (invalidReview && !invalidReview.open && invalidReview.showModal) invalidReview.showModal();
  const dialog = document.querySelector('.feedback-confirm-dialog');
  let source = null, opener = null, confirmed = null;
  document.querySelectorAll('form[data-feedback-confirm]').forEach(form => {
    form.addEventListener('submit', event => {
      if (confirmed === form || !dialog?.showModal) return;
      event.preventDefault();
      source = form; opener = event.submitter;
      dialog.querySelector('[data-feedback-confirm-message]').textContent = form.dataset.feedbackConfirm;
      dialog.returnValue = ''; dialog.showModal();
    });
  });
  dialog?.addEventListener('close', () => {
    if (dialog.returnValue === 'confirm' && source) {
      const input = document.createElement('input'); input.type = 'hidden'; input.name = 'confirm'; input.value = 'yes';
      source.append(input); confirmed = source; source.requestSubmit();
    } else { opener?.focus(); }
    source = null;
  });
  document.querySelectorAll('.feedback-form, form[data-feedback-confirm]').forEach(form => {
    form.addEventListener('submit', event => {
      if (event.defaultPrevented) return;
      form.querySelectorAll('button[type=submit],button:not([type])').forEach(button => button.disabled = true);
    });
  });
})();
