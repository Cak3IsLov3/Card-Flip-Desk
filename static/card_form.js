/* Show "Which parallel?" / "Which insert?" only while that variant is ticked.
 * Without JavaScript both fields simply stay visible. */
(function () {
  function sync() {
    document.querySelectorAll("[data-show-with-variant]").forEach((input) => {
      const variant = input.dataset.showWithVariant;
      const box = document.querySelector(`input[name="variants"][value="${variant}"]`);
      const field = input.closest(".field");
      if (box && field) field.hidden = !box.checked;
    });
  }

  document.addEventListener("change", (e) => {
    if (e.target.matches('input[name="variants"]')) sync();
  });
  sync();
})();
