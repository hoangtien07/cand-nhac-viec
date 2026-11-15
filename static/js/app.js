(function () {
  "use strict";
  var sidebar = document.getElementById("app-sidebar");
  var toggle = document.querySelector("[data-drawer-toggle]");
  var backdrop = document.querySelector("[data-drawer-close]");

  function setDrawer(open) {
    if (!sidebar || !toggle) return;
    sidebar.classList.toggle("is-open", open);
    if (backdrop) backdrop.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Đóng menu" : "Mở menu");
    if (open) {
      var first = sidebar.querySelector("a, button");
      if (first) first.focus();
    }
  }

  if (toggle) toggle.addEventListener("click", function () { setDrawer(!sidebar.classList.contains("is-open")); });
  if (backdrop) backdrop.addEventListener("click", function () { setDrawer(false); });

  function openPopovers() { return document.querySelectorAll("details[data-popover][open]"); }

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    openPopovers().forEach(function (d) { d.open = false; d.querySelector("summary").focus(); });
    if (sidebar && sidebar.classList.contains("is-open")) { setDrawer(false); toggle.focus(); }
  });
  document.addEventListener("click", function (e) {
    openPopovers().forEach(function (d) { if (!d.contains(e.target)) d.open = false; });
  });
  document.querySelectorAll("details[data-popover]").forEach(function (d) {
    d.addEventListener("toggle", function () {
      if (d.open) openPopovers().forEach(function (o) { if (o !== d) o.open = false; });
    });
  });
  document.addEventListener("change", function (e) {
    var form = e.target.closest && e.target.closest("form[data-autosubmit]");
    if (form) form.requestSubmit();
  });
})();
