(() => {
  const form = document.querySelector('[data-application-review]');
  if (!form) return;
  form.addEventListener('submit', event => {
    const reason = form.elements.reason;
    const rejecting = event.submitter?.value === 'rejected';
    reason.setCustomValidity(rejecting && !reason.value.trim() ? 'يرجى كتابة سبب رفض الطلب.' : '');
    if (!reason.reportValidity()) event.preventDefault();
    reason.setCustomValidity('');
  });
  form.elements.reason.addEventListener('input', () => form.elements.reason.setCustomValidity(''));
})();
