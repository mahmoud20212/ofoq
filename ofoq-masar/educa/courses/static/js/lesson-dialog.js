(() => {
 const dialog=document.querySelector('.lesson-dialog');
 if(!dialog)return;
 const frame=dialog.querySelector('iframe');
 const loading=dialog.querySelector('.preview-loading');
 let trigger;
 let resizeObserver;
 const resizeFrame=()=>{
  if(!dialog.open || !frame.contentDocument) return;
  const body=frame.contentDocument.body;
  if(!body) return;
  const height=Math.max(130,Math.ceil(body.getBoundingClientRect().height));
  const available=Math.max(100,Math.floor(window.innerHeight*.9-dialog.querySelector('.lesson-dialog-header').getBoundingClientRect().height-4));
  frame.style.height=Math.min(height,available)+'px';
 };
 window.addEventListener('resize',resizeFrame);
 document.querySelectorAll('[data-preview-url]').forEach(button=>button.addEventListener('click',()=>{
  trigger=button;
  dialog.querySelector('h2').textContent=button.dataset.previewTitle;
  resizeObserver?.disconnect();frame.style.height='140px';frame.hidden=true;loading.hidden=false;
  frame.title=button.dataset.previewTitle;
  frame.src=button.dataset.previewUrl+'?embed=1';
  dialog.showModal();document.body.classList.add('preview-modal-open');
 }));
 frame.addEventListener('load',()=>{if(dialog.open){frame.hidden=false;loading.hidden=true;resizeFrame();resizeObserver?.disconnect();if(frame.contentDocument?.body){resizeObserver=new ResizeObserver(resizeFrame);resizeObserver.observe(frame.contentDocument.body);frame.contentDocument.fonts?.ready.then(resizeFrame);}}});
 dialog.querySelector('.dialog-close').addEventListener('click',()=>dialog.close());
 dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
 dialog.addEventListener('close',()=>{resizeObserver?.disconnect();frame.src='about:blank';frame.hidden=true;document.body.classList.remove('preview-modal-open');trigger?.focus();});
})();