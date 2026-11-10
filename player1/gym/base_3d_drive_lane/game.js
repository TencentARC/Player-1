(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var G3D = window.BaseGamelet3D;
  var rewardConfig = window.Base3DDriveLaneRewardConfig;
  var GAME_ID = "base_3d_drive_lane";
  var LOGIC_WIDTH = 640;
  var LOGIC_HEIGHT = 640;
  var DISPLAY_WIDTH = G3D.viewport.baseWidth;
  var DISPLAY_HEIGHT = G3D.viewport.baseHeight;
  var STEP_MS = 1000 / 60;
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 3;
  var ASSET_REQUIREMENTS = window.CoastHighwayScene.assets;
  var ROAD_WIDTH_PX = 400;
  var ROAD_WIDTH = 7.2;
  var PIXELS_PER_WORLD = ROAD_WIDTH_PX / ROAD_WIDTH;
  var ROAD_LEFT = -ROAD_WIDTH / 2;
  var ROAD_RIGHT = ROAD_WIDTH / 2;
  var LANE_COUNT = 4;
  var LANE_WIDTH = ROAD_WIDTH / LANE_COUNT;
  var MAX_COINS_PER_LANE = 4;
  var MAX_COINS_VISIBLE = 13;
  var BASE_COIN_SPEED = 10;
  var COIN_SIZE_PX = 34;
  var COIN_RADIUS = 0.31;
  var COIN_BASE_Y = 0.72;
  var COIN_SPAWN_Z = 60;
  var COIN_DESPAWN_Z = -2.8;
  var PLAYER_Z = 2.65;
  var COIN_SPAWN_AHEAD = COIN_SPAWN_Z - PLAYER_Z;
  var STARTER_COIN_COUNT = 4;
  var STARTER_COIN_AHEAD = 5.67;
  var COIN_DESPAWN_BEHIND = PLAYER_Z - COIN_DESPAWN_Z;
  var CAR_WIDTH = 0.88;
  var CAR_DEPTH = 1.5;
  var CAR_HEIGHT = 0.36;
  var PLAYER_START_X = 0;
  var COIN_SPAWN_GAP_MIN_PX = 200;
  var COIN_SPAWN_GAP_MAX_PX = 325;
  var STEER_STEP = LANE_WIDTH / 12;
  var CAMERA_FOV_DEGREES = 60;
  var CAMERA_DISTANCE = 5.8;
  var CAMERA_HEIGHT = 3.8;
  var CAMERA_LOOK_HEIGHT = -0.15;
  var CAMERA_FORWARD_LOOK = 8.7;
  var PERTURBATION_CONTRACT = Core.perturbations.defineContract({
    game_id: GAME_ID,
    control_response: {
      move_scale: Core.controlResponse.ranges.move_scale,
      drive_scale: Core.controlResponse.ranges.drive_scale,
    },
    capabilities: {
      appearance: ["palette", "lighting", "background", "assets"],
      camera: ["projection", "rig"],
      scene: ["layout", "player_spawn", "entity_spawn"],
    },
    samplers: { scene: { layout: Core.perturbations.templateSampler("coast-highway", ["causeway", "forest-cut", "village-road"]) } },
    validators: { scene: { layout: Core.perturbations.templateValidator(["coast-highway", "causeway", "forest-cut", "village-road"]) } },
  });

  var canvas = document.getElementById("display");


  function laneCenters() {
    var centers = [];
    for (var i = 0; i < LANE_COUNT; i += 1) centers.push(ROAD_LEFT + (i + 0.5) * LANE_WIDTH);
    return centers;
  }

  function readDriveLaneUrlConfig(defaults) {
    var config = Core.config.readUrl(defaults);
    var params = new URLSearchParams(window.location.search || "");
    config.randInitPos = Core.config.normalizeBoolean(params.get("rand_init_pos"), false);
    return config;
  }

  function mergeDriveLaneEpisodeConfig(urlConfig, normalized, rawOptions) {
    var config = Core.config.mergeEpisode(urlConfig, normalized);
    var raw = rawOptions || {};
    var randInitPos = null;
    if (U.object.hasOwn(raw, "rand_init_pos")) {
      randInitPos = Core.config.normalizeBoolean(raw.rand_init_pos, null);
    } else if (U.object.hasOwn(raw, "randInitPos")) {
      randInitPos = Core.config.normalizeBoolean(raw.randInitPos, null);
    }
    config.randInitPos = randInitPos === null ? !!urlConfig.randInitPos : randInitPos;
    return config;
  }

  function Base3DDriveLane() {
    this.defaults = {
      seed: DEFAULT_SEED,
      difficulty: DEFAULT_DIFFICULTY,
      maxDifficulty: MAX_DIFFICULTY,
    };
    this.urlConfig = readDriveLaneUrlConfig(this.defaults);
    this.laneCenters = laneCenters();
    this.controls = { left: false, right: false };
    this.paused = false;
    this.runtime = { resetCount: 0, episodeCount: 0, lastResetMethod: null };
    this.bestMetrics = { bestPrimaryScore: 0 };
    Core.terminal.initialize(this);
    this.setup3D();
    this.createAsset = G3D.assets.bindGame(this);
    this.bindInput();
    Core.lifecycle.bindResetKeys(this);
    this.beginEpisode({}, false);
    this.startLoop();
  }

  Base3DDriveLane.prototype.setup3D = function setup3D() {
    this.world3d = G3D.createWorld(canvas, {
      width: DISPLAY_WIDTH,
      height: DISPLAY_HEIGHT,
      fov: CAMERA_FOV_DEGREES,
      near: 0.05,
      far: 90,
      clearColor: 0xcfe4ff,
      fogColor: 0xcfe4ff,
      fogNear: 20,
      fogFar: 52,
      ambient: 1.2,
      sun: 2.6,
      sunPosition: [-8, 20, 10],
      visualProfile: "stylized",
    });
    this.sceneMeshes = {
      laneDashes: [],
      roadsideMarkers: [],
      roadTrack: [],
      car: null,
      carLight: null,
    };
    G3D.viewport.install(this, { canvas: canvas, world: this.world3d, baseWidth: DISPLAY_WIDTH, baseHeight: DISPLAY_HEIGHT, baseFov: CAMERA_FOV_DEGREES });
  };

  Base3DDriveLane.prototype.beginEpisode = function beginEpisode(options, countReset, flags) {
    var episodeFlags = flags || {};
    var normalized = Core.config.normalizeOptions(options || {}, MAX_DIFFICULTY);
    var config = mergeDriveLaneEpisodeConfig(this.urlConfig, normalized, options || {});
    this.currentConfig = Core.config.cloneEpisode(config);
    Core.terminal.clear(this, episodeFlags);
    Core.lifecycle.resetEpisode(this, { controls: { left: false, right: false } });
    Core.reward.resetEpisode(this);
    Core.domains.beginEpisode(this, config, PERTURBATION_CONTRACT, DEFAULT_SEED);
    this.sceneLayout = Core.domains.sample(this, "scene", "layout", { template: "coast-highway" });
    this.difficulty = config.difficulty;
    this.randInitPos = !!config.randInitPos;
    G3D.visuals.configure(this, config, {
      defaultAssetPack: "gym-coast-highway",
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
    });
    this.playerX = this.chooseInitialPlayerX();
    this.playerZ = PLAYER_Z;
    this.coins = [];
    this.nextCoinId = 1;
    this.coinsCollected = 0;
    this.visualSteer = 0;
    this.coinsMissed = 0;
    this.distancePx = 0;
    this.nextCoinSpawnDistancePx = 0;
    this.stepCount = 0;
    this.gameTimeMs = 0;
    this.lastAction = "reset";
    this.mode = config.autostart ? "playing" : "paused";
    this.terminal = { isTerminal: false, outcome: null, reason: null };
    this.controls = { left: false, right: false };
    this.spawnInitialCoinStream(this.spawnStarterCoins());
    this.scheduleNextCoinSpawn();
    if (countReset) this.runtime.resetCount += 1;
    this.runtime.episodeCount += 1;
    this.runtime.lastResetMethod = countReset ? "inplace_reset" : "init";
    this.rebuildScene3D();
    this.updateBestMetrics();
    this.render();
    return { accepted: normalized, applied: config, notes: [] };
  };

  Base3DDriveLane.prototype.bindInput = function bindInput() {
    this.inputController = G3D.input.createController(this, {
      canvas: canvas,
      eventTarget: document,
      includeMovement: false,
      controlAliases: {
        left: ["a", "KeyA", "ArrowLeft"],
        right: ["d", "KeyD", "ArrowRight"],
      },
      onPress: function onPress() {
        if (this.mode === "paused") this.startPlaying("manual_start");
      },
    });
    var app = document.getElementById("app");
    if (app) app.focus();
  };

  Base3DDriveLane.prototype.ensureSimulationRunner = function ensureSimulationRunner() {
    if (this.simulationRunner) return this.simulationRunner;
    var self = this;
    this.simulationRunner = Core.createFixedStepRunner({
      game: this,
      stepMs: STEP_MS,
      update: function update() { self.update(); },
      render: function render() { self.render(); },
      isActive: function isActive() { return self.mode === "playing" && !self.paused; },
    });
    return this.simulationRunner;
  };

  Base3DDriveLane.prototype.startLoop = function startLoop() {
    this.ensureSimulationRunner().start();
  };

  Base3DDriveLane.prototype.startPlaying = function startPlaying(method) {
    if (this.mode !== "paused") return false;
    this.mode = "playing";
    this.runtime.lastResetMethod = method || this.runtime.lastResetMethod || "manual_start";
    return true;
  };

  Base3DDriveLane.prototype.pause = function pause() {
    var pauseState = Core.lifecycle.pause(this);
    this.render();
    return pauseState;
  };

  Base3DDriveLane.prototype.resume = function resume() {
    var pauseState = Core.lifecycle.resume(this);
    this.render();
    return pauseState;
  };

  Base3DDriveLane.prototype.getCoinSpawnGapScale = function getCoinSpawnGapScale() {
    return Math.max(0.72, 1 - (this.difficulty - 1) * 0.08);
  };

  Base3DDriveLane.prototype.getCoinSpawnGapRangePx = function getCoinSpawnGapRangePx() {
    var scale = this.getCoinSpawnGapScale();
    return {
      min: COIN_SPAWN_GAP_MIN_PX * scale,
      max: COIN_SPAWN_GAP_MAX_PX * scale,
    };
  };

  Base3DDriveLane.prototype.randomCoinSpawnGapPx = function randomCoinSpawnGapPx() {
    var range = this.getCoinSpawnGapRangePx();
    return Core.domains.gameplayRng(this, "scene", "entity_spawn")
      .range(range.min, range.max);
  };

  Base3DDriveLane.prototype.scheduleNextCoinSpawn = function scheduleNextCoinSpawn() {
    this.nextCoinSpawnDistancePx = this.distancePx + this.randomCoinSpawnGapPx();
  };

  Base3DDriveLane.prototype.getCoinSpeedMultiplier = function getCoinSpeedMultiplier() {
    return 0.85 + this.difficulty * 0.15;
  };

  Base3DDriveLane.prototype.getCoinSpeedPx = function getCoinSpeedPx() {
    return Math.max(1, Math.round(BASE_COIN_SPEED * this.getCoinSpeedMultiplier())) * this.controlResponse.applied.drive_scale;
  };

  Base3DDriveLane.prototype.getCoinSpeedWorld = function getCoinSpeedWorld() {
    return this.getCoinSpeedPx() / PIXELS_PER_WORLD;
  };

  Base3DDriveLane.prototype.chooseInitialPlayerX = function chooseInitialPlayerX() {
    if (!this.randInitPos && Core.domains.profile(this, "scene") !== "perturbed") return PLAYER_START_X;
    var playerRng = Core.domains.gameplayRng(this, "scene", "player_spawn");
    return this.laneCenters[playerRng.randint(0, LANE_COUNT)];
  };

  Base3DDriveLane.prototype.nearestLane = function nearestLane(x) {
    var bestLane = 0;
    var bestDistance = Infinity;
    for (var i = 0; i < this.laneCenters.length; i += 1) {
      var distance = Math.abs(x - this.laneCenters[i]);
      if (distance < bestDistance) {
        bestDistance = distance;
        bestLane = i;
      }
    }
    return bestLane;
  };

  Base3DDriveLane.prototype.movePlayer = function movePlayer(steer) {
    if (steer < -0.1) this.playerX = Math.max(ROAD_LEFT + CAR_WIDTH / 2, this.playerX - STEER_STEP * this.controlResponse.applied.move_scale);
    else if (steer > 0.1) this.playerX = Math.min(ROAD_RIGHT - CAR_WIDTH / 2, this.playerX + STEER_STEP * this.controlResponse.applied.move_scale);
  };

  Base3DDriveLane.prototype.createCoin = function createCoin(lane, aheadDistance) {
    var ahead = Number.isFinite(aheadDistance) ? aheadDistance : COIN_SPAWN_AHEAD;
    return {
      id: "coin_" + this.nextCoinId++,
      type: "coin",
      x: this.laneCenters[lane],
      z: this.playerZ + ahead,
      lane: lane,
      radius: COIN_RADIUS,
      speed: this.getCoinSpeedWorld(),
      speedPx: this.getCoinSpeedPx(),
      spin: Core.domains.gameplayRng(this, "appearance", "palette")
        .range(0, Math.PI * 2),
    };
  };

  Base3DDriveLane.prototype.spawnStarterCoins = function spawnStarterCoins() {
    var spawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var lanes = [];
    for (var lane = 0; lane < LANE_COUNT; lane += 1) lanes.push(lane);
    var ahead = STARTER_COIN_AHEAD;
    for (var i = 0; i < STARTER_COIN_COUNT && lanes.length; i += 1) {
      var lane = spawnRng.choice(lanes);
      lanes.splice(lanes.indexOf(lane), 1);
      this.coins.push(this.createCoin(lane, Math.min(COIN_SPAWN_AHEAD, ahead)));
      ahead += this.randomCoinSpawnGapPx() / PIXELS_PER_WORLD;
    }
    return ahead;
  };

  Base3DDriveLane.prototype.spawnInitialCoinStream = function spawnInitialCoinStream(startAhead) {
    var spawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var laneCounts = [];
    for (var lane = 0; lane < LANE_COUNT; lane += 1) laneCounts[lane] = 0;
    for (var coinIndex = 0; coinIndex < this.coins.length; coinIndex += 1) {
      laneCounts[this.coins[coinIndex].lane] += 1;
    }

    var ahead = startAhead;
    while (this.coins.length < MAX_COINS_VISIBLE && ahead < COIN_SPAWN_AHEAD) {

      var availableLanes = [];
      for (var laneIndex = 0; laneIndex < LANE_COUNT; laneIndex += 1) {
        if (laneCounts[laneIndex] < MAX_COINS_PER_LANE) availableLanes.push(laneIndex);
      }
      if (!availableLanes.length) break;

      var laneChoice = spawnRng.choice(availableLanes);
      this.coins.push(this.createCoin(laneChoice, ahead));
      laneCounts[laneChoice] += 1;
      ahead += this.randomCoinSpawnGapPx() / PIXELS_PER_WORLD;
    }
  };

  Base3DDriveLane.prototype.spawnCoinIfNeeded = function spawnCoinIfNeeded() {
    if (this.distancePx < this.nextCoinSpawnDistancePx) return;
    this.scheduleNextCoinSpawn();
    if (this.coins.length >= MAX_COINS_VISIBLE) return;
    var laneCounts = {};
    for (var lane = 0; lane < LANE_COUNT; lane += 1) laneCounts[lane] = 0;
    for (var i = 0; i < this.coins.length; i += 1) laneCounts[this.coins[i].lane] += 1;
    var spawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var availableLanes = [];
    for (var laneIndex = 0; laneIndex < LANE_COUNT; laneIndex += 1) {
      if (laneCounts[laneIndex] < MAX_COINS_PER_LANE) availableLanes.push(laneIndex);
    }
    if (!availableLanes.length) return;
    var laneChoice = spawnRng.choice(availableLanes);
    var candidate = this.createCoin(laneChoice);
    var minGap = COIN_RADIUS * 2 * 2.2;
    for (var c = 0; c < this.coins.length; c += 1) {
      if (this.coins[c].lane === laneChoice && Math.abs(candidate.z - this.coins[c].z) <= minGap) return;
    }
    this.coins.push(candidate);
  };

  Base3DDriveLane.prototype.moveCoins = function moveCoins() {
    var kept = [];
    var behindLimit = this.playerZ - COIN_DESPAWN_BEHIND;
    for (var i = 0; i < this.coins.length; i += 1) {
      var coin = this.coins[i];
      coin.spin += 0.14;
      if (coin.z >= behindLimit) kept.push(coin);
      else {
        this.coinsMissed += 1;
        this.addReward(-rewardConfig.constants.missedCoinPenalty);
      }
    }
    this.coins = kept;
  };

  Base3DDriveLane.prototype.detectCoinCollection = function detectCoinCollection() {
    var kept = [];
    var minX = this.playerX - CAR_WIDTH / 2;
    var maxX = this.playerX + CAR_WIDTH / 2;
    var minZ = this.playerZ - CAR_DEPTH / 2;
    var maxZ = this.playerZ + CAR_DEPTH / 2;
    for (var i = 0; i < this.coins.length; i += 1) {
      var coin = this.coins[i];
      var closestX = U.math.clamp(coin.x, minX, maxX);
      var closestZ = U.math.clamp(coin.z, minZ, maxZ);
      var dx = coin.x - closestX;
      var dz = coin.z - closestZ;
      if (dx * dx + dz * dz <= COIN_RADIUS * COIN_RADIUS) {
        this.coinsCollected += 1;
        this.addReward(rewardConfig.constants.coinReward);
      } else {
        kept.push(coin);
      }
    }
    this.coins = kept;
  };

  Base3DDriveLane.prototype.addReward = function addReward(value) {
    Core.reward.add(this, value);
  };

  Base3DDriveLane.prototype.update = function update() {
    if (this.mode !== "playing" || this.paused) return;
    var steer = (this.controls.right ? 1 : 0) - (this.controls.left ? 1 : 0);
    this.lastAction = steer < -0.1 ? "steer_left" : steer > 0.1 ? "steer_right" : "hold_lane";
    this.visualSteer += (steer - this.visualSteer) * 0.22;
    this.movePlayer(steer);
    this.spawnCoinIfNeeded();
    this.playerZ += this.getCoinSpeedWorld();
    this.moveCoins();
    this.distancePx += this.getCoinSpeedPx();
    this.stepCount += 1;
    this.gameTimeMs += STEP_MS;
    this.detectCoinCollection();
    this.updateBestMetrics();
  };

  Base3DDriveLane.prototype.advanceTime = function advanceTime(ms, options) {
    this.ensureSimulationRunner().advance(ms, options || {});
    return this.getStatePayload();
  };

  Base3DDriveLane.prototype.normalizeAction = function normalizeAction(action) {
    var actionId = Core.actions.readId(action, { lowercase: true });
    var steer = 0;
    if (Core.actions.hasKey(action, ["ArrowLeft", "KeyA", "a"])) steer -= 1;
    if (Core.actions.hasKey(action, ["ArrowRight", "KeyD", "d"])) steer += 1;
    steer = U.math.clamp(steer, -1, 1);
    return { id: actionId || "wait", args: {}, left: steer < -0.1, right: steer > 0.1, steer: steer };
  };

  Base3DDriveLane.prototype.clearTransientControls = function clearTransientControls() {
    this.controls = { left: false, right: false };
  };

  Base3DDriveLane.prototype.applyAction = function applyAction(normalized, context) {
    this.controls.left = normalized.left;
    this.controls.right = normalized.right;
    var stepOptions = context && context.stepOptions || { source: "agent" };
    if (this.mode === "paused" && !this.paused) this.startPlaying(stepOptions.source + "_step");
  };

  Base3DDriveLane.prototype.advanceSimulation = function advanceSimulation(ms) {
    var state = this.advanceTime(ms, { render: false });
    this.clearTransientControls();
    return state;
  };

  Base3DDriveLane.prototype.buildStepInfo = function buildStepInfo(state, stepOptions, normalized) {
    var info = this.infoPayload();
    info.action = { type: "game_step_action", id: normalized.id, args: normalized.args };
    info.durationMs = stepOptions.durationMs;
    info.source = stepOptions.source;
    info.status = state.status;
    return info;
  };

  Base3DDriveLane.prototype.resetGym = function resetGym(options) {
    this.resetFromAPI(options || {});
    var state = this.getStatePayload();
    return {
      observation: this.getObservationFromState(state),
      reward: 0,
      done: false,
      info: this.infoPayload(),
    };
  };

  Base3DDriveLane.prototype.serializePlayer = function serializePlayer() {
    return {
      x: this.playerX,
      y: 0,
      z: this.playerZ,
      width: CAR_WIDTH,
      height: CAR_HEIGHT,
      depth: CAR_DEPTH,
      lane: this.nearestLane(this.playerX),
      shape: "car",
    };
  };

  Base3DDriveLane.prototype.serializeCoins = function serializeCoins() {
    var self = this;
    return this.coins.map(function serializeCoin(coin, index) {
      return {
        id: coin.id,
        type: "coin",
        x: coin.x,
        y: COIN_BASE_Y + Math.sin(self.gameTimeMs * 0.006 + index) * 0.035,
        z: coin.z,
        relative_z: coin.z - self.playerZ,
        radius: coin.radius,
        width: COIN_RADIUS * 2,
        height: COIN_RADIUS * 2,
        lane: coin.lane,
        speed: coin.speed,
        speed_px_per_step: coin.speedPx,
        shape: "coin",
      };
    });
  };

  Base3DDriveLane.prototype.rewardPayload = function rewardPayload() {
    var scoreMetrics = this.rewardMetrics();
    return {
      env_reward_step: this.envRewardStep,
      env_reward_episode: this.envRewardEpisode,
      primary_positive_score: rewardConfig.computePrimaryPositiveScore(scoreMetrics),
      primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(scoreMetrics),
      primary_score: rewardConfig.computePrimaryScore(scoreMetrics),
    };
  };

  Base3DDriveLane.prototype.rewardMetrics = function rewardMetrics() {
    return {
      coins_collected: this.coinsCollected,
      coins_missed: this.coinsMissed,
    };
  };

  Base3DDriveLane.prototype.getPrimaryScore = function getPrimaryScore() {
    return rewardConfig.computePrimaryScore(this.rewardMetrics());
  };

  Base3DDriveLane.prototype.updateBestMetrics = function updateBestMetrics() {
    var rewards = this.rewardPayload();
    this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, rewards.primary_score);
  };

  Base3DDriveLane.prototype.visualPayload = function visualPayload() {
    return G3D.visuals.payload(this);
  };

  Base3DDriveLane.prototype.getStatePayload = function getStatePayload() {
    G3D.visuals.sync(this);
    var rewards = this.rewardPayload();
    var viewport = this.viewportPayload();
    return {
      schemaVersion: "2.0",
      gameId: GAME_ID,
      seed: this.seed,
      timestampMs: Date.now(),
      gameTimeMs: U.math.finiteNumber(this.gameTimeMs),
      status: this.mode,
      paused: this.mode === "paused" || this.paused,
      runtime_paused: this.paused,
      is_actionable: this.mode === "paused" || this.mode === "playing",
      terminal: { isTerminal: false, outcome: null, reason: null },
      game_state: {
        score: rewards.primary_score,
        level: null,
        player: this.serializePlayer(),
        environment: {
          phase: this.mode,
          viewport_width: viewport.width,
          viewport_height: viewport.height,
          logic_width: viewport.width,
          logic_height: viewport.height,
          base_logic_width: LOGIC_WIDTH,
          base_logic_height: LOGIC_HEIGHT,
          fullscreen: viewport,
          camera_fov: viewport.fov,
          road_left: ROAD_LEFT,
          road_right: ROAD_RIGHT,
          road_width: ROAD_WIDTH,
          lane_count: LANE_COUNT,
          lane_width: LANE_WIDTH,
          lane_centers: this.laneCenters.slice(),
          lane_positions: this.laneCenters.slice(),
          player_z: this.playerZ,
          player_start_z: PLAYER_Z,
          camera_x_mirrored_for_render: true,
          coin_size: COIN_SIZE_PX,
          coin_radius: COIN_RADIUS,
          max_coins_visible: MAX_COINS_VISIBLE,
          coin_spawn_gap_px: this.getCoinSpawnGapRangePx(),
          next_coin_spawn_gap_px: Math.max(0, this.nextCoinSpawnDistancePx - this.distancePx),
          coin_speed_multiplier: this.getCoinSpeedMultiplier(),
          coin_speed_px_per_step: this.getCoinSpeedPx(),
          rand_init_pos: this.randInitPos,
          scene_version: "coast-highway-2",
          scene_layout: this.sceneLayout,
          asset_pack: this.assetContext ? this.assetContext.id : null,
          asset: this.assetContext ? this.assetContext.payload() : null,
          difficulty: this.difficulty,
          perturb_active: Core.perturbations.isActive(this),
          visual_perturbations: this.visualPayload(),
        },
        entities: this.serializeCoins(),
      },
      metrics: {
        env_reward_step: rewards.env_reward_step,
        env_reward_episode: rewards.env_reward_episode,
        primary_positive_score: rewards.primary_positive_score,
        primary_penalty_score: rewards.primary_penalty_score,
        primary_score: rewards.primary_score,
        coins_collected: this.coinsCollected,
        coins_visible: this.coins.length,
        coins_missed: this.coinsMissed,
        distance_px: this.distancePx,
        rand_init_pos: this.randInitPos,
        next_coin_spawn_gap_px: Math.max(0, this.nextCoinSpawnDistancePx - this.distancePx),
        coin_speed_px_per_step: this.getCoinSpeedPx(),
        step_count: this.stepCount,
        best_primary_score: this.bestMetrics.bestPrimaryScore,
        difficulty: this.difficulty,
      },
      debug: {
        mode: this.mode,
        last_action: this.lastAction,
        last_reset_method: this.runtime.lastResetMethod,
        reset_count: this.runtime.resetCount,
        paused: this.paused,
        runtime_paused: this.paused,
        dynamic_mesh_count: this.coinRegistry ? this.coinRegistry.size() : 0,
      },
    };
  };

  Base3DDriveLane.prototype.getObservationFromState = function getObservationFromState(state) {
    var gameState = state.game_state || {};
    var environment = gameState.environment || {};
    return {
      player: gameState.player || null,
      coins: gameState.entities || [],
      road: {
        logic_width: environment.logic_width,
        logic_height: environment.logic_height,
        road_left: environment.road_left,
        road_right: environment.road_right,
        lane_count: environment.lane_count,
        lane_positions: environment.lane_positions || [],
      },
      metrics: state.metrics || {},
    };
  };

  Base3DDriveLane.prototype.getObservation = function getObservation() {
    return this.getObservationFromState(this.getStatePayload());
  };

  Base3DDriveLane.prototype.infoPayload = function infoPayload() {
    var state = this.getStatePayload();
    var info = {
      score: state.metrics.primary_score,
      status: state.status,
    };
    Object.keys(state.metrics).forEach(function copyMetric(key) {
      info[key] = state.metrics[key];
    });
    return info;
  };

  Base3DDriveLane.prototype.renderGameToText = function renderGameToText() {
    var snapshot = this.getStatePayload();
    return JSON.stringify({
      coordinate_system: "x/z ground plane; player z increases over time; render mirrors x so screen-left matches steer_left",
      seed: snapshot.seed,
      status: snapshot.status,
      terminal: snapshot.terminal,
      player: snapshot.game_state.player,
      coins: snapshot.game_state.entities,
      metrics: snapshot.metrics,
      environment: {
        road_left: snapshot.game_state.environment.road_left,
        road_right: snapshot.game_state.environment.road_right,
        lane_positions: snapshot.game_state.environment.lane_positions,
        difficulty: snapshot.game_state.environment.difficulty,
        rand_init_pos: snapshot.game_state.environment.rand_init_pos,
        coin_spawn_gap_px: snapshot.game_state.environment.coin_spawn_gap_px,
        next_coin_spawn_gap_px: snapshot.game_state.environment.next_coin_spawn_gap_px,
        coin_speed_px_per_step: snapshot.game_state.environment.coin_speed_px_per_step,
        perturb_active: snapshot.game_state.environment.perturb_active,
        visual_perturbations: snapshot.game_state.environment.visual_perturbations,
      },
    });
  };


  Base3DDriveLane.prototype.rebuildScene3D = function rebuildScene3D() {
    this.world3d.clear();
    this.sceneMeshes = window.CoastHighwayScene.build(this, {
      roadWidth: ROAD_WIDTH, carWidth: CAR_WIDTH, carDepth: CAR_DEPTH,
      coinRadius: COIN_RADIUS, maxCoins: MAX_COINS_VISIBLE, pixelsPerWorld: PIXELS_PER_WORLD,
    });
    this.syncScene3D();
  };

  Base3DDriveLane.prototype.syncScene3D = function syncScene3D() {
    window.CoastHighwayScene.sync(this, this.sceneMeshes);
    this.world3d.setChaseCamera({
      x: 0, z: this.playerZ, yaw: Math.PI / 2,
      distance: CAMERA_DISTANCE, height: CAMERA_HEIGHT,
      lookHeight: CAMERA_LOOK_HEIGHT, forwardLook: CAMERA_FORWARD_LOOK,
      bounds: { minX: ROAD_LEFT - 1.5, maxX: ROAD_RIGHT + 1.5, minZ: this.playerZ - 8.5, maxZ: this.playerZ + 5.5 },
    });
  };

  Base3DDriveLane.prototype.render = function render() {
    G3D.visuals.sync(this, { sceneReady: true });
    if (!this.world3d) return;
    this.syncScene3D();
    this.world3d.render();
    if (this.infoPanel) this.infoPanel.update();
  };

  Base3DDriveLane.prototype.resetFromAPI = function resetFromAPI(options) {
    return this.beginEpisode(options || {}, true);
  };

  async function start() {
    await G3D.assets.preload("gym-coast-highway", ASSET_REQUIREMENTS);
    var game = new Base3DDriveLane();
    Core.createRuntime({
      game: game,
      presentation: {
        title: "3D Lane Driving",
        controls: "A / D or Left / Right steers. The car moves forward automatically. Collect the road coins.",
        read: function readPresentation() {
          return {
            status: game.paused ? "paused" : game.mode,
            primaryScore: game.getPrimaryScore(),
            stepReward: game.envRewardStep,
            episodeReward: game.envRewardEpisode,
            difficulty: game.difficulty,
            seed: game.seed,
            perturbation: Core.perturbations.label(game),
            details: [
              ["Coins", game.coinsCollected],
              ["Missed", game.coinsMissed],
              ["Lane", (game.nearestLane(game.playerX) + 1) + " / " + LANE_COUNT],
            ],
          };
        },
      },
      renderer: G3D,
      gameId: GAME_ID,
      defaultSeed: DEFAULT_SEED,
      maxDifficulty: MAX_DIFFICULTY,
      defaultStepMs: 200,
      assets: { engine: G3D.assets, requiredAssetIds: ASSET_REQUIREMENTS },
      capabilities: { supports_rand_init_pos: true },
    });
  }

  Core.lifecycle.boot(start);
})();
