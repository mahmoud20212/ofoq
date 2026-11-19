(() => {
  const iconSprite = document.documentElement.dataset.iconSprite ||
    new URL('../vendor/lucide/masar-icons.svg', document.currentScript.src).href;
  const themeButton = document.querySelector('.theme-toggle');
  const applyTheme = (light) => {
    document.documentElement.dataset.theme = light ? 'light' : 'dark';
    themeButton.setAttribute('aria-pressed', String(light));
    themeButton.setAttribute('aria-label', light ? 'تفعيل الوضع الداكن' : 'تفعيل الوضع الفاتح');
    themeButton.innerHTML = light ? `<svg class="icon lucide-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><use href="${iconSprite}#moon" width="24" height="24"/></svg>` : `<svg class="icon lucide-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><use href="${iconSprite}#sun" width="24" height="24"/></svg>`;
    document.querySelector('meta[name="theme-color"]').content = light ? '#f4f5fb' : '#080a12';
  };
  let savedTheme;
  try { savedTheme = localStorage.getItem('ofoq-masar-theme'); } catch (_) {}
  applyTheme(savedTheme ? savedTheme === 'light' : matchMedia('(prefers-color-scheme: light)').matches);
  themeButton.addEventListener('click', () => {
    const light = document.documentElement.dataset.theme !== 'light';
    applyTheme(light);
    try { localStorage.setItem('ofoq-masar-theme', light ? 'light' : 'dark'); } catch (_) {}
  });
  const menuButton = document.querySelector('.menu-toggle');
  const menu = document.querySelector('#mobile-nav');
  const closeMenu = () => { menu.hidden = true; menuButton.setAttribute('aria-expanded', 'false'); };
  menuButton.addEventListener('click', () => {
    menu.hidden = !menu.hidden;
    menuButton.setAttribute('aria-expanded', String(!menu.hidden));
  });
  menu.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMenu));
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !menu.hidden) { closeMenu(); menuButton.focus(); } });
})();

(() => {
 const scene = document.querySelector('.learning-scene');
 if (!scene) return;
 const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
 const finePointer = matchMedia('(hover: hover) and (pointer: fine)');
 const reset = () => { scene.style.setProperty('--scene-x', '0deg'); scene.style.setProperty('--scene-y', '0deg'); };
 scene.addEventListener('pointermove', event => {
   if (reducedMotion.matches || !finePointer.matches) return;
   const rect = scene.getBoundingClientRect();
   scene.style.setProperty('--scene-y', `${((event.clientX - rect.left) / rect.width - .5) * 9}deg`);
   scene.style.setProperty('--scene-x', `${-((event.clientY - rect.top) / rect.height - .5) * 7}deg`);
 });
 scene.addEventListener('pointerleave', reset);

 reducedMotion.addEventListener('change', reset);
})();

(() => {
 const header = document.querySelector('.header');
 const links = [...document.querySelectorAll('.desktop-nav a')];
 let frame = 0;
 const update = () => {
  frame = 0;
  header.classList.toggle('header-scrolled', window.scrollY > 24);
  const line = header.getBoundingClientRect().bottom + 70;
  let active = location.pathname === '/' && window.scrollY < 100 ? links[0] : links.find(link => new URL(link.href).pathname === location.pathname && !new URL(link.href).hash);
  links.forEach(link => {
   const target = new URL(link.href);
   const section = target.pathname === location.pathname && target.hash ? document.querySelector(target.hash) : null;
   if (!section || section.id === 'main') return;
   const bounds = section.getBoundingClientRect();
   if (bounds.top <= line && bounds.bottom > line) active = link;
  });
  links.forEach(link => {
   link.classList.toggle('active', link === active);
   if (link === active) link.setAttribute('aria-current', 'location');
   else link.removeAttribute('aria-current');
  });
 };
 const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
 window.addEventListener('scroll', schedule, {passive:true});
 window.addEventListener('resize', schedule);
 const desktop = matchMedia('(min-width: 1081px)');
 desktop.addEventListener('change', () => {
  if (desktop.matches) {
   document.querySelector('#mobile-nav').hidden = true;
   document.querySelector('.menu-toggle').setAttribute('aria-expanded', 'false');
  }
 });
 update();
})();
