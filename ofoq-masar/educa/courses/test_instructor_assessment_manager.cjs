const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source=fs.readFileSync(path.join(__dirname,'static/js/instructor-assessment-manager.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness() {
  const handlers={},events={},requests=[],refreshes=[];
  const close={disabled:false,addEventListener(){}};
  const status={textContent:''}, error={hidden:true,textContent:''};
  const focus={tagName:'H3',focus(){this.focused=true;}};
  const body={innerHTML:'',inert:false,replaceChildren(){this.innerHTML='';},setAttribute(){},removeAttribute(){},querySelectorAll:()=>[],querySelector:()=>focus,contains:()=>true};
  const dialog={open:false,querySelector:s=>s==='[data-assessment-manager-body]'?body:s==='[data-manager-error]'?error:s==='[data-manager-status]'?status:close,
    addEventListener(n,f){handlers[n]=f;},showModal(){this.open=true;},close(){this.open=false;handlers.close();}};
  const trigger={href:'http://local/teachers/revisions/10/assessments/4/',focus(){this.focused=true;}};
  let fail=false, delayed=false, release, redirects=false;
  const document={querySelector:()=>dialog,addEventListener(n,f){events[n]=f;},body:{classList:{add(){},remove(){}}}};
  const window={fetch:true,dispatchEvent(){},location:{origin:'http://local',href:'http://local/teachers/revisions/10/assessments/',pathname:'/teachers/revisions/10/assessments/'},
    MasarCurriculum:{isBusy:()=>false,refreshSaved:async(...args)=>refreshes.push(args)},initializeMasarAssessmentOptions(){window.initialized=true;}};
  vm.runInNewContext(source,{document,window,URL,Error,Event,AbortController,setTimeout,clearTimeout,FormData:class{constructor(form){this.form=form;this.extra=[];}append(...args){this.extra.push(args);}},
    fetch:async(url,options)=>{requests.push({url,options});if(delayed)await new Promise(resolve=>release=resolve);if(fail)throw Error('offline');
      const json=options.method==='POST'&&redirects;
      return {ok:true,headers:{get:()=>json?'application/json':'text/html'},json:async()=>({workspace_url:trigger.href}),text:async()=>options.method==='POST'?'form errors retained':'question list'};
    }});
  return {handlers,events,requests,refreshes,window,body,dialog,trigger,error,close,
    fail(){fail=true;},redirect(){redirects=true;},wait(){delayed=true;},release(){delayed=false;release();},
    async open(){events.click({target:{closest:()=>trigger},preventDefault(){}});await tick();},
    submit(){const form={action:trigger.href+'questions/new/'};handlers.submit({target:form,submitter:{name:'editor_action',value:'add_option'},preventDefault(){},stopPropagation(){}});return form;}};
}
test('question management opens a large workspace without navigating the document',async()=>{
  const h=harness();await h.open();assert.equal(h.dialog.open,true);assert.equal(h.body.innerHTML,'question list');
  assert.equal(h.requests[0].options.headers['X-Assessment-Workspace'],'1');assert.equal(h.window.initialized,true);
});
test('POST includes form and submitter, validation HTML remains in same dialog',async()=>{
  const h=harness();await h.open();const form=h.submit();await tick();assert.equal(h.requests[1].options.body.form,form);
  assert.deepEqual(h.requests[1].options.body.extra[0],['editor_action','add_option']);assert.equal(h.body.innerHTML,'form errors retained');assert.equal(h.dialog.open,true);
});

test('invalid question is kept in dialog without sending a save request',async()=>{
  const h=harness();await h.open();const form={action:h.trigger.href+'questions/new/',validateAssessment:()=>false};
  h.handlers.submit({target:form,preventDefault(){},stopPropagation(){}});await tick();
  assert.equal(h.requests.length,1);assert.equal(h.dialog.open,true);assert.equal(h.body.innerHTML,'question list');
});
test('successful question save follows JSON workspace URL and refreshes card only on close',async()=>{
  const h=harness();await h.open();h.redirect();h.submit();await tick();await tick();
  assert.equal(h.requests.length,3);assert.equal(h.requests[2].options.method,undefined);assert.equal(h.refreshes.length,0);
  h.dialog.close();assert.equal(h.refreshes.length,1);assert.equal(h.trigger.focused,true);
});
test('failed save retains entered form and closing refreshes server state',async()=>{
  const h=harness();await h.open();h.body.innerHTML='unsaved form';h.fail();h.submit();await tick();
  assert.equal(h.body.innerHTML,'unsaved form');assert.equal(h.error.hidden,false);assert.equal(h.body.inert,false);
  h.dialog.close();assert.equal(h.refreshes.length,1);
});
test('rapid repeated submit is serialized and Escape cannot close pending POST',async()=>{
  const h=harness();await h.open();h.wait();h.submit();h.submit();let prevented=false;
  h.handlers.cancel({preventDefault(){prevented=true;}});assert.equal(prevented,true);assert.equal(h.close.disabled,true);
  assert.equal(h.requests.length,2);h.release();await tick();assert.equal(h.close.disabled,false);
});
test('foreign manager links are rejected without fetching',async()=>{
  const h=harness();await h.open();h.handlers.click({target:{closest:selector=>selector==='a'?{href:'https://other/questions/'}:null},preventDefault(){},stopPropagation(){}});
  assert.equal(h.requests.length,1);assert.equal(h.error.hidden,false);
});

test('question deletion opens confirmation popup without GET navigation and cancel restores focus',async()=>{
  const h=harness();await h.open();const handle={disabled:false};
  const link={href:h.trigger.href+'questions/7/delete/',focus(){this.focused=true;},closest:()=>row};
  const cancel={focus(){this.focused=true;},closest:()=>confirmation};
  const row={querySelector:selector=>selector==='[data-question-confirm]'?confirmation:selector==='[data-drag-handle]'?handle:link};
  const confirmation={open:false,showModal(){this.open=true;},close(){this.open=false;},closest:()=>row,querySelector:()=>cancel};
  h.body.querySelectorAll=()=>confirmation.open?[confirmation]:[];
  h.handlers.click({target:{closest:selector=>selector==='a'?link:null},preventDefault(){},stopPropagation(){}});
  assert.equal(confirmation.open,true);assert.equal(handle.disabled,true);assert.equal(cancel.focused,true);assert.equal(h.requests.length,1);
  h.handlers.click({target:{closest:selector=>selector==='[data-question-delete-cancel]'?cancel:null},preventDefault(){},stopPropagation(){}});
  assert.equal(confirmation.open,false);assert.equal(handle.disabled,false);assert.equal(link.focused,true);assert.equal(h.requests.length,1);
});
