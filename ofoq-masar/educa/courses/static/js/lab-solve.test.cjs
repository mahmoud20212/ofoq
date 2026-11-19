const {test}=require('node:test');const assert=require('node:assert/strict');
const {saveController,tokens}=require('./lab-solve.js');
test('serialized saves retain edits arriving in flight and revision',async()=>{
 let release,calls=[],events=[];const state=saveController('',0,(code,revision)=>{calls.push({code,revision});return new Promise(r=>release=r);},s=>events.push(s));
 state.edit('a');const pending=state.save();state.edit('ab');await state.save();assert.equal(calls.length,1);
 release({revision:1});await pending;assert.equal(state.dirty(),true);assert.equal(events.at(-1),'dirty');
 const second=state.save();assert.deepEqual(calls[1],{code:'ab',revision:1});release({revision:2});await second;assert.equal(state.dirty(),false);
});
test('conflict never overwrites or retries until explicit reload',async()=>{
 let calls=0;const state=saveController('old',1,async()=>{calls++;throw {status:409};},()=>{});
 state.edit('local');await state.save();assert.equal(state.blocked,true);assert.equal(state.dirty(),true);await state.save();assert.equal(calls,1);
 state.load('remote',2);assert.equal(state.dirty(),false);assert.equal(state.blocked,false);
});
test('network failure retains local text and revision, deliberate empty accepted',async()=>{
 let failed=true,received;const state=saveController('start',4,async(code,revision)=>{received={code,revision};if(failed)throw Error('offline');return {revision:5};},()=>{});
 state.edit('');await state.save();assert.equal(state.dirty(),true);failed=false;await state.save();assert.deepEqual(received,{code:'',revision:4});assert.equal(state.dirty(),false);
});
test('syntax tokens preserve all code including Arabic and HTML as plain strings',()=>{
 for(const name of ['Python','JavaScript','C++']){const source='print("مرحبا <img onerror=x>")\n# comment\n123';assert.equal(tokens(source,name).map(p=>p.text).join(''),source);}
 assert.equal(tokens('# comment\nprint(3)','Python')[0].type,'comment');assert.ok(tokens('const x = 5','JavaScript').some(t=>t.type==='keyword'));
});
