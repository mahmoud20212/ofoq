(() => {
  const dialog = document.querySelector('[data-assessment-history-dialog]');
  if (!dialog || typeof dialog.showModal !== 'function' || !window.fetch) return;
  const content = dialog.querySelector('[data-history-content]');
  const status = dialog.querySelector('[data-history-status]');
  const retry = dialog.querySelector('[data-history-retry]');
  const back = dialog.querySelector('[data-history-back]');
  const title = dialog.querySelector('#assessment-history-title');
  let opener, controller, currentUrl, currentView = 'history', historyNodes = [], historyScroll = 0, resultOpener;
  const load = async (url, view = 'history') => {
    controller?.abort();
    controller = new AbortController();
    const current = controller;
    currentUrl = url;
    currentView = view;
    retry.hidden = true;
    status.textContent = view === 'result' ? 'جارٍ تحميل النتيجة' : 'جارٍ تحميل سجل المحاولات';
    content.setAttribute('aria-busy', 'true');
    content.hidden = true;
    try {
      const response = await fetch(url, {credentials: 'same-origin', signal: current.signal});
      if (!response.ok || response.redirected) throw new Error('history');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (current !== controller || !dialog.open) return;
      if (view === 'result') {
        const result = page.querySelector('.assessment-result-material');
        if (!result) throw new Error('result');
        result.querySelector('.assessment-introduction-tools')?.remove();
        result.querySelector('.assessment-result-actions')?.remove();
        content.replaceChildren(result);
        title.textContent = `نتيجة المحاولة ${result.dataset.attemptNumber || ''}`.trim();
        back.hidden = false;
        status.textContent = '';
        dialog.scrollTop = 0;
        back.focus({preventScroll:true});
        return;
      }
      const history = page.querySelector('.student-assessment-history');
      if (!history) throw new Error('history');
      const pages = history.nextElementSibling;
      history.querySelector('.student-assessment-section-heading')?.remove();
      content.replaceChildren(history);
      history.querySelectorAll('a[href]').forEach(link => {
        if (!/\/attempts\/\d+\/summary\/$/.test(new URL(link.getAttribute('href'), response.url || url).pathname)) return;
        link.addEventListener('click', event => {
          event.preventDefault();
          historyNodes = [...content.childNodes];
          historyScroll = dialog.scrollTop;
          resultOpener = link;
          load(link.href, 'result');
        });
      });
      if (pages?.matches('nav.student-assessment-actions')) {
        pages.querySelectorAll('a').forEach(link => {
          link.href = new URL(link.getAttribute('href'), response.url || url).href;
          link.addEventListener('click', event => {
            if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            event.preventDefault(); load(link.href);
          });
        });
        content.append(pages);
      }
      status.textContent = '';
      title.textContent = 'سجل المحاولات';
      back.hidden = true;
    } catch (error) {
      if (current !== controller || error.name === 'AbortError') return;
      status.textContent = view === 'result' ? 'تعذّر تحميل النتيجة' : 'تعذّر تحميل سجل المحاولات';
      retry.hidden = false;
    } finally {
      if (current === controller) {
        content.removeAttribute('aria-busy');
        content.hidden = false;
      }
    }
  };
  document.querySelectorAll('[data-assessment-history-open]').forEach(link => {
    link.addEventListener('click', event => {
      event.preventDefault(); opener = link;
      historyNodes = []; back.hidden = true; title.textContent = 'سجل المحاولات';
      content.replaceChildren(); dialog.showModal(); load(link.dataset.historyUrl);
    });
  });
  retry.addEventListener('click', () => load(currentUrl, currentView));
  back.addEventListener('click', () => {
    controller?.abort();
    content.replaceChildren(...historyNodes);
    title.textContent = 'سجل المحاولات';
    back.hidden = true; retry.hidden = true; status.textContent = '';
    content.removeAttribute('aria-busy');
    content.hidden = false;
    dialog.scrollTop = historyScroll;
    resultOpener?.focus({preventScroll:true});
  });
  dialog.querySelector('[data-assessment-history-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { controller?.abort(); opener?.focus(); });
})();
