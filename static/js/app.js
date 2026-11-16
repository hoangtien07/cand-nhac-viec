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

  // Row-action menus: escape overflow-x clipping by floating the panel fixed over the table.
  document.addEventListener(
    "toggle",
    function (e) {
      var d = e.target;
      if (!(d instanceof HTMLDetailsElement) || !d.classList.contains("po-menu")) return;
      var panel = d.querySelector(".po-menu-panel");
      if (!panel) return;
      if (d.open) {
        var r = d.querySelector("summary").getBoundingClientRect();
        panel.style.position = "fixed";
        panel.style.top = r.bottom + 4 + "px";
        panel.style.right = window.innerWidth - r.right + "px";
        panel.style.left = "auto";
        panel.style.bottom = "auto";
      } else {
        panel.style.position = "";
        panel.style.top = "";
        panel.style.right = "";
        panel.style.left = "";
        panel.style.bottom = "";
      }
    },
    true
  );
  window.addEventListener("scroll", function () {
    document.querySelectorAll("details.po-menu[open]").forEach(function (d) {
      d.open = false;
    });
  }, true);

  // Trim empty GET params: clean URLs for filter forms marked data-trim-params.
  document.addEventListener("htmx:configRequest", function (e) {
    var form = e.detail.elt.closest && e.detail.elt.closest("form[data-trim-params]");
    if (!form) return;
    Object.keys(e.detail.parameters).forEach(function (k) {
      var v = e.detail.parameters[k];
      if (v === "" || v == null) delete e.detail.parameters[k];
    });
  });
  document.addEventListener("submit", function (e) {
    var form = e.target.closest && e.target.closest("form[data-trim-params]");
    if (!form) return;
    form.querySelectorAll("input[name], select[name]").forEach(function (el) {
      if (el.value === "") el.disabled = true;
    });
  });
})();
