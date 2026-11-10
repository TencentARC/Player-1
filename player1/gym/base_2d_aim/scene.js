(function precisionGalleryScene() {
  "use strict";
  var ASSETS = Object.freeze(["gallery_target", "gallery_panel", "gallery_cursor", "gallery_ring", "gallery_spark"]);

  function buildBays(layout, width, height, rng) {
    var templates = {
      open: [[0.18, 0.36, 0.27, 0.54], [0.5, 0.59, 0.27, 0.6], [0.82, 0.4, 0.27, 0.55]],
      range_lanes: [[0.15, 0.49, 0.20, 0.78], [0.385, 0.6, 0.20, 0.55], [0.62, 0.37, 0.20, 0.52], [0.855, 0.54, 0.20, 0.73]],
      split_panels: [[0.25, 0.28, 0.39, 0.34], [0.25, 0.73, 0.39, 0.34], [0.74, 0.5, 0.41, 0.79]],
      corner_bays: [[0.19, 0.28, 0.28, 0.36], [0.19, 0.75, 0.28, 0.32], [0.51, 0.49, 0.24, 0.63], [0.83, 0.25, 0.25, 0.31], [0.83, 0.7, 0.25, 0.39]],
    };
    return templates[layout.template].map(function bay(value, index) {
      var w = Math.round(width * value[2] * rng.range(0.88, 1));
      var h = Math.round(height * value[3] * rng.range(0.87, 1));
      return { id: "target_bay_" + index, x: Math.round(width * value[0] - w / 2),
        y: Math.round(height * value[1] - h / 2), w: w, h: h };
    });
  }

  function create(view, drawAsset, width, height) {
    function image(id, x, y, w, h, colors, options) {
      return drawAsset(id, Object.assign({ x: x, y: y, w: w, h: h, assetContext: colors }, options));
    }
    function rect(x, y, w, h, color, alpha) {
      return view.fillRect(x, y, w, h, { color: color, alpha: alpha === undefined ? 1 : alpha });
    }
    function background(game) {
      var colors = game.assetContext;
      view.clear(colors.color("background"));
      game.targetBays.forEach(function panel(bay) {
        rect(bay.x + 7, bay.y + 9, bay.w, bay.h, 0x070f19, 0.7);
        rect(bay.x - 4, bay.y - 4, bay.w + 8, bay.h + 8, colors.color("surfaceAccent"));
        image("gallery_panel", bay.x + bay.w / 2, bay.y + bay.h / 2,
          bay.w, bay.h, colors, { tint: colors.color("surface") });
        for (var side = 0; side < 2; side += 1) {
          rect(bay.x + 7 + side * (bay.w - 18), bay.y + 7, 4, 4, colors.color("grid"), 0.7);
          rect(bay.x + 7 + side * (bay.w - 18), bay.y + bay.h - 11, 4, 4, colors.color("grid"), 0.7);
        }
      });
    }
    return {
      render: function render(game) {
        background(game);
        var colors = game.assetContext;
        game.visualShots.forEach(function shot(event) {
          var age = game.gameTimeMs - event.timeMs;
          if (age < 0 || age > 250) return;
          image("gallery_spark", event.x, event.y, 22, 22, colors,
            { tint: colors.color("projectile"), alpha: 1 - age / 250 });
        });
        game.targets.forEach(function target(target) {
          image("gallery_target", target.x + 3, target.y + 5, target.radius * 2, target.radius * 2,
            colors, { tint: 0x070e18, alpha: 0.6 });
          image("gallery_ring", target.x, target.y, target.radius * 2.85, target.radius * 2.85,
            colors, { tint: colors.color("target"), alpha: 0.17 });
          image("gallery_target", target.x, target.y, target.radius * 2, target.radius * 2,
            colors, { tint: colors.color("spriteTint") });
        });
        image("gallery_cursor", game.mouse.x, game.mouse.y, 27, 27, colors);
      },
    };
  }
  window.PrecisionGalleryScene = Object.freeze({ create: create, buildBays: buildBays, assets: ASSETS, pack: "gym-gallery", version: "precision-gallery-bays-2" });
})();
