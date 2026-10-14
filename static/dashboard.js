/* Grafieken voor het dashboard (Chart.js).
 *
 * Kleuren komen uit CSS-variabelen, zodat licht en donker hun eigen,
 * vooraf gecontroleerde stappen gebruiken. Eén y-as per grafiek.
 */
(function () {
  const dataEl = document.getElementById("chart-data");
  if (!dataEl || !window.Chart) return;
  const data = JSON.parse(dataEl.textContent);
  const euro = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR" });
  const pct = new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const num = (xs) => xs.map(Number);

  function tokens() {
    const s = getComputedStyle(document.documentElement);
    const v = (name) => s.getPropertyValue(name).trim();
    return {
      s1: v("--series-1"), s2: v("--series-2"), text: v("--text"), muted: v("--muted"),
      line: v("--line"), panel: v("--panel"),
    };
  }

  function baseOptions(t) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false }, // eigen HTML-legenda boven de grafiek
        tooltip: {
          backgroundColor: t.panel, titleColor: t.muted, bodyColor: t.text,
          borderColor: t.line, borderWidth: 1, padding: 10, boxPadding: 4,
          bodyFont: { weight: "600" },
        },
      },
      scales: {
        x: { grid: { display: false }, border: { color: t.line }, ticks: { color: t.muted, maxRotation: 0, autoSkip: true } },
        y: { grid: { color: t.line }, border: { display: false }, ticks: { color: t.muted } },
      },
    };
  }

  const charts = [];

  function monthsChart(t) {
    const el = document.getElementById("chart-months");
    if (!el) return;
    const opts = baseOptions(t);
    opts.scales.y.ticks.callback = (v) => euro.format(v);
    opts.plugins.tooltip.callbacks = { label: (c) => ` ${euro.format(c.parsed.y)}  ${c.dataset.label}` };
    opts.interaction = { mode: "index", intersect: false };
    const bar = { borderRadius: 4, borderSkipped: "start", categoryPercentage: 0.7, barPercentage: 0.9,
                  borderWidth: 0, maxBarThickness: 22 };
    charts.push(new Chart(el, {
      type: "bar",
      data: {
        labels: data.months.labels,
        datasets: [
          { ...bar, label: "Omzet", data: num(data.months.revenue), backgroundColor: t.s1 },
          { ...bar, label: "Winst", data: num(data.months.profit), backgroundColor: t.s2 },
        ],
      },
      options: opts,
    }));
  }

  function setsChart(t) {
    const el = document.getElementById("chart-sets");
    if (!el) return;
    const profit = num(data.sets.profit);
    const opts = baseOptions(t);
    opts.indexAxis = "y";
    opts.scales.x.grid = { color: t.line };
    opts.scales.x.ticks.callback = (v) => `${pct.format(v)}%`;
    opts.scales.y.grid = { display: false };
    opts.plugins.tooltip.callbacks = {
      label: (c) => ` ${pct.format(c.parsed.x)}% marge`,
      afterLabel: (c) => ` ${euro.format(profit[c.dataIndex])} winst`,
    };
    charts.push(new Chart(el, {
      type: "bar",
      data: {
        labels: data.sets.labels,
        datasets: [{
          label: "Marge", data: num(data.sets.margin), backgroundColor: t.s1,
          borderRadius: 4, borderSkipped: "start", borderWidth: 0, maxBarThickness: 18,
        }],
      },
      options: opts,
    }));
  }

  function render() {
    charts.splice(0).forEach((c) => c.destroy());
    const t = tokens();
    monthsChart(t);
    setsChart(t);
  }

  render();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
})();
