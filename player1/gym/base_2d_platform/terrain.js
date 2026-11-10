(function summitTerrainModule() {
  "use strict";
  var PLAYER_H = 34;
  var TERRAIN_MIN_Y = 280;
  var TERRAIN_MAX_Y = 520;
  var TERRAIN_BOTTOM_Y = 760;
  var MIN_GAP_WIDTH = 62;
  var MAX_GAP_WIDTH = 86;
  var BASE_HAZARD_COUNT = 6;
  var COIN_COUNT = 18;
  var FAMILIES = Object.freeze({
    ridge: ["terrace", "gap", "hill", "fork", "gap", "ridge"],
    split_valley: ["gap", "fork", "valley", "terrace", "gap", "fork"],
    stepping_trail: ["terrace", "stones", "hill", "fork", "stones"],
    mesa_trail: ["hill", "gap", "terrace", "fork", "valley", "gap"],
  });

  function sampleLayout(context) {
    var seed = Number(context.rng.seed) >>> 0;
    var families = Object.keys(FAMILIES);
    var offset = context.profile === "perturbed" ? 1 + ((seed >>> 7) % 3) : 0;
    return {
      template: families[((seed % families.length) + offset) % families.length],
      width_scale: context.profile === "perturbed" ? [0.86, 0.92, 1.08, 1.14][(seed >>> 13) % 4]
        : [0.96, 1, 1.04][(seed >>> 13) % 3],
    };
  }

  function shuffledIndices(rng, count, start) {
    var first = Math.max(0, Number(start) || 0);
    var indices = [];
    for (var index = first; index < count; index += 1) indices.push(index);
    for (var cursor = indices.length - 1; cursor > 0; cursor -= 1) {
      var swapIndex = rng.randint(0, cursor + 1);
      var value = indices[cursor];
      indices[cursor] = indices[swapIndex];
      indices[swapIndex] = value;
    }
    return indices;
  }

  function terrainY(value) {
    return Math.round(Math.max(TERRAIN_MIN_Y, Math.min(TERRAIN_MAX_Y, value)));
  }

  function build(options) {
    var layoutRng = options.layoutRng;
    var entityRng = options.entityRng;
    var layout = options.layout;
    if (!layout || !FAMILIES[layout.template]) throw new Error("Unknown platform route family");
    var scale = layout.width_scale;
    var platforms = [];
    var gaps = [];
    var routes = [];
    var platformSerial = 0;
    var gapSerial = 0;
    var cursorX = 0;
    var startHeight = { ridge: 438, split_valley: 370, stepping_trail: 410, mesa_trail: 465 }[layout.template];
    var currentY = terrainY(startHeight + layoutRng.randint(-24, 25));
    var lastMainPlatform = null;

    function addPlatformAt(x, width, y, options) {
      var opts = options || {};
      var kind = opts.kind || "terrain";
      var topY = terrainY(y);
      var platform = {
        id: "platform_" + platformSerial,
        x: Math.round(x),
        y: topY,
        w: Math.round(width),
        h: kind === "ledge" ? 18 : TERRAIN_BOTTOM_Y - topY,
        kind: kind,
        route: opts.route || "main",
        motif: opts.motif || "terrain",
        solid_sides: kind !== "ledge",
        checkpoint_candidate: kind !== "ledge" && opts.checkpoint !== false,
      };
      platformSerial += 1;
      platforms.push(platform);
      return platform;
    }

    function addTerrain(width, y, options) {
      var platform = addPlatformAt(cursorX, width * scale, y, options);
      cursorX += platform.w;
      currentY = platform.y;
      lastMainPlatform = platform;
      return platform;
    }

    function addGapMotif(isSteppingStone) {
      var startX = cursorX;
      var fromPlatform = lastMainPlatform;
      fromPlatform.ends_in_gap = true;
      var width = layoutRng.randint(isSteppingStone ? 56 : MIN_GAP_WIDTH, isSteppingStone ? 77 : MAX_GAP_WIDTH + 1);
      var heightChoices = [-32, 0, 0, 32];
      var nextY = terrainY(currentY + heightChoices[layoutRng.randint(0, heightChoices.length)]);
      cursorX += width;
      var destination = addTerrain(isSteppingStone ? layoutRng.randint(180, 221) : layoutRng.randint(230, 296), nextY, {
        motif: isSteppingStone ? "stone_island" : "gap_landing",
      });
      gaps.push({
        id: "gap_" + gapSerial,
        x: startX,
        y: Math.min(fromPlatform.y, destination.y),
        w: width,
        h: TERRAIN_BOTTOM_Y - Math.min(fromPlatform.y, destination.y),
        from_y: fromPlatform.y,
        to_y: destination.y,
        from_platform_id: fromPlatform.id,
        to_platform_id: destination.id,
        motif: "gap",
        cleared: false,
      });
      gapSerial += 1;
      routes.push({ id: "route_" + routes.length, type: "gap", x: startX, w: cursorX - startX });
    }

    function addTerraceMotif() {
      var startX = cursorX, originY = currentY;
      var rise = layoutRng.randint(42, 67);
      addTerrain(layoutRng.randint(140, 176), originY - rise, { motif: "terrace_step" });
      addTerrain(layoutRng.randint(190, 256), originY - rise - layoutRng.randint(28, 43), { motif: "terrace_top" });
      addTerrain(layoutRng.randint(170, 226), originY - layoutRng.randint(8, 25), { motif: "terrace_exit" });
      routes.push({ id: "route_" + routes.length, type: "terrace", x: startX, w: cursorX - startX });
    }

    function addRidgeMotif() {
      var startX = cursorX, originY = currentY;
      for (var index = 0; index < 5; index += 1) {
        var height = originY - [35, 70, 102, 58, 24][index] + layoutRng.randint(-7, 8);
        addTerrain(layoutRng.randint(130, 191), height, { motif: "ridge_step" });
      }
      routes.push({ id: "route_" + routes.length, type: "ridge", x: startX, w: cursorX - startX });
    }

    function addHillMotif() {
      var startX = cursorX;
      var originY = currentY;
      var peakY = terrainY(originY - layoutRng.randint(88, 121));
      var exitY = terrainY(originY + layoutRng.randint(-16, 17));
      for (var up = 1; up <= 3; up += 1) {
        addTerrain(layoutRng.randint(90, 121), originY + (peakY - originY) * up / 3, {
          motif: "hill_up",
        });
      }
      addTerrain(layoutRng.randint(140, 181), peakY, { motif: "hill_peak" });
      for (var down = 1; down <= 3; down += 1) {
        addTerrain(layoutRng.randint(90, 121), peakY + (exitY - peakY) * down / 3, {
          motif: "hill_down",
        });
      }
      routes.push({ id: "route_" + routes.length, type: "hill", x: startX, w: cursorX - startX });
    }

    function addValleyMotif() {
      var startX = cursorX;
      var originY = currentY;
      var bottomY = terrainY(originY + layoutRng.randint(104, 145));
      var exitY = terrainY(originY + layoutRng.randint(-16, 17));
      for (var down = 1; down <= 3; down += 1) {
        addTerrain(layoutRng.randint(90, 121), originY + (bottomY - originY) * down / 3, {
          motif: "valley_down",
        });
      }
      addTerrain(layoutRng.randint(145, 186), bottomY, { motif: "valley_bottom" });
      for (var up = 1; up <= 3; up += 1) {
        addTerrain(layoutRng.randint(90, 121), bottomY + (exitY - bottomY) * up / 3, {
          motif: "valley_up",
        });
      }
      routes.push({ id: "route_" + routes.length, type: "valley", x: startX, w: cursorX - startX });
    }

    function addForkMotif() {
      var startX = cursorX;
      var ledgeCount = layoutRng.randint(3, 6);
      var ledgeStride = layoutRng.randint(125, 146) * scale;
      var lowerY = terrainY(currentY + layoutRng.randint(72, 105));
      var upperBaseY = terrainY(currentY - layoutRng.randint(44, 69));
      var ledges = [];
      var ledgeX = startX + 24;
      var ledgeY = terrainY(upperBaseY + layoutRng.randint(-10, 11));
      for (var ledgeIndex = 0; ledgeIndex < ledgeCount; ledgeIndex += 1) {
        var ledgeWidth = Math.max(90, Math.round(ledgeStride - layoutRng.randint(24, 35)));
        ledges.push({ x: ledgeX, w: ledgeWidth, y: ledgeY });
        if (ledgeIndex < ledgeCount - 1) {
          // Short, level breaks keep a running rhythm; wider rises require a jump.
          var runningLink = ledgeIndex % 2 === 0;
          var ledgeGap = runningLink ? layoutRng.randint(12, 19) : layoutRng.randint(68, 105);
          ledgeX += ledgeWidth + ledgeGap;
          if (!runningLink) ledgeY = terrainY(ledgeY - layoutRng.randint(10, 23));
        }
      }
      var lastLedge = ledges[ledges.length - 1];
      var forkWidth = lastLedge.x + lastLedge.w + 36 - startX;
      var lower = addPlatformAt(startX, forkWidth, lowerY, {
        route: "lower",
        motif: "fork_lower",
      });
      lower.hazard_preferred = true;
      ledges.forEach(function (ledge) {
        addPlatformAt(
          ledge.x,
          ledge.w,
          ledge.y,
          { kind: "ledge", route: "upper", motif: "fork_upper", checkpoint: false }
        );
      });
      cursorX = startX + forkWidth;
      currentY = lowerY;
      lastMainPlatform = lower;
      addTerrain(layoutRng.randint(180, 226), lowerY, { motif: "fork_merge" });
      routes.push({
        id: "route_" + routes.length,
        type: "fork",
        x: startX,
        w: cursorX - startX,
        upper_y: upperBaseY,
        lower_y: lowerY,
      });
    }

    var startPlatform = addTerrain(layoutRng.randint(240, 301), currentY, { motif: "start" });
    var motifOrder = FAMILIES[layout.template];
    for (var motifIndex = 0; motifIndex < motifOrder.length; motifIndex += 1) {
      if (motifOrder[motifIndex] === "gap") addGapMotif();
      else if (motifOrder[motifIndex] === "stones") { addGapMotif(true); addGapMotif(true); }
      else if (motifOrder[motifIndex] === "hill") addHillMotif();
      else if (motifOrder[motifIndex] === "valley") addValleyMotif();
      else if (motifOrder[motifIndex] === "terrace") addTerraceMotif();
      else if (motifOrder[motifIndex] === "ridge") addRidgeMotif();
      else addForkMotif();
    }
    var finalPlatform = addTerrain(360, currentY, { motif: "finish" });
    var worldWidth = cursorX;

    var hazardPlatformOrder = shuffledIndices(entityRng, platforms.length - 1, 0);
    hazardPlatformOrder.sort(function preferLowerFork(a, b) {
      return Number(!platforms[a].hazard_preferred) - Number(!platforms[b].hazard_preferred);
    });
    var hazardCount = Math.min(
      hazardPlatformOrder.length,
      BASE_HAZARD_COUNT + Math.round(Math.max(0, options.difficulty - 1) * 0.75)
    );
    var spikes = [];
    for (var hazardCursor = 0; hazardCursor < hazardPlatformOrder.length && spikes.length < hazardCount; hazardCursor += 1) {
      var hazardPlatformIndex = hazardPlatformOrder[hazardCursor];
      var hazardPlatform = platforms[hazardPlatformIndex];
      if (
        hazardPlatform.kind !== "terrain"
        || hazardPlatform === startPlatform
        || hazardPlatform === finalPlatform
        || hazardPlatform.ends_in_gap
        || hazardPlatform.w < 170
      ) continue;
      var spikeWidth = entityRng.randint(30, 39);
      var minSpikeX = hazardPlatform.x + 105;
      var maxSpikeX = hazardPlatform.x + hazardPlatform.w - spikeWidth - 20;
      if (maxSpikeX <= minSpikeX) continue;
      var spikeX = entityRng.randint(Math.ceil(minSpikeX), Math.floor(maxSpikeX) + 1);
      var spike = {
        id: "spike_" + spikes.length,
        x: spikeX,
        y: hazardPlatform.y - 18,
        w: spikeWidth,
        h: 18,
        platform_id: hazardPlatform.id,
        cleared: false,
      };
      spikes.push(spike);
      hazardPlatform.has_hazard = true;
    }

    var checkpoints = [];
    var checkpointPlatforms = platforms.filter(function checkpointCandidate(platform) {
      return platform.checkpoint_candidate && platform.w >= 100;
    }).sort(function sortByX(a, b) { return a.x - b.x; });
    for (var checkpointIndex = 0; checkpointIndex < checkpointPlatforms.length; checkpointIndex += 1) {
      var checkpointPlatform = checkpointPlatforms[checkpointIndex];
      var checkpointX = checkpointPlatform === startPlatform
        ? 52
        : checkpointPlatform.x + (checkpointPlatform.has_hazard ? 24 : Math.min(42, checkpointPlatform.w * 0.28));
      var checkpoint = {
        id: "checkpoint_" + checkpoints.length,
        index: checkpoints.length,
        platform_id: checkpointPlatform.id,
        x: Math.round(checkpointX),
        y: checkpointPlatform.y - PLAYER_H / 2,
      };
      checkpointPlatform.checkpoint_id = checkpoint.id;
      checkpoints.push(checkpoint);
    }

    var coins = [];
    var coinPlatformOrder = shuffledIndices(entityRng, platforms.length, 0).filter(function usableCoinPlatform(index) {
      return platforms[index] !== startPlatform && platforms[index].w >= 72;
    });
    coinPlatformOrder.unshift(platforms.indexOf(startPlatform));
    for (var coinPlatformCursor = 0; coins.length < COIN_COUNT && coinPlatformCursor < coinPlatformOrder.length; coinPlatformCursor += 1) {
      var coinPlatformIndex = coinPlatformOrder[coinPlatformCursor];
      var coinPlatform = platforms[coinPlatformIndex];
      var minCoinX = coinPlatform.x + 30;
      var maxCoinX = coinPlatform.x + coinPlatform.w - 30;
      if (coinPlatform === startPlatform) minCoinX = Math.max(minCoinX, 120);
      var platformSpike = spikes.find(function onPlatform(spike) { return spike.platform_id === coinPlatform.id; });
      if (platformSpike) {
        maxCoinX = Math.min(maxCoinX, platformSpike.x - 24);
      }
      if (maxCoinX <= minCoinX) continue;
      coins.push({
        x: Math.round(entityRng.range(minCoinX, maxCoinX)),
        y: coinPlatform.y - PLAYER_H / 2,
        r: 10,
        platform_id: coinPlatform.id,
        collected: false,
      });
    }
    coins.sort(function sortCoinsByX(a, b) { return a.x - b.x; });
    for (var coinIndex = 0; coinIndex < coins.length; coinIndex += 1) {
      coins[coinIndex].id = "coin_" + coinIndex;
    }
    var start = {
      x: 52,
      y: startPlatform.y - PLAYER_H / 2,
      platform_id: startPlatform.id,
    };
    var flag = {
      id: "flag",
      x: finalPlatform.x + finalPlatform.w - entityRng.randint(52, 75),
      y: finalPlatform.y - 70,
      w: 22,
      h: 70,
    };
    return {
      index: options.levelIndex,
      worldWidth: worldWidth,
      layout: { template: layout.template, width_scale: scale, motifs: motifOrder.slice(),
        terrain_height_range: [TERRAIN_MIN_Y, TERRAIN_MAX_Y] },
      start: start,
      flag: flag,
      platforms: platforms,
      gaps: gaps,
      spikes: spikes,
      coins: coins,
      checkpoints: checkpoints,
      routes: routes,
    };
  }

  window.SummitTerrain = Object.freeze({ build: build, sampleLayout: sampleLayout, families: Object.keys(FAMILIES) });
})();
