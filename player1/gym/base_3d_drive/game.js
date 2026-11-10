(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var G3D = window.BaseGamelet3D;
  var rewardConfig = window.Base3DDriveRewardConfig;
  var GAME_ID = "base_3d_drive";
  var LOGIC_WIDTH = 640;
  var LOGIC_HEIGHT = 640;
  var DISPLAY_WIDTH = G3D.viewport.baseWidth;
  var DISPLAY_HEIGHT = G3D.viewport.baseHeight;
  var STEP_MS = 1000 / 60;
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 5;
  var ASSET_REQUIREMENTS = window.CountryDriveScene.assets;
  var PERTURBATION_CONTRACT = Core.perturbations.defineContract({
    game_id: GAME_ID,
    control_response: {
      drive_scale: Core.controlResponse.ranges.drive_scale,
      turn_scale: Core.controlResponse.ranges.turn_scale,
    },
    capabilities: {
      appearance: ["palette", "lighting", "background", "assets"],
      camera: ["projection", "rig"],
      scene: ["layout"],
    },
    defaults: {
      appearance_profile: "default",
      camera_profile: "default",
      scene_profile: "default",
    },
    samplers: { scene: { layout: Core.perturbations.templateSampler("river-bends", ["ridge-sweep", "orchard-esses", "valley-road"]) } },
    validators: { scene: { layout: Core.perturbations.templateValidator(["river-bends", "ridge-sweep", "orchard-esses", "valley-road"]) } },
  });
  // Extend beyond the 90-unit camera far plane, including the perturbed chase offset.
  var ROAD_WINDOW_BEHIND = 100;
  var ROAD_WINDOW_AHEAD = 100;
  var CAR_RADIUS = 0.34;
  var ROAD_WIDTH = window.CountryDriveRoad.roadWidth;
  var ROAD_HALF_WIDTH = ROAD_WIDTH / 2;
  var ROAD_DRIVABLE_HALF_WIDTH = ROAD_HALF_WIDTH - CAR_RADIUS * 0.65;
  var ROAD_COLLISION_DAMPING = 0.55;
  var ROAD_COLLISION_COOLDOWN_MS = 300;

  var canvas = document.getElementById("display");


  function movementCrossesCheckpoint(oldPoint, newPoint, checkpoint) {
    var line = U.track.crossSection(checkpoint, checkpoint.tangentAngle, checkpoint.lineHalfWidth);
    return U.track.sweptCircleIntersectsSegment(oldPoint, newPoint, CAR_RADIUS, line.a, line.b);
  }

  function Base3DDrive() {
    this.defaults = {
      seed: DEFAULT_SEED,
      difficulty: DEFAULT_DIFFICULTY,
      maxDifficulty: MAX_DIFFICULTY,
    };
    this.urlConfig = Core.config.readUrl(this.defaults);
    this.controls = { left: false, right: false, throttle: false, brake: false };
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

  Base3DDrive.prototype.setup3D = function setup3D() {
    this.world3d = G3D.createWorld(canvas, {
      width: DISPLAY_WIDTH,
      height: DISPLAY_HEIGHT,
      fov: 62,
      near: 0.05,
      far: 90,
      clearColor: 0xdbeafe,
      fogColor: 0xdbeafe,
      fogNear: 16,
      fogFar: 42,
      ambient: 1.25,
      sun: 2.6,
      sunPosition: [-8, 18, 6],
      visualProfile: "stylized",
    });
    this.sceneMeshes = { checkpoints: [], road: [], laneDashes: [], guardrails: [] };
    G3D.viewport.install(this, { canvas: canvas, world: this.world3d, baseWidth: DISPLAY_WIDTH, baseHeight: DISPLAY_HEIGHT, baseFov: 62 });
  };

  Base3DDrive.prototype.beginEpisode = function beginEpisode(options, countReset, flags) {
    var episodeFlags = flags || {};
    var normalized = Core.config.normalizeOptions(options || {}, MAX_DIFFICULTY);
    var config = Core.config.mergeEpisode(this.urlConfig, normalized);
    this.currentConfig = Core.config.cloneEpisode(config);
    Core.terminal.clear(this, episodeFlags);
    Core.lifecycle.resetEpisode(this, { controls: { left: false, right: false, throttle: false, brake: false } });
    Core.reward.resetEpisode(this);
    Core.domains.beginEpisode(this, config, PERTURBATION_CONTRACT, DEFAULT_SEED);
    this.difficulty = config.difficulty;
    G3D.visuals.configure(this, config, {
      defaultAssetPack: "gym-country-drive",
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
    });
    this.level = this.buildLevel();
    this.x = this.level.start.x;
    this.y = this.level.start.y;
    this.vx = 0;
    this.vy = 0;
    this.angle = this.level.start.angle;
    var initialization = window.PlayerOneRecoveryInitialization;
    var recovery = initialization.create(this.seed, "road_realignment");
    this.recoveryInitialization = recovery.state;
    var lateralOffset = initialization.centeredNormal(recovery.rng, 0.15, 0.45);
    var headingOffset = initialization.centeredNormal(recovery.rng, Math.PI / 9, Math.PI / 3);
    this.x -= Math.sin(this.angle) * lateralOffset;
    this.y += Math.cos(this.angle) * lateralOffset;
    this.angle = U.math.normalizeAngle(this.angle + headingOffset);
    this.recoveryInitialization.distribution = "truncated_normal";
    this.recoveryInitialization.lateral_stddev = 0.15;
    this.recoveryInitialization.lateral_limit = 0.45;
    this.recoveryInitialization.heading_stddev_radians = Math.PI / 9;
    this.recoveryInitialization.heading_limit_radians = Math.PI / 3;
    this.recoveryInitialization.lateral_offset = lateralOffset;
    this.recoveryInitialization.heading_offset_radians = headingOffset;
    this.checkpointsPassed = 0;
    this.routeCheckpointIndex = 0;
    this.routesCompleted = 0;
    this.distanceDriven = 0;
    this.visualDistance = 0;
    this.contactTimeMs = -1000;
    this.collisions = 0;
    this.offRoadHits = 0;
    this.outOfBounds = 0;
    this.offRoadLastStep = false;
    this.collisionCooldownMs = 0;
    this.stepCount = 0;
    this.gameTimeMs = 0;
    this.lastAction = "reset";
    this.mode = config.autostart ? "playing" : "paused";
    this.terminal = { isTerminal: false, outcome: null, reason: null };
    this.controls = { left: false, right: false, throttle: false, brake: false };
    if (countReset) this.runtime.resetCount += 1;
    this.runtime.episodeCount += 1;
    this.runtime.lastResetMethod = countReset ? "inplace_reset" : "init";
    this.refreshRoadWindow();
    this.rebuildScene3D();
    this.updateBestMetrics();
    this.render();
    return { accepted: normalized, applied: config, notes: [] };
  };

  Base3DDrive.prototype.buildLevel = function buildLevel() {
    var layoutRng = Core.domains.gameplayRng(this, "scene", "layout");
    var layout = Core.domains.sample(this, "scene", "layout", { template: "river-bends" });
    this.road = window.CountryDriveRoad.create(layout, layoutRng);
    this.roadChunks = new Map();
    return {
      template: layout.template,
      sceneVersion: "endless-country-road-3",
      depth: this.road.shape.depth,
      start: this.road.start,
      chunks: [],
      controlRoute: [],
      route: [],
      routeLength: 0,
      roadWidth: ROAD_WIDTH,
      drivableHalfWidth: ROAD_DRIVABLE_HALF_WIDTH,
      checkpoints: [],
      obstacles: [],
      friction: 0.987 - Math.min(0.025, this.difficulty * 0.004),
      maxSpeed: (4.45 + this.difficulty * 0.18) * this.controlResponse.applied.drive_scale,
      acceleration: (4.7 + this.difficulty * 0.14) * 1.5 * this.controlResponse.applied.drive_scale,
      brakePower: 0.84,
      turnRate: 2.9 * this.controlResponse.applied.turn_scale,
    };
  };

  Base3DDrive.prototype.refreshRoadWindow = function refreshRoadWindow() {
    var first = this.road.chunkAtX(this.x - ROAD_WINDOW_BEHIND);
    var last = this.road.chunkAtX(this.x + ROAD_WINDOW_AHEAD);
    if (first !== this.level.firstChunk || last !== this.level.lastChunk) {
      var self = this;
      this.roadChunks.forEach(function evict(chunk, index) {
        if (index < first || index > last) self.roadChunks.delete(index);
      });
      var chunks = [], route = [], controlRoute = [], checkpoints = [];
      var routeLength = 0;
      for (var index = first; index <= last; index += 1) {
        var chunk = this.roadChunks.get(index);
        if (!chunk) {
          chunk = this.road.buildChunk(index);
          this.roadChunks.set(index, chunk);
        }
        chunks.push(chunk);
        route = route.concat(index === first ? chunk.route : chunk.route.slice(1));
        controlRoute = controlRoute.concat(index === first ? chunk.controlRoute : chunk.controlRoute.slice(1));
        routeLength += chunk.routeLength;
        chunk.checkpoints.forEach(function markProgress(checkpoint) {
          checkpoint.passed = checkpoint.index < self.routeCheckpointIndex;
          checkpoints.push(checkpoint);
        });
      }
      Object.assign(this.level, {
        firstChunk: first, lastChunk: last, chunks: chunks, route: route,
        controlRoute: controlRoute, checkpoints: checkpoints, routeLength: routeLength,
        windowStartX: chunks[0].startX, windowEndX: chunks[chunks.length - 1].endX,
      });
    }
    // Simulation keeps absolute coordinates; only the rendered scene uses a nearby origin.
    this.renderOriginX = this.roadChunks.get(this.road.chunkAtX(this.x)).originX;
  };

  Base3DDrive.prototype.bindInput = function bindInput() {
    this.inputController = G3D.input.createController(this, {
      canvas: canvas,
      eventTarget: document,
      includeMovement: false,
      controlAliases: {
        left: ["a", "KeyA", "ArrowLeft"],
        right: ["d", "KeyD", "ArrowRight"],
        throttle: ["w", "KeyW", "ArrowUp"],
        brake: ["s", "KeyS", "ArrowDown"],
      },
    });
    var app = document.getElementById("app");
    if (app) app.focus();
  };

  Base3DDrive.prototype.ensureSimulationRunner = function ensureSimulationRunner() {
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

  Base3DDrive.prototype.startLoop = function startLoop() {
    this.ensureSimulationRunner().start();
  };

  Base3DDrive.prototype.pause = function pause() {
    var pauseState = Core.lifecycle.pause(this);
    this.render();
    return pauseState;
  };

  Base3DDrive.prototype.resume = function resume() {
    var pauseState = Core.lifecycle.resume(this);
    this.render();
    return pauseState;
  };

  Base3DDrive.prototype.speed = function speed() {
    return Math.sqrt(this.vx * this.vx + this.vy * this.vy);
  };

  Base3DDrive.prototype.currentCheckpoint = function currentCheckpoint() {
    return this.road.checkpoint(this.routeCheckpointIndex);
  };

  Base3DDrive.prototype.distanceToCheckpoint = function distanceToCheckpoint() {
    var checkpoint = this.currentCheckpoint();
    if (!checkpoint) return 0;
    var line = U.track.crossSection(checkpoint, checkpoint.tangentAngle, checkpoint.lineHalfWidth);
    return U.geometry2d.distanceToSegment({ x: this.x, y: this.y }, line.a, line.b);
  };

  Base3DDrive.prototype.roadDistance = function roadDistance() {
    return U.track.distanceToPolyline({ x: this.x, y: this.y }, this.level.route).distance;
  };

  Base3DDrive.prototype.addReward = function addReward(value) {
    Core.reward.add(this, value);
  };

  Base3DDrive.prototype.update = function update(dt) {
    if (this.terminal.isTerminal || this.mode !== "playing") return;
    this.collisionCooldownMs = Math.max(0, this.collisionCooldownMs - dt * 1000);
    var steer = (this.controls.right ? 1 : 0) - (this.controls.left ? 1 : 0);
    var throttle = this.controls.throttle ? 1 : 0;
    var brake = this.controls.brake ? 1 : 0;
    var speed = this.speed();
    this.angle = U.math.normalizeAngle(this.angle + steer * this.level.turnRate * dt * (0.45 + speed / Math.max(0.01, this.level.maxSpeed)));
    if (throttle) {
      this.vx += Math.cos(this.angle) * this.level.acceleration * dt;
      this.vy += Math.sin(this.angle) * this.level.acceleration * dt;
    }
    if (brake) {
      this.vx *= this.level.brakePower;
      this.vy *= this.level.brakePower;
    }
    this.vx *= this.level.friction;
    this.vy *= this.level.friction;
    speed = this.speed();
    if (speed > this.level.maxSpeed) {
      var scale = this.level.maxSpeed / speed;
      this.vx *= scale;
      this.vy *= scale;
      speed = this.level.maxSpeed;
    }
    var oldX = this.x;
    var oldY = this.y;
    this.x += this.vx * dt;
    this.y += this.vy * dt;
    this.gameTimeMs += dt * 1000;
    this.stepCount += 1;
    this.lastAction = [steer < 0 ? "left" : steer > 0 ? "right" : null, throttle ? "throttle" : null, brake ? "brake" : null].filter(Boolean).join("+") || "coast";

    var roadInfo = U.track.distanceToPolyline({ x: this.x, y: this.y }, this.level.route);
    var hitFence = roadInfo.distance > this.level.drivableHalfWidth;
    if (hitFence) {
      var normalX = this.x - roadInfo.x;
      var normalY = this.y - roadInfo.y;
      var normalLength = Math.sqrt(normalX * normalX + normalY * normalY) || 1;
      normalX /= normalLength;
      normalY /= normalLength;
      this.x = roadInfo.x + normalX * this.level.drivableHalfWidth;
      this.y = roadInfo.y + normalY * this.level.drivableHalfWidth;
      var outwardSpeed = this.vx * normalX + this.vy * normalY;
      if (outwardSpeed > 0) {
        this.vx -= outwardSpeed * normalX;
        this.vy -= outwardSpeed * normalY;
      }
      this.vx *= ROAD_COLLISION_DAMPING;
      this.vy *= ROAD_COLLISION_DAMPING;
      if (!this.offRoadLastStep && this.collisionCooldownMs <= 0) {
        this.collisions += 1;
        this.contactTimeMs = this.gameTimeMs;
        this.offRoadHits += 1;
        this.outOfBounds += 1;
        this.addReward(-rewardConfig.constants.roadCollisionPenalty);
        this.collisionCooldownMs = ROAD_COLLISION_COOLDOWN_MS;
      }
    }
    this.offRoadLastStep = hitFence;
    this.distanceDriven += Math.sqrt(Math.pow(this.x - oldX, 2) + Math.pow(this.y - oldY, 2));

    this.visualDistance += (this.x - oldX) * Math.cos(this.angle) + (this.y - oldY) * Math.sin(this.angle);
    this.checkCheckpoint(oldX, oldY);
    this.refreshRoadWindow();
    this.updateBestMetrics();
  };

  Base3DDrive.prototype.checkCheckpoint = function checkCheckpoint(oldX, oldY) {
    var checkpoint = this.currentCheckpoint();
    if (!checkpoint) return;
    if (movementCrossesCheckpoint({ x: oldX, y: oldY }, { x: this.x, y: this.y }, checkpoint)) {
      checkpoint.passed = true;
      this.checkpointsPassed += 1;
      this.routeCheckpointIndex += 1;
      this.addReward(rewardConfig.constants.checkpointReward);
      this.routesCompleted = Math.floor(this.checkpointsPassed / this.road.checkpointsPerChunk);
      this.level.checkpoints.forEach(function markPassed(candidate) {
        if (candidate.index === checkpoint.index) candidate.passed = true;
      });
    }
  };

  Base3DDrive.prototype.advanceTime = function advanceTime(ms, options) {
    this.ensureSimulationRunner().advance(ms, options || {});
    return this.getStatePayload();
  };

  Base3DDrive.prototype.normalizeAction = function normalizeAction(action) {
    action = action || {};
    var actionId = Core.actions.readId(action, { lowercase: true });
    var steer = 0;
    if (Core.actions.hasKey(action, ["ArrowLeft", "KeyA", "a"])) steer -= 1;
    if (Core.actions.hasKey(action, ["ArrowRight", "KeyD", "d"])) steer += 1;
    var throttle = Core.actions.hasKey(action, ["ArrowUp", "KeyW", "w"]) ? 1 : 0;
    var brake = Core.actions.hasKey(action, ["ArrowDown", "KeyS", "s"]) ? 1 : 0;
    steer = U.math.clamp(steer, -1, 1);
    throttle = U.math.clamp(throttle, 0, 1);
    brake = U.math.clamp(brake, 0, 1);
    return { id: actionId || "wait", args: {}, steer: steer, throttle: throttle, brake: brake };
  };

  Base3DDrive.prototype.advanceSimulation = function advanceSimulation(ms) {
    var state = this.advanceTime(ms, { render: false });
    this.clearTransientControls();
    return state;
  };

  Base3DDrive.prototype.clearTransientControls = function clearTransientControls() {
    this.controls = { left: false, right: false, throttle: false, brake: false };
  };

  Base3DDrive.prototype.applyAction = function applyAction(normalized) {
    this.controls.left = normalized.steer < -0.1;
    this.controls.right = normalized.steer > 0.1;
    this.controls.throttle = normalized.throttle > 0.1;
    this.controls.brake = normalized.brake > 0.1;
    if (this.mode === "paused") this.mode = "playing";
  };

  Base3DDrive.prototype.buildStepInfo = function buildStepInfo(state, stepOptions, normalized) {
    var info = Core.terminal.withInfo(this, state, this.infoPayload());
    info.action = { type: "game_step_action", id: normalized.id, args: normalized.args };
    info.durationMs = stepOptions.durationMs;
    info.source = stepOptions.source;
    return info;
  };

  Base3DDrive.prototype.resetGym = function resetGym(options) {
    this.resetFromAPI(options || {});
    return { observation: this.getObservation(), reward: 0, done: false, info: this.infoPayload() };
  };

  Base3DDrive.prototype.getObservation = function getObservation() {
    return {
      player: { x: this.x, y: this.y, angle: this.angle, speed: this.speed(), vx: this.vx, vy: this.vy },
      current_checkpoint: this.currentCheckpoint(),
      checkpoints: this.level.checkpoints.map(function (checkpoint) {
        return { id: checkpoint.id, index: checkpoint.index, x: checkpoint.x, y: checkpoint.y,
          line_half_width: checkpoint.lineHalfWidth, tangent_angle: checkpoint.tangentAngle, passed: checkpoint.passed };
      }),
      road: {
        endless: true,
        checkpoint_spacing_x: this.road.checkpointSpacing,
        window_start_x: this.level.windowStartX,
        window_end_x: this.level.windowEndX,
        control_points: this.level.controlRoute.map(U.geometry2d.clonePoint),
        route_points: this.level.route.map(U.geometry2d.clonePoint),
        width: this.level.roadWidth,
        drivable_half_width: this.level.drivableHalfWidth,
        route_length: this.level.routeLength,
        distance_from_center: this.roadDistance(),
      },
      obstacles: [],
      checkpoints_passed: this.checkpointsPassed,
      routes_completed: this.routesCompleted,
    };
  };

  Base3DDrive.prototype.infoPayload = function infoPayload() {
    return {
      score: this.getPrimaryScore(),
      checkpoints_passed: this.checkpointsPassed,
      routes_completed: this.routesCompleted,
      total_checkpoints: null,
      loaded_checkpoints: this.level.checkpoints.length,
      speed: this.speed(),
      distance_to_checkpoint: this.distanceToCheckpoint(),
      road_distance: this.roadDistance(),
      collisions: this.collisions,
      off_road_hits: this.offRoadHits,
      out_of_bounds: this.outOfBounds,
      env_reward_step: this.envRewardStep,
      env_reward_episode: this.envRewardEpisode,
      time_steps: this.stepCount,
    };
  };

  Base3DDrive.prototype.rewardMetrics = function rewardMetrics() {
    return {
      checkpoints_passed: this.checkpointsPassed,
      collisions: this.collisions,
      off_road_hits: this.offRoadHits,
      out_of_bounds: this.outOfBounds,
    };
  };

  Base3DDrive.prototype.getPrimaryScore = function getPrimaryScore() {
    return rewardConfig.computePrimaryScore(this.rewardMetrics());
  };

  Base3DDrive.prototype.rewardPayload = function rewardPayload() {
    return {
      env_reward_step: this.envRewardStep,
      env_reward_episode: this.envRewardEpisode,
      primary_positive_score: rewardConfig.computePrimaryPositiveScore(this.rewardMetrics()),
      primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(this.rewardMetrics()),
      primary_score: this.getPrimaryScore(),
    };
  };

  Base3DDrive.prototype.updateBestMetrics = function updateBestMetrics() {
    var rewards = this.rewardPayload();
    this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, rewards.primary_score);
  };

  Base3DDrive.prototype.entityPayload = function entityPayload() {
    var entities = [{ id: "player", type: "vehicle", x: this.x, y: this.y, z: 0, angle: this.angle, yaw: this.angle, speed: this.speed(), r: CAR_RADIUS }];
    for (var i = 0; i < this.level.checkpoints.length; i += 1) {
      entities.push({
        id: this.level.checkpoints[i].id,
        type: "checkpoint",
        x: this.level.checkpoints[i].x,
        y: this.level.checkpoints[i].y,
        z: 0,
        line_half_width: this.level.checkpoints[i].lineHalfWidth,
        tangent_angle: this.level.checkpoints[i].tangentAngle,
        index: this.level.checkpoints[i].index,
        active: this.level.checkpoints[i].index === this.routeCheckpointIndex,
        passed: this.level.checkpoints[i].passed,
      });
    }
    return entities;
  };

  Base3DDrive.prototype.visualPayload = function visualPayload() {
    return G3D.visuals.payload(this);
  };

  Base3DDrive.prototype.getStatePayload = function getStatePayload() {
    var latched = Core.terminal.consume(this);
    if (latched) return latched;
    G3D.visuals.sync(this);
    var rewards = this.rewardPayload();
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
      terminal: {
        isTerminal: this.terminal.isTerminal,
        outcome: this.terminal.outcome,
        reason: this.terminal.reason,
      },
      game_state: {
        score: this.getPrimaryScore(),
        level: null,
        player: { x: this.x, y: this.y, z: 0, angle: this.angle, yaw: this.angle, speed: this.speed() },
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
          scene_version: this.level.sceneVersion,
          scene_layout: this.level.template,
          world_width: null,
          road_endless: true,
          road_checkpoint_spacing_x: this.road.checkpointSpacing,
          road_chunk_first_index: this.level.firstChunk,
          road_chunk_last_index: this.level.lastChunk,
          road_window_start_x: this.level.windowStartX,
          road_window_end_x: this.level.windowEndX,
          render_origin_x: this.renderOriginX,
          world_depth: this.level.depth,
          difficulty: this.difficulty,
          current_checkpoint_index: this.routeCheckpointIndex,
          current_checkpoint: this.currentCheckpoint(),
          route_control_points: this.level.controlRoute.map(U.geometry2d.clonePoint),
          route_points: this.level.route.map(U.geometry2d.clonePoint),
          road_width: this.level.roadWidth,
          road_drivable_half_width: this.level.drivableHalfWidth,
          road_route_length: this.level.routeLength,
          road_distance: this.roadDistance(),
          friction: this.level.friction,
          max_speed: this.level.maxSpeed,
          asset_pack: this.assetContext ? this.assetContext.id : null,
          asset: this.assetContext ? this.assetContext.payload() : null,
          perturb_active: Core.perturbations.isActive(this),
          visual_perturbations: this.visualPayload(),
        },
        entities: this.entityPayload(),
      },
      metrics: {
        env_reward_step: rewards.env_reward_step,
        env_reward_episode: rewards.env_reward_episode,
        primary_positive_score: rewards.primary_positive_score,
        primary_penalty_score: rewards.primary_penalty_score,
        primary_score: rewards.primary_score,
        checkpoints_passed: this.checkpointsPassed,
        routes_completed: this.routesCompleted,
        route_checkpoint_index: this.routeCheckpointIndex,
        total_checkpoints: null,
        loaded_checkpoints: this.level.checkpoints.length,
        speed: this.speed(),
        distance_to_checkpoint: this.distanceToCheckpoint(),
        road_distance: this.roadDistance(),
        distance_driven: this.distanceDriven,
        collisions: this.collisions,
        off_road_hits: this.offRoadHits,
        out_of_bounds: this.outOfBounds,
        collision_cooldown_ms: this.collisionCooldownMs,
        best_primary_score: this.bestMetrics.bestPrimaryScore,
        step_count: this.stepCount,
        episode_count: this.runtime.episodeCount,
        difficulty: this.difficulty,
      },
      debug: {
        mode: this.mode,
        last_action: this.lastAction,
        last_reset_method: this.runtime.lastResetMethod,
        reset_count: this.runtime.resetCount,
        paused: this.paused,
        runtime_paused: this.paused,
      },
    };
  };

  Base3DDrive.prototype.renderGameToText = function renderGameToText() {
    return JSON.stringify({
      coordinate_system: "x/z ground plane stored as x/y, angle radians with 0 facing +x",
      status: this.mode,
      player: { x: this.x, y: this.y, angle: this.angle, speed: this.speed(), vx: this.vx, vy: this.vy },
      current_checkpoint: this.currentCheckpoint(),
      checkpoints: this.level.checkpoints,
      road: {
        endless: true,
        checkpoint_spacing_x: this.road.checkpointSpacing,
        window_start_x: this.level.windowStartX,
        window_end_x: this.level.windowEndX,
        control_points: this.level.controlRoute,
        route_points: this.level.route,
        width: this.level.roadWidth,
        drivable_half_width: this.level.drivableHalfWidth,
        route_length: this.level.routeLength,
        distance_from_center: this.roadDistance(),
      },
      obstacles: [],
      rewards: this.rewardPayload(),
      progress: {
        checkpoints_passed: this.checkpointsPassed,
        routes_completed: this.routesCompleted,
        route_checkpoint_index: this.routeCheckpointIndex,
        total_checkpoints: null,
        loaded_checkpoints: this.level.checkpoints.length,
        distance_to_checkpoint: this.distanceToCheckpoint(),
        road_distance: this.roadDistance(),
        off_road_hits: this.offRoadHits,
      },
      difficulty: this.difficulty,
      visual_perturbations: this.visualPayload(),
    });
  };


  Base3DDrive.prototype.rebuildScene3D = function rebuildScene3D() {
    this.world3d.clear();
    this.sceneMeshes = window.CountryDriveScene.build(this);
    this.syncScene3D();
  };

  Base3DDrive.prototype.syncScene3D = function syncScene3D() {
    window.CountryDriveScene.sync(this, this.sceneMeshes);
    this.world3d.setChaseCamera({
      x: this.x - this.renderOriginX, z: this.y, yaw: this.angle,
      distance: 4.8, height: 2.7, lookHeight: 0.55, forwardLook: 1.7,
    });
  };

  Base3DDrive.prototype.render = function render() {
    G3D.visuals.sync(this, { sceneReady: true });
    if (!this.world3d) return;
    this.syncScene3D();
    this.world3d.render();
    if (this.infoPanel) this.infoPanel.update();
  };

  Base3DDrive.prototype.resetFromAPI = function resetFromAPI(options) {
    return this.beginEpisode(options || {}, true);
  };

  async function start() {
    await G3D.assets.preload("gym-country-drive", ASSET_REQUIREMENTS);
    var game = new Base3DDrive();
    Core.createRuntime({
      game: game,
      presentation: {
        title: "3D Road Driving",
        controls: "W / Up accelerates. S / Down brakes. A / D or Left / Right steers. Cross the checkpoints in order.",
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
              ["Checkpoints", game.checkpointsPassed],
              ["Speed", game.speed().toFixed(2)],
              ["Road offset", game.roadDistance().toFixed(2)],
              ["Collisions", game.collisions],
            ],
          };
        },
      },
      renderer: G3D,
      gameId: "base_3d_drive",
      defaultSeed: 42,
      maxDifficulty: 5,
      defaultStepMs: 200,
      assets: { engine: G3D.assets, requiredAssetIds: ASSET_REQUIREMENTS },
    });
  }

  Core.lifecycle.boot(start);
})();
