(() => {
  const preference = window.matchMedia("(prefers-color-scheme: dark)");
  function applyTheme() {
    let saved;
    try { saved = localStorage.getItem("ofoq-theme"); } catch {}
    document.documentElement.dataset.theme =
      saved === "light" || saved === "dark" ? saved : preference.matches ? "dark" : "light";
  }
  applyTheme();
  preference.addEventListener("change", applyTheme);
  window.addEventListener("storage", event => {
    if (event.key === "ofoq-theme" || event.key === null) applyTheme();
  });
})();
