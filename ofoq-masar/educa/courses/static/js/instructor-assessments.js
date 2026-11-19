(() => {
  const initialized = new WeakSet();
  const initialize = (root = document) => {
  const form = root.querySelector('[data-option-editor]');
  if (!form) return;
  const list = form.querySelector('[data-options]');
  const template = form.querySelector('[data-option-template]');
  const total = form.querySelector('[name="options-TOTAL_FORMS"]');
  if (!list || !template || !total) return;
  if (initialized.has(form)) return;
  initialized.add(form);
  form.classList.add('assessment-js');
  const rows = () => [...list.querySelectorAll('[data-option-row]')].filter(row => !row.hidden);
  const controls = row => {
    row.querySelector('[data-option-remove]').hidden = false;
    const handle = row.querySelector('[data-option-handle]');
    if (handle) handle.hidden = false;
    const deletion = row.querySelector('input[name$="-DELETE"]');
    if (deletion.checked) row.hidden = true;
  };
  list.querySelectorAll('[data-option-row]').forEach(controls);
  const initial = [...list.querySelectorAll('[data-option-row]')];
  if (initial.some(row => row.querySelector('input[name$="-id"]')?.value)) {
    initial.forEach(row => {
      if (!row.querySelector('input[name$="-id"]')?.value && !row.querySelector('input[name$="-text"]').value?.trim()
          && !row.querySelector('input[type="radio"]').checked) row.hidden = true;
    });
  }
  const order = () => {
    const items = rows();
    items.forEach((row, index) => {
      row.querySelector('input[name$="-order"]').value = index;
      row.querySelector('[data-option-up]').disabled = index === 0;
      row.querySelector('[data-option-down]').disabled = index === items.length - 1;
    });
  };
  order();
  let drag = null;
  const optionStatus = form.querySelector('[data-option-status]');
  const validation = form.querySelector('[data-option-validation]');
  form.validateAssessment = () => {
    if (form.reportValidity && !form.reportValidity()) return false;
    const items = rows().filter(row => !row.querySelector('input[name$="-DELETE"]').checked);
    const filled = items.filter(row => row.querySelector('input[name$="-text"]').value.trim());
    const selected = items.find(row => row.querySelector('input[type="radio"]').checked);
    const blankStored = items.find(row => row.querySelector('input[name$="-id"]')?.value && !row.querySelector('input[name$="-text"]').value.trim());
    const errors = [];
    if (filled.length < 2) errors.push('أضف خيارين مكتملين على الأقل');
    if (!selected) errors.push('حدّد إجابة صحيحة واحدة');
    else if (!selected.querySelector('input[name$="-text"]').value.trim()) errors.push('اكتب نص الإجابة الصحيحة');
    if (blankStored) errors.push('اكتب نص الخيار الفارغ أو احذفه');
    if (validation) { validation.textContent = errors.join(' · '); validation.hidden = !errors.length; }
    if (errors.length) {
      const field = blankStored || (filled.length < 2 ? items.find(row => !row.querySelector('input[name$="-text"]').value.trim()) : null);
      (field?.querySelector('input[name$="-text"]') || selected?.querySelector('input[type="radio"]') || items[0]?.querySelector('input[type="radio"]') || form.querySelector('[data-add-option]')).focus();
      return false;
    }
    return true;
  };
  form.addEventListener?.('submit', event => {
    if (event.submitter?.value !== 'add_option' && !form.validateAssessment()) event.preventDefault();
  });
  const clearValidation = () => { if (validation) validation.hidden = true; };
  form.addEventListener?.('input',clearValidation);
  form.addEventListener?.('change',clearValidation);
  const announceOrder = () => { if (optionStatus) optionStatus.textContent = 'تم ترتيب الخيارات، احفظ السؤال لتثبيت الترتيب'; };
  const move = (row, before) => {
    const selected = rows().find(item => item.querySelector('input[type="radio"]').checked);
    list.insertBefore(row, before);
    if (selected) selected.querySelector('input[type="radio"]').checked = true;
    order();
  };
  const finishDrag = cancelled => {
    if (!drag) return;
    const current = drag; drag = null;
    if (current.frame) cancelAnimationFrame(current.frame);
    current.ghost?.remove(); current.row.classList.remove('is-option-dragging');
    current.handle.removeAttribute('aria-pressed');
    if (current.handle.hasPointerCapture?.(current.pointerId)) current.handle.releasePointerCapture(current.pointerId);
    if (cancelled) {
      const selected = current.previous.find(row => row.querySelector('input[type="radio"]').checked);
      current.previous.forEach(row => list.append(row));
      if (selected) selected.querySelector('input[type="radio"]').checked = true;
      order();
    }
    else if (current.active) announceOrder();
    if (current.handle.isConnected) current.handle.focus({preventScroll:true});
  };
  const placeOption = () => {
    if (!drag?.active) return;
    const scrollTop = drag.scroller?.scrollTop || 0;
    if (drag.lastY === drag.y && drag.lastScroll === scrollTop) return;
    drag.lastY = drag.y; drag.lastScroll = scrollTop;
    const before = rows().filter(row => row !== drag.row).find(row => {
      const rect = row.getBoundingClientRect(); return drag.y < rect.top + rect.height / 2;
    }) || null;
    if (drag.row.nextElementSibling !== before) {
      move(drag.row, before);
      drag.handle.setPointerCapture?.(drag.pointerId);
    }
    drag.ghost.style.transform = `translateY(${drag.y - drag.offset}px)`;
  };
  const scrollOptions = () => {
    if (!drag?.active) return;
    if (form.isConnected === false) { finishDrag(true); return; }
    const scroller = drag.scroller;
    if (scroller) {
      const rect = scroller.getBoundingClientRect();
      if (drag.y < rect.top + 40) scroller.scrollBy(0,-10);
      else if (drag.y > rect.bottom - 40) scroller.scrollBy(0,10);
    }
    placeOption(); drag.frame = requestAnimationFrame(scrollOptions);
  };
  list.addEventListener('pointerdown', event => {
    const handle = event.target.closest('[data-option-handle]');
    if (!handle || drag || !event.isPrimary || event.button !== 0 || rows().length < 2) return;
    const row = handle.closest('[data-option-row]');
    if (!row || row.parentElement !== list) return;
    event.preventDefault(); handle.focus({preventScroll:true}); handle.setPointerCapture?.(event.pointerId);
    const rect = row.getBoundingClientRect();
    drag = {handle,row,previous:rows(),pointerId:event.pointerId,start:event.clientY,y:event.clientY,offset:event.clientY-rect.top,rect,active:false,scroller:form.closest?.('.assessment-manager-body')};
  });
  list.addEventListener('pointermove', event => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    drag.y = event.clientY;
    if (!drag.active && Math.abs(drag.y-drag.start) > 5) {
      drag.active = true; drag.row.classList.add('is-option-dragging'); drag.handle.setAttribute('aria-pressed','true');
      drag.ghost = document.createElement('div'); drag.ghost.className = 'teacher-sort-ghost assessment-option-ghost';
      drag.ghost.textContent = drag.row.querySelector('input[name$="-text"]').value || 'خيار';
      Object.assign(drag.ghost.style,{top:'0px',left:drag.rect.left+'px',width:drag.rect.width+'px',height:drag.rect.height+'px'});
      (form.closest?.('dialog') || document.body).append(drag.ghost); scrollOptions();
    }
  });
  list.addEventListener('pointerup', event => {if (drag?.pointerId === event.pointerId) {placeOption(); finishDrag(false);}});
  list.addEventListener('pointercancel', event => {if (drag?.pointerId === event.pointerId) finishDrag(true);});
  list.addEventListener('keydown', event => {
    if (drag && event.key === 'Escape') {event.preventDefault(); finishDrag(true); return;}
    const handle = event.target.closest('[data-option-handle]');
    if (!handle || !['ArrowUp','ArrowDown','Home','End'].includes(event.key)) return;
    event.preventDefault(); const row = handle.closest('[data-option-row]');
    const items = rows(), index = items.indexOf(row);
    const target = event.key === 'Home' ? 0 : event.key === 'End' ? items.length-1 : index+(event.key === 'ArrowUp'?-1:1);
    if (target < 0 || target >= items.length || target === index) return;
    move(row,target < index ? items[target] : items[target].nextElementSibling);
    handle.focus(); announceOrder();
  });
  form.querySelector('[data-add-option]').addEventListener('click', event => {
    event.preventDefault();
    const unused = [...list.querySelectorAll('[data-option-row]')].find(row => row.hidden
      && !row.querySelector('input[name$="-DELETE"]').checked);
    if (unused) {
      unused.hidden = false; order(); unused.querySelector('input[name$="-text"]').focus(); return;
    }
    const count = Number(total.value);
    if (!Number.isInteger(count) || count >= 100) return;
    const content = template.content.cloneNode(true);
    content.querySelectorAll('*').forEach(node => {
      [...node.attributes].forEach(attr => {
        if (attr.value.includes('__prefix__')) node.setAttribute(attr.name, attr.value.replaceAll('__prefix__', String(count)));
      });
    });
    const row = content.querySelector('[data-option-row]');
    list.append(content);
    total.value = count + 1;
    controls(row); order(); row.querySelector('input[name$="-text"]').focus();
  });
  list.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    const row = button.closest('[data-option-row]');
    if (!row) return;
    if (button.matches('[data-option-remove]')) {
      row.querySelector('input[name$="-DELETE"]').checked = true;
      row.querySelector('input[type="radio"]').checked = false;
      const items = rows(), index = items.indexOf(row);
      row.hidden = true; order();
      clearValidation();
      const next = rows()[Math.min(index, rows().length - 1)];
      (next?.querySelector('input[name$="-text"]') || form.querySelector('[data-add-option]')).focus();
    } else if (button.matches('[data-option-up],[data-option-down]')) {
      const items = rows(), index = items.indexOf(row);
      const target = items[index + (button.matches('[data-option-up]') ? -1 : 1)];
      if (!target) return;
      if (button.matches('[data-option-up]')) list.insertBefore(row, target);
      else list.insertBefore(target, row);
      order(); (button.disabled ? row.querySelector('input[name$="-text"]') : button).focus();
    }
  });
  };
  if (typeof window !== 'undefined') window.initializeMasarAssessmentOptions = initialize;
  initialize();
})();
