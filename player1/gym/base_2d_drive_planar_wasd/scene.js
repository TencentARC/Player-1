(function gardenCircuitScene() {
  "use strict";
  var U = window.BaseGameletCommon;
  var ASSETS = Object.freeze([
    "path_road", "checkpoint_line", "racing_car", "racing_tree", "racing_tree_small", "racing_rock",
    "racing_tent",
  ]);

  function create(view, drawAsset, width, height, fenceWidth) {
    var decor = [];
    function rect(x, y, w, h, color, alpha) {
      return view.fillRect(x, y, w, h, { color: color, alpha: alpha === undefined ? 1 : alpha });
    }
    function image(id, x, y, w, h, colors, options) {
      return drawAsset(id, Object.assign({ x: x, y: y, w: w, h: h, assetContext: colors }, options));
    }
    function road(game, properties) {
      return drawAsset("path_road", Object.assign({ points: game.level.route, assetContext: game.assetContext,
        join: "miter", closed: true, miterLimit: 2.5 }, properties));
    }
    function prepare(game) {
      decor = [];
      // Every solid-looking prop lies beyond the continuous road and its collision boundary.
      for (var row = 0; row < 9; row += 1) {
        for (var col = 0; col < 16; col += 1) {
          var mix = ((col + 11) * 73856093 ^ (row + 7) * 19349663 ^ window.GameEngineCore.seeds.forDomain(game, "scene", 42)) >>> 0;
          if (mix % 5 === 0) continue;
          var x = 44 + col * 101 + mix % 31;
          var y = 72 + row * 91 + (mix >>> 5) % 27;
          if (x > width - 32 || y > height - 54) continue;
          var radius = 24 + (mix >>> 9) % 17;
          var clearance = U.track.distanceToPolyline({ x: x, y: y }, game.level.route).distance;
          if (clearance < game.level.roadWidth / 2 + fenceWidth + radius + 18) continue;
          decor.push({ x: x, y: y, size: radius * 2, angle: mix / 0xffffffff * Math.PI * 2,
            id: mix % 9 === 0 ? "racing_rock" : mix % 3 === 0 ? "racing_tree_small" : "racing_tree" });
        }
      }
      // A service tent is placed only when a full footprint fits outside the road.
      for (var candidate = 0; candidate < decor.length; candidate += 1) {
        var item = decor[candidate];
        if (U.track.distanceToPolyline(item, game.level.route).distance > 155
            && item.x > 160 && item.x < width - 160 && item.y > 160 && item.y < height - 160) {
          item.id = "racing_tent";
          item.size = 98;
          item.angle = 0;
          break;
        }
      }
    }
    return {
      prepare: prepare,
      render: function render(game) {
        var colors = game.assetContext;
        var bounds = view.getVisibleBounds();
        view.clear(colors.color("background"));
        for (var stripe = Math.floor(bounds.left / 160) * 160; stripe < bounds.right; stripe += 320) {
          rect(stripe, bounds.top, 160, bounds.bottom - bounds.top, colors.color("surfaceAccent"), 0.18);
        }
        decor.forEach(function prop(item) {
          image(item.id, item.x + 4, item.y + 5, item.size, item.size, colors,
            { angle: item.angle, tint: 0x233929, alpha: 0.22 });
          image(item.id, item.x, item.y, item.size, item.size, colors,
            { angle: item.angle, tint: colors.color("spriteTint") });
        });
        road(game, { width: game.level.roadWidth + fenceWidth * 2 + 16, roadFill: 0x8f967c });
        road(game, { width: game.level.roadWidth + fenceWidth, shoulderWidth: fenceWidth / 2,
          shoulderFill: colors.color("roadEdge"), roadFill: 0xba665b,
          centerLine: colors.color("roadEdge"), centerLineWidth: game.level.roadWidth + fenceWidth, dash: [20, 20] });
        road(game, { width: game.level.roadWidth, roadFill: colors.color("road"),
          centerLine: view.rgba(colors.color("lane"), 0.6), centerLineWidth: 2, dash: [18, 18] });
        game.level.checkpoints.forEach(function gate(checkpoint, index) {
          var active = index === game.routeCheckpointIndex;
          var normalX = -Math.sin(checkpoint.tangentAngle), normalY = Math.cos(checkpoint.tangentAngle);
          var alpha = active ? 1 : checkpoint.passed ? 0.12 : 0.2;
          drawAsset("checkpoint_line", { x: checkpoint.x, y: checkpoint.y,
            tangentAngle: checkpoint.tangentAngle, halfWidth: checkpoint.lineHalfWidth,
            assetContext: colors, stroke: view.rgba(active ? colors.color("goal") : colors.color("lane"), alpha),
            lineWidth: active ? 10 : 3 });
          if (active) {
            for (var side = -1; side <= 1; side += 2) {
              var px = checkpoint.x + normalX * (checkpoint.lineHalfWidth + 12) * side;
              var py = checkpoint.y + normalY * (checkpoint.lineHalfWidth + 12) * side;
              view.fillCircle(px, py, 7, colors.color("goal"));
            }
          }
        });
        image("racing_car", game.x + 3, game.y + 4, 29, 53, colors,
          { angle: game.angle + Math.PI / 2, tint: 0x13292c, alpha: 0.35 });
        image("racing_car", game.x, game.y, 29, 53, colors,
          { angle: game.angle + Math.PI / 2, tint: colors.color("spriteTint") });
        view.render();
      },
    };
  }
  window.GardenCircuitScene = Object.freeze({ create: create, assets: ASSETS, pack: "gym-circuit", version: "garden-circuit-2" });
})();
