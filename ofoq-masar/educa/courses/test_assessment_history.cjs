const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'static/js/student-assessment-history.js'),'utf8');
function setup() {
  const node=()=>({hidden:false,textContent:'',events:{},attrs:{},addEventListener(n,f){this.events[n]=f;},
    setAttribute(n,v){this.attrs[n]=v;},removeAttribute(n){delete this.attrs[n];},focus(){this.focused=true;}});
  const content=node();content.childNodes=[];content.replaceChildren=(...items)=>content.childNodes=items;
  content.append=item=>content.childNodes.push(item);
  const status=node(),retry=node(),back=node(),title=node(),close=node(),opener=node();
  opener.dataset={historyUrl:'http://localhost/history/'};
  const resultLink=node();resultLink.href='http://localhost/students/courses/4/assessments/5/attempts/1/summary/';resultLink.getAttribute=()=>resultLink.href;
  const heading={remove(){this.removed=true;}};
  const history={querySelector:()=>heading,querySelectorAll:()=>[resultLink],nextElementSibling:null};
  const result={dataset:{attemptNumber:'1'},removed:[],querySelector(selector){return {remove:()=>this.removed.push(selector)};}};
  const dialog=node();dialog.scrollTop=37;dialog.showModal=()=>dialog.open=true;
  dialog.close=()=>{dialog.open=false;dialog.events.close();};
  dialog.querySelector=selector=>({'[data-history-content]':content,'[data-history-status]':status,
    '[data-history-retry]':retry,'[data-history-back]':back,'#assessment-history-title':title,'[data-assessment-history-close]':close})[selector];
  const requests=[];
  const fetch=(url,options)=>new Promise((resolve,reject)=>{
    requests.push({url,options,resolve,reject});
    options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('cancelled'),{name:'AbortError'})));
  });
  const document={querySelector:()=>dialog,querySelectorAll:()=>[opener]};
  class DOMParser {parseFromString(html){return {querySelector:selector=>html==='history'&&selector==='.student-assessment-history'?history:html==='result'&&selector==='.assessment-result-material'?result:null};}}
  vm.runInNewContext(source,{document,window:{fetch},fetch,AbortController,URL,DOMParser});
  const event={preventDefault(){}};
  const flush=async()=>{await new Promise(setImmediate);await new Promise(setImmediate);};
  const resolve=(index,html)=>requests[index].resolve({ok:true,redirected:false,url:requests[index].url,text:async()=>html});
  return {content,status,retry,back,title,close,opener,history,result,resultLink,dialog,requests,event,flush,resolve};
}
test('result opens inside the same dialog and back restores history, scroll and focus without fetching',async()=>{
  const h=setup();h.opener.events.click(h.event);h.resolve(0,'history');await h.flush();
  assert.equal(h.content.childNodes[0],h.history);
  h.dialog.scrollTop=80;h.resultLink.events.click(h.event);
  assert.equal(h.content.hidden,true);
  h.resolve(1,'result');await h.flush();
  assert.equal(h.content.hidden,false);
  assert.equal(h.content.childNodes[0],h.result);assert.equal(h.title.textContent,'نتيجة المحاولة 1');
  assert.equal(h.back.hidden,false);assert.equal(h.back.focused,true);assert.equal(h.dialog.scrollTop,0);
  assert.deepEqual(h.result.removed,['.assessment-introduction-tools','.assessment-result-actions']);
  h.back.events.click();assert.equal(h.content.childNodes[0],h.history);assert.equal(h.dialog.scrollTop,80);
  assert.equal(h.resultLink.focused,true);assert.equal(h.title.textContent,'سجل المحاولات');assert.equal(h.requests.length,2);
});
test('failed result load preserves history and retries the result URL in the dialog',async()=>{
  const h=setup();h.opener.events.click(h.event);h.resolve(0,'history');await h.flush();
  h.resultLink.events.click(h.event);h.requests[1].reject(new Error('offline'));await h.flush();
  assert.equal(h.content.childNodes[0],h.history);assert.equal(h.retry.hidden,false);
  assert.equal(h.content.hidden,false);
  h.retry.events.click();assert.equal(h.requests[2].url,h.resultLink.href);
  h.resolve(2,'result');await h.flush();assert.equal(h.retry.hidden,true);assert.equal(h.content.childNodes[0],h.result);
});
test('closing the dialog aborts an in-flight result and restores the original opener',async()=>{
  const h=setup();h.opener.events.click(h.event);h.resolve(0,'history');await h.flush();
  h.resultLink.events.click(h.event);h.close.events.click();await h.flush();
  assert.equal(h.requests[1].options.signal.aborted,true);assert.equal(h.opener.focused,true);assert.equal(h.dialog.open,false);
});
