(() => {
  document.querySelectorAll('[data-lab-formset]').forEach(group => {
    group.querySelector('[data-lab-add]').addEventListener('click', event => {
      event.preventDefault();
      const total = group.querySelector('[name="'+group.dataset.prefix+'-TOTAL_FORMS"]');
      if (Number(total.value) >= (group.dataset.prefix === 'cases' ? 200 : 100)) return;
      const html = group.querySelector('template').innerHTML.replaceAll('__prefix__',total.value);
      group.querySelector('[data-lab-rows]').insertAdjacentHTML('beforeend',html);
      total.value = Number(total.value)+1;
      const row = group.querySelector('[data-lab-rows]').lastElementChild;
      const order = row.querySelector('[name$="-ORDER"]');
      if (order) order.value = Number(total.value);
      row.querySelector('textarea,input')?.focus();
    });
  });
  const panel = document.querySelector('[data-lab-check]');
  if (!panel || !['queued','running'].includes(panel.dataset.status)) return;
  let stopped=false;
  window.addEventListener('pagehide',()=>{stopped=true;});
  async function poll(){
    if(stopped)return;
    try{
      const response=await fetch(panel.dataset.stateUrl,{headers:{Accept:'application/json'},cache:'no-store'});
      if(!response.ok || response.redirected)throw new Error('unavailable');
      const state=await response.json();
      panel.querySelector('[data-check-label]').textContent=state.label;
      panel.querySelector('[data-check-count]').textContent=(state.finished ?? 0)+' من '+(state.total ?? 0);
      panel.querySelector('[data-check-reason]').textContent=state.reason || '';
      if(['queued','running'].includes(state.status)){setTimeout(poll,2000);return;}
      const link=document.createElement('a');link.href=location.href;link.className='student-outline-button';link.textContent='تحديث الجاهزية';panel.append(link);
    }catch{panel.querySelector('[data-check-reason]').textContent='تعذر تحديث حالة الفحص؛ أعد تحميل الصفحة للمحاولة مجددًا';}
  }
  setTimeout(poll,1500);
})();
