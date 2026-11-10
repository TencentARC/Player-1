(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var G3D = window.BaseGamelet3D;
  var RoomLevel = window.MovementRoomLevel;
  var Scene = window.MovementScene;
  var rewardConfig = window.Base3DMovementRewardConfig;
  var GAME_ID = "base_3d_movement";
  var LOGIC_WIDTH = 640;
  var LOGIC_HEIGHT = 640;
  var DISPLAY_WIDTH = G3D.viewport.baseWidth;
  var DISPLAY_HEIGHT = G3D.viewport.baseHeight;
  var STEP_MS = 1000 / 60;
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 5;
  var ASSET_REQUIREMENTS = Scene.assets;
  var ASSET_PACK = "gym-facility";
  var FLOOR_Y = 0;
  var EYE_HEIGHT = 1.65;
  var FIXED_SENSITIVITY = G3D.input.CAMERA_SENSITIVITY;
  var MOVE_SPEED = 6;
  var PLAYER_RADIUS = 0.24;
  var GOAL_RADIUS = 0.95;
  var PERTURBATION_CONTRACT = Core.perturbations.defineContract({
    game_id: GAME_ID,
    control_response: {
      look_gain_scale: Core.controlResponse.ranges.look_gain_scale,
      move_scale: Core.controlResponse.ranges.move_scale,
    },
    capabilities: {
      appearance: ["palette", "lighting", "background", "assets"],
      camera: ["orientation", "projection", "rig"],
      scene: ["layout", "player_spawn", "entity_spawn"],
    },
    samplers: {
      camera: {
        orientation: Core.perturbations.cameraOrientationSampler("navigation"),
      },
      scene: {
        layout: RoomLevel.sample,
      },
    },
  });

  var canvas = document.getElementById("display");


  function distanceXZ(a, b) {
    var dx = a.x - b.x;
    var dz = a.z - b.z;
    return Math.sqrt(dx * dx + dz * dz);
  }

  function Base3DMovement() {
    this.defaults = { seed: DEFAULT_SEED, difficulty: DEFAULT_DIFFICULTY, maxDifficulty: MAX_DIFFICULTY };
    this.urlConfig = Core.config.readUrl(this.defaults);
    this.controls = { forward: false, back: false, left: false, right: false };
    this.paused = false;
    this.runtime = { resetCount: 0, episodeCount: 0, lastResetMethod: null };
    this.bestMetrics = { bestPrimaryScore: 0 };
    Core.terminal.initialize(this);
    this.setup3D();
    this.createAsset = G3D.assets.bindGame(this);
    this.bindInput();
    Core.lifecycle.bindResetKeys(this);
    this.beginEpisode({}, false);
  }

  Base3DMovement.prototype.setup3D = function setup3D() {
    this.world3d = G3D.createWorld(canvas, {
      width: DISPLAY_WIDTH,
      height: DISPLAY_HEIGHT,
      fov: 70,
      visualProfile: "stylized",
      clearColor: 0xaac6d5,
      eyeHeight: EYE_HEIGHT,
      ambient: 1.25,
      sun: 2.6,
      sunPosition: [-5, 12, -1],
    });
    G3D.viewport.install(this, { canvas: canvas, world: this.world3d, baseWidth: DISPLAY_WIDTH, baseHeight: DISPLAY_HEIGHT, baseFov: 70 });
  };

  Base3DMovement.prototype.beginEpisode = function beginEpisode(options, countReset, flags) {
    var episodeFlags = flags || {};
    var normalized = Core.config.normalizeOptions(options || {}, MAX_DIFFICULTY);
    var config = Core.config.mergeEpisode(this.urlConfig, normalized);
    this.currentConfig = Core.config.cloneEpisode(config);
    Core.terminal.clear(this, episodeFlags);
    Core.lifecycle.resetEpisode(this, { controls: { forward: false, back: false, left: false, right: false } });
    Core.reward.resetEpisode(this);
    Core.domains.beginEpisode(this, config, PERTURBATION_CONTRACT, DEFAULT_SEED);
    this.sceneLayout = Core.domains.sample(this, "scene", "layout", RoomLevel.sample({ profile: "default" }));
    this.map = RoomLevel.build(this.sceneLayout);
    this.layoutObstacles = this.map.colliders;
    this.difficulty = config.difficulty;
    G3D.visuals.configure(this, config, {
      defaultAssetPack: ASSET_PACK,
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
    });
    var spawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var playerRng = Core.domains.isActive(this, "scene")
      ? Core.domains.gameplayRng(this, "scene", "player_spawn")
      : spawnRng;
    var cameraRng = Core.domains.baselineRng(this);
    this.x = this.map.spawn.x + playerRng.range(-0.35, 0.35);
    this.z = this.map.spawn.z + playerRng.range(-0.2, 0.2);
    var legacyYaw = cameraRng.range(-0.11, 0.11);
    var legacyPitch = cameraRng.range(-0.04, 0.04);
    var cameraOrientation = Core.domains.sample(this, "camera", "orientation", {
      yaw_offset_radians: 0,
      pitch_offset_radians: 0,
    });
    this.yaw = legacyYaw + cameraOrientation.yaw_offset_radians;
    this.pitch = legacyPitch + cameraOrientation.pitch_offset_radians;
    this.sensitivity = FIXED_SENSITIVITY * this.controlResponse.applied.look_gain_scale;
    this.goalsReached = 0;
    this.lastGoalReached = false;
    this.collisions = 0;
    this.blockedLastStep = false;
    this.stepCount = 0;
    this.gameTimeMs = 0;
    this.lastAction = "reset";
    this.mode = config.autostart ? "playing" : "paused";
    this.terminal = { isTerminal: false, outcome: null, reason: null };
    this.controls = { forward: false, back: false, left: false, right: false };
    this.spawnGoal();
    this.applyRecoveryInitialization();
    if (countReset) this.runtime.resetCount += 1;
    this.runtime.episodeCount += 1;
    this.runtime.lastResetMethod = countReset ? "inplace_reset" : "init";
    this.rebuildScene3D();
    this.syncScene3D();
    this.updateBestMetrics();
    this.render();
    return { accepted: normalized, applied: config, notes: [] };
  };

  Base3DMovement.prototype.applyRecoveryInitialization = function applyRecoveryInitialization() {
    var initialization = window.PlayerOneRecoveryInitialization;
    var recovery = initialization.create(this.seed, "continuous_navigation");
    this.recoveryInitialization = recovery.state;
    var rng = recovery.rng;
    var origin = { x: this.x, z: this.z };
    var originalGoal = { x: this.goal.x, z: this.goal.z };
    function alongPath(path, progress) {
      var remaining = window.PlayerOneConnectedLayout.pathLength(path) * progress;
      for (var i = 1; i < path.length; i += 1) {
        var a = path[i - 1], b = path[i];
        var length = Math.hypot(b.x - a.x, b.z - a.z);
        if (remaining <= length) {
          var t = length ? remaining / length : 0;
          return { x: a.x + (b.x - a.x) * t, z: a.z + (b.z - a.z) * t };
        }
        remaining -= length;
      }
      return path[path.length - 1];
    }
    var first = rng.randint(0, this.map.blockers.length);
    for (var index = 0; index < this.map.blockers.length; index += 1) {
      var barrier = this.map.blockers[(first + index) % this.map.blockers.length];
      var lateral = rng.range(-0.15, 0.15) * barrier.width;
      var start = { x: barrier.x + lateral, z: barrier.z + barrier.depth / 2 + rng.range(0.7, 1.0) };
      var goal = { x: barrier.x - lateral, z: barrier.z - barrier.depth / 2 - rng.range(1.2, 1.5) };
      if (!this.map.contains(start.x, start.z, PLAYER_RADIUS + 0.1)
          || !this.map.contains(goal.x, goal.z, GOAL_RADIUS + 0.15)
          || this.map.segmentClear(start, goal, PLAYER_RADIUS)
          || this.map.findPath(start, goal, PLAYER_RADIUS + 0.1).length < 3) continue;
      var playerPath = this.map.findPath(origin, start, PLAYER_RADIUS + 0.1);
      var goalPath = this.map.findPath(originalGoal, goal, GOAL_RADIUS + 0.15);
      if (!playerPath.length || !goalPath.length) continue;
      for (var attempt = 0; attempt < 32; attempt += 1) {
        // Beta(1, 3): highest density at the usual start, tapering continuously
        // toward the near-obstacle endpoint. Travel along collision-free paths.
        var progress = 1 - Math.cbrt(1 - rng.next());
        var playerPoint = alongPath(playerPath, progress), goalPoint = alongPath(goalPath, progress);
        if (Math.hypot(goalPoint.x - playerPoint.x, goalPoint.z - playerPoint.z) < 2) continue;
        var yawOffset = initialization.centeredNormal(rng, Math.PI / 6, Math.PI / 2);
        this.x = playerPoint.x;
        this.z = playerPoint.z;
        this.yaw = U.math.normalizeAngle(this.yaw + yawOffset
          + progress * Math.atan2(goalPoint.x - playerPoint.x, playerPoint.z - goalPoint.z));
        this.goal = { id: "goal", x: goalPoint.x, z: goalPoint.z, r: GOAL_RADIUS };
        Object.assign(this.recoveryInitialization, {
          distribution: "continuous_path_beta_1_3",
          progress: progress,
          yaw_stddev_radians: Math.PI / 6,
          yaw_limit_radians: Math.PI / 2,
          yaw_offset_radians: yawOffset,
          barrier_id: barrier.id,
          start: playerPoint,
          goal: goalPoint,
        });
        return;
      }
    }
    throw new Error("Navigation layout has no valid continuous initial state");
  };

  Base3DMovement.prototype.bindInput = function bindInput() {
    this.inputController = G3D.input.createController(this, {
      canvas: canvas,
      onLook: function onLook(dx, dy) { this.applyMouse(dx, dy); },
    });
    var app = document.getElementById("app");
    if (app) app.focus();
  };

  Base3DMovement.prototype.ensureSimulationRunner = function ensureSimulationRunner() {
    if (this.simulationRunner) return this.simulationRunner;
    var self = this;
    this.simulationRunner = Core.createFixedStepRunner({
      game: this,
      stepMs: STEP_MS,
      update: function update(stepMs) { self.update(stepMs / 1000); },
      render: function render() { self.render(); },
      isActive: function isActive() { return self.mode === "playing" && !self.paused; },
    });
    return this.simulationRunner;
  };

  Base3DMovement.prototype.startLoop = function startLoop() {
    this.ensureSimulationRunner().start();
  };

  Base3DMovement.prototype.pause = function pause() {
    return Core.lifecycle.pause(this);
  };

  Base3DMovement.prototype.resume = function resume() {
    return Core.lifecycle.resume(this);
  };

  Base3DMovement.prototype.cameraLookOptions = function cameraLookOptions() {
    return {
      sensitivity: this.sensitivity,
      pitchMin: -1.05,
      pitchMax: 1.05,
    };
  };

  Base3DMovement.prototype.applyMouse = function applyMouse(dx, dy) {
    if (this.terminal.isTerminal) return;
    if (this.mode === "paused") this.mode = "playing";
    G3D.input.applyPointerLook(this, dx, dy, this.cameraLookOptions());
    this.lastAction = "relative_pointer(" + dx.toFixed(1) + "," + dy.toFixed(1) + ")";
    this.syncScene3D();
  };

  Base3DMovement.prototype.applyRelativePointerInput = function applyRelativePointerInput(pointerInput) {
    if (this.terminal.isTerminal || !pointerInput) return;
    if (this.mode === "paused") this.mode = "playing";
    G3D.input.applyRelativePointerInput(this, pointerInput, this.cameraLookOptions());
    this.lastAction = "relative_pointer(" + pointerInput.dx + "," + pointerInput.dy + ")";
    this.syncScene3D();
  };

  Base3DMovement.prototype.spawnGoal = function spawnGoal() {
    var player = { x: this.x, z: this.z };
    var candidates = this.map.targets.filter(function separated(point) {
      return distanceXZ(point, player) >= 4;
    });
    if (this.goalsReached === 0) {
      var visibleCandidates = candidates.filter(function ahead(point) {
        var forward = player.z - point.z;
        return forward > 0 && Math.abs(point.x - player.x) < forward * 0.35;
      });
      if (visibleCandidates.length) candidates = visibleCandidates;
    }
    if (!candidates.length) throw new Error("Movement room has no separated goal spawn");
    var spawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var point = candidates[spawnRng.randint(0, candidates.length)];
    this.goal = { id: "goal", x: point.x, z: point.z, r: GOAL_RADIUS };
  };

  Base3DMovement.prototype.distanceToGoal = function distanceToGoal() {
    return Math.max(0, distanceXZ({ x: this.x, z: this.z }, this.goal) - this.goal.r);
  };

  Base3DMovement.prototype.addReward = function addReward(value) {
    Core.reward.add(this, value);
  };

  Base3DMovement.prototype.reachGoal = function reachGoal() {
    this.goalsReached += 1;
    this.lastGoalReached = true;
    this.addReward(rewardConfig.constants.goalReward);
    this.lastAction = "goal_reached";
    this.spawnGoal();
  };

  Base3DMovement.prototype.update = function update(dt) {
    if (this.terminal.isTerminal || this.mode !== "playing") return;
    this.lastGoalReached = false;
    this.stepCount += 1;
    this.gameTimeMs += dt * 1000;
    var move = G3D.input.moveDelta(this.yaw - Math.PI / 2, this.controls, MOVE_SPEED * this.controlResponse.applied.move_scale, dt);
    if (move.x || move.z) this.tryMove(move.x, move.z);
    else this.blockedLastStep = false;

    if (this.distanceToGoal() === 0) this.reachGoal();

    this.syncScene3D();
    this.updateBestMetrics();
  };

  Base3DMovement.prototype.tryMove = function tryMove(dx, dz) {
    var rawX = this.x + dx;
    var rawZ = this.z + dz;
    var boundedX = U.math.clamp(rawX, this.map.bounds.minX + PLAYER_RADIUS, this.map.bounds.maxX - PLAYER_RADIUS);
    var boundedZ = U.math.clamp(rawZ, this.map.bounds.minZ + PLAYER_RADIUS, this.map.bounds.maxZ - PLAYER_RADIUS);
    var clear = boundedX === rawX && boundedZ === rawZ
      && this.map.segmentClear({ x: this.x, z: this.z }, { x: boundedX, z: boundedZ }, PLAYER_RADIUS);
    var nx = clear ? boundedX : this.x;
    var nz = clear ? boundedZ : this.z;
    var blocked = !clear;
    if (blocked && !this.blockedLastStep) {
      this.collisions += 1;
      this.addReward(-rewardConfig.constants.collisionPenalty);
    }
    this.blockedLastStep = blocked;
    this.x = nx;
    this.z = nz;
  };

  Base3DMovement.prototype.advanceTime = function advanceTime(ms, options) {
    var opts = typeof options === "object" && options !== null ? options : { render: options !== false };
    var reachedBefore = this.goalsReached;
    this.ensureSimulationRunner().advance(ms, opts);
    if (this.goalsReached > reachedBefore) this.lastGoalReached = true;
    if (opts.returnState === false) return null;
    return this.getStatePayload();
  };

  Base3DMovement.prototype.advanceSimulation = function advanceSimulation(ms) {
    var state = this.advanceTime(ms, { render: false });
    this.clearTransientControls();
    return state;
  };

  Base3DMovement.prototype.normalizeAction = function normalizeAction(action) {
    var normalized = G3D.input.readAction(action);
    return {
      id: normalized.id,
      args: normalized.args,
      forward: normalized.controls.forward,
      back: normalized.controls.back,
      left: normalized.controls.left,
      right: normalized.controls.right,
      pointerInput: normalized.pointerInput,
    };
  };

  Base3DMovement.prototype.clearTransientControls = function clearTransientControls() {
    this.controls = { forward: false, back: false, left: false, right: false };
  };

  Base3DMovement.prototype.applyAction = function applyAction(normalized) {
    this.controls.forward = normalized.forward;
    this.controls.back = normalized.back;
    this.controls.left = normalized.left;
    this.controls.right = normalized.right;
    this.applyRelativePointerInput(normalized.pointerInput);
    if (this.mode === "paused") this.mode = "playing";
  };

  Base3DMovement.prototype.buildStepInfo = function buildStepInfo(state, stepOptions, normalized) {
    this.updateBestMetrics();
    var info = Core.terminal.withInfo(this, state, this.infoPayload());
    if (state.metrics && typeof state.metrics.primary_score === "number") {
      info.score = state.metrics.primary_score;
    }
    info.action = { type: "game_step_action", id: normalized.id, args: normalized.args };
    info.durationMs = stepOptions.durationMs;
    info.source = stepOptions.source;
    return info;
  };

  Base3DMovement.prototype.resetGym = function resetGym(options) {
    this.resetFromAPI(options || {});
    return { observation: this.getObservation(), reward: 0, done: false, info: this.infoPayload() };
  };

  Base3DMovement.prototype.taskMetrics = function taskMetrics() {
    return Object.assign(this.rewardMetrics(), {
      goal_reached: this.lastGoalReached,
      distance_to_goal: this.distanceToGoal(),
    });
  };

  Base3DMovement.prototype.getObservation = function getObservation() {
    return Object.assign({
      player: { x: this.x, z: this.z, yaw: this.yaw, pitch: this.pitch },
      goal: this.goal,
    }, this.taskMetrics());
  };

  Base3DMovement.prototype.infoPayload = function infoPayload() {
    return Object.assign(this.taskMetrics(), {
      score: this.getPrimaryScore(),
      env_reward_step: this.envRewardStep,
      env_reward_episode: this.envRewardEpisode,
      time_steps: this.stepCount,
      sensitivity: this.sensitivity,
    });
  };

  Base3DMovement.prototype.rewardMetrics = function rewardMetrics() {
    return {
      goals_reached: this.goalsReached,
      collisions: this.collisions,
    };
  };

  Base3DMovement.prototype.getPrimaryScore = function getPrimaryScore() {
    return rewardConfig.computePrimaryScore(this.rewardMetrics());
  };

  Base3DMovement.prototype.updateBestMetrics = function updateBestMetrics() {
    this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, this.getPrimaryScore());
  };

  Base3DMovement.prototype.entityPayload = function entityPayload() {
    var entities = [
      { id: "player", type: "player", x: this.x, z: this.z, yaw: this.yaw, pitch: this.pitch },
      { id: "goal", type: "goal", x: this.goal.x, z: this.goal.z, r: this.goal.r },
    ];
    (this.layoutObstacles || []).forEach(function appendObstacle(obstacle) {
      entities.push({
        id: obstacle.id,
        type: "scene_obstacle",
        x: obstacle.x,
        z: obstacle.z,
        width: obstacle.width,
        depth: obstacle.depth,
        height: obstacle.height,
      });
    });
    return entities;
  };

  Base3DMovement.prototype.visualPayload = function visualPayload() {
    return G3D.visuals.payload(this);
  };

  Base3DMovement.prototype.getStatePayload = function getStatePayload() {
    var latched = Core.terminal.consume(this);
    if (latched) return latched;
    G3D.visuals.sync(this);
    var rewardMetrics = this.rewardMetrics();
    var primaryPositive = rewardConfig.computePrimaryPositiveScore(rewardMetrics);
    var primaryPenalty = rewardConfig.computePrimaryPenaltyScore(rewardMetrics);
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
        score: rewardConfig.computePrimaryScore(rewardMetrics),
        level: null,
        player: { x: this.x, z: this.z, yaw: this.yaw, pitch: this.pitch },
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
          room_bounds: { min_x: this.map.bounds.minX, max_x: this.map.bounds.maxX, min_z: this.map.bounds.minZ, max_z: this.map.bounds.maxZ },
          level_area: this.map.area,
          level_regions: this.map.rooms,
          level_links: this.map.links,
          scene_layout: this.sceneLayout,
          obstacles: this.layoutObstacles,
          difficulty: this.difficulty,
          scene_version: Scene.version,
          visual_profile: this.world3d.visualProfile,
          sensitivity: this.sensitivity,
          move_speed: MOVE_SPEED * this.controlResponse.applied.move_scale,
          goal: this.goal,
          asset_pack: this.assetContext ? this.assetContext.id : null,
          asset: this.assetContext ? this.assetContext.payload() : null,
          perturb_active: Core.perturbations.isActive(this),
          visual_perturbations: this.visualPayload(),
        },
        entities: this.entityPayload(),
      },
      metrics: Object.assign(this.taskMetrics(), {
        env_reward_step: this.envRewardStep,
        env_reward_episode: this.envRewardEpisode,
        primary_positive_score: primaryPositive,
        primary_penalty_score: primaryPenalty,
        primary_score: this.getPrimaryScore(),
        best_primary_score: this.bestMetrics.bestPrimaryScore,
        step_count: this.stepCount,
        episode_count: this.runtime.episodeCount,
        difficulty: this.difficulty,
      }),
      debug: { mode: this.mode, last_action: this.lastAction, last_reset_method: this.runtime.lastResetMethod, reset_count: this.runtime.resetCount },
    };
  };

  Base3DMovement.prototype.renderGameToText = function renderGameToText() {
    return JSON.stringify({
      coordinate_system: "first-person x/z room coordinates; yaw/pitch radians; relative pointer input uses signed visible game displacement",
      status: this.mode,
      player: { x: this.x, z: this.z, yaw: this.yaw, pitch: this.pitch },
      goal: this.goal,
      progress: this.taskMetrics(),
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

  Base3DMovement.prototype.rebuildScene3D = function rebuildScene3D() {
    if (!this.world3d) return;
    this.world3d.clear();
    this.presentation = Scene.build(this, this.map.bounds, FLOOR_Y);
  };

  Base3DMovement.prototype.syncScene3D = function syncScene3D() {
    if (!this.world3d) return;
    if (this.presentation) this.presentation.sync(this.gameTimeMs);
    this.world3d.setLookCamera({ x: this.x, z: this.z, yaw: this.yaw, pitch: this.pitch, eyeHeight: EYE_HEIGHT });
  };

  Base3DMovement.prototype.render = function render() {
    G3D.visuals.sync(this, { sceneReady: true });
    if (!this.world3d) return;
    this.syncScene3D();
    this.world3d.render();
    if (this.infoPanel) this.infoPanel.update();
  };

  Base3DMovement.prototype.resetFromAPI = function resetFromAPI(options) { return this.beginEpisode(options || {}, true); };

  async function start() {
    await G3D.assets.preload(ASSET_PACK, ASSET_REQUIREMENTS);
    var game = new Base3DMovement();
    await game.world3d.prepare();
    Core.createRuntime({
      game: game,
      presentation: {
        title: "3D Navigation",
        controls: "WASD moves. Move the mouse to look around. Reach the flag, then find its next position.",
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
              ["Flags reached", game.goalsReached],
              ["Distance to flag", game.distanceToGoal().toFixed(2)],
              ["Collisions", game.collisions],
            ],
          };
        },
      },
      renderer: G3D,
      gameId: "base_3d_movement",
      defaultSeed: 42,
      maxDifficulty: 5,
      defaultStepMs: 200,
      assets: { engine: G3D.assets, requiredAssetIds: ASSET_REQUIREMENTS },
    });
    game.startLoop();
  }

  Core.lifecycle.boot(start);
})();
