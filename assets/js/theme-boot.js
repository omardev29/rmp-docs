// Runs in <head>, before the first paint, so a dark page never flashes white.
// The choice is "auto" (follow the system), "light" or "dark"; ?theme=... in
// the address wins for one visit, which is how the screenshots are taken.
(function () {
  var choice = null;
  try {
    var m = /[?&]theme=(light|dark|auto)\b/.exec(location.search);
    choice = m ? m[1] : localStorage.getItem("rmp-theme");
  } catch (e) { /* storage blocked: follow the system */ }
  if (choice === "light" || choice === "dark") {
    document.documentElement.setAttribute("data-theme", choice);
  }
})();
