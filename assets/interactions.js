(function () {
  "use strict";

  function boot() {
    if (!document.querySelector(".section-nav-link")) {
      window.setTimeout(boot, 80);
      return;
    }
    if (document.body.getAttribute("data-silsila-interactions") === "ready") return;
    document.body.setAttribute("data-silsila-interactions", "ready");
    document.body.classList.add("silsila-ready");

    var sections = Array.prototype.slice.call(document.querySelectorAll(".panel, .bottom-panel, .recovery-panel, .mc-panel"));
    sections.forEach(function (section, index) {
      section.classList.add("reveal-section");
      section.style.setProperty("--reveal-delay", Math.min(index * 45, 300) + "ms");
    });

    if ("IntersectionObserver" in window) {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
      sections.forEach(function (section) { observer.observe(section); });
    } else {
      sections.forEach(function (section) { section.classList.add("is-visible"); });
    }

    var links = Array.prototype.slice.call(document.querySelectorAll(".section-nav-link"));
    var manualNavUntil = 0;
    function activateLink(link) {
      links.forEach(function (item) { item.classList.remove("active"); });
      if (link) link.classList.add("active");
    }
    function activateHashLink() {
      var link = document.querySelector('.section-nav-link[href="' + window.location.hash + '"]');
      if (link) activateLink(link);
    }
    links.forEach(function (link) {
      link.addEventListener("click", function () {
        manualNavUntil = Date.now() + 1200;
        activateLink(link);
        window.setTimeout(activateHashLink, 50);
        window.setTimeout(activateHashLink, 350);
      });
    });
    window.addEventListener("hashchange", function () {
      manualNavUntil = Date.now() + 1200;
      activateHashLink();
      window.setTimeout(activateHashLink, 50);
      window.setTimeout(activateHashLink, 350);
    });

    var tracked = Array.prototype.slice.call(document.querySelectorAll("#network-graph, #cascade-log, #recovery-panel, #mc-panel"));
    if ("IntersectionObserver" in window && tracked.length) {
      var activeObserver = new IntersectionObserver(function (entries) {
        if (Date.now() < manualNavUntil) return;
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          var link = document.querySelector('.section-nav-link[href="#' + entry.target.id + '"]');
          if (!link) return;
          activateLink(link);
        });
      }, { rootMargin: "-25% 0px -60% 0px", threshold: 0 });
      tracked.forEach(function (section) { activeObserver.observe(section); });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
