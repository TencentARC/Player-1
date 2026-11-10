(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var G3D = window.BaseGamelet3D;
  var rewardConfig = window.Base3DAimRewardConfig;
  var Scene = window.Base3DAimScene;
  var GAME_ID = "base_3d_aim";
  var LOGIC_WIDTH = 640;
  var LOGIC_HEIGHT = 640;
  var DISPLAY_WIDTH = G3D.viewport.baseWidth;
  var DISPLAY_HEIGHT = G3D.viewport.baseHeight;
  var STEP_MS = 1000 / 60;
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 5;
  var ASSET_PACK = "gym-range";
  var ASSET_REQUIREMENTS = Scene.assets;
  var FIXED_SENSITIVITY = G3D.input.CAMERA_SENSITIVITY;
  var TARGET_SPREAD = 1.32;
  var EASY_TARGET_RADIUS = 0.081;
  var HARD_TARGET_RADIUS = 0.065;
  var EASY_TARGET_WORLD_RADIUS = 0.34;
  var SCENE_LAYOUT_TEMPLATES = Object.freeze(["side_bays", "overhead_frames", "backstop_panels"]);
  var SCENE_LAYOUT_NAMES = Object.freeze(["open_range"].concat(SCENE_LAYOUT_TEMPLATES));
  var PERTURBATION_CONTRACT = Core.perturbations.defineContract({
    game_id: GAME_ID,
    control_response: {
      look_gain_scale: Core.controlResponse.ranges.look_gain_scale,
    },
    capabilities: {
      appearance: ["palette", "lighting", "background", "assets"],
      camera: ["orientation", "projection"],
      scene: ["layout", "entity_spawn"],
    },
    samplers: {
      camera: {
        orientation: Core.perturbations.cameraOrientationSampler("aiming"),
      },
      scene: {
        layout: Core.perturbations.templateSampler("open_range", SCENE_LAYOUT_TEMPLATES),
      },
    },
    validators: {
      scene: {
        layout: Core.perturbations.templateValidator(SCENE_LAYOUT_NAMES),
      },
    },
  });

  var canvas = document.getElementById("display");


  function targetRadiusForDifficulty(difficulty) {
    var denominator = Math.max(1, MAX_DIFFICULTY - 1);
    var t = (U.math.clamp(Number(difficulty) || DEFAULT_DIFFICULTY, 1, MAX_DIFFICULTY) - 1) / denominator;
    return EASY_TARGET_RADIUS + (HARD_TARGET_RADIUS - EASY_TARGET_RADIUS) * t;
  }

  function targetWorldRadiusForHitRadius(targetRadius) {
    return EASY_TARGET_WORLD_RADIUS * (targetRadius / EASY_TARGET_RADIUS);
  }

  function Base3DAim() {
    this.defaults = { seed: DEFAULT_SEED, difficulty: DEFAULT_DIFFICULTY, maxDifficulty: MAX_DIFFICULTY };
    this.urlConfig = Core.config.readUrl(this.defaults);
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

  Base3DAim.prototype.setup3D = function setup3D() {
    this.world3d = G3D.createWorld(canvas, {
      width: DISPLAY_WIDTH,
      height: DISPLAY_HEIGHT,
      fov: 70,
      clearColor: 0xa5bcc3,
      visualProfile: "stylized",
      exposure: 1.03,
      sunPosition: [-3, 4.25, 1],
      eyeHeight: 1.35,
      ambient: 0.74,
      sun: 1.85,
    });
    this.sceneMeshes = {};
    G3D.viewport.install(this, { canvas: canvas, world: this.world3d, baseWidth: DISPLAY_WIDTH, baseHeight: DISPLAY_HEIGHT, baseFov: 70 });
  };

  Base3DAim.prototype.beginEpisode = function beginEpisode(options, countReset, flags) {
    var episodeFlags = flags || {};
    var normalized = Core.config.normalizeOptions(options || {}, MAX_DIFFICULTY);
    var config = Core.config.mergeEpisode(this.urlConfig, normalized);
    this.currentConfig = Core.config.cloneEpisode(config);
    Core.terminal.clear(this, episodeFlags);
    Core.lifecycle.resetEpisode(this);
    Core.reward.resetEpisode(this);
    Core.domains.beginEpisode(this, config, PERTURBATION_CONTRACT, DEFAULT_SEED);
    this.sceneLayout = Core.domains.sample(this, "scene", "layout", { template: "open_range" });
    this.difficulty = config.difficulty;
    G3D.visuals.configure(this, config, {
      defaultAssetPack: ASSET_PACK,
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
    });
    this.sensitivity = FIXED_SENSITIVITY * this.controlResponse.applied.look_gain_scale;
    var targetRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var cameraOrientation = Core.domains.sample(this, "camera", "orientation", {
      yaw_offset_radians: 0,
      pitch_offset_radians: 0,
    });
    this.aimSceneYaw = targetRng.range(-0.225, 0.225);
    this.aimScenePitch = targetRng.range(-0.08, 0.08);
    this.viewYaw = U.math.normalizeAngle(
      this.aimSceneYaw + cameraOrientation.yaw_offset_radians
    );
    this.viewPitch = U.math.clamp(
      this.aimScenePitch + cameraOrientation.pitch_offset_radians,
      -0.72,
      0.72
    );
    this.targetYaw = 0;
    this.targetPitch = 0;
    this.targetDistance = 5;
    this.targetVelocityYaw = 0;
    this.targetRadius = targetRadiusForDifficulty(this.difficulty);
    this.targetWorldRadius = targetWorldRadiusForHitRadius(this.targetRadius);
    this.hits = 0;
    this.shots = 0;
    this.misses = 0;
    this.stepCount = 0;
    this.gameTimeMs = 0;
    this.lastHit = false;
    this.lastShot = null;
    this.lastAction = "reset";
    this.mode = config.autostart ? "playing" : "paused";
    this.terminal = { isTerminal: false, outcome: null, reason: null };
    this.spawnTarget();
    var initialization = window.PlayerOneRecoveryInitialization;
    var recovery = initialization.create(this.seed, "centered_view");
    this.recoveryInitialization = recovery.state;
    var yawOffset = initialization.centeredNormal(recovery.rng, Math.PI / 4, Math.PI * 3 / 4);
    this.viewYaw = U.math.normalizeAngle(this.viewYaw + yawOffset);
    this.recoveryInitialization.distribution = "truncated_normal";
    this.recoveryInitialization.yaw_stddev_radians = Math.PI / 4;
    this.recoveryInitialization.yaw_limit_radians = Math.PI * 3 / 4;
    this.recoveryInitialization.yaw_offset_radians = yawOffset;
    if (countReset) this.runtime.resetCount += 1;
    this.runtime.episodeCount += 1;
    this.runtime.lastResetMethod = countReset ? "inplace_reset" : "init";
    this.rebuildScene3D();
    this.syncScene();
    this.updateBestMetrics();
    this.render();
    return { accepted: normalized, applied: config, notes: [] };
  };

  Base3DAim.prototype.bindInput = function bindInput() {
    this.inputController = G3D.input.createController(this, {
      canvas: canvas,
      includeMovement: false,
      onLook: function onLook(dx, dy) { this.applyMouse(dx, dy); },
      onMouseDown: function onMouseDown(event) {
        if (event.button === 0) this.fire();
      },
    });
    var app = document.getElementById("app");
    if (app) app.focus();
  };

  Base3DAim.prototype.ensureSimulationRunner = function ensureSimulationRunner() {
    if (this.simulationRunner) return this.simulationRunner;
    var self = this;
    this.simulationRunner = Core.createFixedStepRunner({
      game: this,
      stepMs: STEP_MS,
      update: function update(stepMs) { self.update(stepMs); },
      render: function render() { self.render(); },
      isActive: function isActive() { return self.mode === "playing" && !self.paused; },
    });
    return this.simulationRunner;
  };

  Base3DAim.prototype.startLoop = function startLoop() {
    this.ensureSimulationRunner().start();
  };

  Base3DAim.prototype.pause = function pause() {
    return Core.lifecycle.pause(this);
  };

  Base3DAim.prototype.resume = function resume() {
    return Core.lifecycle.resume(this);
  };

  Base3DAim.prototype.cameraLookOptions = function cameraLookOptions() {
    return {
      yawKey: "viewYaw",
      pitchKey: "viewPitch",
      sensitivity: this.sensitivity,
      pitchMin: -1.1,
      pitchMax: 1.1,
    };
  };

  Base3DAim.prototype.applyMouse = function applyMouse(dx, dy) {
    if (this.terminal.isTerminal) return;
    if (this.mode === "paused") this.mode = "playing";
    G3D.input.applyPointerLook(this, dx, dy, this.cameraLookOptions());
    if (Math.abs(dx) + Math.abs(dy) > 80) this.overRotations += 1;
    this.lastAction = "mouse(" + dx.toFixed(1) + "," + dy.toFixed(1) + ")";
    this.syncScene();
  };

  Base3DAim.prototype.applyRelativePointerInput = function applyRelativePointerInput(pointerInput) {
    if (this.terminal.isTerminal || !pointerInput) return;
    if (this.mode === "paused") this.mode = "playing";
    G3D.input.applyRelativePointerInput(this, pointerInput, this.cameraLookOptions());
    if (Math.abs(pointerInput.dx) + Math.abs(pointerInput.dy) > 125) this.overRotations += 1;
    this.lastAction = "relative_pointer(" + pointerInput.dx + "," + pointerInput.dy + ")";
    this.syncScene();
  };

  Base3DAim.prototype.errorPayload = function errorPayload() {
    var yawError = U.math.normalizeAngle(this.targetYaw - this.viewYaw);
    var pitchError = this.targetPitch - this.viewPitch;
    var visible = Math.abs(yawError) < 0.9 && Math.abs(pitchError) < 0.65;
    return { yawError: yawError, pitchError: pitchError, visible: visible };
  };

  Base3DAim.prototype.isTargetCentered = function isTargetCentered(error) {
    return error.visible && Math.abs(error.yawError) <= this.targetRadius && Math.abs(error.pitchError) <= this.targetRadius;
  };

  Base3DAim.prototype.rebuildScene3D = function rebuildScene3D() {
    if (!this.world3d) return;
    this.world3d.clear();
    this.rangeScene = Scene.build(this);
    this.sceneMeshes = { target: this.rangeScene.target };
  };

  Base3DAim.prototype.syncScene = function syncScene() {
    if (!this.world3d || !this.rangeScene) return;
    this.rangeScene.sync(this.gameTimeMs);
    this.world3d.setLookCamera({ yaw: this.viewYaw, pitch: this.viewPitch, eyeHeight: 1.35 });
    this.world3d.camera.updateMatrixWorld(true);
  };

  Base3DAim.prototype.addReward = function addReward(value) {
    Core.reward.add(this, value);
  };

  Base3DAim.prototype.spawnTarget = function spawnTarget() {
    var targetRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    this.targetYaw = U.math.normalizeAngle(this.aimSceneYaw + targetRng.range(-TARGET_SPREAD / 2, TARGET_SPREAD / 2));
    this.targetPitch = U.math.clamp(this.aimScenePitch + targetRng.range(-0.26, 0.26), -0.72, 0.72);
    this.targetDistance = targetRng.range(4.8, 7.1);
    this.targetVelocityYaw = 0;
    this.syncScene();
  };

  Base3DAim.prototype.fire = function fire() {
    if (this.terminal.isTerminal) return;
    if (this.mode === "paused") this.mode = "playing";
    var error = this.errorPayload();
    this.shots += 1;
    var hit = this.isTargetCentered(error);
    this.lastShot = { hit: hit, timeMs: this.gameTimeMs };
    if (hit) {
      this.hits += 1;
      this.lastHit = true;
      this.addReward(rewardConfig.constants.hitReward);
      this.lastAction = "fire_hit";
      this.spawnTarget();
    } else {
      this.misses += 1;
      this.addReward(-rewardConfig.constants.missPenalty);
      this.lastHit = false;
      this.lastAction = "fire_miss";
    }
    this.updateBestMetrics();
    this.render();
  };

  Base3DAim.prototype.update = function update(deltaMs) {
    if (this.terminal.isTerminal || this.mode !== "playing") return;
    this.stepCount += 1;
    this.gameTimeMs += deltaMs;
    if (this.targetVelocityYaw) this.targetYaw = U.math.normalizeAngle(this.targetYaw + this.targetVelocityYaw * deltaMs);
    this.syncScene();
    this.updateBestMetrics();
  };

  Base3DAim.prototype.advanceSimulation = function advanceSimulation(ms) {
    this.ensureSimulationRunner().advance(ms, { render: false });
    return this.getStatePayload();
  };

  Base3DAim.prototype.advanceTime = function advanceTime(ms, render) {
    var state = this.advanceSimulation(ms);
    if (render !== false) this.render();
    return state;
  };

  Base3DAim.prototype.normalizeAction = function normalizeAction(action) {
    var normalized = G3D.input.readAction(action);
    return {
      id: normalized.id,
      args: normalized.args,
      pointerInput: normalized.pointerInput,
      fire: normalized.mouseLeft,
    };
  };

  Base3DAim.prototype.applyAction = function applyAction(normalized) {
    this.applyRelativePointerInput(normalized.pointerInput);
    if (normalized.fire) this.fire();
    if (this.mode === "paused") this.mode = "playing";
  };

  Base3DAim.prototype.buildStepInfo = function buildStepInfo(state, stepOptions, normalized) {
    var info = Core.terminal.withInfo(this, state, this.infoPayload());
    info.action = { type: "game_step_action", id: normalized.id, args: normalized.args };
    info.durationMs = stepOptions.durationMs;
    info.source = stepOptions.source;
    return info;
  };

  Base3DAim.prototype.resetGym = function resetGym(options) {
    this.resetFromAPI(options || {});
    return { observation: this.getObservation(), reward: 0, done: false, info: this.infoPayload() };
  };

  Base3DAim.prototype.getObservation = function getObservation() {
    var error = this.errorPayload();
    return {
      view: { yaw: this.viewYaw, pitch: this.viewPitch },
      target: { yaw: this.targetYaw, pitch: this.targetPitch, distance: this.targetDistance },
      error: error,
      hits: this.hits,
      shots: this.shots,
    };
  };

  Base3DAim.prototype.infoPayload = function infoPayload() {
    var error = this.errorPayload();
    var accuracy = this.shots > 0 ? this.hits / this.shots : 0;
    return {
      score: this.getPrimaryScore(),
      target_visible: error.visible,
      target_error_yaw: error.yawError,
      target_error_pitch: error.pitchError,
      hits: this.hits,
      shots: this.shots,
      misses: this.misses,
      accuracy: accuracy,
      env_reward_step: this.envRewardStep,
      env_reward_episode: this.envRewardEpisode,
      time_steps: this.stepCount,
      sensitivity: this.sensitivity,
    };
  };

  Base3DAim.prototype.getPrimaryScore = function getPrimaryScore() {
    return rewardConfig.computePrimaryScore(this.rewardMetrics());
  };

  Base3DAim.prototype.rewardMetrics = function rewardMetrics() {
    return { hits: this.hits, misses: this.misses };
  };

  Base3DAim.prototype.updateBestMetrics = function updateBestMetrics() {
    this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, this.getPrimaryScore());
  };

  Base3DAim.prototype.entityPayload = function entityPayload() {
    var viewport = this.viewportPayload();
    var screenX = viewport.width / 2;
    var screenY = viewport.height / 2;
    if (this.world3d && this.sceneMeshes.target) {
      var screen = this.world3d.project(this.sceneMeshes.target);
      screenX = screen.x;
      screenY = screen.y;
    } else {
      var error = this.errorPayload();
      screenX = ((U.math.clamp(error.yawError / 0.9, -1, 1) + 1) / 2) * viewport.width;
      screenY = ((1 - U.math.clamp(error.pitchError / 0.65, -1, 1)) / 2) * viewport.height;
    }
    return [
      { id: "camera", type: "camera", yaw: this.viewYaw, pitch: this.viewPitch },
      {
        id: "target",
        type: "target",
        yaw: this.targetYaw,
        pitch: this.targetPitch,
        distance: this.targetDistance,
        screen_x: screenX,
        screen_y: screenY,
        screen_norm_x: (screenX / viewport.width) * 2 - 1,
        screen_norm_y: 1 - (screenY / viewport.height) * 2,
      },
    ];
  };

  Base3DAim.prototype.visualPayload = function visualPayload() {
    return G3D.visuals.payload(this);
  };

  Base3DAim.prototype.getStatePayload = function getStatePayload() {
    var latched = Core.terminal.consume(this);
    if (latched) return latched;
    G3D.visuals.sync(this);
    var error = this.errorPayload();
    var accuracy = this.shots > 0 ? this.hits / this.shots : 0;
    var viewport = this.viewportPayload();
    return {
      schemaVersion: "2.0",
      gameId: GAME_ID,
      seed: this.seed,
      timestampMs: Date.now(),
      gameTimeMs: U.math.finiteNumber(this.gameTimeMs),
      status: this.terminal.isTerminal ? "terminal" : this.mode,
      paused: this.mode === "paused" || this.paused,
      runtime_paused: this.paused,
      is_actionable: !this.terminal.isTerminal && (this.mode === "paused" || this.mode === "playing"),
      terminal: { isTerminal: this.terminal.isTerminal, outcome: this.terminal.outcome, reason: this.terminal.reason },
      game_state: {
        score: this.getPrimaryScore(),
        level: null,
        player: { yaw: this.viewYaw, pitch: this.viewPitch },
        environment: {
          recovery_initialization: this.recoveryInitialization,
          phase: this.terminal.isTerminal ? "terminal" : this.mode,
          viewport_width: viewport.width,
          viewport_height: viewport.height,
          logic_width: viewport.width,
          logic_height: viewport.height,
          base_logic_width: LOGIC_WIDTH,
          base_logic_height: LOGIC_HEIGHT,
          fullscreen: viewport,
          camera_fov: viewport.fov,
          difficulty: this.difficulty,
          sensitivity: this.sensitivity,
          target_radius: this.targetRadius,
          target_world_radius: this.targetWorldRadius,
          scene_revision: Scene.revision,
          asset_pack: this.assetContext ? this.assetContext.id : null,
          asset: this.assetContext ? this.assetContext.payload() : null,
          scene_layout: this.sceneLayout,
          perturb_active: Core.perturbations.isActive(this),
          visual_perturbations: this.visualPayload(),
        },
        entities: this.entityPayload(),
      },
      metrics: {
        env_reward_step: this.envRewardStep,
        env_reward_episode: this.envRewardEpisode,
        primary_positive_score: rewardConfig.computePrimaryPositiveScore(this.rewardMetrics()),
        primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(this.rewardMetrics()),
        primary_score: this.getPrimaryScore(),
        target_visible: error.visible,
        target_error_yaw: error.yawError,
        target_error_pitch: error.pitchError,
        hits: this.hits,
        shots: this.shots,
        misses: this.misses,
        accuracy: accuracy,
        last_hit: this.lastHit,
        best_primary_score: this.bestMetrics.bestPrimaryScore,
        step_count: this.stepCount,
        episode_count: this.runtime.episodeCount,
        difficulty: this.difficulty,
      },
      debug: { mode: this.mode, last_action: this.lastAction, last_reset_method: this.runtime.lastResetMethod, reset_count: this.runtime.resetCount },
    };
  };

  Base3DAim.prototype.renderGameToText = function renderGameToText() {
    var error = this.errorPayload();
    var accuracy = this.shots > 0 ? this.hits / this.shots : 0;
    return JSON.stringify({
      coordinate_system: "camera yaw/pitch in radians; relative pointer input uses signed visible game displacement",
      status: this.mode,
      view: { yaw: this.viewYaw, pitch: this.viewPitch },
      target: { yaw: this.targetYaw, pitch: this.targetPitch, distance: this.targetDistance },
      error: error,
      progress: { hits: this.hits, shots: this.shots, misses: this.misses, accuracy: accuracy },
      rewards: {
        env_reward_step: this.envRewardStep,
        env_reward_episode: this.envRewardEpisode,
        primary_positive_score: rewardConfig.computePrimaryPositiveScore(this.rewardMetrics()),
        primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(this.rewardMetrics()),
        primary_score: this.getPrimaryScore(),
      },
      difficulty: this.difficulty,
      visual_perturbations: this.visualPayload(),
    });
  };


  Base3DAim.prototype.render = function render() {
    G3D.visuals.sync(this, { sceneReady: true });
    this.syncScene();
    if (!this.world3d) return;
    this.world3d.render();
    if (this.infoPanel) this.infoPanel.update();
  };

  Base3DAim.prototype.resetFromAPI = function resetFromAPI(options) { return this.beginEpisode(options || {}, true); };

  async function start() {
    await G3D.assets.preload(ASSET_PACK, ASSET_REQUIREMENTS);
    await document.fonts.ready;
    var game = new Base3DAim();
    await game.world3d.prepare();
    Core.createRuntime({
      game: game,
      presentation: {
        title: "3D Aiming",
        controls: "Move the mouse to aim. Left-click to shoot the active target.",
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
              ["Hits", game.hits],
              ["Shots", game.shots],
              ["Accuracy", (game.shots ? Math.round(game.hits / game.shots * 100) : 0) + "%"],
            ],
          };
        },
      },
      renderer: G3D,
      gameId: "base_3d_aim",
      defaultSeed: 42,
      maxDifficulty: 5,
      defaultStepMs: 200,
      assets: { engine: G3D.assets, requiredAssetIds: ASSET_REQUIREMENTS },
    });
  }

  Core.lifecycle.boot(start);
})();
