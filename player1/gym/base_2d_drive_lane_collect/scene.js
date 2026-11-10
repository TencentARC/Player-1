(function coastalRoadScene() {
  "use strict";
  var ASSETS = Object.freeze([
    "racing_car", "racing_tree", "racing_tree_small", "racing_rock", "racing_tent",
    "racing_barrier", "racing_tires", "racing_coin",
  ]);

  function create(view, drawAsset, dimensions) {
    var d = dimensions;
    function image(id, x, y, w, h, context, options) {
      return drawAsset(id, Object.assign({ x: x, y: y, w: w, h: h, assetContext: context }, options));
    }
    function rect(x, y, w, h, color, alpha) {
      return view.fillRect(x, y, w, h, { color: color, alpha: alpha === undefined ? 1 : alpha });
    }
    function ground(state, colors) {
      var bounds = view.getVisibleBounds();
      view.clear(colors.color("verge"));
      var offset = state.distancePx;
      var layout = state.sceneLayout.template;
      var top = bounds.top - 250;
      var bottom = bounds.bottom + 250;
      // All scenery shares the road's displacement; capture never advances it.
      var period = 720;
      if (layout === "canal-road" || layout === "bridge-road") {
        rect(d.right + 62, bounds.top, bounds.right - d.right, bounds.height, 0x528c9a);
        rect(d.right + 55, bounds.top, 18, bounds.height, colors.color("roadEdge"));
        if (layout === "bridge-road") {
          rect(bounds.left, bounds.top, d.left - bounds.left - 62, bounds.height, 0x528c9a);
          rect(d.left - 73, bounds.top, 18, bounds.height, colors.color("roadEdge"));
        }
        for (var waveY = Math.floor((bounds.top - offset) / 71) * 71 + offset; waveY < bounds.bottom; waveY += 71) {
          rect(d.right + 100, waveY, 130, 2, 0xc6e3df, 0.45);
          if (layout === "bridge-road") rect(d.left - 240, waveY + 35, 130, 2, 0xc6e3df, 0.45);
        }
      }
      for (var row = Math.floor((top - offset) / period); row * period + offset < bottom; row += 1) {
        var y = row * period + offset;
        if (layout === "bridge-road") {
          for (var pier = 0; pier < 4; pier += 1) {
            rect(d.left - 106, y + pier * 180, 41, 64, colors.color("neutral"));
            rect(d.right + 65, y + pier * 180, 41, 64, colors.color("neutral"));
          }
          continue;
        }
        if (layout === "orchard-road") {
          for (var treeRow = 0; treeRow < 5; treeRow += 1) {
            for (var side = -1; side <= 1; side += 2) {
              for (var treeCol = 0; treeCol < 2; treeCol += 1) {
                var treeX = side < 0 ? d.left - 140 - treeCol * 155 : d.right + 140 + treeCol * 155;
                image(treeCol ? "racing_tree_small" : "racing_tree", treeX, y + treeRow * 144,
                  92, 92, colors, { tint: colors.color("spriteTint") });
              }
            }
          }
          continue;
        }
        rect(d.left - 280, y + 30, 180, 280, colors.color("surface"));
        if (layout !== "canal-road") rect(d.right + 120, y + 420, 140, 260, colors.color("surface"));
        rect(d.left - 216, y + 80, 80, 180, colors.color("road"), 0.24);
        image("racing_tent", d.left - 178, y + 127, 126, 126, colors, { tint: colors.color("spriteTint") });
        for (var tire = 0; tire < 4; tire += 1) {
          image("racing_tires", d.left - 232 + tire * 35, y + 246, 24, 24, colors);
        }
        image("racing_tree", d.left - 156, y + 440, 125, 125, colors, { tint: colors.color("spriteTint") });
        image("racing_tree_small", d.left - 284, y + 620, 89, 89, colors, { tint: colors.color("spriteTint") });
        if (layout !== "canal-road") {
          image("racing_tree", d.right + 175, y + 143, 144, 144, colors, { tint: colors.color("spriteTint") });
          image("racing_tree_small", d.right + 298, y + 55, 89, 89, colors, { tint: colors.color("spriteTint") });
          image("racing_rock", d.right + 158, y + 490, 67, 54, colors, { tint: colors.color("spriteTint") });
          image("racing_tree", d.right + 235, y + 650, 117, 117, colors, { tint: colors.color("spriteTint") });
        }
      }
      rect(d.left - 55, bounds.top, d.width + 110, bounds.height, colors.color("road"), 0.28);
      rect(d.left - 36, bounds.top, d.width + 72, bounds.height, colors.color("neutral"));
      rect(d.left, bounds.top, d.width, bounds.height, colors.color("road"));
      rect(d.left, bounds.top, 8, bounds.height, colors.color("roadEdge"));
      rect(d.right - 8, bounds.top, 8, bounds.height, colors.color("roadEdge"));
      // Broad lane wear and restrained seams make speed legible without obscuring coins.
      for (var lane = 0; lane < 4; lane += 1) {
        rect(d.left + lane * 100 + 18, bounds.top, 64, bounds.height, 0xffffff, 0.025);
      }
      for (var seam = Math.floor((bounds.top - offset) / 180); seam * 180 + offset < bounds.bottom; seam += 1) {
        rect(d.left + 8, seam * 180 + offset, d.width - 16, 1, 0xffffff, 0.04);
      }
      var stripeOffset = offset % 101;
      for (var stripeY = Math.floor((bounds.top - stripeOffset) / 101) * 101 + stripeOffset; stripeY < bounds.bottom; stripeY += 101) {
        for (var separator = 1; separator < 4; separator += 1) {
          rect(d.left + separator * 100 - 3, stripeY, 6, 56, colors.color("lane"), 0.8);
        }
      }
      var curbOffset = offset % 64;
      for (var curbY = Math.floor((bounds.top - curbOffset) / 64) * 64 + curbOffset; curbY < bounds.bottom; curbY += 64) {
        rect(d.left - 20, curbY, 12, 32, colors.color("roadEdge"));
        rect(d.left - 20, curbY + 32, 12, 32, 0xc87452);
        rect(d.right + 8, curbY, 12, 32, colors.color("roadEdge"));
        rect(d.right + 8, curbY + 32, 12, 32, 0xc87452);
      }
      // The verge barrier sits beyond the drivable boundary.
      for (var railY = Math.floor((bounds.top - offset) / 220) * 220 + offset; railY < bounds.bottom + 100; railY += 220) {
        image("racing_barrier", d.left - 60, railY, 174, 23, colors, { rotation: Math.PI / 2 });
        image("racing_barrier", d.right + 60, railY, 174, 23, colors, { rotation: Math.PI / 2 });
      }
    }
    return {
      render: function render(state, colors) {
        ground(state, colors);
        var carX = state.playerX + d.carWidth / 2;
        var carY = state.playerY + d.carHeight / 2;
        image("racing_car", carX + 5, carY + 7, d.carWidth, d.carHeight, colors, { tint: 0x102631, alpha: 0.25 });
        image("racing_car", carX, carY, d.carWidth, d.carHeight, colors, { tint: colors.color("spriteTint") });
        state.opponents.forEach(function drawCoin(coin) {
          image("racing_coin", coin.x + d.coinSize / 2 + 2, coin.y + d.coinSize / 2 + 3,
            d.coinSize, d.coinSize, colors, { tint: 0x1c2b37, alpha: 0.24 });
          image("racing_coin", coin.x + d.coinSize / 2, coin.y + d.coinSize / 2,
            d.coinSize, d.coinSize, colors, { tint: colors.color("spriteTint") });
        });
      },
    };
  }
  window.CoastalRoadScene = Object.freeze({ create: create, assets: ASSETS, pack: "gym-racing", version: "coastal-run-2" });
})();
