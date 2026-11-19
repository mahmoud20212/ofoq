const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'static/js/instructor-assessments.js'),'utf8');

function harness(supported=true, withoutBlank=false, inPopup=false) {
  const events={}, actions={}, orderEvents=[];
  let moves=0, frame=null, ghost=null;
  const control = () => ({hidden:false,disabled:false,focused:false,focus(){this.focused=true;},addEventListener(name,fn){this.action=fn;}});
  const makeRow = prefix => {
    const row={hidden:false, attributes:[], input:{value:'0'}, id:{value:''}, deletion:{checked:false}, radio:{checked:false,focus(){this.focused=true;}}};
    row.remove=control();row.up=control();row.down=control();row.text=control();row.handle=control();
    row.classList={add(){},remove(){}}; row.text.value=prefix;
    row.handle.closest=key=>key==='[data-option-row]'?row:row.handle;
    row.handle.setPointerCapture=()=>{};row.handle.hasPointerCapture=()=>false;row.handle.setAttribute=()=>{};row.handle.removeAttribute=()=>{};row.handle.isConnected=true;
    for (const [button,kind] of [[row.remove,'remove'],[row.up,'up'],[row.down,'down']]) {
      button.closest=key=>key==='[data-option-row]'?row:key==='[hidden]'?(row.hidden?row:null):button;
      button.matches=selector=>kind==='remove'?selector.includes('remove'):selector.includes('option-'+kind);
      button.isConnected=true;
    }
    row.querySelector=key=>key.includes('-id')?row.id:key.includes('DELETE')?row.deletion:key.includes('-order')?row.input:key.includes('radio')?row.radio:
      key==='[data-option-remove]'?row.remove:key==='[data-option-up]'?row.up:key==='[data-option-down]'?row.down:key==='[data-option-handle]'?row.handle:row.text;
    row.prefix=prefix;
    return row;
  };
  const first=makeRow('options-0'), second=makeRow('options-1'), items=[first,second];
  const add=control(), cancel=control(), confirm=control(), total={value:'2'}, confirmed={value:''}, blank={checked:false};
  const list={querySelectorAll:()=>items,addEventListener:(name,fn)=>{events[name]=fn;if(name==='click')events.list=fn;},
    insertBefore(row,target){moves++;items.splice(items.indexOf(row),1);items.splice(target?items.indexOf(target):items.length,0,row);},
    append(fragment){const row=fragment.row||fragment;const i=items.indexOf(row);if(i>=0)items.splice(i,1);items.push(row);}};
  [first,second].forEach(row=>{row.parentElement=list;row.getBoundingClientRect=()=>({top:items.indexOf(row)*60,left:10,width:300,height:44});Object.defineProperty(row,'nextElementSibling',{get:()=>items[items.indexOf(row)+1]||null});});
  let cloned;
  const template={content:{cloneNode(){
    const row=makeRow('options-__prefix__'); cloned=row;
    row.attributes=[{name:'name',value:'options-__prefix__-text'}];
    row.setAttribute=(name,value)=>{row.resolved=value;};
    return {row,querySelector:()=>row,querySelectorAll:()=>[row]};
  }}};
  const dialog={open:false,showModal:supported?function(){this.open=true;}:undefined,
    close(){this.open=false;events.close?.();},querySelector:()=>confirm,querySelectorAll:()=>[cancel],
    addEventListener:(name,fn)=>events[name]=fn};
  const form={classList:{add:name=>actions.className=name},querySelector:key=>
    key==='[data-options]'?list:key==='[data-option-template]'?template:key.includes('TOTAL_FORMS')?total:
    key==='[data-add-option]'?add:key.includes('correct_option')?(withoutBlank?null:blank):confirmed};
  if(inPopup) form.closest=selector=>selector==='dialog'?{append(node){ghost=node;}}:null;
  const document={querySelector:key=>key==='[data-option-editor]'?form:dialog,createElement:()=>({style:{},remove(){}}),body:{append(){}}};
  vm.runInNewContext(source,{document,requestAnimationFrame:fn=>{frame=fn;return 1;},cancelAnimationFrame(){}});
  const click=button=>events.list({target:{closest:()=>button}});
  return {form,events,actions,items,first,second,click,add,cancel,confirm,dialog,total,confirmed,blank,get cloned(){return cloned;},moves:()=>moves,frame:()=>frame?.(),ghost:()=>ghost};
}

test('keyboard move changes DOM order and serialized order fields',()=>{
  const h=harness();h.click(h.second.up);
  assert.equal(h.items[0],h.second);assert.equal(h.second.input.value,0);assert.equal(h.first.input.value,1);
  assert.equal(h.second.up.disabled,true);assert.equal(h.first.down.disabled,true);
});
test('option is removed immediately without opening confirmation and focus moves to next input',()=>{
  const h=harness();h.click(h.first.remove);
  assert.equal(h.dialog.open,false);assert.equal(h.first.hidden,true);assert.equal(h.first.deletion.checked,true);assert.equal(h.second.text.focused,true);
});
test('direct deletion clears selected correct option and removing all options focuses add button',()=>{
  const h=harness();h.first.radio.checked=true;h.click(h.first.remove);
  assert.equal(h.first.hidden,true);assert.equal(h.first.deletion.checked,true);assert.equal(h.first.radio.checked,false);
  h.click(h.second.remove);assert.equal(h.dialog.open,false);assert.equal(h.add.focused,true);
});
test('dynamic option has a unique field prefix, updates management count and receives focus',()=>{
  const h=harness();h.add.action({preventDefault(){}});
  assert.equal(h.total.value,3);assert.equal(h.cloned.resolved,'options-2-text');assert.equal(h.items.length,3);assert.equal(h.cloned.text.focused,true);
});
test('adding reuses a hidden blank extra row without duplicating form IDs',()=>{
  const h=harness();h.first.hidden=true;h.add.action({preventDefault(){}});
  assert.equal(h.first.hidden,false);assert.equal(h.first.text.focused,true);assert.equal(h.total.value,'2');assert.equal(h.items.length,2);
});
test('direct deletion does not require dialog browser support',()=>{
  const h=harness(false);h.click(h.first.remove);assert.equal(h.first.hidden,true);assert.equal(h.first.deletion.checked,true);
});

test('option drag changes serialized order without losing selected correct answer',()=>{
  const h=harness();h.first.radio.checked=true;
  h.events.pointerdown({target:{closest:()=>h.first.handle},isPrimary:true,button:0,pointerId:1,clientY:20,preventDefault(){}});
  h.events.pointermove({pointerId:1,clientY:140});h.events.pointerup({pointerId:1});
  assert.equal(h.items[0],h.second);assert.equal(h.first.input.value,1);assert.equal(h.second.input.value,0);assert.equal(h.first.radio.checked,true);
});
test('Escape cancels option drag and keyboard handle also reorders',()=>{
  const h=harness();h.events.pointerdown({target:{closest:()=>h.first.handle},isPrimary:true,button:0,pointerId:1,clientY:20,preventDefault(){}});
  h.events.pointermove({pointerId:1,clientY:140});h.events.keydown({key:'Escape',preventDefault(){}});
  assert.equal(h.items[0],h.first);assert.equal(h.first.input.value,0);
  h.events.keydown({target:{closest:()=>h.second.handle},key:'ArrowUp',preventDefault(){}});
  assert.equal(h.items[0],h.second);assert.equal(h.second.input.value,0);
});
test('deleting correct option works without a visible blank-answer radio',()=>{
  const h=harness(true,true);h.first.radio.checked=true;h.click(h.first.remove);
  assert.equal(h.first.radio.checked,false);assert.equal(h.first.deletion.checked,true);assert.equal(h.dialog.open,false);
});

test('stationary option drag does not repeatedly reinsert rows on animation frames',()=>{
  const h=harness();h.events.pointerdown({target:{closest:()=>h.first.handle},isPrimary:true,button:0,pointerId:1,clientY:20,preventDefault(){}});
  h.events.pointermove({pointerId:1,clientY:140});const moves=h.moves();
  for(let i=0;i<30;i++){h.events.pointermove({pointerId:1,clientY:140});h.frame();}
  assert.equal(h.moves(),moves);assert.equal(moves,1);h.events.pointerup({pointerId:1});
});
test('drag ghost belongs to modal top layer and retains field row dimensions',()=>{
  const h=harness(true,false,true);h.events.pointerdown({target:{closest:()=>h.first.handle},isPrimary:true,button:0,pointerId:1,clientY:20,preventDefault(){}});
  h.events.pointermove({pointerId:1,clientY:140});assert.ok(h.ghost());
  assert.equal(h.ghost().style.height,'44px');assert.equal(h.ghost().style.width,'300px');
  assert.match(h.ghost().className,/assessment-option-ghost/);h.events.pointerup({pointerId:1});
});

test('question validation requires two text options and a selected nonempty correct answer',()=>{
  const h=harness();assert.equal(h.form.validateAssessment(),false);
  h.first.radio.checked=true;assert.equal(h.form.validateAssessment(),true);
  h.second.text.value='   ';assert.equal(h.form.validateAssessment(),false);
  h.second.text.value='اختيار';h.first.text.value='';assert.equal(h.form.validateAssessment(),false);
  h.first.text.value='إجابة';assert.equal(h.form.validateAssessment(),true);
  h.click(h.second.remove);assert.equal(h.form.validateAssessment(),false);
});
