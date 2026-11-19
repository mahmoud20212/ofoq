(() => {
 const filters = document.querySelector('.filter-panel');
 if (!filters) return;
 const small = matchMedia('(max-width: 760px)');
 const update = () => { filters.open = !small.matches; };
 small.addEventListener('change', update); update();
})();