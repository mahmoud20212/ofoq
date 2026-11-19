const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, 'static/js/student-progress.js'), 'utf8');

function harness(fetcher, withoutFetch = false, withCheckbox = false, withToasts = false, assessmentRows = []) {
  const events = {}, attributes = {};
  const button = { disabled: false, classList: { toggle() {} }, setAttribute: (key, value) => { attributes[key] = value; } };
  const label = { textContent: 'تحديد كمكتمل' }, state = { textContent: 'لم تحدّد هذا المحتوى كمكتمل' };
  const message = { textContent: '', attributes: {}, setAttribute(key,value) {this.attributes[key]=value;} }, login = { hidden: true };
  const nodes = { '[data-completion-button]': button, '[data-completion-label]': label, '[data-completion-state]': state, '[data-progress-message]': message, '[data-progress-login]': login };
  const form = { action: '/complete/', dataset: { courseId: '2', contentId: '6', completed: 'false', completeUrl: '/complete/', incompleteUrl: '/incomplete/' },
    querySelector: key => nodes[key], querySelectorAll: () => [button], addEventListener: (key, value) => { events[key] = value; }, setAttribute() {}, removeAttribute() {} };
  const checkEvents = {};
  const checkbox = {checked: false, disabled: false, addEventListener: (key, value) => { checkEvents[key] = value; }};
  const peer = { ...form, dataset: {...form.dataset}, querySelector: key => key === '[data-completion-checkbox]' ? checkbox : null,
    querySelectorAll: () => [checkbox], addEventListener() {} };
  const count = { textContent: '0 من 4 محتوى مكتمل' }, percent = { textContent: '0%' }, bar = { value: 0, tagName:'PROGRESS', classList:{add(){}}, after(track){this.track=track;} };
  const panel = { dataset: { courseProgress: '2' }, querySelector: key => ({ '[data-progress-count]': count, '[data-progress-percent]': percent, '[data-progress-bar]': bar }[key]) };
  const imageEvents = {}, mediaError = { hidden: true };
  const image = { hidden: false, parentElement: { querySelector: () => mediaError }, addEventListener: (key, value) => { imageEvents[key] = value; } };
  const document = {createElement: () => ({style:{},setAttribute(){},append(child){this.child=child;},getBoundingClientRect(){return {};}}),
    querySelector: key => key === '[data-learning-feedback]' ? message : login,
    querySelectorAll: key => key === '[data-assessment-row]' ? assessmentRows : key === '[data-completion-form]' ? (withCheckbox ? [form, peer] : [form]) : key === '[data-course-progress]' ? [panel] : [image] };
  const requests = [];
  const notices = [];
  const window = withToasts ? {appAlerts: {show(text,level,action) {const notice={text,level,action,dismissed:false,dismiss(){this.dismissed=true;}};notices.push(notice);return notice;}}} : undefined;
  vm.runInNewContext(source, { document, window, fetch: withoutFetch ? undefined : async (url, options) => { requests.push({ url, options }); return fetcher(url, options); },
    FormData: class { constructor(value) { this.form = value; } }, AbortController, setTimeout, clearTimeout });
  return { form, button, label, state, message, login, count, percent, bar, attributes, requests, image, mediaError,
    notices, checkbox, peer, change: value => { checkbox.checked = value; return checkEvents.change({preventDefault() {}}); },
    submit: () => events.submit({ preventDefault() {} }), imageError: () => imageEvents.error() };
}
const ok = (completed = true) => ({ ok: true, status: 200, json: async () => ({ course_id: 2, content_id: 6, completed,
  progress: { available_content_count: 4, completed_content_count: completed ? 1 : 0, completion_percentage: completed ? 25 : 0 } }) });

test('completion updates assessment locks immediately from server state and undo restores lock', async () => {
  const lock={hidden:false}, label={textContent:'مقفل'};
  const row={dataset:{assessmentRow:'5'},querySelectorAll:key=>key==='[data-assessment-lock]'?[lock]:[label]};
  const h=harness(async url=>{
    const response=ok(url==='/complete/'),data=await response.json();
    data.assessment_states=[{id:5,is_unlocked:url==='/complete/',state_label:'لم يبدأ'}];
    return {...response,json:async()=>data};
  },false,true,false,[row]);
  await h.change(true);assert.equal(lock.hidden,true);assert.equal(label.textContent,'لم يبدأ');
  await h.change(false);assert.equal(lock.hidden,false);assert.equal(label.textContent,'مقفل');
});

test('successful completion and undo use explicit routes and server progress', async () => {
  const h = harness(url => ok(url === '/complete/'));
  await h.submit();
  assert.equal(h.form.action, '/incomplete/'); assert.equal(h.bar.value, 25); assert.equal(h.percent.textContent, '25%');
  assert.equal(h.bar.track.child.style.width, '25%');
  const originalTrack = h.bar.track;
  assert.equal(h.attributes['aria-pressed'], 'true'); assert.equal(h.label.textContent, 'مكتمل');
  assert.equal(h.message.attributes['data-quiet-success'], 'true');
  await h.submit();
  assert.equal(h.form.action, '/complete/'); assert.equal(h.bar.value, 0); assert.equal(h.label.textContent, 'تحديد كمكتمل');
  assert.equal(h.bar.track.child.style.width, '0%'); assert.equal(h.bar.track, originalTrack);
  assert.equal(h.requests[0].options.headers.Accept, 'application/json'); assert.equal(h.requests[0].options.credentials, 'same-origin');
});
test('repeated submit while pending sends only one request', async () => {
  let finish; const h = harness(() => new Promise(resolve => { finish = resolve; }));
  const first = h.submit(); assert.equal(h.button.disabled, true); await h.submit();
  assert.equal(h.requests.length, 1); finish(ok()); await first; assert.equal(h.button.disabled, false);
});
test('network failure preserves previous state and enables retry', async () => {
  let fail = true; const h = harness(() => { if (fail) throw new Error('offline'); return ok(); });
  await h.submit();
  assert.equal(h.form.dataset.completed, 'false'); assert.equal(h.bar.value, 0); assert.equal(h.form.action, '/complete/');
  assert.equal(h.button.disabled, false); assert.equal(h.label.textContent, 'تحديد كمكتمل'); assert.match(h.message.textContent, /أعد المحاولة/);
  assert.equal(h.message.attributes['data-quiet-success'], 'false');
  fail = false; await h.submit(); assert.equal(h.bar.value, 25);
});
test('expired session shows login without changing completion', async () => {
  const h = harness(() => ({ status: 401 })); await h.submit();
  assert.equal(h.login.hidden, false); assert.equal(h.form.dataset.completed, 'false'); assert.equal(h.bar.value, 0);
  assert.match(h.message.textContent, /انتهت جلستك/); assert.equal(h.button.disabled, false);
});
test('server, csrf and malformed responses never report success', async () => {
  for (const response of [{ status: 500, ok: false }, { status: 403, ok: false }, { status: 200, ok: true, json: async () => ({ completed: true }) }]) {
    const h = harness(() => response); await h.submit();
    assert.equal(h.form.dataset.completed, 'false'); assert.equal(h.bar.value, 0); assert.equal(h.button.disabled, false); assert.ok(h.message.textContent);
  }
});
test('without fetch native form submission is left intact', async () => {
  const h = harness(() => ok(), true); await h.submit(); assert.equal(h.requests.length, 0); assert.equal(h.button.disabled, false);
});
test('image load failure exposes error and never completes content', () => {
  const h = harness(() => ok()); h.imageError(); assert.equal(h.image.hidden, true); assert.equal(h.mediaError.hidden, false);
  assert.equal(h.requests.length, 0); assert.equal(h.form.dataset.completed, 'false');
});

test('curriculum checkbox and current button share confirmed state and server totals', async () => {
  const h = harness(url => ok(url === '/complete/'), false, true);
  await h.change(true);
  assert.equal(h.form.dataset.completed, 'true'); assert.equal(h.checkbox.checked, true);
  assert.equal(h.label.textContent, 'مكتمل'); assert.equal(h.count.textContent, 'أكملت 1 من 4');
  await h.submit();
  assert.equal(h.checkbox.checked, false); assert.equal(h.peer.dataset.completed, 'false'); assert.equal(h.bar.value, 0);
});

test('checkbox failure rolls back and can retry without navigating', async () => {
  let fail = true;
  const h = harness(() => { if (fail) throw Error('offline'); return ok(); }, false, true);
  await h.change(true);
  assert.equal(h.checkbox.checked, false); assert.equal(h.checkbox.disabled, false); assert.equal(h.form.dataset.completed, 'false');
  fail = false; await h.change(true); assert.equal(h.checkbox.checked, true);
});

test('same-content controls lock together and repeated events send one request', async () => {
  let finish;
  const h = harness(() => new Promise(resolve => { finish = resolve; }), false, true);
  const pending = h.change(true);
  assert.equal(h.checkbox.disabled, true); assert.equal(h.button.disabled, true);
  await h.submit(); assert.equal(h.requests.length, 1);
  finish(ok()); await pending;
  assert.equal(h.checkbox.disabled, false); assert.equal(h.button.disabled, false);
});

test('expired session rolls checkbox back and exposes login', async () => {
  const h = harness(() => ({status:401}), false, true);
  await h.change(true);
  assert.equal(h.checkbox.checked, false); assert.equal(h.login.hidden, false);
  assert.equal(h.button.disabled, false); assert.equal(h.bar.value, 0);
});

test('shared error alert retries original desired state without an inline duplicate', async () => {
  let fail=true;
  const h=harness(() => {if(fail) throw Error('offline');return ok();},false,true,true);
  await h.change(true);
  assert.equal(h.notices.length,1);assert.equal(h.notices[0].level,'error');
  assert.equal(h.message.textContent,'');assert.equal(h.checkbox.checked,false);
  fail=false;await h.notices[0].action.run();
  assert.equal(h.checkbox.checked,true);assert.equal(h.notices[0].dismissed,true);
});

test('session expiry uses login action in shared alert instead of inline link', async () => {
  const h=harness(() => ({status:401}),false,true,true);
  await h.change(true);
  assert.equal(h.notices[0].action.label,'تسجيل الدخول مجددًا');
  assert.equal(h.login.hidden,true);assert.equal(h.message.textContent,'');assert.equal(h.checkbox.checked,false);
});
