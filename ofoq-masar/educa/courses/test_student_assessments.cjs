const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'static/js/student-assessments.js'),'utf8');

function harness({fetchSupported=true, dialogSupported=true, autoSave=false}={}) {
  const calls=[],timers=[],events={},notices=[],navigation=[];
  const control=()=>({hidden:false,disabled:false,textContent:'',events:{},
    addEventListener(name,fn){this.events[name]=fn;},focus(){this.focused=true;}});
  const save=control(),submit=control(),recover=control(),status=control(),error=control(),login=control(),count=control();
  recover.hidden=error.hidden=login.hidden=true;
  const csrf={value:'initial-csrf'};
  const questions=['10','20'].map(key=>({dataset:{assessmentQuestion:key},value:'',disabled:false,
    querySelector(){return {value:this.value};}}));
  const form={dataset:{saveUrl:'/save/',submitUrl:'/submit/',readUrl:'/read/',resultUrl:'/summary/',loginUrl:'/login/',assessmentAutosave:String(autoSave)},
    events:{},attrs:{},querySelectorAll:()=>questions,addEventListener(name,fn){this.events[name]=fn;},
    setAttribute(name,value){this.attrs[name]=value;},querySelector(key){return {
      '[data-assessment-save]':save,'[data-assessment-submit]':submit,'[data-assessment-recover]':recover,
      '[data-save-status]':status,'[data-request-error]':error,'[data-assessment-login]':login,
      '[name="csrfmiddlewaretoken"]':csrf,'[data-answered-count]':count}[key];}};
  const cancel=control(),confirm=control(),unanswered=control();
  const dialog={open:false,events:{},showModal:dialogSupported?function(){this.open=true;}:undefined,
    close(){this.open=false;this.events.close?.();},addEventListener(name,fn){this.events[name]=fn;},
    querySelectorAll:()=>[cancel],querySelector:key=>key==='[data-unanswered-count]'?unanswered:confirm};
  const fetch=(url,options)=>new Promise((resolve,reject)=>{
    calls.push({url,options,resolve,reject});
    options.signal?.addEventListener('abort',()=>reject(new Error('AbortError')));
  });
  const window={fetch:fetchSupported?fetch:undefined,AbortController,
    location:{assign:url=>navigation.push(url)},addEventListener:(name,fn)=>events[name]=fn,
    appAlerts:{show:(message,level,action)=>{notices.push({message,level,action});return {dismiss(){}};}}};
  const document={querySelectorAll:()=>[],querySelector:key=>key==='[data-assessment-form]'?form:dialog,
    getElementById:()=>({textContent:JSON.stringify(questions.map(q=>({question_key:q.dataset.assessmentQuestion,option_key:''})))})};
  const cancelledTimers=new Set();
  vm.runInNewContext(source,{window,document,setTimeout:fn=>{const id=timers.length+1;timers.push(()=>{if(!cancelledTimers.has(id))fn();});return id;},clearTimeout:id=>cancelledTimers.add(id)});
  const flush=async()=>{await new Promise(setImmediate);await new Promise(setImmediate);};
  const response=(data,status=200,token=null)=>({ok:status>=200&&status<300,status,redirected:false,
    headers:{get:()=>token},json:async()=>data});
  const data=(selections=['',''])=>({attempt_id:1,status:'in_progress',questions:questions.map((q,i)=>({question_key:q.dataset.assessmentQuestion,selected_option_key:selections[i]}))});
  const change=(index,value)=>{questions[index].value=value;form.events.change();};
  const press=action=>form.events.submit({preventDefault(){},submitter:{value:action}});
  return {form,questions,save,submit,recover,status,error,login,count,csrf,dialog,cancel,confirm,unanswered,
    calls,timers,events,notices,navigation,flush,response,data,change,press};
}

test('save success is announced only after server confirmation and preserves clear-choice contract',async()=>{
  const h=harness();h.change(0,'101');h.press('save');
  assert.equal(h.status.textContent,'جارٍ الحفظ');assert.equal(h.save.disabled,true);
  assert.deepEqual(JSON.parse(h.calls[0].options.body).answers,[{question_key:'10',option_key:'101'},{question_key:'20',option_key:''}]);
  assert.equal(h.calls[0].options.headers['X-CSRFToken'],'initial-csrf');
  h.calls[0].resolve(h.response(h.data(['101',''])));await h.flush();
  assert.equal(h.status.textContent,'تم الحفظ');
  h.change(0,'');h.press('save');assert.equal(JSON.parse(h.calls[1].options.body).answers[0].option_key,'');
  h.calls[1].resolve(h.response(h.data()));await h.flush();assert.equal(h.count.textContent,'0');
});
test('an older save response cannot overwrite choices edited while saving',async()=>{
  const h=harness();h.change(0,'101');h.press('save');h.change(0,'102');
  h.press('save');h.press('confirm_submit');assert.equal(h.calls.length,1);assert.equal(h.dialog.open,false);
  h.calls[0].resolve(h.response(h.data(['101',''])));await h.flush();
  assert.equal(h.questions[0].value,'102');assert.equal(h.status.textContent,'تغييرات غير محفوظة');
  h.press('save');assert.equal(JSON.parse(h.calls[1].options.body).answers[0].option_key,'102');
});
test('save failure leaves choices and beforeunload protection intact, retry uses current choices',async()=>{
  const h=harness();h.change(0,'101');h.press('save');h.calls[0].reject(new Error('offline'));await h.flush();
  assert.equal(h.questions[0].value,'101');assert.equal(h.status.textContent,'تعذر الحفظ');assert.equal(h.save.disabled,false);
  let prevented=false;const event={preventDefault(){prevented=true;}};h.events.beforeunload(event);assert.equal(prevented,true);
  h.change(1,'201');const retry=h.notices.at(-1).action.run();assert.equal(h.calls.length,2);
  h.calls[1].resolve(h.response(h.data(['101','201'])));await retry;
});
test('confirmation counts unanswered and submission includes current unsaved choices',async()=>{
  const h=harness();h.change(0,'101');h.press('confirm_submit');assert.equal(h.dialog.open,true);assert.equal(h.unanswered.textContent,'1');
  h.cancel.events.click();assert.equal(h.dialog.open,false);assert.equal(h.calls.length,0);
  h.press('confirm_submit');h.confirm.events.click();assert.equal(h.questions[0].disabled,true);assert.equal(h.save.disabled,true);
  assert.equal(JSON.parse(h.calls[0].options.body).answers[0].option_key,'101');
  h.calls[0].resolve(h.response({attempt_id:1,status:'submitted',result:{passed:true}}));await h.flush();
  assert.deepEqual(h.navigation,['/summary/']);let warned=false;h.events.beforeunload({preventDefault(){warned=true;}});assert.equal(warned,false);
});
test('lost submission response requires read recovery and never starts another attempt',async()=>{
  const h=harness();h.change(0,'101');h.press('confirm_submit');h.confirm.events.click();
  h.calls[0].reject(new Error('connection lost after commit'));await h.flush();
  assert.equal(h.recover.hidden,false);assert.equal(h.submit.disabled,true);assert.equal(h.questions[0].value,'101');
  h.recover.events.click();assert.equal(h.calls[1].url,'/read/');assert.equal(h.calls[1].options.method,'GET');
  h.calls[1].resolve(h.response({attempt_id:1,status:'submitted',result:{passed:true}}));await h.flush();
  assert.deepEqual(h.navigation,['/summary/']);assert.equal(h.calls.length,2);
});
test('recovery of an active attempt preserves unsaved choices and enables a deliberate retry',async()=>{
  const h=harness();h.change(0,'101');h.press('confirm_submit');h.confirm.events.click();h.calls[0].reject(new Error('lost'));await h.flush();
  h.recover.events.click();h.calls[1].resolve(h.response(h.data()));await h.flush();
  assert.equal(h.questions[0].value,'101');assert.equal(h.submit.disabled,false);assert.equal(h.recover.hidden,true);
  assert.match(h.status.textContent,/غير محفوظة/);h.press('confirm_submit');h.confirm.events.click();assert.equal(h.calls.length,3);
});
test('expired session preserves answers, then recovery refreshes CSRF after login in another tab',async()=>{
  const h=harness();h.change(0,'101');h.press('save');h.calls[0].resolve(h.response({},401));await h.flush();
  assert.equal(h.login.hidden,false);assert.equal(h.questions[0].value,'101');assert.equal(h.save.disabled,true);
  h.recover.events.click();h.calls[1].resolve(h.response(h.data(),200,'new-csrf'));await h.flush();
  assert.equal(h.save.disabled,false);h.press('save');assert.equal(h.calls[2].options.headers['X-CSRFToken'],'new-csrf');
});
test('403 from CSRF checks session before claiming an expired login',async()=>{
  const h=harness();h.change(0,'101');h.press('save');h.calls[0].resolve(h.response({},403));await h.flush();
  assert.equal(h.calls[1].url,'/read/');h.calls[1].resolve(h.response({},401));await h.flush();assert.equal(h.login.hidden,false);
});
test('submission validation failure is retryable without dropping choices',async()=>{
  const h=harness();h.change(1,'201');h.press('confirm_submit');h.confirm.events.click();
  h.calls[0].resolve(h.response({error:'invalid_request',detail:'أعد المحاولة'},400));await h.flush();
  assert.equal(h.questions[1].value,'201');assert.equal(h.submit.disabled,false);assert.equal(h.recover.hidden,true);
});
test('submission timeout also enters uncertain-state recovery',async()=>{
  const h=harness();h.change(0,'101');h.press('confirm_submit');h.confirm.events.click();h.timers[0]();await h.flush();
  assert.equal(h.recover.hidden,false);assert.equal(h.submit.disabled,true);
});
test('a response for another attempt is never acknowledged as saved',async()=>{
  const h=harness();h.form.dataset.readUrl='/attempts/1/';h.change(0,'101');h.press('save');
  h.calls[0].resolve(h.response({...h.data(),attempt_id:2}));await h.flush();
  assert.equal(h.status.textContent,'تعذر الحفظ');assert.equal(h.questions[0].value,'101');
});
test('failed recovery retains the uncertain state and permits another read retry',async()=>{
  const h=harness();h.change(0,'101');h.press('confirm_submit');h.confirm.events.click();h.calls[0].reject(new Error('lost'));await h.flush();
  h.recover.events.click();h.calls[1].reject(new Error('offline'));await h.flush();
  assert.equal(h.submit.disabled,true);assert.equal(h.recover.hidden,false);assert.equal(h.recover.disabled,false);assert.equal(h.questions[0].value,'101');
});
test('without fetch or native dialog support ordinary POST forms remain functional',()=>{
  for (const options of [{fetchSupported:false},{dialogSupported:false}]) {
    const h=harness(options);assert.equal(h.form.events.submit,undefined);assert.equal(h.save.disabled,false);
  }
});

test('autosave debounces choices and confirms saving only after server response',async()=>{
  const h=harness({autoSave:true});assert.equal(h.save.hidden,true);
  h.change(0,'101');h.change(0,'102');assert.equal(h.calls.length,0);
  h.timers[0]();assert.equal(h.calls.length,0);
  h.timers[1]();assert.equal(h.calls.length,1);assert.equal(h.status.textContent,'جارٍ الحفظ');
  assert.equal(JSON.parse(h.calls[0].options.body).answers[0].option_key,'102');
  h.calls[0].resolve(h.response(h.data(['102',''])));await h.flush();
  assert.equal(h.status.textContent,'تم الحفظ');assert.equal(h.save.hidden,true);
});
test('autosave serializes a newer choice behind an in-flight save',async()=>{
  const h=harness({autoSave:true});h.change(0,'101');h.timers[0]();
  h.change(0,'102');h.timers.at(-1)();assert.equal(h.calls.length,1);
  h.calls[0].resolve(h.response(h.data(['101',''])));await h.flush();
  h.timers.at(-1)();assert.equal(h.calls.length,2);
  assert.equal(JSON.parse(h.calls[1].options.body).answers[0].option_key,'102');
  h.calls[1].resolve(h.response(h.data(['102',''])));await h.flush();
  assert.equal(h.status.textContent,'تم الحفظ');
});
test('failed autosave retains choices without a retry loop and exposes explicit retry',async()=>{
  const h=harness({autoSave:true});h.change(0,'101');h.timers[0]();
  h.calls[0].reject(new Error('offline'));await h.flush();
  assert.equal(h.questions[0].value,'101');assert.equal(h.status.textContent,'تعذر الحفظ');
  assert.equal(h.calls.length,1);
  h.notices.at(-1).action.run();assert.equal(h.calls.length,2);
  h.calls[1].resolve(h.response(h.data(['101',''])));await h.flush();assert.equal(h.status.textContent,'تم الحفظ');
});
test('submission cancels pending autosave and sends current choices exactly once',async()=>{
  const h=harness({autoSave:true});h.change(0,'101');h.press('confirm_submit');
  h.timers[0]();assert.equal(h.calls.length,0);h.confirm.events.click();
  h.timers.forEach(timer=>timer());assert.equal(h.calls.length,1);assert.equal(h.calls[0].url,'/submit/');
});
test('clear choice is autosaved and expired sessions block later automatic writes',async()=>{
  const h=harness({autoSave:true});h.change(0,'101');h.timers[0]();
  h.calls[0].resolve(h.response(h.data(['101',''])));await h.flush();
  h.change(0,'');h.timers.at(-1)();assert.equal(JSON.parse(h.calls[1].options.body).answers[0].option_key,'');
  h.calls[1].resolve(h.response({},401));await h.flush();
  assert.equal(h.login.hidden,false);assert.equal(h.submit.disabled,true);
});

test('a newly locked assessment preserves answers, stops autosave and permits recovery after requirements are restored',async()=>{
  const h=harness({autoSave:true});h.change(0,'101');h.timers[0]();
  h.calls[0].resolve(h.response({error:'prerequisites_not_met',detail:'أكمل محتويات الوحدة أولًا'},409));await h.flush();
  assert.equal(h.questions[0].value,'101');assert.equal(h.submit.disabled,true);
  assert.equal(h.recover.hidden,false);assert.match(h.notices.at(-1).message,/أكمل محتويات الوحدة/);
  h.recover.events.click();h.calls[1].resolve(h.response(h.data()));await h.flush();
  assert.equal(h.submit.disabled,false);h.timers.at(-1)();assert.equal(h.calls[2].url,'/save/');
});
test('prerequisite failure at submission is not reported as a completed attempt',async()=>{
  const h=harness();h.change(0,'101');h.press('confirm_submit');h.confirm.events.click();
  h.calls[0].resolve(h.response({error:'prerequisites_not_met',detail:'أكمل محتويات الدورة'},409));await h.flush();
  assert.equal(h.navigation.length,0);assert.equal(h.submit.disabled,true);assert.equal(h.recover.hidden,false);
  assert.equal(h.questions[0].value,'101');
});
