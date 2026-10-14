/* Tekenteller en kopieerknoppen voor de listing-generator.
 * Gebonden aan document, zodat het ook werkt na een HTMX-swap. */
(function () {
  function updateCount(input) {
    const counter = document.querySelector(`[data-count-for="${input.id}"]`);
    if (!counter) return;
    const max = Number(input.getAttribute("maxlength")) || 80;
    counter.textContent = input.value.length;
    counter.classList.toggle("bad", input.value.length >= max);
  }

  document.addEventListener("input", (e) => {
    if (e.target.matches("[data-counter]")) updateCount(e.target);
  });

  document.addEventListener("click", async (e) => {
    const button = e.target.closest("[data-copy]");
    if (!button) return;
    const source = document.getElementById(button.dataset.copy);
    if (!source) return;
    const original = button.textContent;
    try {
      await navigator.clipboard.writeText(source.value);
      button.textContent = "Gekopieerd ✓";
    } catch {
      source.select(); // geen klembord-toegang: selecteer, dan kan Ctrl+C
      button.textContent = "Geselecteerd – druk Ctrl+C";
    }
    setTimeout(() => (button.textContent = original), 1800);
  });
})();
