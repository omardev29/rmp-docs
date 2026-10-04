// What every page does once it has loaded: the theme switch, the navigation
// dialog on narrow screens, copy buttons, "On this page" following the
// reader, and opening search. Nothing here is needed to READ a page; with
// JavaScript off the site is the same text, minus these conveniences.
(function () {
  "use strict";
  var root = document.body.getAttribute("data-root") || "";

  // --- theme: auto -> light -> dark -> auto ---------------------------------
  var ORDER = ["auto", "light", "dark"];
  var themeButton = document.querySelector(".theme-toggle");
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") || "auto";
  }
  function showTheme() {
    if (!themeButton) return;
    var t = currentTheme();
    themeButton.setAttribute("aria-label", "Colour theme: " + t + ". Change it.");
    themeButton.setAttribute("data-theme-now", t);
    var label = themeButton.querySelector(".label");
    if (label) label.textContent = t.charAt(0).toUpperCase() + t.slice(1);
  }
  if (themeButton) {
    themeButton.addEventListener("click", function () {
      var next = ORDER[(ORDER.indexOf(currentTheme()) + 1) % ORDER.length];
      if (next === "auto") document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("rmp-theme", next); } catch (e) { /* private window */ }
      showTheme();
    });
    showTheme();
  }

  // --- navigation dialog ------------------------------------------------------
  var navDialog = document.getElementById("nav-dialog");
  var navToggle = document.querySelector(".nav-toggle");
  if (navDialog && navToggle && navDialog.showModal) {
    navToggle.addEventListener("click", function () {
      navDialog.showModal();
      navToggle.setAttribute("aria-expanded", "true");
    });
    navDialog.addEventListener("close", function () {
      navToggle.setAttribute("aria-expanded", "false");
    });
    navDialog.addEventListener("click", function (e) {
      if (e.target === navDialog) navDialog.close();  // a click on the backdrop
    });
    var close = navDialog.querySelector(".dialog-close");
    if (close) close.addEventListener("click", function () { navDialog.close(); });
  }

  // --- copy buttons -------------------------------------------------------------
  document.querySelectorAll(".code-block").forEach(function (block) {
    var pre = block.querySelector("pre");
    if (!pre || !navigator.clipboard) return;
    var b = document.createElement("button");
    b.type = "button";
    b.className = "icon-button copy-button";
    b.textContent = "Copy";
    b.addEventListener("click", function () {
      navigator.clipboard.writeText(pre.innerText.replace(/\n$/, "")).then(function () {
        b.textContent = "Copied";
        setTimeout(function () { b.textContent = "Copy"; }, 1500);
      });
    });
    var head = block.querySelector(".code-head");
    (head || block).appendChild(b);
  });

  // --- "On this page" follows the reader -------------------------------------
  var tocLinks = Array.prototype.slice.call(document.querySelectorAll(".toc a[href^='#']"));
  if (tocLinks.length && "IntersectionObserver" in window) {
    var byId = {};
    tocLinks.forEach(function (a) { byId[decodeURIComponent(a.hash.slice(1))] = a; });
    var visible = {};
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { visible[e.target.id] = e.isIntersecting; });
      var first = null;
      document.querySelectorAll(".prose h2[id], .prose h3[id]").forEach(function (h) {
        if (!first && visible[h.id]) first = h.id;
      });
      if (!first) return;
      tocLinks.forEach(function (a) { a.removeAttribute("aria-current"); });
      if (byId[first]) byId[first].setAttribute("aria-current", "true");
    }, { rootMargin: "-10% 0px -70% 0px" });
    document.querySelectorAll(".prose h2[id], .prose h3[id]").forEach(function (h) {
      observer.observe(h);
    });
  }

  // --- search: loaded the first time somebody asks for it -----------------------
  var searchLoaded = null;
  function openSearch() {
    if (!searchLoaded) {
      searchLoaded = new Promise(function (resolve, reject) {
        var s = document.createElement("script");
        s.src = root + "assets/js/search.js";
        s.onload = resolve;
        s.onerror = reject;
        document.head.appendChild(s);
      });
    }
    searchLoaded.then(function () { window.rmpSearch.open(root); });
  }
  document.querySelectorAll(".search-open").forEach(function (b) {
    b.addEventListener("click", openSearch);
  });
  document.addEventListener("keydown", function (e) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) ||
                 document.activeElement.isContentEditable;
    if ((e.key === "/" && !typing) || (e.key.toLowerCase() === "k" && (e.ctrlKey || e.metaKey))) {
      e.preventDefault();
      openSearch();
    }
  });
})();

// --- examples: a poster until somebody asks, then the example itself ---------
(function () {
  "use strict";
  var root = document.body.getAttribute("data-root") || "";
  document.querySelectorAll(".player[data-play]").forEach(function (player) {
    var button = player.querySelector(".play-button");
    if (!button) return;
    button.addEventListener("click", function () {
      // One example at a time: another one playing is stopped by removing it.
      document.querySelectorAll(".player iframe").forEach(function (f) {
        var p = f.parentNode;
        f.remove();
        if (p.dataset.poster) p.insertAdjacentHTML("afterbegin", p.dataset.poster);
      });
      var img = player.querySelector("img");
      player.dataset.poster = img ? img.outerHTML : "";
      if (img) img.remove();
      button.hidden = true;
      var frame = document.createElement("iframe");
      frame.src = root + player.getAttribute("data-play").replace(/^\//, "");
      frame.width = 800;
      frame.height = 450;
      frame.title = "The example, running";
      frame.setAttribute("allow", "autoplay; fullscreen; gamepad");
      player.appendChild(frame);
      // The example draws at its design size; the page scales it to fit, and
      // the browser maps every click back through the same scale.
      function fit() { frame.style.transform = "scale(" + player.clientWidth / 800 + ")"; }
      fit();
      window.addEventListener("resize", fit);
      frame.addEventListener("load", function () { frame.contentWindow.focus(); });
    });
  });
})();
