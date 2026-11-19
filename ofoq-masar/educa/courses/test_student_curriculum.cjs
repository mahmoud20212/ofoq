const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'static/js/student-curriculum.js'),'utf8');

function harness(small=true, reduced=false) {
  const events={}, changes={}, actions={}, attrs={};
  const animations=[];
  const list={style:{},scrollHeight:180,getBoundingClientRect:()=>({height:90}),animate(frames,options){const animation={frames,options,cancelled:false,cancel(){this.cancelled=true;}};animations.push(animation);return animation;}};
  const unit={open:false,dataset:{}}, scroll={scrollTop:0,getBoundingClientRect:()=>({top:50,bottom:200})};
  unit.querySelector=key=>key==='ul'?list:{addEventListener:(name,fn)=>{actions.unit=fn;}};
  const row={closest:()=>unit,getBoundingClientRect:()=>({top:220,bottom:265})};
  const panel={location:'workspace',before(){},querySelector:key=>key==='[data-current-content]'?row:key==='[data-curriculum-scroll]'?scroll:{addEventListener:(name,fn)=>{actions.close=fn;}},
    querySelectorAll:key=>key==='.learning-unit'?[unit]:[{addEventListener:(name,fn)=>{actions.link=fn;}}]};
  const opener={focused:false,addEventListener:(name,fn)=>{actions.open=fn;},setAttribute:(key,value)=>{attrs[key]=value;},focus(){this.focused=true;}};
  const dialog={open:false,append:()=>{panel.location='dialog';},showModal(){this.open=true;},close(){this.open=false;events.close?.();},addEventListener:(name,fn)=>{events[name]=fn;}};
  const media={matches:small,addEventListener:(name,fn)=>{changes.layout=fn;}};
  const document={body:{classList:{add(){}}},createComment:()=>({after:()=>{panel.location='workspace';}}),getElementById:()=>panel,
    querySelector:key=>key==='[data-learning-workspace]'?{}:key==='[data-curriculum-dialog]'?dialog:opener};
  vm.runInNewContext(source,{document,window:{matchMedia:query=>query.includes('reduced-motion')?{matches:reduced}:media},requestAnimationFrame:fn=>fn()});
  return {panel,dialog,opener,attrs,unit,scroll,media,actions,events,changes,list,animations};
}
test('mobile uses one curriculum, opens current unit and scrolls only the list',()=>{
  const h=harness();assert.equal(h.panel.location,'dialog');assert.equal(h.unit.open,true);assert.ok(h.scroll.scrollTop>0);
  h.actions.open();assert.equal(h.dialog.open,true);assert.equal(h.attrs['aria-expanded'],'true');
});
test('close and native Escape close event restore focus and expanded state',()=>{
  const h=harness();h.actions.open();h.actions.close();assert.equal(h.opener.focused,true);assert.equal(h.attrs['aria-expanded'],'false');
  h.actions.open();h.dialog.close();assert.equal(h.opener.focused,true);assert.equal(h.dialog.open,false);
});
test('choosing title closes drawer and desktop restores the same sidebar',()=>{
  const h=harness();h.actions.open();h.actions.link();assert.equal(h.dialog.open,false);
  h.media.matches=false;h.changes.layout();assert.equal(h.panel.location,'workspace');
});
test('desktop initially keeps curriculum in workspace',()=>{
  const h=harness(false);assert.equal(h.panel.location,'workspace');assert.equal(h.dialog.open,false);
});
test('unit closes after animation and opens smoothly again',()=>{
  const h=harness();h.actions.unit({preventDefault(){}});
  assert.equal(h.unit.open,true);assert.equal(h.animations[0].frames[1].height,'0px');
  assert.equal(h.unit.dataset.expanded,'false');assert.equal(h.animations[0].frames[1].marginBottom,'0px');assert.equal(h.animations[0].options.fill,'both');
  h.animations[0].onfinish();assert.equal(h.unit.open,false);assert.equal(h.list.style.overflow,'');
  h.actions.unit({preventDefault(){}});assert.equal(h.animations[1].frames[1].height,'180px');
  h.animations[1].onfinish();assert.equal(h.unit.open,true);
});
test('rapid reversal cancels previous animation and ignores its stale finish',()=>{
  const h=harness();h.actions.unit({preventDefault(){}});h.actions.unit({preventDefault(){}});
  assert.equal(h.animations[0].cancelled,true);
  h.animations[0].onfinish();assert.equal(h.unit.open,true);
  h.animations[1].onfinish();assert.equal(h.unit.open,true);assert.equal(h.list.style.overflow,'');
});
test('reduced motion toggles units immediately without animation',()=>{
  const h=harness(true,true);h.actions.unit({preventDefault(){}});
  assert.equal(h.unit.open,false);assert.equal(h.animations.length,0);
});
