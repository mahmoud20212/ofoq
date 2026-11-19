const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, 'static/js/instructor-sort.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness(fail = false, withoutFeedback = false, kind = 'lesson') {
  const events = {}, handlers = {}, requests = [], classes = () => ({ add() {}, remove() {}, toggle() {} });
  const status = { textContent: '', classList: classes() }, reload = { hidden: true, addEventListener() {} };
  let list, moveCount = 0;
  const rows = [1, 2, 3].map(id => {
    const position = { textContent: id };
    const row = { dataset: { sortId: String(id) }, classList: classes(), hasAttribute: () => true,
      querySelector: selector => selector === '[data-position]' ? position : { textContent: `درس ${id}` },
      getBoundingClientRect: () => ({ top: 100 + list.children.indexOf(row) * 60, left: 20, width: 300, height: 60 }) };
    row.handle = { hidden: true, disabled: false, isConnected: true, focused: false, closest: selector => selector === '[data-sort-id]' ? row : row.handle,
      focus() { this.focused = true; }, setPointerCapture() {}, hasPointerCapture: () => false, setAttribute() {}, removeAttribute() {} };
    Object.defineProperty(row, 'nextElementSibling', { get: () => list.children[list.children.indexOf(row) + 1] || null });
    return row;
  });
  const detach = row => { const index = list.children.indexOf(row); if (index !== -1) list.children.splice(index, 1); };
  list = { children: [...rows], dataset: { sortList: kind, moduleId: kind === 'question' ? '' : '8' }, addEventListener: (name, fn) => { handlers[name] = fn; }, querySelectorAll: () => rows.map(row => row.handle),
    append: row => { detach(row); list.children.push(row); }, insertBefore: (row, before) => { moveCount++; if (before === row) return; detach(row); const i = before ? list.children.indexOf(before) : -1; list.children.splice(i === -1 ? list.children.length : i, 0, row); }, getBoundingClientRect: () => ({ top: 100, bottom: 280 }) };
  rows.forEach(row => { row.parentElement = list; });
  const builder = { classList:classes(), dataset: { sortUrl: '/teachers/revisions/4/reorder/' }, querySelectorAll: () => [list], querySelector: () => ({ value: 'csrf-test' }), setAttribute() {}, removeAttribute() {} };
  const document = { querySelector: selector => selector === '[data-curriculum-builder]' ? builder : withoutFeedback ? null : selector === '[data-sort-status]' ? status : reload, createElement: () => ({ style: {}, remove() {} }), body: { classList: classes(), append() {} } };
  const window = { addEventListener: (name, fn) => { events[name] = fn; }, innerHeight: 900, scrollBy() {}, location: { reload() {} } };
  vm.runInNewContext(source, { document, window, Error, TypeError, AbortController, setTimeout, clearTimeout, requestAnimationFrame: () => 1, cancelAnimationFrame() {},
    fetch: async (url, options) => { requests.push({ url, options, data: JSON.parse(options.body) }); if (fail) throw new TypeError('Network unavailable'); return { ok: true, json: async () => ({ order: JSON.parse(options.body).order }) }; } });
  return { rows, status, reload, requests, events, handlers, moves: () => moveCount, order: () => list.children.map(row => Number(row.dataset.sortId)) };
}
test('keyboard move saves scoped order and CSRF then restores focus', async () => {
  const h = harness(); h.handlers.keydown({ target: h.rows[0].handle, key: 'ArrowDown', preventDefault() {} }); await tick();
  assert.deepEqual(h.order(), [2, 1, 3]);
  assert.deepEqual(h.requests[0].data, { kind: 'lesson', module_id: 8, order: [2, 1, 3], previous_order: [1, 2, 3] });
  assert.equal(h.requests[0].options.headers['X-CSRFToken'], 'csrf-test'); assert.equal(h.status.textContent, 'تم حفظ الترتيب'); assert.equal(h.rows[0].handle.focused, true);
});

test('question keyboard ordering posts question scope and restores order on failure', async () => {
  const h = harness(false, false, 'question');
  h.handlers.keydown({target:h.rows[0].handle,key:'ArrowDown',preventDefault(){}});await tick();
  assert.equal(h.requests[0].data.kind,'question');assert.equal(h.requests[0].data.module_id,null);
  assert.deepEqual(h.requests[0].data.order,[2,1,3]);assert.equal(h.rows[0].handle.focused,true);
  const failed = harness(true, false, 'question');
  failed.handlers.keydown({target:failed.rows[0].handle,key:'End',preventDefault(){}});await tick();
  assert.deepEqual(failed.order(),[1,2,3]);assert.equal(failed.reload.hidden,false);
});
test('touch pointer drag moves lesson and saves', async () => {
  const h = harness(); h.handlers.pointerdown({ target: h.rows[0].handle, isPrimary: true, button: 0, pointerId: 1, clientY: 120, preventDefault() {} }); h.events.pointermove({ pointerId: 1, clientY: 265 });
  assert.deepEqual(h.order(), [2, 3, 1]); h.events.pointerup({ pointerId: 1 }); await tick(); assert.deepEqual(h.requests[0].data.order, [2, 3, 1]);
});
test('Escape cancels drag without saving', async () => {
  const h = harness(); h.handlers.pointerdown({ target: h.rows[0].handle, isPrimary: true, button: 0, pointerId: 1, clientY: 120, preventDefault() {} }); h.events.pointermove({ pointerId: 1, clientY: 265 }); h.events.keydown({ key: 'Escape', preventDefault() {} }); await tick();
  assert.deepEqual(h.order(), [1, 2, 3]); assert.equal(h.requests.length, 0);
});
test('failed save rolls back order and offers reload', async () => {
  const h = harness(true); h.handlers.keydown({ target: h.rows[0].handle, key: 'End', preventDefault() {} }); await tick();
  assert.deepEqual(h.order(), [1, 2, 3]); assert.equal(h.reload.hidden, false); assert.match(h.status.textContent, /تعذّر الاتصال/); assert.equal(h.rows[0].handle.disabled, false);
});

test('missing status markup does not freeze saving or disable the next move', async () => {
  const h = harness(false, true);
  h.handlers.keydown({ target: h.rows[0].handle, key: 'ArrowDown', preventDefault() {} }); await tick();
  assert.equal(h.requests.length, 1);
  assert.equal(h.rows[0].handle.disabled, false);
  h.handlers.keydown({ target: h.rows[0].handle, key: 'ArrowDown', preventDefault() {} }); await tick();
  assert.equal(h.requests.length, 2);
  assert.deepEqual(h.order(), [2, 3, 1]);
});

test('stationary drag does not repeatedly reinsert DOM rows', async () => {
  const h = harness();
  h.handlers.pointerdown({ target: h.rows[0].handle, isPrimary: true, button: 0, pointerId: 1, clientY: 120, preventDefault() {} });
  h.events.pointermove({ pointerId: 1, clientY: 265 });
  const moves = h.moves();
  for (let index = 0; index < 20; index++) h.events.pointermove({ pointerId: 1, clientY: 265 });
  assert.equal(h.moves(), moves);
  h.events.pointerup({ pointerId: 1 }); await tick();
  assert.equal(h.requests.length, 1);
});
