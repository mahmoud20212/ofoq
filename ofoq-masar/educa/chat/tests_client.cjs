// Run with: node --test chat/tests_client.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const vm = require('node:vm');
const { randomUUID } = require('node:crypto');
const source = readFileSync(resolve(__dirname, '../courses/static/js/chat.js'), 'utf8');

class Node {
  constructor(tag = 'div') {
    this.tag = tag; this.className = ''; this.textContent = ''; this.children = [];
    this.dataset = {}; this.style = {}; this.handlers = {}; this.hidden = false; this.value = ''; this.scrollTop = 0; this.clientHeight = 200;
    this.classList = { toggle: (name, force) => {
      const values = new Set(this.className.split(' ').filter(Boolean));
      if (force ?? !values.has(name)) values.add(name); else values.delete(name);
      this.className = [...values].join(' ');
    } };
  }
  set innerHTML(_) { throw new Error('Untrusted messages must never use innerHTML'); }
  append(...nodes) { nodes.forEach(node => this.insertBefore(node, null)); }
  insertBefore(node, before) {
    if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1);
    const index = before ? this.children.indexOf(before) : this.children.length;
    this.children.splice(index, 0, node); node.parent = this;
  }
  addEventListener(name, callback) { this.handlers[name] = callback; }
  dispatch(name, event = {}) { return this.handlers[name]?.({ preventDefault() {}, ...event }); }
  querySelector(selector) { return this.children.find(node => node.className.split(' ').includes(selector.slice(1))) || null; }
  get scrollHeight() { return this.children.filter(node => !node.hidden).length * 80; }
  getBoundingClientRect() { return { top: (this.parent?.children.indexOf(this) || 0) * 80 - (this.parent?.scrollTop || 0) }; }
}

const message = (id, content = `نص ${id}`, extra = {}) => ({ id, content, sent_at: '2026-11-09T12:00:00Z', user: { id: 2, name: 'زميل', is_teacher: false }, ...extra });
function setup(initial = [], respond = async () => ({ messages: [], has_more: false })) {
  const nodes = Object.fromEntries(['log', 'input', 'send', 'retry', 'older', 'reconnect', 'jump', 'connection', 'send-status', 'empty', 'login', 'composer'].map(name => [name, new Node()]));
  nodes.log.append(nodes.empty);
  const room = { querySelector: selector => nodes[selector.match(/data-([^\]]+)/)[1]] };
  const config = { user_id: 1, history_url: '/chat/room/1/messages/', socket_path: '/ws/chat/room/1/' };
  const sockets = [], timers = new Map(), requests = [];
  let timerId = 0;
  class Socket {
    static OPEN = 1; static CLOSING = 2;
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
    async open() { this.readyState = 1; await this.onopen(); }
    send(value) { this.sent.push(JSON.parse(value)); }
    deliver(value) { this.onmessage({ data: JSON.stringify(value) }); }
    close(code = 1000) { this.readyState = 3; this.onclose?.({ code }); }
  }
  vm.runInNewContext(source, {
    document: { querySelector: () => room, getElementById: id => ({ textContent: JSON.stringify(id === 'chat-config' ? config : initial) }), createElement: tag => new Node(tag) },
    window: { addEventListener() {} },
    location: { origin: 'http://localhost:8000', protocol: 'http:', host: 'localhost:8000' },
    WebSocket: Socket, crypto: { randomUUID }, URL, Date,
    fetch: async url => { requests.push(new URL(url)); return { ok: true, status: 200, redirected: false, json: () => respond(new URL(url)) }; },
    setTimeout: (callback, delay) => { timers.set(++timerId, { callback, delay }); return timerId; },
    clearTimeout: id => timers.delete(id),
  });
  return { nodes, sockets, timers, requests,
    ids: () => nodes.log.children.filter(node => node.dataset.messageId).map(node => node.dataset.messageId),
    runTimer: delay => { const [id, timer] = [...timers].find(([, timer]) => timer.delay === delay); timers.delete(id); timer.callback(); },
  };
}

test('messages are plain text, sorted and deduplicated; acknowledgement clears only the sent draft', async () => {
  const app = setup([message(1, '<img src=x onerror=alert(1)>')]);
  await app.sockets[0].open();
  const first = app.nodes.log.children.find(node => node.dataset.messageId === 1);
  assert.equal(first.children[1].textContent, '<img src=x onerror=alert(1)>');
  assert.equal(first.children[1].children.length, 0);
  app.nodes.input.value = 'رسالة عربية';
  app.nodes.composer.dispatch('submit');
  const packet = app.sockets[0].sent[0];
  assert.equal(packet.content, 'رسالة عربية');
  assert.equal(app.nodes.input.value, 'رسالة عربية');
  const saved = message(3, packet.content, { client_id: packet.client_id, user: { id: 1, name: 'أنا', is_teacher: false } });
  app.sockets[0].deliver({ type: 'message.ack', message: saved });
  app.sockets[0].deliver({ type: 'message', message: saved });
  app.sockets[0].deliver({ type: 'message', message: message(2) });
  assert.deepEqual(app.ids(), [1, 2, 3]);
  assert.equal(app.nodes.input.value, '');
});

test('failed acknowledgement keeps the draft and retries with the same request identifier', async () => {
  const app = setup(); await app.sockets[0].open();
  app.nodes.input.value = 'لا تضِع هذه الرسالة'; app.nodes.composer.dispatch('submit');
  const original = app.sockets[0].sent[0];
  app.runTimer(10000);
  assert.equal(app.nodes.input.value, original.content);
  assert.equal(app.nodes.retry.hidden, false);
  app.nodes.retry.dispatch('click');
  assert.equal(app.sockets[0].sent[1].client_id, original.client_id);
});

test('recovery cursor is frozen before concurrent live messages, preserving history gaps', async () => {
  let release;
  const app = setup([message(1)], () => new Promise(resolve => { release = resolve; }));
  const opening = app.sockets[0].open();
  await new Promise(resolve => setImmediate(resolve));
  app.sockets[0].deliver({ type: 'message', message: message(4) });
  release({ messages: [message(2), message(3), message(4)], has_more: false });
  await opening;
  assert.equal(app.requests[0].searchParams.get('after_id'), '1');
  assert.deepEqual(app.ids(), [1, 2, 3, 4]);
});

test('reconnect uses three bounded delays, then offers a manual retry', () => {
  const app = setup();
  for (const delay of [1000, 2000, 5000]) { app.sockets.at(-1).close(1006); app.runTimer(delay); }
  app.sockets.at(-1).close(1006);
  assert.equal(app.nodes.reconnect.hidden, false);
  assert.equal(app.timers.size, 0);
});

test('new messages do not move a reader away from older history', async () => {
  const app = setup(Array.from({ length: 10 }, (_, index) => message(index + 1)));
  await app.sockets[0].open();
  app.nodes.log.scrollTop = 0;
  app.sockets[0].deliver({ type: 'message', message: message(11) });
  assert.equal(app.nodes.log.scrollTop, 0);
  assert.equal(app.nodes.jump.hidden, false);
  app.nodes.jump.dispatch('click');
  assert.equal(app.nodes.jump.hidden, true);
});

test('Arabic composition and Shift+Enter do not submit, and revoked sessions stop reconnecting', async () => {
  const app = setup(); await app.sockets[0].open(); app.nodes.input.value = 'نص';
  app.nodes.input.dispatch('keydown', { key: 'Enter', isComposing: true });
  app.nodes.input.dispatch('keydown', { key: 'Enter', shiftKey: true });
  assert.equal(app.sockets[0].sent.length, 0);
  app.nodes.input.dispatch('keydown', { key: 'Enter' });
  assert.equal(app.sockets[0].sent.length, 1);
  app.sockets[0].close(4401);
  assert.equal(app.nodes.login.hidden, false);
  assert.equal(app.nodes.send.disabled, true);
  assert.equal(app.timers.size, 0);
});
