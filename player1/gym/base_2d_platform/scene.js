(function summitRunScene() {
  "use strict";

  var PACK = "gym-summit";
  var ASSETS = Object.freeze([
    "runner_idle", "runner_walk_a", "runner_walk_b", "runner_jump", "runner_hit", "runner_duck",
    "ground_top", "ground_body", "ledge_left", "ledge_middle", "ledge_right", "spikes", "coin", "coin_edge",
    "flag_a", "flag_b", "checkpoint", "bush", "rock", "clouds", "forest",
  ]);

  function createState() {
    return { facing: 1, runDistance: 0, landedAt: -10000, respawnAt: -10000,
      events: [] };
  }

  function record(game, kind, x, y) {
    game.sceneState.events.push({ kind: kind, x: x, y: y, at: game.gameTimeMs });
  }

  function advance(game, wasOnGround, previousX) {
    var state = game.sceneState;
    if (Math.abs(game.vx) > 0.1) state.facing = game.vx < 0 ? -1 : 1;
    if (game.onGround) state.runDistance += Math.abs(game.x - previousX);
    if (!wasOnGround && game.onGround) {
      state.landedAt = game.gameTimeMs;
      record(game, "land", game.x, game.y + 17);
    }
    state.events = state.events.filter(function recent(event) { return game.gameTimeMs - event.at < 700; });
  }

  function pose(game) {
    var state = game.sceneState;
    if (game.gameTimeMs - state.respawnAt < 280) return "hit";
    if (!game.onGround) return game.vy < 0 ? "jump" : "fall";
    if (game.gameTimeMs - state.landedAt < 110) return "land";
    if (Math.abs(game.vx) > 12) return Math.floor(state.runDistance / 23) % 2 ? "walk_b" : "walk_a";
    return "idle";
  }

  function create(view, width, height) {
    function image(game, id, x, y, w, h, options) {
      var mesh = BaseGameletThree2D.assets.create(id, Object.assign({ view: view, assetContext: game.assetContext,
        x: x, y: y, w: w, h: h, anchor: [0, 0] }, options || {}));
      mesh.userData.platformSurface = null;
      mesh.userData.hazardBounds = null;
      mesh.userData.platformRunner = null;
      mesh.userData.platformDecoration = null;
      return mesh;
    }
    function rect(x, y, w, h, color, alpha) {
      return view.fillRect(x, y, w, h, { color: color, alpha: alpha === undefined ? 1 : alpha });
    }
    function visible(x, w) { return x + w >= -180 && x <= width + 180; }
    function color(game, role) { return game.assetContext.color(role); }
    function mountainLayer(game, cameraX, parallax, baseY, peakHeight, fill) {
      var stride = 660, offset = cameraX * parallax;
      var first = Math.floor((offset - 300) / stride);
      for (var i = first; i < first + 4; i += 1) {
        var x = i * stride - offset;
        var peak = peakHeight * (0.82 + 0.16 * Math.sin(i * 1.9 + game.seed));
        view.fillPolygon([
          { x: x - 70, y: baseY }, { x: x + 110, y: baseY - peak * 0.52 },
          { x: x + 227, y: baseY - peak * 0.41 }, { x: x + 360, y: baseY - peak },
          { x: x + 493, y: baseY - peak * 0.46 }, { x: x + 700, y: baseY },
        ], fill);
        view.fillPolygon([
          { x: x + 290, y: baseY - peak * 0.72 }, { x: x + 360, y: baseY - peak },
          { x: x + 411, y: baseY - peak * 0.79 }, { x: x + 364, y: baseY - peak * 0.85 },
          { x: x + 337, y: baseY - peak * 0.76 },
        ], { color: color(game, "grid"), alpha: 0.65 });
      }
    }
    function background(game, cameraX) {
      view.clear(color(game, "sky"));
      var cloudOffset = (cameraX * 0.04) % 840;
      for (var c = -1; c < 3; c += 1) image(game, "clouds", c * 840 - cloudOffset, -42, 840, 400,
        { tint: color(game, "background"), alpha: 0.9 });
      mountainLayer(game, cameraX, 0.1, 394, 222, color(game, "surface"));
      mountainLayer(game, cameraX + 1800, 0.2, 495, 229, color(game, "surfaceAccent"));
      var offset = (cameraX * 0.32) % 900;
      for (var f = -1; f < 3; f += 1) image(game, "forest", f * 900 - offset, 174, 900, 440,
        { tint: color(game, "surfaceAccent"), alpha: 0.52 });
      rect(-180, 510, width + 360, height - 510 + 180, color(game, "surfaceAccent"), 0.62);
    }
    function ground(game, cameraX) {
      var tint = color(game, "spriteTint");
      var terrain = game.level.platforms.filter(function solid(platform) { return platform.kind !== "ledge"; });
      terrain.forEach(function body(platform) {
        var x = platform.x - cameraX;
        if (!visible(x, platform.w)) return;
        var columns = Math.ceil(platform.w / 64), tileW = platform.w / columns;
        for (var col = 0; col < columns; col += 1) {
          for (var y = platform.y + 64; y < height + 170; y += 64) {
            image(game, "ground_body", x + col * tileW, y, tileW + 0.12, 64.12, { tint: tint });
          }
          var top = image(game, "ground_top", x + col * tileW, platform.y, tileW + 0.12, 64.12, { tint: tint });
          top.userData.platformSurface = { id: platform.id, top: platform.y, kind: "terrain" };
        }
        var previous = terrain.find(function adjacent(other) { return other.x + other.w === platform.x; });
        var next = terrain.find(function adjacent(other) { return other.x === platform.x + platform.w; });
        var leftBottom = previous ? previous.y : height + 170;
        var rightBottom = next ? next.y : height + 170;
        if (leftBottom > platform.y) rect(x, platform.y, 3, leftBottom - platform.y, 0x353541);
        if (rightBottom > platform.y) rect(x + platform.w - 3, platform.y, 3, rightBottom - platform.y, 0x353541);
      });
      game.level.platforms.forEach(function ledge(platform) {
        if (platform.kind !== "ledge") return;
        var x = platform.x - cameraX;
        if (!visible(x, platform.w)) return;
        var columns = Math.max(2, Math.ceil(platform.w / 52)), tileW = platform.w / columns;
        for (var col = 0; col < columns; col += 1) {
          var id = col === 0 ? "ledge_left" : col === columns - 1 ? "ledge_right" : "ledge_middle";
          var mesh = image(game, id, x + col * tileW, platform.y, tileW + 0.12, platform.h, { tint: tint });
          mesh.userData.platformSurface = { id: platform.id, top: platform.y, kind: "ledge" };
        }
      });
    }
    function scenery(game, cameraX) {
      var tint = color(game, "spriteTint");
      var decorationWidth = 38, decorationHeight = 24, edgeSetback = 72, taskSetback = 32;
      var reserved = [];
      game.level.platforms.forEach(function reserveLedge(platform) {
        if (platform.kind === "ledge") reserved.push([platform.x - edgeSetback, platform.x + platform.w + edgeSetback]);
      });
      game.level.spikes.forEach(function reserveSpike(hazard) {
        reserved.push([hazard.x - taskSetback, hazard.x + hazard.w + taskSetback]);
      });
      game.level.coins.forEach(function reserveCoin(coin) {
        reserved.push([coin.x - coin.r - taskSetback, coin.x + coin.r + taskSetback]);
      });
      game.level.checkpoints.forEach(function reserveCheckpoint(marker) {
        reserved.push([marker.x - 8 - taskSetback, marker.x + 10 + taskSetback]);
      });
      reserved.push([game.level.flag.x - 4 - taskSetback, game.level.flag.x + 66 + taskSetback]);
      game.level.platforms.forEach(function decor(platform, index) {
        var x = platform.x - cameraX;
        if (platform.kind === "ledge" || platform.w < edgeSetback * 2 + decorationWidth || !visible(x, platform.w)) return;
        // Reserve complete sprite bounds inside a flat, away from transitions and task silhouettes.
        var intervals = [[platform.x + edgeSetback, platform.x + platform.w - edgeSetback]];
        reserved.forEach(function exclude(blocked) {
          var remaining = [];
          intervals.forEach(function split(interval) {
            if (blocked[1] <= interval[0] || blocked[0] >= interval[1]) remaining.push(interval);
            else {
              if (blocked[0] > interval[0]) remaining.push([interval[0], blocked[0]]);
              if (blocked[1] < interval[1]) remaining.push([blocked[1], interval[1]]);
            }
          });
          intervals = remaining;
        });
        var flat = intervals.reduce(function widest(best, interval) {
          return interval[1] - interval[0] > best[1] - best[0] ? interval : best;
        }, [0, 0]);
        if (flat[1] - flat[0] < decorationWidth) return;
        var worldX = (flat[0] + flat[1] - decorationWidth) / 2;
        var mesh = image(game, index % 3 ? "bush" : "rock", worldX - cameraX, platform.y - decorationHeight,
          decorationWidth, decorationHeight, { tint: tint, alpha: 0.85 });
        mesh.userData.platformDecoration = { platform_id: platform.id, x: worldX, y: platform.y - decorationHeight,
          w: decorationWidth, h: decorationHeight };
      });
      game.level.checkpoints.forEach(function checkpoint(marker) {
        var x = marker.x - cameraX;
        if (!visible(x, 20)) return;
        var active = marker.index === game.currentCheckpointIndex;
        var baseY = marker.y + 17;
        image(game, "checkpoint", x - 2, baseY - 23, 7, 23, { tint: tint, alpha: active ? 1 : 0.42 });
        rect(x - 3, baseY - 23, 11, 6, active ? color(game, "goal") : color(game, "neutral"), active ? 1 : 0.55);
        if (active) rect(x - 8, baseY - 3, 18, 3, color(game, "goal"));
      });
    }
    function tasks(game, cameraX) {
      var tint = color(game, "spriteTint");
      game.level.spikes.forEach(function spike(hazard) {
        var x = hazard.x - cameraX;
        if (!visible(x, hazard.w)) return;
        rect(x, hazard.y + hazard.h - 3, hazard.w, 3, color(game, "hazard"));
        var mesh = image(game, "spikes", x, hazard.y, hazard.w, hazard.h, { tint: tint });
        mesh.userData.hazardBounds = { x: hazard.x, y: hazard.y, w: hazard.w, h: hazard.h };
      });
      game.level.coins.forEach(function coin(token, index) {
        if (token.collected || !visible(token.x - cameraX, 20)) return;
        var edge = (game.gameTimeMs + index * 117) % 1100 > 920;
        image(game, edge ? "coin_edge" : "coin", token.x - cameraX - token.r, token.y - token.r,
          token.r * 2, token.r * 2, { tint: tint });
      });
      var flag = game.level.flag;
      if (visible(flag.x - cameraX, 70)) {
        image(game, Math.floor(game.gameTimeMs / 240) % 2 ? "flag_b" : "flag_a", flag.x - cameraX - 4, flag.y, 70, flag.h,
          { tint: tint });

      }
    }
    function runner(game, cameraX) {
      var phase = pose(game), state = game.sceneState;
      var asset = phase === "fall" ? "jump" : phase === "land" ? "duck" : phase;
      var drawH = phase === "land" ? 34 : 37;
      var drawW = 31.3;
      var footY = game.y + 17;
      if (game.onGround) {
        var shadow = view.fillCircle(game.x - cameraX, footY - 1, 12, { color: 0x183c37, alpha: 0.18 });
        shadow.scale.y *= 0.2;
      }
      if (game.onGround && Math.abs(game.vx) > 190) {
        for (var d = 0; d < 3; d += 1) {
          var age = ((game.gameTimeMs + d * 85) % 255) / 255;
          view.fillCircle(game.x - cameraX - state.facing * (10 + age * 25), footY - 1 - age * 6,
            1.5 + age * 2, { color: 0xfbe5bf, alpha: (1 - age) * 0.55 });
        }
      }
      var mesh = image(game, "runner_" + asset, game.x - cameraX, footY, drawW, drawH,
        { anchor: [0.5, 1], tint: color(game, "spriteTint") });
      mesh.scale.x *= state.facing;
      mesh.userData.platformRunner = { pose: phase, facing: state.facing, footY: footY };
      if (phase === "fall") mesh.rotation.z = state.facing * 0.075;

    }
    function landingDust(game, cameraX) {
      game.sceneState.events.forEach(function event(item) {
        var age = (game.gameTimeMs - item.at) / 700;
        if (age < 0 || age >= 1) return;
        var x = item.x - cameraX;
        if (!visible(x - 40, 80)) return;
        if (item.kind === "land" && age < 0.45) {
          for (var direction = -1; direction <= 1; direction += 2) {
            view.fillCircle(x + direction * (8 + age * 32), item.y - 2 - age * 12, 2.5,
              { color: 0xf4ddbe, alpha: 0.5 * (1 - age / 0.45) });
          }
        }
      });
    }
    return {
      render: function render(game) {
        var cameraX = game.cameraX();
        background(game, cameraX);
        scenery(game, cameraX);
        ground(game, cameraX);
        tasks(game, cameraX);
        runner(game, cameraX);
        landingDust(game, cameraX);
        view.render();
      },
    };
  }

  window.SummitRunScene = Object.freeze({ pack: PACK, assets: ASSETS, version: "summit-biomes-2",
    create: create, createState: createState, advance: advance, pose: pose });
})();
