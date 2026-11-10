(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var G3D = window.BaseGamelet3D;
  var rewardConfig = window.Base3DNavigateChaseRewardConfig;
  var GAME_ID = "base_3d_navigate_chase";
  var LOGIC_WIDTH = 640;
  var LOGIC_HEIGHT = 640;
  var DISPLAY_WIDTH = G3D.viewport.baseWidth;
  var DISPLAY_HEIGHT = G3D.viewport.baseHeight;
  var STEP_MS = 1000 / 60;
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 5;
  var ChaseScene = window.CourtyardChaseScene;
  var ASSET_REQUIREMENTS = ChaseScene.assets;
  var ROOM_SIZE = 28;
  var FOV = Math.PI / 2;
  var MOVE_SPEED = 6;
  var PLAYER_RADIUS = 0.32;
  var PLAYER_EYE_HEIGHT = 0.96;
  var PLAYER_AVATAR_HEIGHT = 1.2;
  var CAMERA_HORIZONTAL_DISTANCE = 2.4;
  var CAMERA_LOOK_HEIGHT = 0.82;
  var CAMERA_FORWARD_LOOK = 0.8;
  var CAMERA_DEFAULT_HEIGHT = 1.9;
  var CAMERA_DEFAULT_HEIGHT_OFFSET = CAMERA_DEFAULT_HEIGHT - CAMERA_LOOK_HEIGHT;
  var CAMERA_DISTANCE = Math.hypot(
    CAMERA_HORIZONTAL_DISTANCE + CAMERA_FORWARD_LOOK,
    CAMERA_DEFAULT_HEIGHT_OFFSET,
  );
  var CAMERA_PITCH_MIN = 0.14;
  var CAMERA_PITCH_MAX = 0.61;
  var CAMERA_INITIAL_PITCHES = [0.42, 0.48, 0.54];
  var TARGET_AVATAR_HEIGHT = PLAYER_AVATAR_HEIGHT;
  var TARGET_BODY_RADIUS = 0.32;
  var TARGET_CAPTURE_DISTANCE = 1.0;
  var TARGET_SIGHT_HEIGHT = PLAYER_EYE_HEIGHT;
  var TARGET_SPAWN_MIN_DISTANCE = 2;
  var TARGET_SPAWN_MAX_DISTANCE = 6;
  var TARGET_SPAWN_CLEARANCE = 0.12;
  var TARGET_BASE_SPEED = 2;
  var TARGET_DIFFICULTY_SPEED = 0.5;
  var TARGET_TURN_INTERVAL_MIN = 1.4;
  var TARGET_TURN_INTERVAL_MAX = 3.2;
  var TARGET_TURN_JITTER = 0.7;
  var TARGET_FLEE_ENTER_DISTANCE = 3.5;
  var TARGET_FLEE_EXIT_DISTANCE = 4.5;
  var TARGET_FLEE_TURN_RATE = 4.5;
  var TARGET_COLLISION_AVOIDANCE_TIME = 0.45;
  var PERTURBATION_CONTRACT = Core.perturbations.defineContract({
    game_id: GAME_ID,
    control_response: {
      look_gain_scale: Core.controlResponse.ranges.look_gain_scale,
      move_scale: Core.controlResponse.ranges.chase_move_scale,
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
    },
  });

  var canvas = document.getElementById("display");

  function sampleInitialCamera(game, referenceYaw) {
    var rng = new U.Rng((Core.seeds.forDomain(game, "camera") ^ 0x63616d32) >>> 0,
      DEFAULT_SEED, { allowZeroSeed: true });
    var pitchBand = rng.randint(0, 3);
    var yawSide = rng.randint(0, 3) - 1;
    var pitch = CAMERA_INITIAL_PITCHES[pitchBand] + (pitchBand === 1 ? 0 : rng.range(-0.015, 0.015));
    return {
      reference_yaw: referenceYaw,
      reference_pitch: CAMERA_INITIAL_PITCHES[1],
      yaw_residual: yawSide === 0 ? 0 : yawSide * rng.range(0.10, 0.24),
      pitch_residual: pitch - CAMERA_INITIAL_PITCHES[1],
      pitch_band: ["shallow", "center", "steep"][pitchBand],
      pitch: pitch,
    };
  }

  function Base3DNavigateChase() {
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
    this.startLoop();
  }

  Base3DNavigateChase.prototype.setup3D = function setup3D() {
    this.world3d = G3D.createWorld(canvas, {
      width: DISPLAY_WIDTH,
      height: DISPLAY_HEIGHT,
      fov: 68,
      visualProfile: "stylized",
      clearColor: 0xb7d1d8,
      fogColor: 0xb7d1d8,
      fogNear: 23,
      fogFar: 55,
      ambient: 0.8,
      sun: 2.6,
      exposure: 0.96,
      sunPosition: [3, 14, 6],
    });
    this.sceneMeshes = { obstacles: [] };
    G3D.viewport.install(this, { canvas: canvas, world: this.world3d, baseWidth: DISPLAY_WIDTH, baseHeight: DISPLAY_HEIGHT, baseFov: 68 });
  };

  Base3DNavigateChase.prototype.beginEpisode = function beginEpisode(options, countReset, flags) {
    var episodeFlags = flags || {};
    var normalized = Core.config.normalizeOptions(options || {}, MAX_DIFFICULTY);
    var config = Core.config.mergeEpisode(this.urlConfig, normalized);
    this.currentConfig = Core.config.cloneEpisode(config);
    Core.terminal.clear(this, episodeFlags);
    Core.lifecycle.resetEpisode(this, { controls: { forward: false, back: false, left: false, right: false } });
    Core.reward.resetEpisode(this);
    Core.domains.beginEpisode(this, config, PERTURBATION_CONTRACT, DEFAULT_SEED);
    this.difficulty = config.difficulty;
    G3D.visuals.configure(this, config, {
      defaultAssetPack: "gym-chase",
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
    });
    this.map = window.NeighborhoodChaseLayout(this);
    var spawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var playerRng = Core.domains.isActive(this, "scene")
      ? Core.domains.gameplayRng(this, "scene", "player_spawn")
      : spawnRng;
    var cameraRng = Core.domains.baselineRng(this);
    var spawnCenters = [[14, 4], [24, 14], [14, 24], [4, 14]];
    var spawnCenter = spawnCenters[Core.domains.isActive(this, "scene") ? playerRng.randint(0, 3) : 0];
    this.x = spawnCenter[0] + playerRng.range(-0.5, 0.5);
    this.z = spawnCenter[1] + playerRng.range(-0.5, 0.5);
    this.walls = this.map.colliders;
    this.obstacles = [];
    this.beacon = { x: 0, z: 0, r: TARGET_CAPTURE_DISTANCE };
    this.targetSpawnSerial = -1;
    this.placeTargetRandomly();
    // Keep existing random streams aligned; the reset distribution owns the initial pose.
    cameraRng.range(-0.22, 0.22);
    Core.domains.sample(this, "camera", "orientation", {
      yaw_offset_radians: 0,
      pitch_offset_radians: 0,
    });
    this.cameraInitialization = sampleInitialCamera(this, Math.atan2(this.beacon.z - this.z, this.beacon.x - this.x));
    this.yaw = U.math.normalizeAngle(this.cameraInitialization.reference_yaw + this.cameraInitialization.yaw_residual);
    this.pitch = this.cameraInitialization.pitch;
    this.sensitivity = G3D.input.CAMERA_SENSITIVITY * this.controlResponse.applied.look_gain_scale;
    this.targetSpeed = TARGET_BASE_SPEED + this.difficulty * TARGET_DIFFICULTY_SPEED;
    this.playerMoving = false;
    this.targetMoving = false;
    this.playerHeading = this.yaw;
    this.playerStrideMs = 0;
    this.targetStrideMs = 0;
    this.startDistance = this.distanceToBeacon();
    this.resetDistanceProgress();
    this.targetsReached = 0;
    this.collisions = 0;
    this.blockedLastStep = false;
    this.stepCount = 0;
    this.gameTimeMs = 0;
    this.lastAction = "reset";
    this.mode = config.autostart ? "playing" : "paused";
    this.terminal = { isTerminal: false, outcome: null, reason: null };
    this.controls = { forward: false, back: false, left: false, right: false };
    if (countReset) this.runtime.resetCount += 1;
    this.runtime.episodeCount += 1;
    this.runtime.lastResetMethod = countReset ? "inplace_reset" : "init";
    this.rebuildScene3D();
    this.updateBestMetrics();
    this.render();
    return { accepted: normalized, applied: config, notes: [] };
  };


  Base3DNavigateChase.prototype.bindInput = function bindInput() {
    this.inputController = G3D.input.createController(this, {
      canvas: canvas,
      eventTarget: document,
      onLook: function onLook(dx, dy) { this.applyMouse(dx, dy); },
    });
    var app = document.getElementById("app");
    if (app) app.focus();
  };

  Base3DNavigateChase.prototype.ensureSimulationRunner = function ensureSimulationRunner() {
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

  Base3DNavigateChase.prototype.startLoop = function startLoop() {
    this.ensureSimulationRunner().start();
  };

  Base3DNavigateChase.prototype.pause = function pause() {
    return Core.lifecycle.pause(this);
  };

  Base3DNavigateChase.prototype.resume = function resume() {
    return Core.lifecycle.resume(this);
  };

  Base3DNavigateChase.prototype.cameraLookOptions = function cameraLookOptions() {
    return {
      sensitivity: this.sensitivity,
      pitchSign: 1,
      pitchMin: CAMERA_PITCH_MIN,
      pitchMax: CAMERA_PITCH_MAX,
    };
  };

  Base3DNavigateChase.prototype.applyMouse = function applyMouse(dx, dy) {
    if (this.terminal.isTerminal) return;
    if (this.mode === "paused") this.mode = "playing";
    G3D.input.applyPointerLook(this, dx, dy, this.cameraLookOptions());
    this.lastAction = "orbit(" + dx.toFixed(1) + "," + dy.toFixed(1) + ")";
  };

  Base3DNavigateChase.prototype.applyRelativePointerInput = function applyRelativePointerInput(pointerInput) {
    if (this.terminal.isTerminal || !pointerInput) return;
    if (this.mode === "paused") this.mode = "playing";
    G3D.input.applyRelativePointerInput(this, pointerInput, this.cameraLookOptions());
    this.lastAction = "relative_pointer(" + pointerInput.dx + "," + pointerInput.dy + ")";
  };

  Base3DNavigateChase.prototype.distanceToBeacon = function distanceToBeacon() {
    return U.geometry3d.horizontalDistance({ x: this.x, z: this.z }, this.beacon);
  };

  Base3DNavigateChase.prototype.yawError = function yawError() {
    return U.math.normalizeAngle(Math.atan2(this.beacon.z - this.z, this.beacon.x - this.x) - this.yaw);
  };

  Base3DNavigateChase.prototype.targetVisible = function targetVisible() {
    return Math.abs(this.yawError()) < FOV / 2 && this.hasLineOfSight();
  };

  Base3DNavigateChase.prototype.hasLineOfSight = function hasLineOfSight() {
    return U.geometry3d.hasLineOfSight(
      { x: this.x, y: PLAYER_EYE_HEIGHT, z: this.z },
      { x: this.beacon.x, y: TARGET_SIGHT_HEIGHT, z: this.beacon.z },
      this.walls.concat(this.obstacles),
      { bounds: U.geometry3d.aabbFromBox }
    );
  };

  Base3DNavigateChase.prototype.addReward = function addReward(value) {
    Core.reward.add(this, value);
  };

  Base3DNavigateChase.prototype.resetDistanceProgress = function resetDistanceProgress() {
    this.progressBestDistance = this.distanceToBeacon();
    this.progressRewardEarned = 0;
  };

  Base3DNavigateChase.prototype.recordDistanceProgress = function recordDistanceProgress(after, moved) {
    if (!moved) {
      if (after < this.progressBestDistance) this.progressBestDistance = after;
      return;
    }
    if (after >= this.progressBestDistance) return;
    this.progressBestDistance = after;
    var remaining = rewardConfig.constants.progressRewardCap - this.progressRewardEarned;
    if (remaining <= 0) return;
    var reward = Math.min(rewardConfig.constants.progressRewardScale, remaining);
    this.progressRewardEarned += reward;
    this.addReward(reward);
  };

  Base3DNavigateChase.prototype.targetColliders = function targetColliders() {
    return this.walls.concat(this.obstacles);
  };

  Base3DNavigateChase.prototype.scheduleTargetTurn = function scheduleTargetTurn() {
    this.targetTurnRemaining = this.targetBehaviorRng.range(
      TARGET_TURN_INTERVAL_MIN,
      TARGET_TURN_INTERVAL_MAX
    );
  };

  Base3DNavigateChase.prototype.resetTargetBehavior = function resetTargetBehavior() {
    this.targetBehavior = this.distanceToBeacon() <= TARGET_FLEE_ENTER_DISTANCE
      ? "fleeing"
      : "wandering";
    this.targetCollisionAvoidanceRemaining = 0;
  };

  Base3DNavigateChase.prototype.updateTargetBehavior = function updateTargetBehavior(dt) {
    var distance = this.distanceToBeacon();
    if (this.targetBehavior === "fleeing") {
      if (distance >= TARGET_FLEE_EXIT_DISTANCE) {
        this.targetBehavior = "wandering";
        this.scheduleTargetTurn();
      }
    } else if (distance <= TARGET_FLEE_ENTER_DISTANCE) {
      this.targetBehavior = "fleeing";
    }

    if (this.targetBehavior === "fleeing") {
      this.targetCollisionAvoidanceRemaining = Math.max(0, this.targetCollisionAvoidanceRemaining - dt);
      if (this.targetCollisionAvoidanceRemaining <= 0) {
        var fleeHeading = Math.atan2(this.beacon.z - this.z, this.beacon.x - this.x);
        var headingError = U.math.normalizeAngle(fleeHeading - this.targetHeading);
        var maxTurn = TARGET_FLEE_TURN_RATE * dt;
        this.targetHeading = U.math.normalizeAngle(
          this.targetHeading + U.math.clamp(headingError, -maxTurn, maxTurn)
        );
      }
      return;
    }

    this.targetTurnRemaining -= dt;
    if (this.targetTurnRemaining <= 0) {
      this.targetHeading = U.math.normalizeAngle(
        this.targetHeading
          + this.targetBehaviorRng.range(-TARGET_TURN_JITTER, TARGET_TURN_JITTER)
      );
      this.scheduleTargetTurn();
    }
  };

  Base3DNavigateChase.prototype.placeTargetRandomly = function placeTargetRandomly() {
    var self = this;
    var spawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var point = U.geometry3d.sampleOpenPointXZ(spawnRng, {
      bounds: { minX: 0, maxX: ROOM_SIZE, minZ: 0, maxZ: ROOM_SIZE },
      radius: TARGET_BODY_RADIUS + TARGET_SPAWN_CLEARANCE,
      colliders: this.targetColliders(),
      reference: { x: this.x, z: this.z },
      minDistance: TARGET_SPAWN_MIN_DISTANCE,
      maxDistance: TARGET_SPAWN_MAX_DISTANCE,
      maxAttempts: 512,
      accept: function reachable(point) { return self.map.contains(point.x, point.z, TARGET_BODY_RADIUS + TARGET_SPAWN_CLEARANCE); },
    });
    if (!point) throw new Error("Unable to sample a collision-free target position");
    this.beacon.x = point.x;
    this.beacon.z = point.z;
    this.targetSpawnSerial += 1;
    this.targetHeading = spawnRng.range(-Math.PI, Math.PI);
    this.targetVisualHeading = this.targetHeading;
    this.targetBehaviorRng = Core.domains.createEntityRng(this, spawnRng, DEFAULT_SEED);
    this.scheduleTargetTurn();
    this.resetTargetBehavior();
  };

  Base3DNavigateChase.prototype.startNextTarget = function startNextTarget() {
    this.targetsReached += 1;
    this.placeTargetRandomly();
    this.startDistance = this.distanceToBeacon();
    this.resetDistanceProgress();
    this.lastAction = "target_reached";
  };

  Base3DNavigateChase.prototype.update = function update(dt) {
    if (this.terminal.isTerminal || this.mode !== "playing") return;
    this.stepCount += 1;
    this.gameTimeMs += dt * 1000;
    this.updateTarget(dt);
    var move = G3D.input.moveDelta(this.yaw, this.controls, MOVE_SPEED * this.controlResponse.applied.move_scale, dt);
    var moved = !!(move.x || move.z);
    var beforeX = this.x;
    var beforeZ = this.z;
    if (moved) this.tryMove(move.x, move.z);
    else this.blockedLastStep = false;
    var playerDistance = Math.hypot(this.x - beforeX, this.z - beforeZ);
    this.playerMoving = playerDistance > 0.000001;
    if (this.playerMoving) this.playerHeading = Math.atan2(this.z - beforeZ, this.x - beforeX);
    this.playerStrideMs += playerDistance * 250;
    var after = this.distanceToBeacon();
    this.recordDistanceProgress(after, moved);
    if (!this.terminal.isTerminal && after <= this.beacon.r) {
      this.addReward(rewardConfig.constants.targetReward);
      this.startNextTarget();
    }
    this.updateBestMetrics();
  };

  Base3DNavigateChase.prototype.updateTarget = function updateTarget(dt) {
    this.updateTargetBehavior(dt);
    var step = this.targetSpeed * dt;
    var movement = U.geometry3d.moveCircleWithAabbs(
      this.beacon,
      { x: Math.cos(this.targetHeading) * step, z: Math.sin(this.targetHeading) * step },
      {
        radius: TARGET_BODY_RADIUS,
        bounds: { minX: 0, maxX: ROOM_SIZE, minZ: 0, maxZ: ROOM_SIZE },
        colliders: this.targetColliders(),
      }
    );
    var targetDistance = Math.hypot(movement.x - this.beacon.x, movement.z - this.beacon.z);
    this.targetMoving = targetDistance > 0.000001;
    if (this.targetMoving) {
      this.targetVisualHeading = Math.atan2(movement.z - this.beacon.z, movement.x - this.beacon.x);
    }
    this.targetStrideMs += targetDistance * 250;
    this.beacon.x = movement.x;
    this.beacon.z = movement.z;
    if (movement.blockedX) this.targetHeading = Math.PI - this.targetHeading;
    if (movement.blockedZ) this.targetHeading = -this.targetHeading;
    if (movement.blockedX || movement.blockedZ) {
      this.targetHeading = U.math.normalizeAngle(
        this.targetHeading + this.targetBehaviorRng.range(-0.22, 0.22)
      );
      if (this.targetBehavior === "fleeing") {
        this.targetCollisionAvoidanceRemaining = TARGET_COLLISION_AVOIDANCE_TIME;
      }
      this.scheduleTargetTurn();
    }
  };

  Base3DNavigateChase.prototype.tryMove = function tryMove(dx, dz) {
    var movement = U.geometry3d.moveCircleWithAabbs(
      { x: this.x, z: this.z },
      { x: dx, z: dz },
      {
        radius: PLAYER_RADIUS,
        bounds: { minX: 0, maxX: ROOM_SIZE, minZ: 0, maxZ: ROOM_SIZE },
        colliders: this.walls.concat(this.obstacles),
      }
    );
    var blocked = movement.blockedX || movement.blockedZ;
    if (blocked && !this.blockedLastStep) {
      this.collisions += 1;
      this.addReward(-rewardConfig.constants.collisionPenalty);
    }
    this.blockedLastStep = blocked;
    this.x = movement.x;
    this.z = movement.z;
  };

  Base3DNavigateChase.prototype.advanceTime = function advanceTime(ms, options) {
    this.ensureSimulationRunner().advance(ms, options || {});
    return this.getStatePayload();
  };

  Base3DNavigateChase.prototype.normalizeAction = function normalizeAction(action) {
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

  Base3DNavigateChase.prototype.clearTransientControls = function clearTransientControls() {
    this.controls = { forward: false, back: false, left: false, right: false };
  };

  Base3DNavigateChase.prototype.applyAction = function applyAction(normalized) {
    this.controls.forward = normalized.forward;
    this.controls.back = normalized.back;
    this.controls.left = normalized.left;
    this.controls.right = normalized.right;
    this.applyRelativePointerInput(normalized.pointerInput);
    if (this.mode === "paused") this.mode = "playing";
  };

  Base3DNavigateChase.prototype.advanceSimulation = function advanceSimulation(ms) {
    var state = this.advanceTime(ms, { render: false });
    this.clearTransientControls();
    return state;
  };

  Base3DNavigateChase.prototype.buildStepInfo = function buildStepInfo(state, stepOptions, normalized) {
    var info = Core.terminal.withInfo(this, state, this.infoPayload());
    info.action = { type: "game_step_action", id: normalized.id, args: normalized.args };
    info.durationMs = stepOptions.durationMs;
    info.source = stepOptions.source;
    return info;
  };

  Base3DNavigateChase.prototype.resetGym = function resetGym(options) {
    this.resetFromAPI(options || {});
    return { observation: this.getObservation(), reward: 0, done: false, info: this.infoPayload() };
  };

  Base3DNavigateChase.prototype.getObservation = function getObservation() {
    return {
      player: { x: this.x, z: this.z, yaw: this.yaw, pitch: this.pitch },
      target: this.beacon,
      obstacles: this.obstacles,
      walls: this.walls,
      distance_to_target: this.distanceToBeacon(),
      yaw_error: this.yawError(),
      camera_pitch: this.pitch,
      target_visible: this.targetVisible(),
      line_of_sight: this.hasLineOfSight(),
    };
  };

  Base3DNavigateChase.prototype.infoPayload = function infoPayload() {
    return {
      score: this.getPrimaryScore(),
      targets_reached: this.targetsReached,
      distance_to_target: this.distanceToBeacon(),
      yaw_error: this.yawError(),
      target_visible: this.targetVisible(),
      line_of_sight: this.hasLineOfSight(),
      collisions: this.collisions,
      env_reward_step: this.envRewardStep,
      env_reward_episode: this.envRewardEpisode,
      time_steps: this.stepCount,
    };
  };

  Base3DNavigateChase.prototype.rewardMetrics = function rewardMetrics() {
    return {
      targets_reached: this.targetsReached,
      collisions: this.collisions,
    };
  };

  Base3DNavigateChase.prototype.getPrimaryScore = function getPrimaryScore() {
    return rewardConfig.computePrimaryScore(this.rewardMetrics());
  };
  Base3DNavigateChase.prototype.updateBestMetrics = function updateBestMetrics() {
    this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, this.getPrimaryScore());
  };

  Base3DNavigateChase.prototype.visualPayload = function visualPayload() {
    return G3D.visuals.payload(this);
  };

  Base3DNavigateChase.prototype.entityPayload = function entityPayload() {
    return [
      { id: "player", type: "player", x: this.x, z: this.z, yaw: this.yaw, pitch: this.pitch },
      { id: "target", type: "target", appearance: "humanoid", color_role: "target", x: this.beacon.x, z: this.beacon.z, r: this.beacon.r, height: TARGET_AVATAR_HEIGHT, spawn_serial: this.targetSpawnSerial, heading: this.targetHeading, speed: this.targetSpeed, behavior: this.targetBehavior },
    ].concat(
      this.walls.map(function (wall) { return { id: wall.id, type: "wall", x: wall.x, z: wall.z, width: wall.width, depth: wall.depth, height: wall.height }; }),
      this.obstacles.map(function (obstacle) { return { id: obstacle.id, type: "obstacle", x: obstacle.x, z: obstacle.z, r: obstacle.r, height: obstacle.height }; }),
    );
  };

  Base3DNavigateChase.prototype.getStatePayload = function getStatePayload() {
    var latched = Core.terminal.consume(this);
    if (latched) return latched;
    G3D.visuals.sync(this);
    var dist = this.distanceToBeacon();
    var yawError = this.yawError();
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
        player: { x: this.x, z: this.z, yaw: this.yaw, pitch: this.pitch },
        environment: {
          phase: this.terminal.isTerminal ? "terminal" : this.mode,
          viewport_width: viewport.width,
          viewport_height: viewport.height,
          fullscreen: viewport,
          camera_fov: viewport.fov,
          camera_mode: "third_person_optical_chase",
          scene_version: "neighborhood-2",
          map: { id: this.map.id, revision: this.map.revision, regions: this.map.regions },
          player_radius: PLAYER_RADIUS,
          player_avatar_height: PLAYER_AVATAR_HEIGHT,
          target_body_radius: TARGET_BODY_RADIUS,
          room_bounds: { min_x: 0, max_x: ROOM_SIZE, min_z: 0, max_z: ROOM_SIZE },
          room_size: ROOM_SIZE,
          difficulty: this.difficulty,
          sensitivity: this.sensitivity,
          camera_pitch_min: CAMERA_PITCH_MIN,
          camera_pitch_max: CAMERA_PITCH_MAX,
          camera_initialization: this.cameraInitialization,
          move_speed: MOVE_SPEED * this.controlResponse.applied.move_scale,
          target: this.beacon,
          target_spawn_strategy: "random_open_point",
          target_spawn_min_distance: TARGET_SPAWN_MIN_DISTANCE,
          target_spawn_max_distance: TARGET_SPAWN_MAX_DISTANCE,
          target_spawn_serial: this.targetSpawnSerial,
          target_speed: this.targetSpeed,
          target_flee_enter_distance: TARGET_FLEE_ENTER_DISTANCE,
          target_flee_exit_distance: TARGET_FLEE_EXIT_DISTANCE,
          asset_pack: this.assetContext ? this.assetContext.id : null,
          asset: this.assetContext ? this.assetContext.payload() : null,
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
        distance_to_target: dist,
        start_distance: this.startDistance,
        yaw_error: yawError,
        camera_pitch: this.pitch,
        target_visible: this.targetVisible(),
        line_of_sight: this.hasLineOfSight(),
        target_spawn_serial: this.targetSpawnSerial,
        target_heading: this.targetHeading,
        target_speed: this.targetSpeed,
        target_behavior: this.targetBehavior,
        collisions: this.collisions,
        targets_reached: this.targetsReached,
        best_primary_score: this.bestMetrics.bestPrimaryScore,
        step_count: this.stepCount,
        episode_count: this.runtime.episodeCount,
        difficulty: this.difficulty,
      },
      debug: { mode: this.mode, last_action: this.lastAction, last_reset_method: this.runtime.lastResetMethod, reset_count: this.runtime.resetCount },
    };
  };

  Base3DNavigateChase.prototype.renderGameToText = function renderGameToText() {
    return JSON.stringify({
      coordinate_system: "third-person x/z room coordinates; yaw/pitch radians; relative pointer input uses signed visible game displacement",
      status: this.mode,
      player: { x: this.x, z: this.z, yaw: this.yaw, pitch: this.pitch },
      target: this.beacon,
      target_spawn_strategy: "random_open_point",
      target_spawn_serial: this.targetSpawnSerial,
      target_heading: this.targetHeading,
      target_behavior: this.targetBehavior,
      walls: this.walls,
      obstacles: this.obstacles,
      error: {
        yaw_error: this.yawError(),
        distance_to_target: this.distanceToBeacon(),
        target_visible: this.targetVisible(),
        line_of_sight: this.hasLineOfSight(),
      },
      rewards: {
        env_reward_step: this.envRewardStep,
        env_reward_episode: this.envRewardEpisode,
        primary_positive_score: rewardConfig.computePrimaryPositiveScore(this.rewardMetrics()),
        primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(this.rewardMetrics()),
        primary_score: this.getPrimaryScore(),
      },
      visual_perturbations: this.visualPayload(),
    });
  };


  Base3DNavigateChase.prototype.rebuildScene3D = function rebuildScene3D() {
    if (!this.world3d) return;
    this.world3d.clear();
    this.sceneMeshes = ChaseScene.build(this, ROOM_SIZE, PLAYER_AVATAR_HEIGHT);
  };

  Base3DNavigateChase.prototype.syncScene3D = function syncScene3D() {
    if (!this.world3d) return;
    ChaseScene.sync(this);
    this.world3d.setOpticalChaseCamera({
      x: this.x,
      z: this.z,
      yaw: this.yaw,
      pitch: this.pitch,
      distance: CAMERA_DISTANCE,
      lookHeight: CAMERA_LOOK_HEIGHT,
      forwardLook: CAMERA_FORWARD_LOOK,
      bounds: { minX: 0.32, maxX: ROOM_SIZE - 0.32, minZ: 0.32, maxZ: ROOM_SIZE - 0.32 },
    });
    ChaseScene.avoidCameraObstacles(this);
  };

  Base3DNavigateChase.prototype.render = function render() {
    G3D.visuals.sync(this, { sceneReady: true });
    if (!this.world3d) return;
    this.syncScene3D();
    this.world3d.render();
    if (this.infoPanel) this.infoPanel.update();
  };

  Base3DNavigateChase.prototype.resetFromAPI = function resetFromAPI(options) { return this.beginEpisode(options || {}, true); };
  async function start() {
    await G3D.assets.preload("gym-chase", ASSET_REQUIREMENTS);
    var game = new Base3DNavigateChase();
    Core.createRuntime({
      game: game,
      presentation: {
        title: "3D Chasing",
        controls: "WASD moves relative to the camera. Move the mouse to orbit the camera. Chase and reach the moving target.",
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
              ["Targets reached", game.targetsReached],
              ["Distance", game.distanceToBeacon().toFixed(2)],
              ["Bearing", Math.round(game.yawError() * 180 / Math.PI) + "°"],
              ["Collisions", game.collisions],
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
    });
  }

  Core.lifecycle.boot(start);
})();
