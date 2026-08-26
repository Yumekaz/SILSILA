(function () {
  "use strict";

  function start() {
    var canvas = document.getElementById("hero-scene");
    var hero = document.querySelector(".command-hero");
    if (!canvas || !hero) {
      window.setTimeout(start, 100);
      return;
    }
    if (canvas.getAttribute("data-ready") === "true") return;
    canvas.setAttribute("data-ready", "true");

    var ctx = canvas.getContext("2d");
    if (!ctx) return;

    var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    var pointer = { x: 0.5, y: 0.5 };
    var size = { width: 0, height: 0, ratio: 1 };
    var startedAt = performance.now();
    var nodes = [
      [0.67, 0.34], [0.77, 0.23], [0.87, 0.37], [0.75, 0.53],
      [0.92, 0.61], [0.62, 0.59], [0.84, 0.79], [0.55, 0.23],
      [0.98, 0.28], [0.70, 0.78], [0.48, 0.47], [0.89, 0.86]
    ];
    var routes = [[0, 1], [0, 2], [0, 3], [3, 4], [3, 5], [5, 6], [2, 8], [4, 7], [6, 9], [9, 10], [7, 11]];

    function resize() {
      var rect = hero.getBoundingClientRect();
      size.width = Math.max(1, rect.width);
      size.height = Math.max(1, rect.height);
      size.ratio = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(size.width * size.ratio);
      canvas.height = Math.round(size.height * size.ratio);
      canvas.style.width = size.width + "px";
      canvas.style.height = size.height + "px";
      ctx.setTransform(size.ratio, 0, 0, size.ratio, 0, 0);
    }

    function point(node, t) {
      return {
        x: node[0] * size.width + (pointer.x - 0.5) * 18,
        y: node[1] * size.height + (pointer.y - 0.5) * 12 + Math.sin(t * 0.00045 + node[0] * 8) * 2,
      };
    }

    function draw(now) {
      var t = reduced.matches ? startedAt : now;
      var w = size.width;
      var h = size.height;
      ctx.clearRect(0, 0, w, h);

      var glow = ctx.createRadialGradient(w * 0.78, h * 0.44, 0, w * 0.78, h * 0.44, Math.max(w, h) * 0.55);
      glow.addColorStop(0, "rgba(208,167,217,.11)");
      glow.addColorStop(0.6, "rgba(208,167,217,.025)");
      glow.addColorStop(1, "rgba(208,167,217,0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, w, h);

      routes.forEach(function (route, index) {
        var a = point(nodes[route[0]], t);
        var b = point(nodes[route[1]], t);
        var bend = (a.x + b.x) * 0.5;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.bezierCurveTo(bend, a.y - 28 - index * 2, bend, b.y + 28, b.x, b.y);
        ctx.strokeStyle = index % 3 === 0 ? "rgba(230,199,142,.30)" : "rgba(208,167,217,.20)";
        ctx.lineWidth = index % 3 === 0 ? 1.2 : 0.8;
        ctx.setLineDash(index % 2 ? [2, 7] : []);
        ctx.stroke();
      });
      ctx.setLineDash([]);

      nodes.forEach(function (node, index) {
        var p = point(node, t);
        var pulse = reduced.matches ? 0 : Math.sin(t * 0.002 + index) * 1.8;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 2.2 + pulse * 0.25, 0, Math.PI * 2);
        ctx.fillStyle = index === 0 ? "#75E0C0" : index % 3 === 0 ? "#E6C78E" : "#D0A7D9";
        ctx.shadowBlur = 12;
        ctx.shadowColor = ctx.fillStyle;
        ctx.fill();
        ctx.shadowBlur = 0;
      });

      if (!reduced.matches && !document.hidden) window.requestAnimationFrame(draw);
    }

    hero.addEventListener("pointermove", function (event) {
      var rect = hero.getBoundingClientRect();
      pointer.x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
      pointer.y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
    }, { passive: true });
    hero.addEventListener("pointerleave", function () { pointer.x = 0.5; pointer.y = 0.5; }, { passive: true });
    document.addEventListener("visibilitychange", function () { if (!document.hidden && !reduced.matches) window.requestAnimationFrame(draw); });
    if (window.ResizeObserver) new ResizeObserver(resize).observe(hero);
    window.addEventListener("resize", resize, { passive: true });
    resize();
    draw(startedAt);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
}());
