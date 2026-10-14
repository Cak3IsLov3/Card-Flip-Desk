/* Character counter and copy buttons for the listing generator.
 * Bound to document, so it keeps working after an HTMX swap. */
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
      button.textContent = "Copied ✓";
    } catch {
      source.select(); // no clipboard access: select it so Ctrl+C works
      button.textContent = "Selected – press Ctrl+C";
    }
    setTimeout(() => (button.textContent = original), 1800);
  });
})();
