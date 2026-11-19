(() => {
  const room = document.querySelector('[data-chat-room]');
  if (!room) return;
  const config = JSON.parse(document.getElementById('chat-config').textContent);
  const initial = JSON.parse(document.getElementById('chat-initial-messages').textContent);
  const find = name => room.querySelector(`[data-${name}]`);
  const log = find('log'), input = find('input'), send = find('send'), retry = find('retry');
  const older = find('older'), reconnect = find('reconnect'), jump = find('jump');
  const status = find('connection'), sendStatus = find('send-status');
  const entries = new Map();
  let socket, ready = false, stopped = false, attempts = 0, reconnectTimer, acknowledgementTimer;
  let pending = null, highest = 0, lowest = null, unseen = 0;
  const delays = [1000, 2000, 5000];
  const atBottom = () => log.scrollHeight - log.scrollTop - log.clientHeight < 100;
  const bottom = () => { log.scrollTop = log.scrollHeight; unseen = 0; jump.hidden = true; };
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const connection = (text, state = '') => {
    status.textContent = text;
    status.className = `chat-connection ${state}`;
  };
  const feedback = (text = '', error = false) => {
    sendStatus.textContent = text;
    sendStatus.classList.toggle('is-error', error);
  };
  const controls = () => {
    input.style.height = 'auto';
    input.style.height = `${Math.min(160, Math.max(68, input.scrollHeight + 2))}px`;
    send.disabled = !ready || !input.value.trim() || pending?.state === 'sending';
    input.readOnly = pending?.state === 'sending';
    retry.hidden = !(pending?.state === 'failed' && input.value.trim() === pending.content);
    retry.disabled = !ready;
  };
  const failPending = detail => {
    if (pending) pending.state = 'failed';
    clearTimeout(acknowledgementTimer);
    feedback(detail, true);
    controls();
  };
  const addMessage = (message, notify = false) => {
    if (!message || !Number.isSafeInteger(message.id) || !message.user) return;
    const ownPending = message.user.id === config.user_id && pending?.id === message.client_id;
    if (ownPending) {
      clearTimeout(acknowledgementTimer);
      if (input.value.trim() === pending.content) input.value = '';
      pending = null;
      feedback();
      controls();
    }
    if (entries.has(message.id)) return;
    const follow = notify && (atBottom() || ownPending);
    const mine = message.user.id === config.user_id;
    const article = element('article', `chat-message${mine ? ' is-mine' : ''}`);
    article.dataset.messageId = message.id;
    const header = element('div', 'chat-message-header');
    if (!mine) {
      header.append(element('bdi', 'chat-message-name', message.user.name));
      if (message.user.is_teacher) header.append(element('span', 'chat-teacher-badge', 'معلّم الدورة'));
    }
    const content = element('p', 'chat-message-content', message.content);
    content.dir = 'auto';
    const time = element('time', '');
    const date = new Date(message.sent_at);
    time.dateTime = message.sent_at;
    time.textContent = date.toLocaleString('ar', { hour: 'numeric', minute: '2-digit' });
    time.title = date.toLocaleString('ar');
    if (!mine) article.append(header);
    article.append(content, time);
    const nextId = [...entries.keys()].filter(id => id > message.id).sort((a, b) => a - b)[0];
    log.insertBefore(article, nextId === undefined ? null : entries.get(nextId));
    entries.set(message.id, article);
    highest = Math.max(highest, message.id);
    lowest = lowest === null ? message.id : Math.min(lowest, message.id);
    find('empty').hidden = true;
    if (follow) bottom();
    else if (notify) { unseen += 1; jump.textContent = `رسائل جديدة (${unseen})`; jump.hidden = false; }
  };
  initial.forEach(message => addMessage(message));
  bottom();
  const expired = () => {
    stopped = true; ready = false;
    clearTimeout(reconnectTimer);
    connection('انتهت الجلسة أو تغيّرت صلاحية الدخول', 'is-error');
    find('login').hidden = false;
    reconnect.hidden = true;
    failPending('سجّل الدخول مجددًا للمتابعة. النص ما زال في الحقل.');
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
  };
  const history = async params => {
    const url = new URL(config.history_url, location.origin);
    Object.entries(params).forEach(([key, value]) => url.searchParams.set(key, value));
    const response = await fetch(url, { cache: 'no-store', credentials: 'same-origin', redirect: 'manual', headers: { Accept: 'application/json' } });
    if (response.redirected || response.type === 'opaqueredirect' || [301, 302, 303, 307, 308, 401, 403].includes(response.status)) { expired(); throw new Error('access'); }
    if (!response.ok) throw new Error('history');
    return response.json();
  };
  const catchUp = async cursor => {
    let more = true;
    while (more && !stopped) {
      const data = await history({ after_id: cursor });
      data.messages.forEach(message => addMessage(message, true));
      const last = data.messages.at(-1)?.id;
      more = data.has_more && last > cursor;
      if (last) cursor = last;
    }
  };
  const scheduleReconnect = () => {
    ready = false;
    controls();
    if (stopped) return;
    if (attempts < delays.length) {
      connection('انقطع الاتصال؛ جارٍ إعادة المحاولة…');
      reconnectTimer = setTimeout(connect, delays[attempts++]);
    } else {
      connection('تعذّر الاتصال', 'is-error');
      reconnect.hidden = false;
    }
  };
  const connect = () => {
    if (stopped) return;
    clearTimeout(reconnectTimer);
    reconnect.hidden = true;
    connection('جارٍ الاتصال…');
    const recoveryCursor = highest;
    try { socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${config.socket_path}`); }
    catch (_) { scheduleReconnect(); return; }
    const current = socket;
    socket.onopen = async () => {
      connection('جارٍ مزامنة الرسائل…');
      try {
        await catchUp(recoveryCursor);
        if (stopped || current !== socket || socket.readyState !== WebSocket.OPEN) return;
        ready = true; attempts = 0;
        connection('متصل', 'is-connected');
        controls();
      } catch (_) {
        if (!stopped && current === socket) current.close();
      }
    };
    socket.onmessage = event => {
      if (current !== socket) return;
      let data;
      try { data = JSON.parse(event.data); } catch (_) { return; }
      if (data.type === 'message' || data.type === 'message.ack') addMessage(data.message, true);
      if (data.type === 'error') {
        if (!data.client_id || data.client_id === pending?.id) {
          failPending(data.detail || 'تعذّر الإرسال. حاول مجددًا.');
          if (!data.retryable) { pending = null; controls(); }
        }
      }
    };
    socket.onclose = event => {
      if (current !== socket) return;
      ready = false;
      if (pending?.state === 'sending') failPending('انقطع الاتصال قبل تأكيد الإرسال. يمكنك إعادة المحاولة بعد الاتصال.');
      if ([4401, 4403].includes(event.code)) { expired(); return; }
      scheduleReconnect();
    };
    socket.onerror = () => { /* onclose drives bounded retries. */ };
  };
  const submit = () => {
    if (!ready || socket?.readyState !== WebSocket.OPEN || pending?.state === 'sending') return;
    const content = input.value.trim();
    if (!content || Array.from(content).length > 2000) { feedback('اكتب رسالة بين حرف واحد و2000 حرف.', true); return; }
    const id = pending?.content === content ? pending.id : crypto.randomUUID();
    pending = { id, content, state: 'sending' };
    feedback('جارٍ الإرسال…');
    controls();
    try { socket.send(JSON.stringify({ type: 'message.send', client_id: id, content })); }
    catch (_) { failPending('تعذّر الإرسال. احتفظنا بالنص لإعادة المحاولة.'); return; }
    acknowledgementTimer = setTimeout(() => failPending('لم يصل تأكيد الإرسال. يمكنك إعادة المحاولة دون تكرار الرسالة.'), 10000);
  };
  find('composer').addEventListener('submit', event => { event.preventDefault(); submit(); });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) { event.preventDefault(); submit(); }
  });
  input.addEventListener('input', controls);
  retry.addEventListener('click', submit);
  reconnect.addEventListener('click', () => { attempts = 0; connect(); });
  jump.addEventListener('click', bottom);
  log.addEventListener('scroll', () => { if (atBottom()) { unseen = 0; jump.hidden = true; } });
  older.addEventListener('click', async () => {
    if (lowest === null) return;
    older.disabled = true; older.textContent = 'جارٍ تحميل الرسائل…';
    const anchor = log.querySelector('.chat-message');
    const anchorTop = anchor?.getBoundingClientRect().top;
    try {
      const data = await history({ before_id: lowest });
      data.messages.forEach(message => addMessage(message));
      if (anchor) log.scrollTop += anchor.getBoundingClientRect().top - anchorTop;
      older.hidden = !data.has_more;
    } catch (_) { if (!stopped) feedback('تعذّر تحميل الرسائل القديمة. حاول مجددًا.', true); }
    finally { older.disabled = false; older.textContent = 'تحميل رسائل أقدم'; }
  });
  window.addEventListener('pagehide', () => { stopped = true; clearTimeout(reconnectTimer); clearTimeout(acknowledgementTimer); socket?.close(); });
  window.addEventListener('pageshow', event => { if (event.persisted) { stopped = false; attempts = 0; connect(); } });
  connect();
})();
