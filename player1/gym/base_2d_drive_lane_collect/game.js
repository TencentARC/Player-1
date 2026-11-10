(function () {
  "use strict";

  var rewardConfig = window.Base2DDriveLaneCollectRewardConfig;
  var T2D = window.BaseGameletThree2D;
  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var RoadScene = window.CoastalRoadScene;
  var GAME_ID = "base_2d_drive_lane_collect";
  var PERTURBATION_CONTRACT = Core.perturbations.defineContract({
    game_id: GAME_ID,
    control_response: {
      move_scale: Core.controlResponse.ranges.move_scale,
      drive_scale: Core.controlResponse.ranges.drive_scale,
    },
    capabilities: {
      appearance: ["palette", "background", "assets"],
      camera: ["projection"],
      scene: ["layout", "player_spawn", "entity_spawn"],
    },
    samplers: {
      camera: { projection: T2D.camera.projectionSampler },
      scene: { layout: Core.perturbations.templateSampler("service-road", ["canal-road", "orchard-road", "bridge-road"]) },
    },
    validators: {
      camera: { projection: T2D.camera.projectionValidator },
      scene: { layout: Core.perturbations.templateValidator(["service-road", "canal-road", "orchard-road", "bridge-road"]) },
    },
  });
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 3;
  var ASSET_REQUIREMENTS = RoadScene.assets;
  var DIFFICULTY_CHOICE_SEED_OFFSET = 0x4cf5ad43;
  var LOGICAL_HEIGHT = 640;
  var LOGICAL_WIDTH = T2D.viewport.widthForHeight(LOGICAL_HEIGHT);
  var DEFAULT_STAGE_WIDTH = T2D.viewport.baseWidth;
  var DEFAULT_STAGE_HEIGHT = T2D.viewport.baseHeight;
  var CAR_WIDTH = 56;
  var CAR_HEIGHT = 96;
  var ROAD_WIDTH = 400;
  var LANE_COUNT = 4;
  var MAX_COINS_PER_LANE = 3;
  var MAX_COINS_VISIBLE = 5;
  var BASE_COIN_SPEED = 8;
  var COIN_SIZE = 34;
  var PLAYER_START_Y = LOGICAL_HEIGHT - CAR_HEIGHT - 24;
  var PLAYER_START_X = Math.floor(LOGICAL_WIDTH / 2) - Math.floor(CAR_WIDTH / 2);
  var ROAD_LEFT = Math.floor(LOGICAL_WIDTH / 2) - Math.floor(ROAD_WIDTH / 2);
  var ROAD_RIGHT = ROAD_LEFT + ROAD_WIDTH;
  var FRAME_MS = 1000 / 60;
  var PLAYER_STEER_LANES_PER_SECOND = 5;
  var SPAWN_PROBABILITY = 0.08;
  var MIN_SPAWN_INTERVAL_MS = 300;
  var MIN_SPAWN_INTERVAL_STEPS = Math.round(MIN_SPAWN_INTERVAL_MS / FRAME_MS);
  var STEER_STEP = ((ROAD_WIDTH / LANE_COUNT) * PLAYER_STEER_LANES_PER_SECOND * FRAME_MS) / 1000;
  var lanePositions = [];
  var laneWidth = ROAD_WIDTH / LANE_COUNT;
  for (var i = 0; i < LANE_COUNT; i += 1) {
    lanePositions.push(Math.floor(ROAD_LEFT + (i + 0.5) * laneWidth - CAR_WIDTH / 2));
  }

  var canvas = document.getElementById("display") || document.getElementById("game");
  var view = null;
  var presentation = null;
  var game = null;

  var createAsset = T2D.assets.bindView(function currentView() { return view; });

  var state = {
    phase: "paused",
    runtimePaused: false,
    playerX: PLAYER_START_X,
    playerY: PLAYER_START_Y,
    opponents: [],
    coinsCollected: 0,
    coinsMissed: 0,
    lastCoinSpawnStep: -MIN_SPAWN_INTERVAL_STEPS,
    distancePx: 0,
    stepCount: 0,
    envRewardStep: 0,
    envRewardEpisode: 0,
    attempts: 0,
    config: {
      seed: DEFAULT_SEED,
      difficulty: DEFAULT_DIFFICULTY,
      difficultyChoices: null,
      perturb: null,
      visualFlags: Core.visuals.cloneFlags(),
      randInitPos: false,
    },
    keys: { left: false, right: false },
    lastResetMethod: null,
  };

  var entitySpawnRng = null;
  var simulationRunner = null;

  var configDefaults = {
    seed: DEFAULT_SEED,
    difficulty: DEFAULT_DIFFICULTY,
    maxDifficulty: MAX_DIFFICULTY,
    difficultyChoiceSeedOffset: DIFFICULTY_CHOICE_SEED_OFFSET,
    visualFlags: { bgColor: false },
  };

  function randomInt(minValue, maxValue) {
    return entitySpawnRng.randint(minValue, maxValue);
  }

  function readUrlConfig() {
    return Core.config.readUrl(configDefaults);
  }

  function normalizeEpisodeConfig(overrides) {
    return Core.config.mergeEpisode(
      readUrlConfig(),
      Core.config.normalizeOptions(overrides || {}, MAX_DIFFICULTY)
    );
  }

  function getSeed() {
    return state.config.seed;
  }

  function getAssetContext() {
    T2D.visuals.sync(state);
    return state.assetContext;
  }

  function getSpawnProbability() {
    return U.math.clamp(SPAWN_PROBABILITY * state.config.difficulty, 0, 0.6);
  }

  function getCoinSpeedMultiplier() {
    return 0.85 + state.config.difficulty * 0.15;
  }

  function getCoinSpeed() {
    return Math.max(1, Math.round(BASE_COIN_SPEED * getCoinSpeedMultiplier())) * state.controlResponse.applied.drive_scale;
  }

  function createOpponent(lane) {
    var laneCenter = getLaneCenterX(lane);
    return {
      x: Math.round(laneCenter - COIN_SIZE / 2),
      y: -COIN_SIZE,
      speed: getCoinSpeed(),
      lane: lane,
    };
  }

  function chooseInitialPlayerX() {
    if (!state.config.randInitPos && Core.domains.profile(state, "scene") !== "perturbed") {
      return PLAYER_START_X;
    }
    var playerSpawnRng = Core.domains.gameplayRng(state, "scene", "player_spawn");
    var lane = playerSpawnRng.randint(0, LANE_COUNT);
    return lanePositions[lane];
  }

  function deriveActionFromKeys() {
    if (state.keys.left && !state.keys.right) return 1;
    if (state.keys.right && !state.keys.left) return 2;
    return 0;
  }

  function applyPausedState(resetMethod) {
    state.phase = "paused";
    state.playerX = chooseInitialPlayerX();
    state.playerY = PLAYER_START_Y;
    state.opponents = [];
    state.coinsCollected = 0;
    state.coinsMissed = 0;
    state.lastCoinSpawnStep = -MIN_SPAWN_INTERVAL_STEPS;
    state.distancePx = 0;
    state.stepCount = 0;
    state.envRewardStep = 0;
    state.envRewardEpisode = 0;
    state.runtimePaused = false;
    state.keys.left = false;
    state.keys.right = false;
    state.lastResetMethod = resetMethod || null;
    if (simulationRunner) simulationRunner.resetClock();
    render();
  }

  function activateFromPause(initialAction, startMethod) {
    if (state.phase !== "paused") return false;
    state.phase = "playing";
    state.lastResetMethod = startMethod || state.lastResetMethod || "manual_start";
    state.attempts += 1;
    if (initialAction) {
      movePlayer(initialAction);
    }
    render();
    return true;
  }

  function resetEpisodeState(resetMethod) {
    Core.domains.beginEpisode(state, state.config, PERTURBATION_CONTRACT, DEFAULT_SEED);
    state.sceneLayout = Core.domains.sample(state, "scene", "layout", { template: "service-road" });
    entitySpawnRng = Core.domains.gameplayRng(state, "scene", "entity_spawn");
    T2D.visuals.configure(state, state.config, {
      baseWidth: DEFAULT_STAGE_WIDTH,
      baseHeight: DEFAULT_STAGE_HEIGHT,
      backingWidth: LOGICAL_WIDTH,
      backingHeight: LOGICAL_HEIGHT,
      defaultAssetPack: RoadScene.pack,
      view: view,
    });
    applyPausedState(resetMethod);
  }

  function beginEpisode(overrides, resetMethod, autostart) {
    state.config = normalizeEpisodeConfig(overrides);
    resetEpisodeState(resetMethod);
    var shouldAutostart = autostart === undefined ? state.config.autostart : autostart;
    if (shouldAutostart) {
      activateFromPause(0, resetMethod);
    }
    var applied = {
      seed: getSeed(),
      difficulty: state.config.difficulty,
      difficulty_choices: state.config.difficultyChoices ? state.config.difficultyChoices.slice() : null,
      autostart: shouldAutostart,
      rand_init_pos: state.config.randInitPos,
      perturb: state.config.perturb,
      perturb_entity_color: state.config.visualFlags.entityColor,
    };
    return {
      accepted: overrides || {},
      applied: applied,
      notes: [],
    };
  }

  function movePlayer(action) {
    if (action === 1 && state.playerX > ROAD_LEFT) {
      state.playerX = Math.max(ROAD_LEFT, state.playerX - STEER_STEP * state.controlResponse.applied.move_scale);
    } else if (action === 2 && state.playerX < ROAD_RIGHT - CAR_WIDTH) {
      state.playerX = Math.min(ROAD_RIGHT - CAR_WIDTH, state.playerX + STEER_STEP * state.controlResponse.applied.move_scale);
    }
  }

  function getLaneCenterX(lane) {
    return lanePositions[lane] + CAR_WIDTH / 2;
  }

  function spawnOpponentIfNeeded() {
    var laneCounts = {};
    for (var lane = 0; lane < LANE_COUNT; lane += 1) {
      laneCounts[lane] = 0;
    }
    for (var i = 0; i < state.opponents.length; i += 1) {
      laneCounts[state.opponents[i].lane] += 1;
    }

    var spawnIntervalElapsed = state.stepCount - state.lastCoinSpawnStep >= MIN_SPAWN_INTERVAL_STEPS;
    if (
      entitySpawnRng.next() < getSpawnProbability() &&
      spawnIntervalElapsed &&
      state.opponents.length < MAX_COINS_VISIBLE
    ) {
      var laneChoice = randomInt(0, LANE_COUNT);
      if (laneCounts[laneChoice] < MAX_COINS_PER_LANE) {
        var candidate = createOpponent(laneChoice);
        var sameLane = state.opponents.filter(function (opponent) {
          return opponent.lane === laneChoice;
        });
        var noOverlap = sameLane.every(function (opponent) {
          return Math.abs(candidate.y - opponent.y) > COIN_SIZE * 2.2;
        });
        if (noOverlap) {
          state.opponents.push(candidate);
          state.lastCoinSpawnStep = state.stepCount;
        }
      }
    }
  }

  function moveOpponents() {
    for (var i = 0; i < state.opponents.length; i += 1) {
      var opponent = state.opponents[i];
      opponent.y += opponent.speed;
    }
    state.opponents = state.opponents.filter(function (opponent) {
      if (opponent.y <= LOGICAL_HEIGHT) return true;
      state.coinsMissed += 1;
      Core.reward.add(state, -rewardConfig.constants.coinMissPenalty);
      return false;
    });
  }

  function serializePlayer(playerX, playerY) {
    if (playerY >= LOGICAL_HEIGHT) return null;
    return {
      x: playerX,
      y: playerY,
      width: CAR_WIDTH,
      height: CAR_HEIGHT,
      shape: "rect",
    };
  }

  function serializeOpponents(opponents) {
    var assets = getAssetContext();
    return opponents.map(function (opponent, index) {
      return {
        id: "coin_" + index,
        type: "coin",
        x: opponent.x,
        y: opponent.y,
        width: COIN_SIZE,
        height: COIN_SIZE,
        radius: COIN_SIZE / 2,
        lane: opponent.lane,
        speed: opponent.speed,
        shape: "circle",
        color: assets.colorChannels("coin"),
        asset: assets.payload(),
      };
    });
  }

  function buildRewardMetricPayload(envRewardStep, envRewardEpisode, coinsCollected, coinsMissed) {
    var scoreMetrics = {
      coinsCollected: coinsCollected,
      coinsMissed: coinsMissed,
      envRewardEpisode: envRewardEpisode,
    };
    return {
      env_reward_step: envRewardStep,
      env_reward_episode: envRewardEpisode,
      primary_positive_score: rewardConfig.computePrimaryPositiveScore(scoreMetrics),
      primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(scoreMetrics),
      primary_score: rewardConfig.computePrimaryScore(scoreMetrics),
    };
  }

  function buildStateSnapshot(overrides) {
    var snapshot = overrides || {};
    var phase = snapshot.phase !== undefined ? snapshot.phase : state.phase;
    var playerX = snapshot.playerX !== undefined ? snapshot.playerX : state.playerX;
    var playerY = snapshot.playerY !== undefined ? snapshot.playerY : state.playerY;
    var opponents = snapshot.opponents !== undefined ? snapshot.opponents : state.opponents;
    var coinsCollected = snapshot.coinsCollected !== undefined ? snapshot.coinsCollected : state.coinsCollected;
    var coinsMissed = snapshot.coinsMissed !== undefined ? snapshot.coinsMissed : state.coinsMissed;
    var distancePx = snapshot.distancePx !== undefined ? snapshot.distancePx : state.distancePx;
    var stepCount = snapshot.stepCount !== undefined ? snapshot.stepCount : state.stepCount;
    var envRewardStep = snapshot.envRewardStep !== undefined ? snapshot.envRewardStep : state.envRewardStep;
    var envRewardEpisode =
      snapshot.envRewardEpisode !== undefined ? snapshot.envRewardEpisode : state.envRewardEpisode;
    var attempts = snapshot.attempts !== undefined ? snapshot.attempts : state.attempts;
    var lastResetMethod =
      snapshot.lastResetMethod !== undefined ? snapshot.lastResetMethod : state.lastResetMethod;
    var runtimePaused = snapshot.runtimePaused !== undefined ? snapshot.runtimePaused : state.runtimePaused;
    var status = phase === "terminal" ? "terminal" : phase === "playing" ? "playing" : "paused";
    var visualPerturbations = T2D.visuals.sync(state);
    var perturbActive = visualPerturbations.active_any;
    var assets = getAssetContext();
    var rewardMetrics = buildRewardMetricPayload(envRewardStep, envRewardEpisode, coinsCollected, coinsMissed);

    return {
      schemaVersion: "2.0",
      gameId: GAME_ID,
      seed: getSeed(),
      timestampMs: Date.now(),
      gameTimeMs: Math.round(stepCount * FRAME_MS),
      status: status,
      paused: status === "paused" || runtimePaused,
      runtime_paused: runtimePaused,
      is_actionable: status === "paused" || status === "playing",
      terminal: {
        isTerminal: false,
        outcome: null,
        reason: null,
      },
      game_state: {
        score: rewardMetrics.primary_score,
        player: serializePlayer(playerX, playerY),
        environment: {
          logical_width: LOGICAL_WIDTH,
          logical_height: LOGICAL_HEIGHT,
          road_left: ROAD_LEFT,
          road_right: ROAD_RIGHT,
          road_width: ROAD_WIDTH,
          scene_layout: state.sceneLayout,
          lane_count: LANE_COUNT,
          lane_positions: lanePositions.slice(),
          perturb: state.config.perturb || "none",
          perturb_active: perturbActive,
          visual_perturbations: visualPerturbations,
          difficulty: state.config.difficulty,
          asset_pack: RoadScene.pack,
          scene_version: RoadScene.version,
          asset: assets.payload(),
          difficulty_choices: state.config.difficultyChoices ? state.config.difficultyChoices.slice() : null,
          rand_init_pos: state.config.randInitPos,
          collection_mode: true,
          coin_reward: rewardConfig.constants.coinReward,
          coin_size: COIN_SIZE,
          spawn_probability: getSpawnProbability(),
          coin_spawn_probability: getSpawnProbability(),
          coin_spawn_min_interval_ms: MIN_SPAWN_INTERVAL_MS,
          coin_speed_multiplier: getCoinSpeedMultiplier(),
          coin_speed_px_per_step: getCoinSpeed(),
          player_shape: "rect",
          coin_shape: "circle",
        },
        entities: serializeOpponents(opponents),
      },
      metrics: {
        env_reward_step: rewardMetrics.env_reward_step,
        env_reward_episode: rewardMetrics.env_reward_episode,
        primary_positive_score: rewardMetrics.primary_positive_score,
        primary_penalty_score: rewardMetrics.primary_penalty_score,
        primary_score: rewardMetrics.primary_score,
        coins_collected: coinsCollected,
        coins_visible: opponents.length,
        coins_missed: coinsMissed,
        distance_px: distancePx,
        coin_spawn_probability: getSpawnProbability(),
        coin_spawn_min_interval_ms: MIN_SPAWN_INTERVAL_MS,
        coin_speed_px_per_step: getCoinSpeed(),
        step_count: stepCount,
        episode_count: attempts,
        rand_init_pos: state.config.randInitPos,
      },
      debug: {
        last_reset_method: lastResetMethod,
        rand_init_pos: state.config.randInitPos,
        visual_perturbations: visualPerturbations,
        url_search: window.location.search || "",
      },
    };
  }

  function detectCollision() {
    var kept = [];
    for (var i = 0; i < state.opponents.length; i += 1) {
      var opponent = state.opponents[i];
      if (
        state.playerX < opponent.x + COIN_SIZE &&
        state.playerX + CAR_WIDTH > opponent.x &&
        state.playerY < opponent.y + COIN_SIZE &&
        state.playerY + CAR_HEIGHT > opponent.y
      ) {
        state.coinsCollected += 1;
        Core.reward.add(state, rewardConfig.constants.coinReward);
      } else {
        kept.push(opponent);
      }
    }
    state.opponents = kept;
    return false;
  }

  function stepSimulation() {
    if (state.phase !== "playing" || state.runtimePaused) {
      return false;
    }

    state.envRewardStep = 0;
    movePlayer(deriveActionFromKeys());
    spawnOpponentIfNeeded();
    moveOpponents();
    state.distancePx += getCoinSpeed();
    state.stepCount += 1;
    detectCollision();
    return true;
  }


  function render() {
    T2D.visuals.sync(state);
    presentation.render(state, getAssetContext());
    view.render();
    if (game && game.infoPanel) game.infoPanel.update();
  }

  function renderGameToText() {
    var snapshot = buildStateSnapshot();
    return JSON.stringify({
      coordinate_system: "origin=(0,0) top-left, +x right, +y down",
      seed: snapshot.seed,
      status: snapshot.status,
      terminal: snapshot.terminal,
      player: snapshot.game_state.player,
      coins: snapshot.game_state.entities,
      metrics: snapshot.metrics,
      environment: {
        logical_width: snapshot.game_state.environment.logical_width,
        logical_height: snapshot.game_state.environment.logical_height,
        road_left: snapshot.game_state.environment.road_left,
        road_right: snapshot.game_state.environment.road_right,
        lane_positions: snapshot.game_state.environment.lane_positions,
        perturb: snapshot.game_state.environment.perturb,
        perturb_active: snapshot.game_state.environment.perturb_active,
        visual_perturbations: snapshot.game_state.environment.visual_perturbations,
        asset_pack: snapshot.game_state.environment.asset_pack,
        asset: snapshot.game_state.environment.asset,
        difficulty: snapshot.game_state.environment.difficulty,
        rand_init_pos: snapshot.game_state.environment.rand_init_pos,
        coin_spawn_probability: snapshot.game_state.environment.coin_spawn_probability,
        coin_speed_multiplier: snapshot.game_state.environment.coin_speed_multiplier,
        coin_speed_px_per_step: snapshot.game_state.environment.coin_speed_px_per_step,
        player_shape: snapshot.game_state.environment.player_shape,
        coin_shape: snapshot.game_state.environment.coin_shape,
      },
    });
  }

  function getStatePayload() {
    return buildStateSnapshot();
  }

  function getObservationFromSnapshot(snapshot) {
    var gameState = snapshot.game_state || {};
    var environment = gameState.environment || {};
    return {
      player: gameState.player || null,
      coins: gameState.entities || [],
      road: {
        logical_width: environment.logical_width,
        logical_height: environment.logical_height,
        road_left: environment.road_left,
        road_right: environment.road_right,
        lane_count: environment.lane_count,
        lane_positions: environment.lane_positions || [],
      },
      metrics: snapshot.metrics || {},
    };
  }

  function getObservation() {
    return getObservationFromSnapshot(getStatePayload());
  }

  function normalizeAction(action) {
    action = action || {};
    var actionId = Core.actions.readId(action);
    var steer = 0;
    if (Core.actions.hasKey(action, ["ArrowLeft", "a", "KeyA"])) steer -= 1;
    if (Core.actions.hasKey(action, ["ArrowRight", "d", "KeyD"])) steer += 1;
    steer = U.math.clamp(steer, -1, 1);
    return {
      id: actionId || "wait",
      args: {},
      left: steer < -0.1,
      right: steer > 0.1,
      steer: steer,
    };
  }

  function setControls(controls) {
    state.keys.left = controls.left;
    state.keys.right = controls.right;
  }

  function clearTransientControls() {
    state.keys.left = false;
    state.keys.right = false;
  }

  function buildStepInfo(snapshot, stepOptions, controls) {
    var info = {
      action: { type: "game_step_action", id: controls.id, args: controls.args || {} },
      durationMs: stepOptions.durationMs,
      source: stepOptions.source,
      status: snapshot.status,
    };
    var metrics = snapshot.metrics || {};
    Object.keys(metrics).forEach(function (key) {
      info[key] = metrics[key];
    });
    if (snapshot.terminal && snapshot.terminal.isTerminal) {
      info.outcome = snapshot.terminal.outcome;
      info.reason = snapshot.terminal.reason;
      info.terminal = snapshot.terminal;
    }
    return info;
  }

  function applyAction(controls, context) {
    setControls(controls);
    if (state.phase === "paused" && !state.runtimePaused) {
      activateFromPause(0, context.stepOptions.source + "_step");
    }
  }

  function advanceSimulation(ms) {
    var snapshot = advanceTime(ms, { render: false });
    clearTransientControls();
    return snapshot;
  }

  function resetGym(options) {
    beginEpisode(options || {}, "inplace_reset");
    var snapshot = buildStateSnapshot();
    return {
      observation: getObservationFromSnapshot(snapshot),
      reward: 0,
      done: false,
      info: buildStepInfo(snapshot, { durationMs: 0, source: "reset" }, { id: "reset", args: {} }),
    };
  }

  function advanceTime(ms, options) {
    var duration = Number(ms);
    if (!Number.isFinite(duration) || duration <= 0) {
      duration = FRAME_MS;
    }
    var result = ensureSimulationRunner().advance(duration, { render: false });
    if (!options || options.render !== false) render();
    var snapshot = getStatePayload();
    snapshot.debug = snapshot.debug || {};
    snapshot.debug.advanceSteps = result.steps;
    snapshot.debug.advanceDurationMs = duration;
    return snapshot;
  }

  function ensureSimulationRunner() {
    if (simulationRunner) return simulationRunner;
    simulationRunner = Core.createFixedStepRunner({
      game: state,
      stepMs: FRAME_MS,
      maxFrameDeltaMs: 100,
      update: function update() { return stepSimulation(); },
      render: render,
      isActive: function isActive() { return !state.runtimePaused && state.phase === "playing"; },
    });
    return simulationRunner;
  }

  function keyToAction(key) {
    if (key === "ArrowLeft" || key === "KeyA") return 1;
    if (key === "ArrowRight" || key === "KeyD") return 2;
    return 0;
  }

  function onKeyChange(event, isDown) {
    var key = event.code || event.key;
    var action = keyToAction(key);

    if (state.runtimePaused) {
      if (action === 1 || action === 2 || key === "Space" || key === "Enter") {
        event.preventDefault();
      }
      return;
    }

    if (action === 1) {
      state.keys.left = isDown;
      if (isDown && state.phase === "paused") {
        activateFromPause(1, "manual_start");
      }
      event.preventDefault();
      return;
    }

    if (action === 2) {
      state.keys.right = isDown;
      if (isDown && state.phase === "paused") {
        activateFromPause(2, "manual_start");
      }
      event.preventDefault();
      return;
    }

    if (isDown && key === "KeyF") {
      return;
    }

    if (isDown && state.phase === "paused") {
      activateFromPause(0, "manual_start");
      event.preventDefault();
    }
  }

  window.addEventListener("keydown", function (event) {
    onKeyChange(event, true);
  });
  window.addEventListener("keyup", function (event) {
    onKeyChange(event, false);
  });

  function getPauseState() {
    return {
      ok: true,
      source: "game",
      paused: state.runtimePaused,
      runtime_paused: state.runtimePaused,
    };
  }

  function pauseRuntime() {
    if (!state.runtimePaused) {
      state.runtimePaused = true;
      state.keys.left = false;
      state.keys.right = false;
      if (simulationRunner) simulationRunner.resetClock();
    }
    render();
    return getPauseState();
  }

  function resumeRuntime() {
    if (state.runtimePaused) {
      state.runtimePaused = false;
      if (simulationRunner) simulationRunner.resetClock();
    }
    render();
    return getPauseState();
  }

  async function start() {
    var bootConfig = readUrlConfig();
    await T2D.assets.preload(RoadScene.pack, ASSET_REQUIREMENTS);
    view = await T2D.createStage(canvas, { width: LOGICAL_WIDTH, height: LOGICAL_HEIGHT, background: 0xffffff });
    if (!view) throw new Error("Three.js 2D engine unavailable");
    presentation = RoadScene.create(view, createAsset, {
      left: ROAD_LEFT, right: ROAD_RIGHT, width: ROAD_WIDTH,
      carWidth: CAR_WIDTH, carHeight: CAR_HEIGHT, coinSize: COIN_SIZE,
    });
    game = {
      get currentConfig() { return state.config; },
      get seedDomains() { return state.seedDomains; },
      get domainEpisode() { return state.domainEpisode; },
      get perturbationContract() { return state.perturbationContract; },
      get domainState() { return state.domainState; },
      get controlResponse() { return state.controlResponse; },
      get rng() { return state.rng; },
      get envRewardStep() { return state.envRewardStep; },
      set envRewardStep(value) { state.envRewardStep = value; },
      get envRewardEpisode() { return state.envRewardEpisode; },
      set envRewardEpisode(value) { state.envRewardEpisode = value; },
      initFromAPI: function (options) {
        return beginEpisode(options || {}, "init");
      },
      resetFromAPI: function (options) {
        return beginEpisode(options || {}, "inplace_reset");
      },
      getState: function () {
        return getStatePayload();
      },
      advanceTime: advanceTime,
      render_game_to_text: renderGameToText,
      getConfigFromUrl: readUrlConfig,
      getSeed: getSeed,
      getObservation: getObservation,
      resetGym: resetGym,
      normalizeAction: normalizeAction,
      applyAction: applyAction,
      advanceSimulation: advanceSimulation,
      render: render,
      buildStepInfo: buildStepInfo,
      pause: pauseRuntime,
      resume: resumeRuntime,
      getPauseState: getPauseState,
      getGameSpeedState: function () {
        return {
          isPaused: state.runtimePaused,
        };
      },
    };
    Core.lifecycle.bindResetKeys(game);
    Core.createRuntime({
      game: game,
      presentation: {
        title: "2D Lane Driving",
        controls: "Left/right arrows or A/D steer. Collect coins across four lanes; release keys to hold your lateral position.",
        read: function readPresentation() {
          return {
            status: state.runtimePaused ? "paused" : state.phase,
            primaryScore: rewardConfig.computePrimaryScore(state),
            stepReward: state.envRewardStep,
            episodeReward: state.envRewardEpisode,
            difficulty: state.config.difficulty,
            seed: getSeed(),
            perturbation: Core.perturbations.label(state),
            details: [["Coins", state.coinsCollected], ["Missed", state.coinsMissed],
              ["Coins visible", state.opponents.length], ["Distance", Math.round(state.distancePx) + " px"]],
          };
        },
      },
      renderer: T2D,
      gameId: "base_2d_drive_lane_collect",
      defaultSeed: 42,
      maxDifficulty: 3,
      defaultStepMs: 200,
      assets: { engine: T2D.assets, requiredAssetIds: ASSET_REQUIREMENTS },
      capabilities: { supports_rand_init_pos: true },
      renderGameToText: renderGameToText,
    });
    beginEpisode(bootConfig, "boot", bootConfig.autostart);
    canvas.focus();
    ensureSimulationRunner().start();
  }

  Core.lifecycle.boot(start);
})();
