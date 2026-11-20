/* Price advice: median price per day and source (Chart.js).
 *
 * Colours come from CSS variables (validated categorical slots 1-3, light and
 * dark). Each source also has its own point shape, so lines stay apart without
 * colour; the snapshots table below holds the same figures. Re-renders after
 * HTMX swaps in new advice.
 */
(function () {
  const euro = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" });
  const style = {
    manual_sold: { color: "--series-1", point: "circle" },
    own_history: { color: "--series-2", point: "rect" },
    ebay_active: { color: "--series-3", point: "triangle" },
  };
  let chart = null;

  function render() {
    const dataEl = document.getElementById("price-history");
    const canvas = document.getElementById("chart-price-history");
    if (chart) { chart.destroy(); chart = null; }
    if (!dataEl || !canvas || !window.Chart) return;
    const data = JSON.parse(dataEl.textContent);
    const css = getComputedStyle(document.documentElement);
    const v = (name) => css.getPropertyValue(name).trim();
    const t = { text: v("--text"), muted: v("--muted"), line: v("--line"), panel: v("--panel") };

    chart = new Chart(canvas, {
      type: "line",
      data: {
        labels: data.days,
        datasets: data.series.map((s) => {
          const colour = v(style[s.key].color);
          return {
            label: s.label,
            data: s.values.map((x) => (x === null ? null : Number(x))),
            borderColor: colour, backgroundColor: colour, borderWidth: 2,
            pointStyle: style[s.key].point, pointRadius: 5, pointHoverRadius: 7,
            pointBorderColor: t.panel, pointBorderWidth: 1,
            spanGaps: true, tension: 0,
          };
        }),
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false }, // HTML legend above the chart
          tooltip: {
            backgroundColor: t.panel, titleColor: t.muted, bodyColor: t.text,
            borderColor: t.line, borderWidth: 1, padding: 10, boxPadding: 4, usePointStyle: true,
            filter: (item) => item.parsed.y !== null,
            callbacks: { label: (c) => ` ${euro.format(c.parsed.y)}  ${c.dataset.label}` },
          },
        },
        scales: {
          x: { grid: { display: false }, border: { color: t.line }, ticks: { color: t.muted, maxRotation: 0, autoSkip: true } },
          y: { grid: { color: t.line }, border: { display: false },
               ticks: { color: t.muted, callback: (value) => euro.format(value) } },
        },
      },
    });
  }

  document.addEventListener("DOMContentLoaded", render);
  document.body.addEventListener("htmx:afterSwap", render);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
})();
