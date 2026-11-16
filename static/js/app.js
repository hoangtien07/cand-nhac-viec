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

  function closeModal() {
    var root = document.getElementById("modal-root");
    if (root) root.innerHTML = "";
  }

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    openPopovers().forEach(function (d) { d.open = false; d.querySelector("summary").focus(); });
    if (sidebar && sidebar.classList.contains("is-open")) { setDrawer(false); toggle.focus(); }
    closeModal();
  });
  document.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest("[data-modal-close]")) closeModal();
    var results = document.getElementById("qs-results");
    if (results && results.childElementCount && !(e.target.closest && e.target.closest(".po-combo"))) {
      results.innerHTML = "";
    }
  });
  document.addEventListener("htmx:afterSwap", function (e) {
    if (e.target.id === "modal-root") {
      var field = e.target.querySelector(".po-modal input:not([type=radio]), .po-modal button");
      if (field) field.focus();
    }
  });
  document.addEventListener("click", function (e) {
    var opener = e.target.closest && e.target.closest("[data-open-popover]");
    var target = opener && document.querySelector('details[data-testid="' + opener.dataset.openPopover + '"]');
    if (target) {
      e.preventDefault();
      target.open = true;
      target.querySelector("summary").focus();
      window.scrollTo({ top: 0 });
      return;
    }
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
