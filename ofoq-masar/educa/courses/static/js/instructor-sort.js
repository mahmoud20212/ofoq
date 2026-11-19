(() => {
  let cleanup = () => {};
  const initialize = () => {
  cleanup();
  const builder = document.querySelector('[data-curriculum-builder]');
  if (!builder) return;
  const lifecycle = new AbortController();
  const lists = [...builder.querySelectorAll('[data-sort-list]')];
  const status = document.querySelector('[data-sort-status]');
  const reload = document.querySelector('[data-sort-reload]');
  const csrf = builder.querySelector('[name=csrfmiddlewaretoken]').value;
  let busy = false;
  let drag = null;
  const scrollBox = builder.closest?.('.assessment-manager-body');
  if (lists.some(list => list.dataset.sortList === 'question')) builder.classList.add('assessment-question-sortable');
  const rows = list => [...list.children].filter(row => row.hasAttribute('data-sort-id'));
  const ids = list => rows(list).map(row => Number(row.dataset.sortId));
  const announce = (message, error = false) => {
    if (status) {
      status.textContent = message;
      status.classList.toggle('is-error', error);
      status.classList.toggle('is-saved', !error && message === 'تم حفظ الترتيب');
    }
    if (reload) reload.hidden = !error;
    if (error && lists.some(list => list.dataset.sortList === 'question')) window.appAlerts?.show(message, 'error');
  };
  const renumber = list => rows(list).forEach((row, index) => {
    const position = row.querySelector('[data-position]');
    if (position) position.textContent = index + 1;
  });
  const restore = (list, previous) => {
    const items = new Map(rows(list).map(row => [Number(row.dataset.sortId), row]));
    previous.forEach(id => list.append(items.get(id)));
    renumber(list);
  };
  const save = async (list, previous, handle) => {
    const order = ids(list);
    if (order.every((id, index) => id === previous[index])) return;
    busy = true;
    builder.setAttribute('aria-busy', 'true');
    lists.forEach(node => node.querySelectorAll('[data-drag-handle]').forEach(button => { button.disabled = true; }));
    announce('جارٍ حفظ الترتيب');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(builder.dataset.sortUrl, {
        method: 'POST', credentials: 'same-origin', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'Accept': 'application/json' },
        body: JSON.stringify({ kind: list.dataset.sortList, module_id: Number(list.dataset.moduleId) || null, order, previous_order: previous })
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(data?.error || (response.status === 403 ? 'انتهت الجلسة أو أصبحت النسخة للقراءة فقط، حدّث الصفحة' : 'تعذّر حفظ الترتيب، حدّث المنهج ثم أعد المحاولة'));
      if (!Array.isArray(data?.order) || data.order.join(',') !== order.join(',')) throw new Error('تعذّر تأكيد الترتيب، حدّث المنهج');
      announce('تم حفظ الترتيب');
    } catch (error) {
      restore(list, previous);
      announce(error.name === 'AbortError' ? 'لم يصل تأكيد الحفظ، حدّث المنهج للتحقق من الترتيب' : (error instanceof TypeError ? 'تعذّر الاتصال، حدّث المنهج ثم أعد المحاولة' : error.message || 'تعذّر حفظ الترتيب، أعد المحاولة'), true);
    } finally {
      clearTimeout(timeout);
      busy = false;
      builder.removeAttribute('aria-busy');
      lists.forEach(node => node.querySelectorAll('[data-drag-handle]').forEach(button => { button.disabled = false; }));
      if (handle?.isConnected) handle.focus({ preventScroll: true });
    }
  };
  const place = () => {
    if (!drag?.active) return;
    const scrollY = scrollBox ? scrollBox.scrollTop : window.scrollY || 0;
    if (drag.lastY === drag.y && drag.lastScrollY === scrollY) return;
    drag.lastY = drag.y;
    drag.lastScrollY = scrollY;
    const others = rows(drag.list).filter(row => row !== drag.row);
    const before = others.find(row => {
      const rect = row.getBoundingClientRect();
      return drag.y < rect.top + rect.height / 2;
    });
    if (drag.row.nextElementSibling !== (before || null)) {
      drag.list.insertBefore(drag.row, before || null);
      renumber(drag.list);
    }
    drag.ghost.style.transform = `translateY(${drag.y - drag.offsetY}px)`;
  };
  const scroll = () => {
    if (!drag?.active) return;
    const listRect = drag.list.getBoundingClientRect();
    const bounds = scrollBox?.getBoundingClientRect();
    const top = bounds ? bounds.top + 40 : 100;
    const bottom = bounds ? bounds.bottom - 40 : window.innerHeight - 80;
    if (drag.y < top && listRect.top < top) (scrollBox || window).scrollBy(0, -12);
    else if (drag.y > bottom && listRect.bottom > bottom) (scrollBox || window).scrollBy(0, 12);
    place();
    drag.frame = requestAnimationFrame(scroll);
  };
  const finish = cancelled => {
    if (!drag) return;
    const current = drag;
    drag = null;
    cancelAnimationFrame(current.frame);
    current.ghost?.remove();
    current.row.classList.remove('is-dragging');
    current.handle.removeAttribute('aria-pressed');
    document.body.classList.remove('teacher-sorting');
    if (current.handle.hasPointerCapture?.(current.pointerId)) current.handle.releasePointerCapture(current.pointerId);
    if (cancelled) { restore(current.list, current.previous); announce('تم إلغاء الترتيب'); }
    else if (current.active) save(current.list, current.previous, current.handle);
    if (!busy) current.handle.focus({ preventScroll: true });
  };
  lists.forEach(list => {
    list.addEventListener('pointerdown', event => {
      const handle = event.target.closest('[data-drag-handle]');
      if (!handle || busy || drag || !event.isPrimary || event.button !== 0) return;
      const row = handle.closest('[data-sort-id]');
      if (row.parentElement !== list || rows(list).length < 2) return;
      event.preventDefault();
      handle.focus({ preventScroll: true });
      handle.setPointerCapture(event.pointerId);
      const rect = row.getBoundingClientRect();
      drag = { list, row, handle, previous: ids(list), pointerId: event.pointerId, startY: event.clientY, y: event.clientY, offsetY: event.clientY - rect.top, active: false, rect };
    });
    list.addEventListener('keydown', event => {
      const handle = event.target.closest('[data-drag-handle]');
      if (!handle || busy || drag || !['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const row = handle.closest('[data-sort-id]');
      const items = rows(list), previous = ids(list), index = items.indexOf(row);
      const target = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : index + (event.key === 'ArrowUp' ? -1 : 1);
      if (target < 0 || target >= items.length || target === index) return;
      list.insertBefore(row, target < index ? items[target] : items[target].nextElementSibling);
      renumber(list);
      save(list, previous, handle);
    });
    list.querySelectorAll('[data-drag-handle]').forEach(handle => { handle.hidden = false; });
  });
  cleanup = () => { finish(true); lifecycle.abort(); };
  window.addEventListener('pointermove', event => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    drag.y = event.clientY;
    if (!drag.active && Math.abs(drag.y - drag.startY) > 5) {
      drag.active = true;
      drag.row.classList.add('is-dragging');
      drag.handle.setAttribute('aria-pressed', 'true');
      drag.ghost = document.createElement('div');
      drag.ghost.className = 'teacher-sort-ghost';
      drag.ghost.textContent = (drag.row.querySelector('[data-sort-title]') || drag.row.querySelector('strong') || drag.row.querySelector('.teacher-builder-lesson-info a')).textContent;
      Object.assign(drag.ghost.style, { top: '0px', left: `${drag.rect.left}px`, width: `${drag.rect.width}px`, height: `${drag.rect.height}px` });
      (builder.closest?.('dialog') || document.body).append(drag.ghost);
      document.body.classList.add('teacher-sorting');
      scroll();
    }
    place();
  }, {signal:lifecycle.signal});
  window.addEventListener('pointerup', event => { if (drag?.pointerId === event.pointerId) finish(false); }, {signal:lifecycle.signal});
  window.addEventListener('pointercancel', event => { if (drag?.pointerId === event.pointerId) finish(true); }, {signal:lifecycle.signal});
  window.addEventListener('blur', () => finish(true), {signal:lifecycle.signal});
  window.addEventListener('keydown', event => { if (drag && event.key === 'Escape') { event.preventDefault(); finish(true); } }, {signal:lifecycle.signal});
  reload?.addEventListener('click', () => {
    if (lists.some(list => list.dataset.sortList === 'question') && window.MasarAssessmentManager) window.MasarAssessmentManager.reload();
    else if (window.MasarCurriculum) window.MasarCurriculum.refreshSaved(window.location.href, 'تم تحديث المنهج');
    else window.location.reload();
  });
  };
  initialize();
  window.addEventListener('masar:curriculum-before-update', () => cleanup());
  window.addEventListener('masar:curriculum-updated', initialize);
})();
