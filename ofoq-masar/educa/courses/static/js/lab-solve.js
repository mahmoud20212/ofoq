/* Native accessible code input; no remote assets or execution in the page. */
(function (global) {
  'use strict';
  function saveController(initial, revision, send, notify) {
    let confirmed=initial, current=initial, busy=false, blocked=false, rev=revision;
    return {
      edit(value){current=value;}, dirty(){return current!==confirmed;},
      get blocked(){return blocked;},
      load(value,number){current=confirmed=value;rev=number;blocked=false;},
      async save(force=false){
        if(busy||blocked||(!force&&current===confirmed))return;
        busy=true; const submitted=current;notify('saving');
        try {const response=await send(submitted,rev);confirmed=submitted;rev=response.revision;
          notify(current===confirmed?'saved':'dirty');
        } catch(error){if(error.status===409)blocked=true;notify(blocked?'conflict':'failed',error);}
        finally{busy=false;}
      }
    };
  }
  function tokens(source,language){
    const python=/python/i.test(language),cpp=/c\+\+|cpp/i.test(language);
    const pattern=python?/(#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b(?:def|class|return|if|else|elif|for|while|in|import|from|as|True|False|None|and|or|not|print|input)\b|\b\d+(?:\.\d+)?\b)/g:
      /(\/\/[^\n]*|\/\*[\s\S]*?\*\/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b(?:const|let|var|function|return|if|else|for|while|class|new|true|false|null|int|double|char|void|include|using|namespace|std|auto|cout|cin)\b|\b\d+(?:\.\d+)?\b)/g;
    let end=0,parts=[];
    for(const match of source.matchAll(pattern)){if(match.index>end)parts.push({text:source.slice(end,match.index)});
      const text=match[0],type=/^(#|\/\/|\/\*)/.test(text)?'comment':/^["'`]/.test(text)?'string':/^\d/.test(text)?'number':'keyword';
      parts.push({text,type});end=match.index+text.length;}
    parts.push({text:source.slice(end)});return parts;
  }
  const core={saveController,tokens};
  if(typeof module!=='undefined'&&module.exports)module.exports=core;
  if(!global.document)return;
  const root=document.getElementById('lab-solve');if(!root)return;
  const config=JSON.parse(document.getElementById('lab-config').textContent);
  const $=selector=>root.querySelector(selector),all=selector=>Array.from(root.querySelectorAll(selector));
  const source=$('#lab-source'),highlight=$('.lab-highlight'),paint=highlight.querySelector('code'),lines=$('.lab-lines');
  let timer,composing=false,highlightFrame,history=[source.value],historyIndex=0,pollTimer,runRecord=null,runPending=null,creating=false,polling=false;
  function notice(message,login=false){$('[data-notice]').textContent=message;$('[data-login]').hidden=!login;$('.lab-notice').hidden=false;}
  function runFeedback(message='',login=false){
    $('[data-run-message]').textContent=message;
    $('[data-run-login]').hidden=!login;
    $('[data-run-feedback]').hidden=!message;
  }
  async function request(url,payload){
    const abort=new AbortController(),timeout=setTimeout(()=>abort.abort(),15000);
    try {const response=await fetch(url,{method:payload?'POST':'GET',credentials:'same-origin',signal:abort.signal,
      headers:payload?{'Content-Type':'application/json','X-CSRFToken':root.querySelector('[name=csrfmiddlewaretoken]').value}:{},
      body:payload?JSON.stringify(payload):undefined});
      const data=await response.json().catch(()=>null);
      if(!response.ok||!data){
        const fallback = response.redirected || response.status === 401
          ? 'انتهت جلسة الدخول. سجّل الدخول مجددًا.'
          : response.status === 403
            ? 'رُفض الطلب. حدّث الصفحة ثم أعد المحاولة.'
            : response.status >= 500
              ? 'تعذّر على الخادم تأكيد الطلب. حاول استرجاع الحالة.'
              : 'أعاد الخادم استجابة غير متوقعة.';
        const error=new Error(data?.error?.message||fallback);
        error.status=response.redirected&&!data?401:response.status;
        throw error;
      }
      return data;
    }catch(error){
      if(error.name==='AbortError')throw new Error('انتهت مهلة الاتصال قبل تأكيد الطلب.');
      if(error instanceof TypeError)throw new Error('تعذّر الاتصال بالخادم. تحقق من اتصالك.');
      throw error;
    }finally{clearTimeout(timeout);}
  }
  const saves=saveController(source.value,config.draft.revision,(code,revision)=>request(config.save_url,{code,revision}),(state,error)=>{
    const messages={saving:'جارٍ الحفظ',saved:'تم الحفظ',dirty:'تغييرات غير محفوظة',failed:'تعذر الحفظ · أعد المحاولة',conflict:'تعارض الحفظ · كودك لم يُستبدل'};
    $('[data-save-state]').textContent=messages[state];
    if(state==='conflict'){$('.lab-conflict').hidden=false;clearTimeout(timer);}
    if(error&&state!=='conflict')notice(error.message,error.status===401);
    if(state==='dirty')schedule();
  });
  function schedule(){clearTimeout(timer);if(!composing&&!saves.blocked)timer=setTimeout(()=>saves.save(),900);}
  function draw(){paint.replaceChildren();const fragment=document.createDocumentFragment();
    for(const part of tokens(source.value,config.draft.language.name)){const node=document.createElement('span');node.textContent=part.text;if(part.type)node.className='lab-token-'+part.type;fragment.append(node);}
    fragment.append(document.createTextNode('\n'));paint.append(fragment);
    lines.textContent=Array.from({length:source.value.split('\n').length},(_,i)=>i+1).join('\n');syncScroll();}
  function syncScroll(){highlight.scrollTop=source.scrollTop;highlight.scrollLeft=source.scrollLeft;lines.scrollTop=source.scrollTop;}
  function changed(record=true){if(record){history=history.slice(0,historyIndex+1);history.push(source.value);if(history.length>100)history.shift();historyIndex=history.length-1;}
    saves.edit(source.value);$('[data-save-state]').textContent=saves.blocked?'تعارض الحفظ · كودك لم يُستبدل':'تغييرات غير محفوظة';schedule();
    cancelAnimationFrame(highlightFrame);highlightFrame=requestAnimationFrame(draw);}
  source.addEventListener('input',()=>changed());source.addEventListener('scroll',syncScroll);
  source.addEventListener('compositionstart',()=>{composing=true;clearTimeout(timer);});source.addEventListener('compositionend',()=>{composing=false;schedule();});
  function undo(delta){const next=historyIndex+delta;if(next<0||next>=history.length)return;historyIndex=next;source.value=history[next];changed(false);source.focus();}
  $('[data-undo]').onclick=()=>undo(-1);$('[data-redo]').onclick=()=>undo(1);
  source.addEventListener('keydown',event=>{if(event.isComposing)return;if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();saves.save(true);}
    if((event.ctrlKey||event.metaKey)&&['z','y'].includes(event.key.toLowerCase())){event.preventDefault();undo(event.shiftKey||event.key.toLowerCase()==='y'?1:-1);}});
  $('[data-save]').onclick=()=>saves.save(true);
  all('[data-copy]').forEach(button=>button.onclick=async()=>{try{await navigator.clipboard.writeText(source.value);$('[data-save-state]').textContent='تم نسخ الكود';}catch(_){source.focus();source.select();notice('تعذّر النسخ التلقائي؛ اضغط Ctrl+C لنسخ الكود المحدد');}});
  $('[data-reload]').onclick=async()=>{if(!global.confirm('سيُستبدل كودك الحالي بالنسخة المحفوظة. هل نسخت تعديلاتك وتريد المتابعة؟'))return;
    const before=source.value;
    try{const data=await request(config.read_url);if(!data.editable)throw new Error('هذه النسخة لم تعد قابلة للتعديل؛ احتفظ بكودك وافتح التحدي مجددًا');
      if(source.value!==before)throw new Error('كتبت تعديلات أثناء التحميل؛ احتفظنا بها. أعد طلب التحميل عندما تكون مستعدًا');
      source.value=data.code;saves.load(data.code,data.revision);history=[data.code];historyIndex=0;$('.lab-conflict').hidden=true;$('[data-save-state]').textContent=data.saved?'تم تحميل النسخة المحفوظة':'تم تحميل كود البداية';draw();
    }catch(error){notice(error.message,error.status===401);}};
  global.addEventListener('beforeunload',event=>{if(saves.dirty()){event.preventDefault();event.returnValue='';}});
  function tab(name){root.dataset.active=name;all('[data-tab]').forEach(button=>{const selected=button.dataset.tab===name;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;});}
  all('[data-tab]').forEach((button,index)=>{button.onclick=()=>tab(button.dataset.tab);button.onkeydown=event=>{let next=index;
    if(event.key==='ArrowLeft')next=(index+1)%3;else if(event.key==='ArrowRight')next=(index+2)%3;else if(event.key==='Home')next=0;else if(event.key==='End')next=2;else return;
    event.preventDefault();const target=all('[data-tab]')[next];tab(target.dataset.tab);target.focus();};});tab('problem');root.classList.add('is-ready');
  const splitter=$('.lab-splitter'),workspace=$('.lab-workspace');let width=34;
  function resize(value){width=Math.min(45,Math.max(25,value));workspace.style.setProperty('--problem-width',width+'%');splitter.setAttribute('aria-valuenow',String(Math.round(width)));}
  splitter.onpointerdown=event=>{splitter.setPointerCapture(event.pointerId);};splitter.onpointermove=event=>{if(!splitter.hasPointerCapture(event.pointerId))return;const box=workspace.getBoundingClientRect();resize((box.right-event.clientX)/box.width*100);};splitter.onpointerup=event=>splitter.releasePointerCapture(event.pointerId);
  splitter.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();resize(event.key==='Home'?25:event.key==='End'?45:width+(event.key==='ArrowLeft'?3:-3));};
  const stdin=$('#lab-stdin');
  const runButton=$('[data-run]'), verifyButton=$('[data-verify]'), customButton=$('[data-custom]');
  function ioTab(name){all('[data-io-tab]').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.ioTab===name)));all('[data-io-pane]').forEach(pane=>{pane.hidden=pane.dataset.ioPane!==name;});}
  all('[data-io-tab]').forEach(button=>button.onclick=()=>ioTab(button.dataset.ioTab));
  customButton.onclick=()=>{tab('results');ioTab('input');stdin.focus();};
  let ioHeight=34;const horizontal=$('.lab-horizontal-splitter'),coding=$('.lab-coding');
  function resizeIo(value){ioHeight=Math.min(60,Math.max(20,value));coding.style.setProperty('--io-height',ioHeight+'%');horizontal.setAttribute('aria-valuenow',String(Math.round(ioHeight)));}
  horizontal.onpointerdown=event=>horizontal.setPointerCapture(event.pointerId);horizontal.onpointermove=event=>{if(!horizontal.hasPointerCapture(event.pointerId))return;const box=coding.getBoundingClientRect();resizeIo((box.bottom-event.clientY)/box.height*100);};horizontal.onpointerup=event=>horizontal.releasePointerCapture(event.pointerId);
  horizontal.onkeydown=event=>{if(!['ArrowUp','ArrowDown','Home','End'].includes(event.key))return;event.preventDefault();resizeIo(event.key==='Home'?20:event.key==='End'?60:ioHeight+(event.key==='ArrowUp'?3:-3));};
  $('[data-reset]').onclick=()=>{if(source.value===config.starter_code)return;if(!global.confirm('سيُستبدل الكود الحالي بكود البداية. هل تريد المتابعة؟'))return;
    source.value=config.starter_code;history=history.slice(0,historyIndex+1);history.push(source.value);historyIndex=history.length-1;changed(false);source.focus();};
  const fullscreenButton=$('[data-fullscreen]');
  function fullscreenState(){const active=document.fullscreenElement===root;const label=active?'الخروج من ملء الشاشة':'ملء الشاشة';fullscreenButton.setAttribute('aria-label',label);fullscreenButton.title=label;fullscreenButton.dataset.tooltip=label;const use=fullscreenButton.querySelector('use');if(use)use.setAttribute('href',use.getAttribute('href').replace(/#(?:expand|minimize-2)$/,'#'+(active?'minimize-2':'expand')));}
  fullscreenButton.onclick=async()=>{try{if(document.fullscreenElement===root)await document.exitFullscreen();else await root.requestFullscreen();}catch(_){notice('تعذر فتح وضع ملء الشاشة في هذا المتصفح');}};
  document.addEventListener('fullscreenchange',fullscreenState);document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.fullscreenElement===root)document.exitFullscreen().catch(()=>{});});
  function remember(){try{if(runRecord)localStorage.setItem(config.storage_key,JSON.stringify({url:runRecord}));else localStorage.removeItem(config.storage_key);}catch(_){}}
  function setBusy(busy){
    runButton.disabled=busy||!config.run_enabled||!config.examples.length;
    customButton.disabled=busy||!config.run_enabled;
    $('[data-run-custom]').disabled=busy||!config.run_enabled;
    verifyButton.disabled=busy||!config.submission_enabled;
  }
  function runReady(){creating=false;setBusy(false);}
  async function poll(){clearTimeout(pollTimer);if(!runRecord||polling)return;polling=true;
    try{const data=await request(runRecord);runFeedback(data.error_message||'');$('[data-run-state]').textContent=data.verdict_label||data.status_label;
      const output=$('[data-output]');
      if(data.submission_id){
        $('[data-run-state]').textContent=!data.terminal?'التحقّق قيد المعالجة':data.passed?'تم حل التحدي':data.error_message?'تعذّر التحقق':'الحل لم يجتز جميع الحالات';
        const hidden=data.hidden_summary;
        $('[data-hidden-summary]').textContent=data.terminal&&hidden.total?'الحالات المخفية: اجتاز '+hidden.passed+' من '+hidden.total:'';
        output.textContent=data.visible_results.flatMap((item,index)=>item.verdict?[
          'الحالة '+(index+1)+' — '+({accepted:'مطابق',wrong_answer:'غير مطابق',compile_error:'خطأ ترجمة',runtime_error:'خطأ تشغيل',time_limit:'تجاوز الوقت',memory_limit:'تجاوز الذاكرة',output_limit:'تجاوز حد المخرجات'}[item.verdict]||'تعذّر التنفيذ'),
          item.stdout,item.stderr,item.compile_output
        ].filter(Boolean):[]).join('\n');
      }else{
        if(typeof data.example_matches==='boolean')$('[data-run-state]').textContent=data.example_matches?'الناتج مطابق للمثال':'الناتج غير مطابق للمثال';
        output.textContent=[data.stdout,data.stderr,data.compile_output].filter(Boolean).join('\n');
      }
      if(data.terminal){runRecord=null;remember();runReady();$('[data-resume]').hidden=true;}
      else if(data.needs_operator_review||data.phase==='uncertain'){runFeedback('حالة التنفيذ غير محسومة وتحتاج مراجعة المشغّل');$('[data-resume]').hidden=false;}
      else pollTimer=setTimeout(poll,1500);
    }catch(error){runFeedback(error.message,error.status===401);$('[data-resume]').hidden=false;$('[data-run-state]').textContent='تعذّر استرجاع حالة التشغيل';}finally{polling=false;}}
  async function sendRun(){if(creating||!runPending)return;creating=true;setBusy(true);$('[data-run-state]').textContent='جارٍ قبول الطلب';
    runFeedback();
    $('[data-output]').textContent='';
    $('[data-hidden-summary]').textContent='';
    try{const data=await request(runPending.url,runPending.payload);runRecord=data.status_url;runPending=null;remember();$('[data-resume]').hidden=true;poll();}
    catch(error){creating=false;runFeedback(error.message,error.status===401);$('[data-run-state]').textContent='';
      if(error.status>=400&&error.status<500){runPending=null;runReady();}else{$('[data-resume]').hidden=false;}}
  }
  function execute(url,inputs={}){
    if(runRecord||runPending||creating)return;
    if(!source.value.trim()){tab('results');ioTab('output');runFeedback('اكتب الكود أولًا.');return;}
    runPending={url,payload:{request_id:crypto.randomUUID(),version_id:config.draft.version_id,code:source.value,...inputs}};
    tab('results');ioTab('output');sendRun();};
  runButton.onclick=()=>execute(config.run_url,{example_id:config.examples[0].id});
  $('[data-run-custom]').onclick=()=>execute(config.run_url,{stdin:stdin.value});
  verifyButton.onclick=()=>execute(config.submission_url);
  runReady();
  $('[data-resume]').onclick=()=>{if(runPending)sendRun();else poll();};$('[data-dismiss]').onclick=()=>{$('.lab-notice').hidden=true;};
  try{const saved=JSON.parse(localStorage.getItem(config.storage_key));if(saved&&/^\/lab\/(runs|submissions)\/\d+\/$/.test(saved.url)){runRecord=saved.url;setBusy(true);tab('results');ioTab('output');poll();}}catch(_){}
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&runRecord)poll();});draw();
})(typeof window==='undefined'?globalThis:window);
