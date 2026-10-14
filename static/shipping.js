/* A shipping method fills in the shipping cost. The cost stays editable;
 * without JavaScript the server fills it in when it is left at 0. */
(function () {
  document.addEventListener("change", (e) => {
    const select = e.target;
    if (!select.matches("select[data-fills]")) return;
    const cost = select.selectedOptions[0]?.dataset.cost;
    const input = select.form?.elements[select.dataset.fills];
    if (cost === undefined || !input) return;
    input.value = cost;
    // Let the HTMX calculator recalculate straight away.
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
})();
