(function roverHangarScene() {
  "use strict";
  var ASSETS = Object.freeze([
    "rover_player", "rover_enemy", "barrel_player", "barrel_enemy", "cover", "floor", "burst_0", "burst_1", "burst_2",
  ]);

  function create(view, drawAsset, width, height, playerRadius) {
    function rect(x, y, w, h, color, alpha) {
      return view.fillRect(x, y, w, h, { color: color, alpha: alpha === undefined ? 1 : alpha });
    }
    function image(id, x, y, w, h, colors, options) {
      return drawAsset(id, Object.assign({ x: x, y: y, w: w, h: h, assetContext: colors }, options));
    }
    function rover(game, x, y, radius, heading, aim, hostile) {
      radius *= 1.2;
      var colors = game.assetContext;
      var role = colors.color(hostile ? "hostile" : "friendly");
      view.fillCircle(x + 2, y + 4, radius, view.rgba(0x08171e, 0.55));
      view.fillCircle(x, y, radius, view.rgba(role, 0.2));
      image(hostile ? "rover_enemy" : "rover_player", x, y, radius * 1.8, radius * 1.95,
        colors, { angle: heading + Math.PI / 2, tint: colors.color("spriteTint") });
      var offset = radius * 0.36;
      image(hostile ? "barrel_enemy" : "barrel_player", x + Math.cos(aim) * offset,
        y + Math.sin(aim) * offset, radius * 0.48, radius * 1.2, colors,
        { angle: aim + Math.PI / 2, tint: colors.color("spriteTint") });
      view.fillCircle(x, y, 2.3, role);
    }
    return {
      render: function render(game) {
        var colors = game.assetContext;
        var bounds = view.getVisibleBounds();
        view.clear(colors.color("background"));
        game.floorMap.floorPatches.forEach(function floor(patch) {
          var left = patch.x - patch.width / 2, top = patch.z - patch.depth / 2;
          for (var y = top; y < top + patch.depth; y += 96) {
            for (var x = left; x < left + patch.width; x += 96) {
              var w = Math.min(96, left + patch.width - x), h = Math.min(96, top + patch.depth - y);
              image("floor", x + w / 2, y + h / 2, w, h, colors,
                { tint: colors.color("surface"), alpha: patch.style === "service" ? 0.78 : 1 });
            }
          }
          view.strokeRect(left + 7, top + 7, patch.width - 14, patch.depth - 14,
            view.rgba(colors.color("surfaceAccent"), 0.12), 2);
        });
        game.obstacles.forEach(function cover(obstacle) {
          if (obstacle.kind === "boundary") {
            rect(obstacle.x + 4, obstacle.y + 5, obstacle.w, obstacle.h, 0x102129, 0.55);
            rect(obstacle.x, obstacle.y, obstacle.w, obstacle.h, colors.color("neutral"));
            rect(obstacle.x + 2, obstacle.y + 2, Math.max(2, obstacle.w - 4), Math.max(2, obstacle.h - 4),
              colors.color("surfaceAccent"), 0.45);
            return;
          }
          rect(obstacle.x + 4, obstacle.y + 6, obstacle.w, obstacle.h, 0x102129, 0.6);
          image("cover", obstacle.x + obstacle.w / 2, obstacle.y + obstacle.h / 2,
            obstacle.w, obstacle.h, colors, { tint: colors.color("neutral") });
          rect(obstacle.x, obstacle.y, obstacle.w, 3, colors.color("surfaceAccent"));
          for (var stripe = 4; stripe < obstacle.w - 7; stripe += 16) {
            rect(obstacle.x + stripe, obstacle.y + obstacle.h - 7, 8, 4, colors.color("grid"));
          }
        });
        rover(game, game.x, game.y, playerRadius, game.visualHeading,
          Math.atan2(game.cursor.y - game.y, game.cursor.x - game.x), false);
        game.enemies.forEach(function enemy(value) {
          rover(game, value.x, value.y, value.r, value.heading, value.heading, true);
        });
        game.visualShots.forEach(function shot(event) {
          var age = game.gameTimeMs - event.timeMs;
          if (age < 0 || age > 450) return;
          var alpha = 1 - age / 450;
          view.line([{ x: event.x1, y: event.y1 }, { x: event.x2, y: event.y2 }],
            view.rgba(colors.color("projectile"), alpha * 0.75), 2);
          image("burst_" + Math.min(2, Math.floor(age / 150)), event.x2, event.y2,
            28, 28, colors, { alpha: alpha });
        });
        view.crosshair(game.cursor.x, game.cursor.y, { radius: 8, stroke: 0x10202b, lineWidth: 4 });
        view.crosshair(game.cursor.x, game.cursor.y, { radius: 8, stroke: colors.color("text"), lineWidth: 1.5 });
        view.render();
      },
    };
  }
  window.RoverHangarScene = Object.freeze({ create: create, assets: ASSETS, pack: "gym-rover-arena", version: "rover-connected-hangars-2" });
})();
