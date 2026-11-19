const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'static/js/student-media.js'),'utf8');

function harness(supported=true) {
  const events={},actions={};
  const trigger={focused:false,attributes:{},setAttribute(key,value){this.attributes[key]=value;},addEventListener(name,fn){actions.open=fn;},focus(){this.focused=true;}};
  const dialog={open:false,showModal:supported?function(){this.open=true;}:undefined,
    close(){this.open=false;events.close?.();},querySelector:()=>({addEventListener(name,fn){actions.close=fn;}}),
    addEventListener(name,fn){events[name]=fn;},getBoundingClientRect:()=>({left:20,right:400,top:20,bottom:400})};
  vm.runInNewContext(source,{document:{querySelector:key=>key==='[data-image-open]'?trigger:dialog}});
  return {trigger,dialog,events,actions};
}
test('zoom dialog opens, closes and restores focus',()=>{
  const h=harness();let prevented=false;
  h.actions.open({preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assert.equal(h.dialog.open,true);assert.equal(h.trigger.attributes['aria-haspopup'],'dialog');
  h.actions.close();assert.equal(h.dialog.open,false);assert.equal(h.trigger.focused,true);
});
test('backdrop closes, but clicks within image dialog do not',()=>{
  const h=harness();h.actions.open({preventDefault(){}});
  h.events.click({target:h.dialog,clientX:100,clientY:100});assert.equal(h.dialog.open,true);
  h.events.click({target:h.dialog,clientX:10,clientY:10});assert.equal(h.dialog.open,false);
});
test('unsupported dialogs leave native image link available',()=>{
  const h=harness(false);assert.equal(h.actions.open,undefined);assert.equal(h.trigger.attributes['aria-haspopup'],undefined);
});
