(function () {
  "use strict";

  function chartData() {
    var el = document.getElementById("report-charts-data");
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  function render(id, config) {
    var canvas = document.getElementById(id);
    if (!canvas || typeof Chart === "undefined") return;
    var existing = Chart.getChart(canvas);
    if (existing) existing.destroy();
    new Chart(canvas, config);
  }

  function init() {
    var data = chartData();
    if (!data) return;
    var palette = { navy: "#1e3a5f", burgundy: "#7c2d3e", amber: "#b45309", green: "#15803d", slate: "#64748b" };

    render("chart-monthly", {
      type: "bar",
      data: {
        labels: data.monthly.labels,
        datasets: [
          { label: "Tạo mới", data: data.monthly.created, backgroundColor: palette.navy },
          { label: "Hoàn thành", data: data.monthly.completed, backgroundColor: palette.green },
        ],
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } },
    });

    render("chart-status", {
      type: "doughnut",
      data: {
        labels: data.status.labels,
        datasets: [{
          data: data.status.counts,
          backgroundColor: [palette.green, "#b91c1c", palette.amber, palette.slate],
        }],
      },
      options: { responsive: true, maintainAspectRatio: false },
    });

    render("chart-folder", {
      type: "bar",
      data: {
        labels: data.by_folder.labels,
        datasets: [{ label: "Số hồ sơ", data: data.by_folder.counts, backgroundColor: palette.burgundy }],
      },
      options: {
        indexAxis: "y", responsive: true, maintainAspectRatio: false,
        scales: { x: { beginAtZero: true, ticks: { precision: 0 } } },
        plugins: { legend: { display: false } },
      },
    });

    render("chart-age", {
      type: "bar",
      data: {
        labels: data.overdue_age.labels,
        datasets: [{ label: "Số hồ sơ", data: data.overdue_age.counts, backgroundColor: "#b91c1c" }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
        plugins: { legend: { display: false } },
      },
    });
  }

  document.addEventListener("DOMContentLoaded", init);
  document.body.addEventListener("htmx:load", init);
})();
