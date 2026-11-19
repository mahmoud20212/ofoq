const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, 'static/js/instructor-curriculum.js'), 'utf8');
function harness(tabs=false) {
  const events = {}, windowEvents={}, requests = [], alerts = [], dispatched = [];
  const root = {dataset:tabs?{revisionId:'10',contentTabUrl:'/teachers/revisions/10/?step=curriculum',assessmentTabUrl:'/teachers/revisions/10/assessments/'}:{},children:['old'], inert:false, setAttribute() {}, removeAttribute() {}, replaceChildren(...nodes) {this.children=nodes;}};
  const closeButton = {disabled:false};
  const dialog = {closed:false, addEventListener() {}, removeEventListener() {}, querySelectorAll:()=>[closeButton], close() {this.closed=true;}};
  const form = {action:'http://local/teachers/revisions/10/module/3/delete/', dataset:{}, closest:()=>dialog};
  let failed=false, pending=false, release, valid=true, sortBusy=false;
  const window = {fetch:true, DOMParser:true, location:{href:'http://local/teachers/revisions/10/?step=curriculum',origin:'http://local',pathname:'/teachers/revisions/10/'},
    history:{state:null,replaceState(_,__,url) {this.url=url;},pushState(_,__,url){this.url=url;this.pushed=true;}}, appAlerts:{show(...args){alerts.push(args);}}, dispatchEvent(e){dispatched.push(e.type);},addEventListener(name,fn){windowEvents[name]=fn;}};
  const document = {querySelector(s) {if(s==='[data-curriculum-builder][aria-busy="true"]') return sortBusy?{}:null; if(s==='[data-curriculum-page]')return root; return null;}, addEventListener(n,fn){events[n]=fn;}};
  class Parser {parseFromString(){return {querySelector:()=>valid?{dataset:root.dataset,childNodes:['new']}:null};}}
  vm.runInNewContext(source,{document,window,URL,Error,AbortController,Event,DOMParser:Parser,setTimeout,clearTimeout,
    FormData:class{constructor(value){this.form=value;}}, fetch:async(url,options)=>{
      requests.push({url,options}); if(pending)await new Promise(resolve=>release=resolve); if(failed)throw new Error('offline');
      return options.method==='POST'?{ok:true,json:async()=>({redirect_url:'/teachers/revisions/10/?step=curriculum',message:'deleted'})}:{ok:true,text:async()=>'<page>'};
    }});
  return {window,root,requests,alerts,dispatched,events,windowEvents,form,dialog,closeButton,
    fail(value=true){failed=value;}, invalid(){valid=false;}, wait(){pending=true;}, release(){pending=false;release();}, sortBusy(){sortBusy=true;}};
}
test('refresh replaces only curriculum and updates module URL, then reinitializes sorting',async()=>{
  const h=harness();await h.window.MasarCurriculum.refresh('/teachers/revisions/10/?step=curriculum&module=4');
  assert.deepEqual(h.root.children,['new']);assert.equal(h.root.inert,false);
  assert.deepEqual(h.dispatched,['masar:curriculum-before-update','masar:curriculum-updated']);
  assert.match(h.window.history.url,/module=4/);assert.equal(h.requests[0].options.credentials,'same-origin');
});
test('failed refresh retains old curriculum and offers GET-only retry after successful mutation',async()=>{
  const h=harness();h.fail();assert.equal(await h.window.MasarCurriculum.refreshSaved('/teachers/revisions/10/','saved'),false);
  assert.deepEqual(h.root.children,['old']);assert.equal(h.root.inert,false);
  h.fail(false);await h.alerts[0][2].run();assert.equal(h.requests.length,2);
  assert.ok(h.requests.every(r=>r.options.method!=='POST'));assert.deepEqual(h.root.children,['new']);
});
test('login or malformed HTML is not accepted as a curriculum update',async()=>{
  const h=harness();h.invalid();await assert.rejects(h.window.MasarCurriculum.refresh('/teachers/revisions/10/'));
  assert.deepEqual(h.root.children,['old']);assert.equal(h.dispatched.length,0);
});
test('cross-origin and unrelated navigation are rejected without fetching',async()=>{
  const h=harness();await assert.rejects(h.window.MasarCurriculum.refresh('https://other/teachers/revisions/10/'));
  await assert.rejects(h.window.MasarCurriculum.refresh('/teachers/revisions/11/'));assert.equal(h.requests.length,0);
});
test('duplicate refreshes and mutations while sorting are blocked',async()=>{
  const h=harness();h.wait();const first=h.window.MasarCurriculum.refresh('/teachers/revisions/10/');
  await assert.rejects(h.window.MasarCurriculum.refresh('/teachers/revisions/10/'));h.release();await first;
  h.sortBusy();await assert.rejects(h.window.MasarCurriculum.refresh('/teachers/revisions/10/'));assert.equal(h.requests.length,1);
});
test('confirmed deletion posts existing CSRF form once, then fetches the new curriculum',async()=>{
  const h=harness();const event={target:{closest:()=>h.form},preventDefault(){this.prevented=true;},stopImmediatePropagation(){}};
  await h.events.submit(event);assert.equal(event.prevented,true);assert.equal(h.dialog.closed,true);
  assert.equal(h.requests.length,2);assert.equal(h.requests[0].options.method,'POST');
  assert.equal(h.requests[0].options.body.form,h.form);assert.equal(h.requests[0].options.headers['X-Curriculum-Action'],'1');
  assert.equal(h.closeButton.disabled,false);assert.deepEqual(h.root.children,['new']);
});
test('step navigation is not intercepted and failed deletion offers read recovery',async()=>{
  const h=harness();h.form.action='http://local/teachers/revisions/10/submit/';
  await h.events.submit({target:{closest:()=>h.form},preventDefault(){throw Error('must stay native');}});assert.equal(h.requests.length,0);
  h.form.action='http://local/teachers/revisions/10/module/3/delete/';h.fail();
  await h.events.submit({target:{closest:()=>h.form},preventDefault(){},stopImmediatePropagation(){}});
  assert.deepEqual(h.root.children,['old']);assert.equal(h.alerts[0][1],'error');assert.ok(h.alerts[0][2]);
});

test('curriculum tab switch fetches shared region and pushes browser history without reload',async()=>{
  const h=harness(true);
  const link={href:'http://local/teachers/revisions/10/assessments/',hasAttribute:()=>true};
  const event={target:{closest:()=>link},preventDefault(){this.prevented=true;}};
  await h.events.click(event);
  assert.equal(event.prevented,true);assert.equal(h.requests.length,1);assert.equal(h.window.history.pushed,true);
  assert.deepEqual(h.root.children,['new']);assert.equal(h.root.inert,false);
  assert.match(h.window.history.url,/assessments\/$/);
  await h.window.MasarCurriculum.refresh('/teachers/revisions/10/?step=curriculum');
  assert.equal(h.requests.length,2);
  await assert.rejects(h.window.MasarCurriculum.refresh('/teachers/revisions/11/assessments/'));
});

test('failed tab switch preserves region and does not push browser history',async()=>{
  const h=harness(true);h.fail();
  await h.events.click({target:{closest:()=>({href:'http://local/teachers/revisions/10/assessments/',hasAttribute:()=>true})},preventDefault(){}});
  assert.deepEqual(h.root.children,['old']);assert.equal(h.window.history.pushed,undefined);assert.equal(h.alerts[0][1],'error');
});
