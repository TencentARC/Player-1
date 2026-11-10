(function dispatchFloorScene() {
  "use strict";
  var ASSETS = Object.freeze([
    "factory_floor", "factory_floor_worn", "factory_robot", "factory_hazard", "factory_hatch",
    "factory_vent", "factory_coin",
  ]);

  function create(view, drawAsset) {
    function rect(x, y, w, h, color, alpha) {
      return view.fillRect(x, y, w, h, { color: color, alpha: alpha === undefined ? 1 : alpha });
    }
    function image(id, x, y, w, h, colors, options) {
      return drawAsset(id, Object.assign({ x: x, y: y, w: w, h: h, assetContext: colors }, options));
    }
    return {
      render: function render(game) {
        var colors = game.assetContext;
        var state = game.visualFailure ? Object.assign({}, game, game.visualFailure) : game;
        var bounds = view.getVisibleBounds();
        view.clear(colors.color("background"));
        game.workzone.floorPatches.forEach(function floor(patch) {
          var left = patch.x - patch.width / 2, top = patch.z - patch.depth / 2;
          for (var y = top; y < top + patch.depth; y += 80) {
            for (var x = left; x < left + patch.width; x += 80) {
              var w = Math.min(80, left + patch.width - x), h = Math.min(80, top + patch.depth - y);
              image(patch.style === "bay" ? "factory_floor_worn" : "factory_floor", x + w / 2, y + h / 2, w, h,
                colors, { tint: colors.color("spriteTint") });
            }
          }
        });
        game.workzone.regions.forEach(function servicePanel(region, index) {
          if (!index) return;
          image(index % 2 ? "factory_hatch" : "factory_vent", region.x, region.z, 74, 74, colors, { alpha: 0.32 });
        });
        game.workzone.walls.forEach(function wall(value) {
          var x = value.x - value.width / 2, y = value.z - value.depth / 2;
          rect(x + 4, y + 5, value.width, value.depth, 0x101822, 0.6);
          rect(x, y, value.width, value.depth, colors.color("surfaceAccent"));
          rect(x + 2, y + 2, Math.max(2, value.width - 4), Math.max(2, value.depth - 4), colors.color("neutral"));
        });
        state.items.forEach(function coin(item) {
          image("factory_coin", item[0] + game.itemSize / 2 + 3, item[1] + game.itemSize / 2 + 4,
            game.itemSize, game.itemSize, colors, { tint: 0x181824, alpha: 0.35 });
          image("factory_coin", item[0] + game.itemSize / 2, item[1] + game.itemSize / 2,
            game.itemSize, game.itemSize, colors, { tint: colors.color("spriteTint") });
        });
        state.obstacles.forEach(function hazard(obstacle) {
          var cx = obstacle[0] + game.itemSize / 2;
          var cy = obstacle[1] + game.itemSize / 2;
          var direction = obstacle[2] > 0 ? 1 : -1;
          rect(obstacle[0] - direction * 12, obstacle[1] + 8, game.itemSize, game.itemSize - 16, colors.color("hazard"), 0.12);
          rect(obstacle[0], obstacle[1], game.itemSize, game.itemSize, 0x573d43);
          view.strokeRect(obstacle[0], obstacle[1], game.itemSize, game.itemSize, colors.color("hazard"), 2);
          image("factory_hazard", cx, cy, game.itemSize, game.itemSize, colors, { tint: colors.color("spriteTint") });
          rect(cx + direction * 10 - 3, cy - 3, 6, 6, 0xffe8c7);
        });
        var px = state.playerX, py = state.playerY, w = game.playerWidth, h = game.playerHeight;
        rect(px + 4, py + 6, w, h, 0x1b1b28, 0.38);
        image("factory_robot", px + w / 2, py + h / 2, w, h, colors, { tint: colors.color("spriteTint") });
        // The squared body and its wheels stay inside the exported collision rectangle.
        var moving = state.lastAction !== "wait" && !game.visualFailure;
        var stride = moving ? Math.floor(state.gameTimeMs / 100) % 2 * 3 : 0;
        rect(px + 3, py + 21 + stride, 5, h - 42, colors.color("friendlyAccent"));
        rect(px + w - 8, py + 21 - stride, 5, h - 42, colors.color("friendlyAccent"));
        rect(px + 21, py + 27, w - 42, 21, 0x263847);
        rect(px + 27, py + 33, 7, 8, colors.color("friendly"));
        rect(px + w - 34, py + 33, 7, 8, colors.color("friendly"));

      },
    };
  }
  window.DispatchFloorScene = Object.freeze({ create: create, assets: ASSETS, pack: "gym-dispatch", version: "dispatch-workzones-2" });
})();
