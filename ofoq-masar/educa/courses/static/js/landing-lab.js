const labEditor = document.querySelector('.lab-editor');
if (labEditor && 'IntersectionObserver' in window && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
  const labObserver = new IntersectionObserver(([entry]) => {
    if (!entry.isIntersecting) return;
    labEditor.classList.add('lab-animate');
    labObserver.disconnect();
  }, { threshold: 0.35 });
  labObserver.observe(labEditor);
}
