(() => {
  const trigger = document.querySelector('[data-image-open]');
  const dialog = document.querySelector('[data-image-dialog]');
  if (!trigger || !dialog || typeof dialog.showModal !== 'function') return;
  trigger.setAttribute('aria-haspopup', 'dialog');
  trigger.addEventListener('click', event => { event.preventDefault(); dialog.showModal(); });
  dialog.querySelector('[data-image-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => trigger.focus());
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
})();
