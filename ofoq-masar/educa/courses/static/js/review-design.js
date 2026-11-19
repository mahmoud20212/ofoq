(() => {
 const picker=document.querySelector('.rating-picker');
 if(!picker)return;
 const options=[...picker.querySelectorAll('input[type=radio]')];
 picker.addEventListener('change',()=>{
  const value=Number(options.find(input=>input.checked)?.value || 0);
  options.forEach(input=>input.closest('label').classList.toggle('rating-filled',Number(input.value)<=value));
  picker.querySelector('.rating-caption').textContent=`${value} من 5 — معاينة للتقييم`;
 });
})();
