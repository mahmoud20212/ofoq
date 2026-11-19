const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'static/js/instructor-assessment-preview.js'),'utf8');
function harness(hash='') {
  const control=()=>({disabled:false,attributes:{},mark:{hidden:true},querySelector(){return this.mark;},setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];},addEventListener(_,fn){this.click=fn;}});
  const numbers=[control(),control(),control()];
  const questions=[1,2,3].map(id=>({id:'preview-question-'+id,hidden:false,choice:{checked:false,value:'option'},querySelector(selector){return selector==='h2'?{focus:()=>this.focused=true}:this.choice.checked?this.choice:null;},addEventListener(_,fn){this.change=fn;},scrollIntoView(){this.scrolled=true;}}));
  const previous=control(),next=control(),position={textContent:''},navigation={hidden:true};
  const root={classList:{add(){}},querySelectorAll:s=>s==='[data-preview-question]'?questions:numbers,
    querySelector:s=>s==='[data-preview-previous]'?previous:s==='[data-preview-next]'?next:s==='[data-preview-position]'?position:navigation};
  vm.runInNewContext(source,{document:{querySelector:()=>root},window:{location:{hash}}});
  return {numbers,questions,previous,next,position,navigation};
}
test('preview shows first question with native navigation boundaries',()=>{
  const h=harness();assert.deepEqual(h.questions.map(q=>q.hidden),[false,true,true]);
  assert.equal(h.previous.disabled,true);assert.equal(h.next.disabled,false);assert.equal(h.navigation.hidden,false);
  assert.equal(h.numbers[0].attributes['aria-current'],'step');
});
test('number navigation and previous/next keep choices and move focus',()=>{
  const h=harness();h.questions[0].choice.checked=true;h.next.click();
  assert.deepEqual(h.questions.map(q=>q.hidden),[true,false,true]);assert.equal(h.questions[1].focused,true);
  h.numbers[2].click({preventDefault(){}});assert.equal(h.next.disabled,true);assert.equal(h.position.textContent,'السؤال 3 من 3');
  h.previous.click();h.previous.click();assert.equal(h.questions[0].choice.checked,true);assert.equal(h.previous.disabled,true);
});
test('deep link selects its question and modified anchor clicks remain native',()=>{
  const h=harness('#preview-question-2');assert.equal(h.questions[1].hidden,false);
  h.numbers[2].click({ctrlKey:true,preventDefault(){throw Error('must remain native');}});assert.equal(h.questions[1].hidden,false);
});

test('answered state is independent of current question without adding a check mark',()=>{
  const h=harness();assert.equal(h.numbers[0].attributes['data-answered'],'false');
  h.questions[0].choice.checked=true;h.questions[0].change();
  assert.equal(h.numbers[0].attributes['data-answered'],'true');
  assert.equal(h.numbers[0].attributes['aria-current'],'step');assert.match(h.numbers[0].attributes['aria-label'],/مجاب/);
  h.next.click();assert.equal(h.numbers[0].attributes['aria-current'],undefined);assert.equal(h.numbers[0].attributes['data-answered'],'true');
  assert.equal(h.numbers[1].attributes['data-answered'],'false');
  h.questions[0].choice.checked=false;h.questions[0].change();assert.equal(h.numbers[0].attributes['data-answered'],'false');
});

test('student clear-selection radio stays unanswered while question remains current',()=>{
  const h=harness();h.questions[0].choice.checked=true;h.questions[0].choice.value='';h.questions[0].change();
  assert.equal(h.numbers[0].attributes['data-answered'],'false');assert.equal(h.numbers[0].attributes['aria-current'],'step');
  h.questions[0].choice.value='answer';h.questions[0].change();assert.equal(h.numbers[0].attributes['data-answered'],'true');
  h.next.click();assert.equal(h.numbers[0].attributes['data-answered'],'true');
});
