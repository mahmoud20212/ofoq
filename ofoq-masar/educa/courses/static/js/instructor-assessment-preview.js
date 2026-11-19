(() => {
  const info = document.querySelector('[data-preview-info-dialog]');
  const infoButton = document.querySelector('[data-preview-info-open]');
  if (info && infoButton && typeof info.showModal === 'function') {
    infoButton.hidden = false;
    infoButton.addEventListener('click', () => info.showModal());
    info.querySelector('[data-preview-info-close]').addEventListener('click', () => info.close());
    info.addEventListener('close', () => infoButton.focus());
  }
  const root = document.querySelector('[data-assessment-preview]');
  if (!root) return;
  const questions = [...root.querySelectorAll('[data-preview-question]')];
  const numbers = [...root.querySelectorAll('[data-question-number]')];
  const previous = root.querySelector('[data-preview-previous]');
  const next = root.querySelector('[data-preview-next]');
  const position = root.querySelector('[data-preview-position]');
  const navigation = root.querySelector('[data-preview-navigation]');
  if (!questions.length || numbers.length !== questions.length) return;
  let current = 0;
  const syncAnswers = () => questions.forEach((question,index) => {
    const answered = Boolean(question.querySelector('input[type="radio"]:checked')?.value);
    numbers[index].setAttribute('data-answered',String(answered));
    numbers[index].setAttribute('aria-label',`السؤال ${index + 1}، ${answered ? 'مجاب' : 'غير مجاب'}`);
  });
  const show = (index, focus = false) => {
    if (index < 0 || index >= questions.length) return;
    current = index;
    questions.forEach((question, offset) => { question.hidden = offset !== current; });
    numbers.forEach((number, offset) => {
      if (offset === current) number.setAttribute('aria-current','step');
      else number.removeAttribute('aria-current');
    });
    previous.disabled = current === 0;
    next.disabled = current === questions.length - 1;
    position.textContent = `السؤال ${current + 1} من ${questions.length}`;
    syncAnswers();
    if (focus) {
      questions[current].querySelector('h2').focus({preventScroll:true});
      questions[current].scrollIntoView({block:'nearest'});
    }
  };
  numbers.forEach((number, index) => number.addEventListener('click', event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); show(index, true);
  }));
  previous.addEventListener('click', () => show(current - 1, true));
  questions.forEach(question => question.addEventListener('change',syncAnswers));
  next.addEventListener('click', () => show(current + 1, true));
  const initial = questions.findIndex(question => '#' + question.id === window.location.hash);
  root.classList.add('is-paged-preview');
  navigation.hidden = false;
  show(initial < 0 ? 0 : initial);
})();
