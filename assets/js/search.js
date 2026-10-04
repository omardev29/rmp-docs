// The search dialog. Loaded by site.js the first time somebody opens search,
// and it loads search.json then -- a page nobody searches from never pays for
// either. Names from the reference come first: someone typing `spawn` wants
// rmp::Scene::spawn before a paragraph that mentions spawning.
//
// The tokenizer is the one tools/rmpdocs/search.py indexes with: lowercase,
// then runs of [a-z0-9]. tests/test_search.py holds the two to it.
(function () {
  "use strict";
  var data = null;
  var dialog, input, list, status;
  var results = [];
  var selected = -1;
  var root = "";

  function tokens(text) { return (text.toLowerCase().match(/[a-z0-9]+/g) || []); }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function build() {
    dialog = document.createElement("dialog");
    dialog.className = "search-dialog";
    dialog.setAttribute("aria-label", "Search the documentation");
    dialog.innerHTML =
      '<input type="search" role="combobox" aria-expanded="false" aria-autocomplete="list" ' +
      'aria-controls="search-results" placeholder="Search names and pages" autocomplete="off" spellcheck="false">' +
      '<p class="visually-hidden" role="status" aria-live="polite"></p>' +
      '<ul id="search-results" class="search-results" role="listbox" aria-label="Results"></ul>';
    document.body.appendChild(dialog);
    input = dialog.querySelector("input");
    list = dialog.querySelector("ul");
    status = dialog.querySelector("[role=status]");
    input.addEventListener("input", run);
    input.addEventListener("keydown", keys);
    dialog.addEventListener("click", function (e) { if (e.target === dialog) dialog.close(); });
  }

  function load() {
    if (data) return Promise.resolve(data);
    return fetch(root + "assets/search.json").then(function (r) { return r.json(); })
      .then(function (d) { data = d; return d; });
  }

  function search(query) {
    var q = tokens(query);
    if (!q.length) return [];
    var out = [];
    var lowered = query.toLowerCase().trim();
    // Names: every query word in the qualified name, the last one as a prefix.
    data.symbols.forEach(function (s) {
      var words = tokens(s.n);
      var ok = q.every(function (w, i) {
        return words.some(function (x) { return i === q.length - 1 ? x.indexOf(w) === 0 : x === w; });
      });
      if (!ok) return;
      var last = s.n.split("::").pop().toLowerCase();
      var score = 1000 + (last === q[q.length - 1] ? 400 : 0) + (s.n.toLowerCase() === lowered ? 500 : 0)
                  - s.n.length;
      out.push({ kind: s.k || "name", title: s.n, url: s.u, note: s.d, score: score });
    });
    // Pages: the sum of each word's weight; the last word matches as a prefix.
    var scores = {};
    var matched = {};
    q.forEach(function (w, i) {
      var keys = i === q.length - 1
        ? Object.keys(data.index).filter(function (k) { return k.indexOf(w) === 0; }).slice(0, 40)
        : (data.index[w] ? [w] : []);
      keys.forEach(function (k) {
        data.index[k].forEach(function (hit) {
          scores[hit[0]] = (scores[hit[0]] || 0) + hit[1];
          matched[hit[0]] = (matched[hit[0]] || {});
          matched[hit[0]][i] = true;
        });
      });
    });
    Object.keys(scores).forEach(function (d) {
      if (Object.keys(matched[d]).length < q.length) return;  // every word, somewhere
      var doc = data.docs[d];
      out.push({ kind: doc.s || "page", title: doc.t, url: doc.u, note: doc.x, score: scores[d] });
    });
    out.sort(function (a, b) { return b.score - a.score; });
    return out.slice(0, 30);
  }

  function run() {
    results = search(input.value);
    selected = results.length ? 0 : -1;
    render();
  }

  function render() {
    input.setAttribute("aria-expanded", results.length ? "true" : "false");
    if (!results.length) {
      list.innerHTML = input.value.trim() ? '<li class="search-empty">Nothing matches that.</li>' : "";
      status.textContent = input.value.trim() ? "No results" : "";
      input.removeAttribute("aria-activedescendant");
      return;
    }
    list.innerHTML = results.map(function (r, i) {
      return '<li role="option" id="search-r' + i + '" aria-selected="' + (i === selected) + '">' +
        '<a href="' + esc(root + r.url) + '"><span class="kind">' + esc(r.kind) + "</span> " +
        esc(r.title) + (r.note ? "<small>" + esc(r.note) + "</small>" : "") + "</a></li>";
    }).join("");
    status.textContent = results.length + " results";
    if (selected >= 0) input.setAttribute("aria-activedescendant", "search-r" + selected);
  }

  function keys(e) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!results.length) return;
      selected = (selected + (e.key === "ArrowDown" ? 1 : -1) + results.length) % results.length;
      render();
      var el = document.getElementById("search-r" + selected);
      if (el) el.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" && selected >= 0) {
      e.preventDefault();
      location.href = root + results[selected].url;
    }
  }

  window.rmpSearch = {
    open: function (siteRoot) {
      root = siteRoot || "";
      if (!dialog) build();
      dialog.showModal();
      input.select();
      load().then(run);
    },
    tokens: tokens,
  };
})();
