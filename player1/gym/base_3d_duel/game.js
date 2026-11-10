(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var G3D = window.BaseGamelet3D;
  var rewardConfig = window.Base3DDuelRewardConfig;
  var GAME_ID = "base_3d_duel";
  var LOGIC_WIDTH = 640;
  var LOGIC_HEIGHT = 640;
  var DISPLAY_WIDTH = G3D.viewport.baseWidth;
  var DISPLAY_HEIGHT = G3D.viewport.baseHeight;
  var STEP_MS = 1000 / 60;
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 5;
  var ASSET_PACK = "gym-duel";
  var ASSET_REQUIREMENTS = window.SpearCourtyardScene.assets;
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
    defaults: {
      appearance_profile: "default",
      camera_profile: "default",
      scene_profile: "default",
    },
    samplers: {
      camera: {
        orientation: Core.perturbations.cameraOrientationSampler("combat"),
      },
    },
  });

  var FLOOR_Y = 0;
  var ARENA_MIN_X = -12;
  var ARENA_MAX_X = 12;
  var ARENA_MIN_Z = -11;
  var ARENA_MAX_Z = 11;
  var PLAYER_RADIUS = 0.34;
  var PLAYER_ENEMY_COLLISION_PADDING = 0.08;
  var PLAYER_HEIGHT = 1.64;
  var PLAYER_MOVE_SPEED = 5;
  var PLAYER_STAGGER_SECONDS = 0.18;
  var PLAYER_KNOCKBACK_SECONDS = 0.14;
  var PLAYER_KNOCKBACK_SPEED = 3.4;
  var PLAYER_EYE_HEIGHT = 1.48;
  var PLAYER_START_YAW = -Math.PI / 2;
  var LOOK_SENSITIVITY = G3D.input.CAMERA_SENSITIVITY;
  var CAMERA_PITCH_DEFAULT = 0;
  var CAMERA_PITCH_MIN = -0.62;
  var CAMERA_PITCH_MAX = 0.68;

  var PLAYER_SPEAR_REACH = 2.625;
  var PLAYER_COMBAT_CENTER_HEIGHT = 0.92;
  var PLAYER_SPEAR_BODY_RADIUS = 0.4;
  var PLAYER_SPEAR_CHARGE_SECONDS = 0.4;
  var PLAYER_SPEAR_THRUST_SECONDS = 0.12;
  var PLAYER_SPEAR_RECOVERY_SECONDS = 0.22;
  var PLAYER_SPEAR_DAMAGE = 1;
  var PLAYER_SPEAR_OCCLUSION_EPSILON = 0.025;
  var ENEMY_STAGGER_SECONDS = 0.28;
  var ENEMY_KNOCKBACK_SECONDS = 0.18;
  var ENEMY_KNOCKBACK_SPEED = 3.2;
  var ENEMY_RETURN_SPEED = 2.4;
  var ENEMY_RETURN_TOLERANCE = 0.025;
  var ENEMY_SPEAR_REACH_MARGIN = 0.04;

  var DODGE_SPEED = 10.5;
  var DODGE_SECONDS = 0.28;
  var DODGE_COOLDOWN_SECONDS = 1.05;

  var ENEMY_RADIUS = 0.38;
  var ENEMY_LATERAL_SPEED_SCALE = 0.6;
  var ENEMY_ORBIT_MAX_SWEEP_RADIANS = Math.PI / 4;
  var ENEMY_ORBIT_RECENTER_MIN_SECONDS = 0.24;
  var ENEMY_ORBIT_RECENTER_MAX_SECONDS = 0.38;
  var ENEMY_ATTACK_TRIGGER_DISTANCE = 1.52;
  var ENEMY_ATTACK_RANGE = 1.36;
  var ENEMY_ATTACK_HALF_ANGLE = Math.PI * 0.28;
  var ENEMY_ATTACK_ACTIVE_SECONDS = 0.16;
  var ENEMY_SPAWN_MIN_DISTANCE = 2;
  var ENEMY_SPAWN_MAX_DISTANCE = 2.8;
  var ENEMY_SPAWN_SIDE_ANGLE_MIN = Math.PI * 0.28;
  var ENEMY_SPAWN_SIDE_ANGLE_MAX = Math.PI * 0.53;
  var ENEMY_STARTER_DISTANCE_MIN = 2.2;
  var ENEMY_STARTER_DISTANCE_MAX = 2.8;
  var ENEMY_STARTER_SIDE_ANGLE_MIN = Math.PI * 0.045;
  var ENEMY_STARTER_SIDE_ANGLE_MAX = Math.PI * 0.135;
  var ENEMY_JUMP_SPEED = 4.8;
  var ENEMY_GRAVITY = 12.5;
  var RESPAWN_MIN_SECONDS = 0.45;
  var RESPAWN_JITTER_SECONDS = 0.35;

  var ENEMY_PROFILES = Object.freeze([
    Object.freeze({
      id: "duelist",
      health: 3,
      orbitSpeed: 2.9,
      windupSeconds: 0.72,
      recoverySeconds: 0.52,
      scale: 1,
      jumpWeight: 0.14,
    }),
    Object.freeze({
      id: "skirmisher",
      health: 3,
      orbitSpeed: 3.25,
      windupSeconds: 0.6,
      recoverySeconds: 0.48,
      scale: 0.92,
      jumpWeight: 0.2,
    }),
    Object.freeze({
      id: "hopper",
      health: 3,
      orbitSpeed: 3.1,
      windupSeconds: 0.68,
      recoverySeconds: 0.52,
      scale: 0.96,
      jumpWeight: 0.56,
    }),
  ]);

  var canvas = document.getElementById("display");


  function readOptionalBoolean(object, snakeKey, camelKey) {
    if (U.object.hasOwn(object, snakeKey)) return Core.config.normalizeBoolean(object[snakeKey], null);
    if (U.object.hasOwn(object, camelKey)) return Core.config.normalizeBoolean(object[camelKey], null);
    return null;
  }

  function readDuelUrlConfig(defaults) {
    var config = Core.config.readUrl(defaults);
    var params = new URLSearchParams(window.location.search || "");
    config.noObstacles = Core.config.normalizeBoolean(params.get("no_obstacles"), false);
    return config;
  }

  function mergeDuelEpisodeConfig(urlConfig, normalized, rawOptions) {
    var config = Core.config.mergeEpisode(urlConfig, normalized);
    var noObstacles = readOptionalBoolean(rawOptions || {}, "no_obstacles", "noObstacles");
    config.noObstacles = noObstacles === null ? !!urlConfig.noObstacles : noObstacles;
    return config;
  }

  function normalizedDirection(dx, dz) {
    var length = Math.sqrt(dx * dx + dz * dz);
    if (length <= 0.000001) return { x: 0, z: 0, length: 0 };
    return { x: dx / length, z: dz / length, length: length };
  }

  function profileById(id) {
    for (var i = 0; i < ENEMY_PROFILES.length; i += 1) {
      if (ENEMY_PROFILES[i].id === id) return ENEMY_PROFILES[i];
    }
    return ENEMY_PROFILES[0];
  }

  function Base3DDuel() {
    this.defaults = {
      seed: DEFAULT_SEED,
      difficulty: DEFAULT_DIFFICULTY,
      maxDifficulty: MAX_DIFFICULTY,
    };
    this.urlConfig = readDuelUrlConfig(this.defaults);
    this.controls = { forward: false, back: false, left: false, right: false };
    this.chargeButton = Core.actions.createButtonLifecycle();
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

  Base3DDuel.prototype.setup3D = function setup3D() {
    canvas.tabIndex = 0;
    this.world3d = G3D.createWorld(canvas, {
      width: DISPLAY_WIDTH,
      height: DISPLAY_HEIGHT,
      fov: 70,
      near: 0.05,
      eyeHeight: PLAYER_EYE_HEIGHT,
      visualProfile: "stylized",
      clearColor: 0xb9d4dc,
      fogColor: 0xc7d8e8,
      fogNear: 16,
      fogFar: 34,
      ambient: 0.52,
      sun: 0.98,
    });
    this.sceneReady = false;
    this.sceneMeshes = {};
    G3D.viewport.install(this, {
      canvas: canvas,
      world: this.world3d,
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
      baseFov: 70,
    });
  };

  Base3DDuel.prototype.setupViewSpear = function setupViewSpear() {
    if (this.viewSpear) G3D.entities.remove(this.viewSpear, this.world3d.camera);
    this.viewSpear = window.SpearCourtyardScene.createWeapon(this);
  };

  Base3DDuel.prototype.beginEpisode = function beginEpisode(options, countReset, flags) {
    var episodeFlags = flags || {};
    var rawOptions = options || {};
    var normalized = Core.config.normalizeOptions(rawOptions, MAX_DIFFICULTY);
    var config = mergeDuelEpisodeConfig(this.urlConfig, normalized, rawOptions);
    this.currentConfig = Core.config.cloneEpisode(config);
    this.currentConfig.noObstacles = !!config.noObstacles;
    Core.terminal.clear(this, episodeFlags);
    Core.lifecycle.resetEpisode(this, {
      controls: { forward: false, back: false, left: false, right: false },
    });
    Core.reward.resetEpisode(this);
    Core.domains.beginEpisode(this, config, PERTURBATION_CONTRACT, DEFAULT_SEED);
    this.difficulty = config.difficulty;
    this.noObstacles = !!config.noObstacles;
    G3D.visuals.configure(this, config, {
      defaultAssetPack: ASSET_PACK,
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
    });
    this.map = window.SpearCloisterLayout(this);
    var entitySpawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var playerRng = Core.domains.isActive(this, "scene")
      ? Core.domains.gameplayRng(this, "scene", "player_spawn")
      : entitySpawnRng;
    var cameraRng = Core.domains.baselineRng(this);
    var cameraOrientation = Core.domains.sample(this, "camera", "orientation", {
      yaw_offset_radians: 0,
      pitch_offset_radians: 0,
    });
    this.x = playerRng.range(-0.65, 0.65);
    this.z = playerRng.range(6.6, 7.2);
    var spawnSide = Core.domains.isActive(this, "scene") && playerRng.next() < 0.5 ? -1 : 1;
    this.z *= spawnSide;
    this.sceneStartYaw = PLAYER_START_YAW * spawnSide + cameraRng.range(-0.14, 0.14);
    this.yaw = this.sceneStartYaw + cameraOrientation.yaw_offset_radians;
    this.pitch = CAMERA_PITCH_DEFAULT
      + cameraRng.range(-0.025, 0.025)
      + cameraOrientation.pitch_offset_radians;
    this.health = null;
    this.maxHealth = null;
    this.healthUnlimited = true;
    this.nativeChargeHeld = false;
    this.chargeButton.reset();
    this.chargeElapsed = 0;
    this.playerAttackState = "ready";
    this.playerAttackPhaseRemaining = 0;
    this.playerAttackPhaseDuration = 0;
    this.lastSpearTrace = null;
    this.dodgeRemaining = 0;
    this.dodgeCooldown = 0;
    this.invulnerableRemaining = 0;
    this.dodgeVelocity = { x: 0, z: 0 };
    this.playerStaggerRemaining = 0;
    this.playerKnockbackRemaining = 0;
    this.playerKnockbackVelocity = { x: 0, z: 0 };
    this.playerMoving = false;
    this.starterPoint = this.buildStarterPoint();
    this.covers = this.map.colliders;
    this.enemies = [];
    this.respawnQueue = [];
    this.enemySerial = 0;
    this.maxEnemySpawnDistance = 0;
    this.targetEnemyCount = 1;

    this.kills = 0;
    this.damageDealt = 0;
    this.damageTaken = 0;
    this.chargeStarts = 0;
    this.chargeReleases = 0;
    this.chargedReleases = 0;
    this.underchargedReleases = 0;
    this.chargeInterruptions = 0;
    this.chargeHeldMs = 0;
    this.spearThrusts = 0;
    this.spearHits = 0;
    this.spearWhiffs = 0;
    this.spearBlockedThrusts = 0;
    this.dodges = 0;
    this.attacksDodged = 0;
    this.enemyAttacks = 0;
    this.enemyHits = 0;
    this.enemyAttacksInterrupted = 0;
    this.enemyTelegraphs = 0;
    this.enemyStaggers = 0;
    this.enemyKnockbacks = 0;
    this.playerKnockbacks = 0;
    this.enemiesSpawned = 0;
    this.enemyRespawns = 0;
    this.enemyOrbits = 0;
    this.enemyReturns = 0;
    this.enemyJumps = 0;
    this.enemyHoldMs = 0;
    this.hitsAfterEvade = 0;
    this.enemyDistanceTravelled = 0;
    this.enemyOutOfRangeMs = 0;
    this.playerCollisions = 0;
    this.enemyCollisions = 0;
    this.stepCount = 0;
    this.gameTimeMs = 0;
    this.lastDamageSource = null;
    this.lastAction = "reset";
    this.mode = config.autostart ? "playing" : "paused";
    this.terminal = { isTerminal: false, outcome: null, reason: null };
    this.controls = { forward: false, back: false, left: false, right: false };

    var initialEnemy = this.spawnEnemy(false, this.starterPoint);
    this.initializeCamera(initialEnemy);
    if (countReset) this.runtime.resetCount += 1;
    this.runtime.episodeCount += 1;
    this.runtime.lastResetMethod = countReset ? "inplace_reset" : "init";
    this.rebuildScene3D();
    this.updateBestMetrics();
    this.render();
    return { accepted: normalized, applied: config, notes: [] };
  };

  Base3DDuel.prototype.initializeCamera = function initializeCamera(enemy) {
    // Keep camera sampling independent of scene and legacy gameplay RNG streams.
    var rng = new U.Rng((Core.seeds.forDomain(this, "camera") ^ 0x63616d32) >>> 0, DEFAULT_SEED,
      { allowZeroSeed: true });
    var yawMode = rng.randint(-1, 2);
    var pitchMode = rng.randint(-1, 2);
    var yawResidual = yawMode * rng.range(0.12, 0.28);
    var pitchResidual = pitchMode * rng.range(0.06, 0.12);
    var rig = Core.domains.sample(this, "camera", "rig", { height_scale: 1, pitch_offset_radians: 0 });
    var target = this.combatPoint(enemy);
    var dx = target.x - this.x;
    var dz = target.z - this.z;
    var referenceYaw = Math.atan2(dz, dx);
    var referencePitch = Math.atan2(
      target.y - (FLOOR_Y + PLAYER_EYE_HEIGHT * rig.height_scale),
      Math.max(0.0001, Math.hypot(dx, dz))
    ) - rig.pitch_offset_radians;
    this.yaw = U.math.normalizeAngle(referenceYaw + yawResidual);
    this.pitch = U.math.clamp(referencePitch + pitchResidual, CAMERA_PITCH_MIN, CAMERA_PITCH_MAX);
    this.cameraInitialization = {
      target_id: enemy.id,
      reference_yaw: referenceYaw,
      reference_pitch: referencePitch,
      yaw_residual: yawResidual,
      pitch_residual: pitchResidual,
      applied_pitch: this.pitch,
    };
  };

  Base3DDuel.prototype.buildStarterPoint = function buildStarterPoint() {
    var entitySpawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var distance = entitySpawnRng.range(ENEMY_STARTER_DISTANCE_MIN, ENEMY_STARTER_DISTANCE_MAX);
    var side = entitySpawnRng.next() < 0.5 ? -1 : 1;
    var heading = this.sceneStartYaw + side * entitySpawnRng.range(
      ENEMY_STARTER_SIDE_ANGLE_MIN,
      ENEMY_STARTER_SIDE_ANGLE_MAX,
    );
    return {
      x: U.math.clamp(this.x + Math.cos(heading) * distance, ARENA_MIN_X + 1.1, ARENA_MAX_X - 1.1),
      z: U.math.clamp(this.z + Math.sin(heading) * distance, ARENA_MIN_Z + 1.1, ARENA_MAX_Z - 1.1),
    };
  };

  Base3DDuel.prototype.coverBounds = function coverBounds(cover, padding) {
    var bounds = U.geometry3d.aabbFromBox(cover);
    var amount = Math.max(0, Number(padding) || 0);
    return {
      minX: bounds.minX - amount,
      maxX: bounds.maxX + amount,
      minY: bounds.minY - amount,
      maxY: bounds.maxY + amount,
      minZ: bounds.minZ - amount,
      maxZ: bounds.maxZ + amount,
    };
  };


  Base3DDuel.prototype.bindInput = function bindInput() {
    this.inputController = G3D.input.createController(this, {
      canvas: canvas,
      controlAliases: {
        dodge: [" ", "Space", "Spacebar"],
      },
      onPress: function onPress(control) {
        if (control === "dodge") this.startDodge();
      },
      onLook: function onLook(dx, dy) { this.applyMouse(dx, dy); },
      onMouseDown: function onMouseDown(event) {
        if (event.button === 0) {
          this.nativeChargeHeld = true;
          this.setChargeHeld(true);
        }
      },
      onMouseUp: function onMouseUp(event) {
        if (event.button === 0) {
          this.nativeChargeHeld = false;
          this.setChargeHeld(false);
        }
      },
      onReset: function onReset() {
        this.nativeChargeHeld = false;
        this.setChargeHeld(false);
      },
    });
    var app = document.getElementById("app");
    if (app) app.focus();
    canvas.focus();
  };

  Base3DDuel.prototype.ensureSimulationRunner = function ensureSimulationRunner() {
    if (this.simulationRunner) return this.simulationRunner;
    var self = this;
    this.simulationRunner = Core.createFixedStepRunner({
      game: this,
      stepMs: STEP_MS,
      maxFrameDeltaMs: 100,
      update: function update(stepMs) { self.update(stepMs / 1000); },
      render: function render() { self.render(); },
      isActive: function isActive() {
        return self.mode === "playing" && !self.paused && !self.terminal.isTerminal;
      },
    });
    return this.simulationRunner;
  };

  Base3DDuel.prototype.startLoop = function startLoop() {
    this.ensureSimulationRunner().start();
  };

  Base3DDuel.prototype.pause = function pause() {
    return Core.lifecycle.pause(this);
  };

  Base3DDuel.prototype.resume = function resume() {
    return Core.lifecycle.resume(this);
  };

  Base3DDuel.prototype.cameraLookOptions = function cameraLookOptions() {
    return {
      sensitivity: LOOK_SENSITIVITY * this.controlResponse.applied.look_gain_scale,
      pitchKey: "pitch",
      pitchSign: -1,
      pitchMin: CAMERA_PITCH_MIN,
      pitchMax: CAMERA_PITCH_MAX,
    };
  };

  Base3DDuel.prototype.applyMouse = function applyMouse(dx, dy) {
    if (this.terminal.isTerminal) return;
    if (this.mode === "paused") this.mode = "playing";
    G3D.input.applyPointerLook(this, dx, dy, this.cameraLookOptions());
    this.lastAction = "orbit(" + dx.toFixed(1) + "," + dy.toFixed(1) + ")";
  };

  Base3DDuel.prototype.applyRelativePointerInput = function applyRelativePointerInput(pointerInput) {
    if (this.terminal.isTerminal || !pointerInput) return;
    if (this.mode === "paused") this.mode = "playing";
    G3D.input.applyRelativePointerInput(this, pointerInput, this.cameraLookOptions());
    this.lastAction = "relative_pointer(" + pointerInput.dx + "," + pointerInput.dy + ")";
  };

  Base3DDuel.prototype.addReward = function addReward(value) {
    Core.reward.add(this, value);
  };

  Base3DDuel.prototype.difficultyRatio = function difficultyRatio() {
    return U.math.clamp((this.difficulty - 1) / Math.max(1, MAX_DIFFICULTY - 1), 0, 1);
  };

  Base3DDuel.prototype.circleOverlapsCover = function circleOverlapsCover(x, z, radius) {
    for (var i = 0; i < this.covers.length; i += 1) {
      if (U.geometry3d.circleOverlapsAabbXZ(x, z, radius, this.coverBounds(this.covers[i]))) return true;
    }
    return false;
  };

  Base3DDuel.prototype.lineBlocked = function lineBlocked(from, to) {
    var start = this.combatPoint(from);
    var end = this.combatPoint(to);
    var segmentLength = U.geometry3d.distance(start, end);
    for (var i = 0; i < this.covers.length; i += 1) {
      var hit = U.geometry3d.segmentAabbHitDistance(start, end, this.coverBounds(this.covers[i]), 0.02);
      if (hit !== null && hit < segmentLength - 0.08) return true;
    }
    return false;
  };

  Base3DDuel.prototype.combatPoint = function combatPoint(actor) {
    if (actor === this) {
      return { x: this.x, y: PLAYER_COMBAT_CENTER_HEIGHT, z: this.z };
    }
    var profile = profileById(actor && actor.type);
    return {
      x: Number(actor && actor.x) || 0,
      y: (Number(actor && actor.y) || 0) + PLAYER_HEIGHT * profile.scale * 0.78,
      z: Number(actor && actor.z) || 0,
    };
  };

  Base3DDuel.prototype.playerEyePoint = function playerEyePoint() {
    return { x: this.x, y: FLOOR_Y + PLAYER_EYE_HEIGHT, z: this.z };
  };

  Base3DDuel.prototype.enemyHitVolume = function enemyHitVolume(enemy) {
    var profile = profileById(enemy && enemy.type);
    var scale = profile.scale;
    var baseY = Number(enemy && enemy.y) || FLOOR_Y;
    return {
      x: Number(enemy && enemy.x) || 0,
      z: Number(enemy && enemy.z) || 0,
      bottomY: baseY,
      topY: baseY + PLAYER_HEIGHT * scale,
      radius: PLAYER_SPEAR_BODY_RADIUS * scale,
    };
  };

  Base3DDuel.prototype.enemySpawnBlocked = function enemySpawnBlocked(point) {
    if (this.circleOverlapsCover(point.x, point.z, ENEMY_RADIUS + 0.12)) return true;
    for (var i = 0; i < this.enemies.length; i += 1) {
      if (!this.enemies[i].alive) continue;
      if (U.geometry3d.horizontalDistance(point, this.enemies[i]) < ENEMY_RADIUS * 2 + 0.55) return true;
    }
    return false;
  };

  Base3DDuel.prototype.sampleEnemySpawnPoint = function sampleEnemySpawnPoint(referenceYaw) {
    var self = this;
    var spawnYaw = Number.isFinite(referenceYaw) ? referenceYaw : this.yaw;
    var spawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var options = {
      bounds: { minX: ARENA_MIN_X, maxX: ARENA_MAX_X, minZ: ARENA_MIN_Z, maxZ: ARENA_MAX_Z },
      radius: ENEMY_RADIUS + 0.12,
      colliders: this.covers,
      reference: { x: this.x, z: this.z },
      minDistance: ENEMY_SPAWN_MIN_DISTANCE,
      maxDistance: ENEMY_SPAWN_MAX_DISTANCE,
      heading: spawnYaw,
      minAngleOffset: ENEMY_SPAWN_SIDE_ANGLE_MIN,
      maxAngleOffset: ENEMY_SPAWN_SIDE_ANGLE_MAX,
      mirrorAngle: true,
      maxAttempts: 192,
      accept: function accept(candidate) {
        // The route starts at the player; enemy clearance is checked at the destination.
        return !self.enemySpawnBlocked(candidate) && self.map.contains(candidate.x, candidate.z, ENEMY_RADIUS + 0.12)
          && self.map.segmentClear(self, candidate, PLAYER_RADIUS);
      },
    };
    var point = U.geometry3d.sampleOpenPointXZ(spawnRng, options);
    if (point) return point;
    var unrestrictedOptions = Object.assign({}, options, {
      minAngleOffset: -Math.PI,
      maxAngleOffset: Math.PI,
      mirrorAngle: false,
      maxAttempts: 384,
    });
    point = U.geometry3d.sampleOpenPointXZ(spawnRng, unrestrictedOptions);
    if (point) return point;
    throw new Error("Unable to sample an in-range enemy spawn point");
  };

  Base3DDuel.prototype.spawnEnemy = function spawnEnemy(isRespawn, explicitPoint, referenceYaw) {
    var entitySpawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var point = explicitPoint || this.sampleEnemySpawnPoint(referenceYaw);
    var profile = entitySpawnRng.choice(ENEMY_PROFILES);
    var behaviorRng = Core.domains.createEntityRng(this, entitySpawnRng, DEFAULT_SEED);
    var ratio = this.difficultyRatio();
    var spawnDistance = U.geometry3d.horizontalDistance(this, point);
    var heading = Math.atan2(this.z - point.z, this.x - point.x);
    var enemy = {
      id: "enemy_" + (this.enemySerial + 1),
      type: profile.id,
      x: point.x,
      y: FLOOR_Y,
      z: point.z,
      radius: ENEMY_RADIUS * profile.scale,
      spawnDistance: spawnDistance,
      returnDistance: spawnDistance,
      heading: heading,
      health: profile.health,
      maxHealth: profile.health,
      orbitSpeed: profile.orbitSpeed * ENEMY_LATERAL_SPEED_SCALE * (1 + ratio * 0.14),
      jumpWeight: U.math.clamp(profile.jumpWeight + ratio * 0.1, 0, 0.75),
      windupSeconds: profile.windupSeconds * (1 - ratio * 0.24),
      recoverySeconds: profile.recoverySeconds * (1 - ratio * 0.16),
      strafeSign: behaviorRng.next() < 0.5 ? -1 : 1,
      attackCooldown: behaviorRng.range(0.35, 0.78),
      combatState: "ready",
      locomotionState: "hold",
      locomotionRemaining: behaviorRng.range(0.65, 0.95),
      jumpCooldown: behaviorRng.range(0.45, 0.9),
      jumpDecisionRemaining: profile.id === "hopper" ? behaviorRng.range(1.1, 1.9) : null,
      verticalVelocity: 0,
      grounded: true,
      evadedSinceLastHit: false,
      pendingLocomotionReason: null,
      phaseRemaining: 0,
      phaseDuration: 0,
      attackApplied: false,
      attacks: 0,
      hits: 0,
      dodgedAttacks: 0,
      knockbackRemaining: 0,
      knockbackVelocity: { x: 0, z: 0 },
      alive: true,
      moving: false,
    };
    enemy.behaviorRng = behaviorRng;
    this.enemySerial += 1;
    this.enemiesSpawned += 1;
    this.maxEnemySpawnDistance = Math.max(this.maxEnemySpawnDistance, spawnDistance);
    if (isRespawn) this.enemyRespawns += 1;
    this.enemies.push(enemy);
    if (this.sceneReady) this.attachEnemyMesh(enemy);
    return enemy;
  };

  Base3DDuel.prototype.controlDirection = function controlDirection() {
    var move = G3D.input.moveDelta(this.yaw, this.controls, 1, 1);
    var direction = normalizedDirection(move.x, move.z);
    if (direction.length <= 0) return { x: Math.cos(this.yaw), z: Math.sin(this.yaw) };
    return direction;
  };

  Base3DDuel.prototype.cancelCharge = function cancelCharge(reason) {
    if (this.chargeElapsed <= 0) return false;
    this.chargeElapsed = 0;
    this.chargeInterruptions += 1;
    if (reason) this.lastAction = "charge_interrupted_" + reason;
    return true;
  };

  Base3DDuel.prototype.setChargeHeld = function setChargeHeld(value) {
    if (this.terminal && this.terminal.isTerminal) value = false;
    var changed = this.chargeButton.setDown(value);
    if (value && this.mode === "paused") this.mode = "playing";
    if (changed) this.lastAction = value ? "charge_pressed" : "charge_released";
    return changed;
  };

  Base3DDuel.prototype.startDodge = function startDodge() {
    if (this.terminal.isTerminal || this.dodgeCooldown > 0 || this.playerStaggerRemaining > 0) return false;
    if (this.mode === "paused") this.mode = "playing";
    var direction = this.controlDirection();
    this.dodgeVelocity = { x: direction.x, z: direction.z };
    this.dodgeRemaining = DODGE_SECONDS;
    this.invulnerableRemaining = DODGE_SECONDS;
    this.dodgeCooldown = DODGE_COOLDOWN_SECONDS;
    this.dodges += 1;
    this.cancelCharge("dodge");
    this.lastAction = "dodge";
    return true;
  };

  Base3DDuel.prototype.tryMovePlayer = function tryMovePlayer(dx, dz) {
    var movement = U.geometry3d.moveCircleWithAabbs(
      { x: this.x, z: this.z },
      { x: dx, z: dz },
      {
        radius: PLAYER_RADIUS,
        bounds: { minX: ARENA_MIN_X, maxX: ARENA_MAX_X, minZ: ARENA_MIN_Z, maxZ: ARENA_MAX_Z },
        colliders: this.covers,
        circles: this.enemies,
        circlePadding: PLAYER_ENEMY_COLLISION_PADDING,
        circleFilter: function liveEnemy(enemy) { return enemy.alive; },
      }
    );
    this.x = movement.x;
    this.z = movement.z;
    if (movement.blockedX || movement.blockedZ) this.playerCollisions += 1;
    return movement.movedX || movement.movedZ;
  };

  Base3DDuel.prototype.updatePlayerMotion = function updatePlayerMotion(dt) {
    var beforeX = this.x;
    var beforeZ = this.z;
    if (this.playerKnockbackRemaining > 0) {
      this.tryMovePlayer(
        this.playerKnockbackVelocity.x * PLAYER_KNOCKBACK_SPEED * dt,
        this.playerKnockbackVelocity.z * PLAYER_KNOCKBACK_SPEED * dt,
      );
      this.playerKnockbackRemaining = Math.max(0, this.playerKnockbackRemaining - dt);
    } else if (this.dodgeRemaining > 0) {
      var dodgeMoved = this.tryMovePlayer(
        this.dodgeVelocity.x * DODGE_SPEED * dt,
        this.dodgeVelocity.z * DODGE_SPEED * dt,
      );
      if (!dodgeMoved) this.dodgeRemaining = 0;
    } else {
      var speedScale = this.playerStaggerRemaining > 0 ? 0.35 : 1;
      var move = G3D.input.moveDelta(this.yaw, this.controls, PLAYER_MOVE_SPEED * this.controlResponse.applied.move_scale * speedScale, dt);
      if (move.forward && move.strafe) {
        move.x *= Math.SQRT1_2;
        move.z *= Math.SQRT1_2;
      }
      if (move.x || move.z) this.tryMovePlayer(move.x, move.z);
    }
    this.playerMoving = Math.abs(this.x - beforeX) + Math.abs(this.z - beforeZ) > 0.000001;
  };

  Base3DDuel.prototype.playerAimPitch = function playerAimPitch() {
    return this.pitch;
  };

  Base3DDuel.prototype.playerAimDirection = function playerAimDirection() {
    return G3D.input.directionFromLook(this.yaw, this.playerAimPitch());
  };

  Base3DDuel.prototype.enemyAimErrors = function enemyAimErrors(enemy) {
    if (!enemy) return { yaw: null, pitch: null };
    var origin = this.playerEyePoint();
    var target = this.combatPoint(enemy);
    var horizontal = Math.sqrt(
      Math.pow(target.x - origin.x, 2) + Math.pow(target.z - origin.z, 2)
    );
    return {
      yaw: U.math.normalizeAngle(Math.atan2(target.z - origin.z, target.x - origin.x) - this.yaw),
      pitch: Math.atan2(target.y - origin.y, Math.max(0.0001, horizontal)) - this.playerAimPitch(),
    };
  };

  Base3DDuel.prototype.playerSpearTrace = function playerSpearTrace() {
    var origin = this.playerEyePoint();
    var direction = this.playerAimDirection();
    var nearestEnemy = null;
    for (var i = 0; i < this.enemies.length; i += 1) {
      var enemy = this.enemies[i];
      if (!enemy.alive) continue;
      var enemyHit = U.geometry3d.raycastVerticalCapsule(
        origin,
        direction,
        this.enemyHitVolume(enemy),
        { maxDistance: PLAYER_SPEAR_REACH }
      );
      if (!enemyHit || (nearestEnemy && enemyHit.distance >= nearestEnemy.hit.distance)) continue;
      nearestEnemy = { enemy: enemy, hit: enemyHit };
    }
    var self = this;
    var coverHit = U.geometry3d.raycastAabbs(origin, direction, this.covers, {
      maxDistance: PLAYER_SPEAR_REACH,
      bounds: function bounds(cover) { return self.coverBounds(cover); },
    });
    var blocked = !!nearestEnemy && !!coverHit
      && coverHit.distance < nearestEnemy.hit.distance - PLAYER_SPEAR_OCCLUSION_EPSILON;
    var targetHit = nearestEnemy && !blocked ? nearestEnemy.hit : null;
    var endpointHit = targetHit;
    if (coverHit && (!endpointHit || coverHit.distance < endpointHit.distance)) endpointHit = coverHit;
    return {
      origin: origin,
      direction: direction,
      enemy: targetHit ? nearestEnemy.enemy : null,
      enemyHit: nearestEnemy ? nearestEnemy.hit : null,
      coverHit: coverHit,
      blocked: blocked,
      endpoint: endpointHit ? endpointHit.point : {
        x: origin.x + direction.x * PLAYER_SPEAR_REACH,
        y: origin.y + direction.y * PLAYER_SPEAR_REACH,
        z: origin.z + direction.z * PLAYER_SPEAR_REACH,
      },
    };
  };

  Base3DDuel.prototype.damageEnemy = function damageEnemy(enemy, damage) {
    if (!enemy || !enemy.alive) return false;
    var interruptedAttack = enemy.combatState === "windup"
      || (enemy.combatState === "active" && !enemy.attackApplied);
    var applied = Math.min(enemy.health, Math.max(0, damage));
    enemy.health -= applied;
    this.damageDealt += applied;
    enemy.returnDistance = Math.min(
      U.geometry3d.horizontalDistance(this, enemy),
      this.enemySpearReachLimit(enemy),
    );
    var push = normalizedDirection(enemy.x - this.x, enemy.z - this.z);
    enemy.knockbackVelocity = { x: push.x, z: push.z };
    enemy.knockbackRemaining = ENEMY_KNOCKBACK_SECONDS;
    enemy.combatState = "stagger";
    enemy.phaseDuration = ENEMY_STAGGER_SECONDS;
    enemy.phaseRemaining = ENEMY_STAGGER_SECONDS;
    enemy.pendingLocomotionReason = "hit";
    enemy.moving = false;
    if (interruptedAttack) this.enemyAttacksInterrupted += 1;
    if (enemy.evadedSinceLastHit) {
      this.hitsAfterEvade += 1;
      enemy.evadedSinceLastHit = false;
    }
    this.enemyStaggers += 1;
    this.enemyKnockbacks += 1;
    if (enemy.health > 0) {
      this.lastAction = "spear_hit";
      return false;
    }
    enemy.alive = false;
    this.kills += 1;
    this.respawnQueue.push({
      remaining: enemy.behaviorRng.range(
        RESPAWN_MIN_SECONDS,
        RESPAWN_MIN_SECONDS + RESPAWN_JITTER_SECONDS
      ),
    });
    this.lastAction = "spear_kill";
    return true;
  };

  Base3DDuel.prototype.beginPlayerAttackPhase = function beginPlayerAttackPhase(state, duration) {
    this.playerAttackState = state;
    this.playerAttackPhaseDuration = duration;
    this.playerAttackPhaseRemaining = duration;
  };

  Base3DDuel.prototype.resolveSpearThrust = function resolveSpearThrust() {
    var trace = this.playerSpearTrace();
    this.lastSpearTrace = trace;
    this.spearThrusts += 1;
    this.beginPlayerAttackPhase("thrust", PLAYER_SPEAR_THRUST_SECONDS);
    if (trace.blocked) {
      this.spearBlockedThrusts += 1;
      this.spearWhiffs += 1;
      this.lastAction = "spear_blocked";
      return false;
    }
    if (!trace.enemy) {
      this.spearWhiffs += 1;
      this.lastAction = "spear_whiff";
      return false;
    }
    this.spearHits += 1;
    this.addReward(rewardConfig.constants.hitReward);
    this.damageEnemy(trace.enemy, PLAYER_SPEAR_DAMAGE);
    return true;
  };

  Base3DDuel.prototype.updatePlayerAttackPhase = function updatePlayerAttackPhase(dt) {
    if (this.playerAttackState === "ready") return;
    this.playerAttackPhaseRemaining = Math.max(0, this.playerAttackPhaseRemaining - dt);
    if (this.playerAttackPhaseRemaining > 0) return;
    if (this.playerAttackState === "thrust") {
      this.beginPlayerAttackPhase("recovery", PLAYER_SPEAR_RECOVERY_SECONDS);
      return;
    }
    this.playerAttackState = "ready";
    this.playerAttackPhaseDuration = 0;
    this.lastSpearTrace = null;
  };

  Base3DDuel.prototype.updateChargedSpear = function updateChargedSpear(dt) {
    this.chargeButton.advance(dt * 1000);
    if (this.chargeButton.pressed_this_step) this.chargeStarts += 1;
    if (this.chargeButton.down) this.chargeHeldMs += dt * 1000;

    if (this.chargeButton.released_this_step) {
      this.chargeReleases += 1;
      var charged = this.chargeElapsed + 0.000001 >= PLAYER_SPEAR_CHARGE_SECONDS;
      var canThrust = this.playerAttackState === "ready"
        && this.dodgeRemaining <= 0
        && this.playerStaggerRemaining <= 0;
      if (charged && canThrust) {
        this.chargedReleases += 1;
        this.resolveSpearThrust();
      } else {
        this.underchargedReleases += 1;
            this.lastAction = charged ? "charge_interrupted" : "charge_undercharged";
      }
      this.chargeElapsed = 0;
    }

    this.updatePlayerAttackPhase(dt);
    var canCharge = this.chargeButton.down
      && this.playerAttackState === "ready"
      && this.dodgeRemaining <= 0
      && this.playerStaggerRemaining <= 0;
    if (canCharge) {
      var wasReady = this.chargeElapsed + 0.000001 >= PLAYER_SPEAR_CHARGE_SECONDS;
      this.chargeElapsed = Math.min(PLAYER_SPEAR_CHARGE_SECONDS, this.chargeElapsed + dt);
      if (!wasReady && this.chargeElapsed + 0.000001 >= PLAYER_SPEAR_CHARGE_SECONDS) {
        this.lastAction = "charge_ready";
      }
    } else if (this.chargeButton.down && this.chargeElapsed > 0) {
      this.cancelCharge(this.dodgeRemaining > 0 ? "dodge" : "stagger");
    }
    this.chargeButton.endStep();
  };

  Base3DDuel.prototype.turnEnemyTowardPlayer = function turnEnemyTowardPlayer(enemy, dt) {
    var target = Math.atan2(this.z - enemy.z, this.x - enemy.x);
    var error = U.math.normalizeAngle(target - enemy.heading);
    var maxTurn = (enemy.combatState === "windup" ? 2.2 : 4.5) * dt;
    enemy.heading = U.math.normalizeAngle(enemy.heading + U.math.clamp(error, -maxTurn, maxTurn));
  };

  Base3DDuel.prototype.enemyPositionAvailable = function enemyPositionAvailable(enemy, x, z) {
    if (U.geometry3d.horizontalDistance({ x: x, z: z }, this) < PLAYER_RADIUS + enemy.radius + 0.08) return false;
    for (var i = 0; i < this.enemies.length; i += 1) {
      var other = this.enemies[i];
      if (other === enemy || !other.alive) continue;
      if (U.geometry3d.horizontalDistance({ x: x, z: z }, other) < enemy.radius + other.radius + 0.12) return false;
    }
    return true;
  };

  Base3DDuel.prototype.enemySpearReachLimit = function enemySpearReachLimit(enemy) {
    return PLAYER_SPEAR_REACH + enemy.radius - ENEMY_SPEAR_REACH_MARGIN;
  };

  Base3DDuel.prototype.moveEnemy = function moveEnemy(enemy, dx, dz, options) {
    var opts = options || {};
    var beforeX = enemy.x;
    var beforeZ = enemy.z;
    var movement = U.geometry3d.moveCircleWithAabbs(
      { x: enemy.x, z: enemy.z },
      { x: dx, z: dz },
      {
        radius: enemy.radius,
        bounds: { minX: ARENA_MIN_X, maxX: ARENA_MAX_X, minZ: ARENA_MIN_Z, maxZ: ARENA_MAX_Z },
        colliders: this.covers,
      }
    );
    var maxDistanceFromPlayer = Number(opts.maxDistanceFromPlayer);
    var beforeDistance = U.geometry3d.horizontalDistance(this, enemy);
    var candidateDistance = U.geometry3d.horizontalDistance(this, movement);
    var reachBlocked = Number.isFinite(maxDistanceFromPlayer)
      && candidateDistance > Math.max(maxDistanceFromPlayer, beforeDistance) + 0.000001;
    var moved = false;
    if (!reachBlocked && this.enemyPositionAvailable(enemy, movement.x, movement.z)) {
      moved = movement.movedX || movement.movedZ;
      enemy.x = movement.x;
      enemy.z = movement.z;
    }
    if (moved) {
      this.enemyDistanceTravelled += Math.sqrt(
        Math.pow(enemy.x - beforeX, 2) + Math.pow(enemy.z - beforeZ, 2)
      );
    }
    var blocked = movement.blockedX || movement.blockedZ || reachBlocked || !moved;
    if (blocked) this.enemyCollisions += 1;
    enemy.moving = moved;
    return { moved: moved, blocked: blocked };
  };

  Base3DDuel.prototype.moveEnemyAlongOrbit = function moveEnemyAlongOrbit(enemy, distance) {
    var offsetX = enemy.x - this.x;
    var offsetZ = enemy.z - this.z;
    var currentRadius = Math.sqrt(offsetX * offsetX + offsetZ * offsetZ);
    if (currentRadius <= 0.000001) return { moved: false, blocked: true };
    var orbitRadius = Math.min(currentRadius, this.enemySpearReachLimit(enemy));
    var angle = Math.atan2(offsetZ, offsetX)
      - enemy.strafeSign * Math.max(0, distance) / Math.max(0.000001, orbitRadius);
    var targetX = this.x + Math.cos(angle) * orbitRadius;
    var targetZ = this.z + Math.sin(angle) * orbitRadius;
    return this.moveEnemy(enemy, targetX - enemy.x, targetZ - enemy.z, {
      maxDistanceFromPlayer: this.enemySpearReachLimit(enemy),
    });
  };

  Base3DDuel.prototype.startEnemyWindup = function startEnemyWindup(enemy) {
    enemy.combatState = "windup";
    enemy.phaseDuration = enemy.windupSeconds;
    enemy.phaseRemaining = enemy.windupSeconds;
    enemy.attackApplied = false;
    enemy.moving = false;
    this.enemyTelegraphs += 1;
  };

  Base3DDuel.prototype.takePlayerDamage = function takePlayerDamage(enemy) {
    this.damageTaken += 1;
    this.enemyHits += 1;
    this.lastDamageSource = enemy.id;
    this.lastAction = "player_hit";
    this.playerStaggerRemaining = PLAYER_STAGGER_SECONDS;
    var push = normalizedDirection(this.x - enemy.x, this.z - enemy.z);
    this.playerKnockbackVelocity = { x: push.x, z: push.z };
    this.playerKnockbackRemaining = PLAYER_KNOCKBACK_SECONDS;
    this.playerKnockbacks += 1;
    this.cancelCharge("enemy_hit");
    this.addReward(-rewardConfig.constants.hitPenalty);
  };

  Base3DDuel.prototype.resolveEnemyAttack = function resolveEnemyAttack(enemy) {
    enemy.attackApplied = true;
    enemy.attacks += 1;
    this.enemyAttacks += 1;
    var inRange = U.geometry3d.circleIntersectsSectorXZ(
      enemy,
      enemy.heading,
      { x: this.x, z: this.z, radius: PLAYER_RADIUS },
      {
        range: ENEMY_ATTACK_RANGE,
        halfAngle: ENEMY_ATTACK_HALF_ANGLE,
        targetRadius: PLAYER_RADIUS,
      }
    );
    if (!inRange || this.lineBlocked(enemy, this)) return;
    if (this.invulnerableRemaining > 0) {
      enemy.dodgedAttacks += 1;
      this.attacksDodged += 1;
      this.lastAction = "enemy_attack_dodged";
      return;
    }
    enemy.hits += 1;
    this.takePlayerDamage(enemy);
  };

  Base3DDuel.prototype.limitEnemyOrbitDuration = function limitEnemyOrbitDuration(enemy, duration) {
    var distance = U.geometry3d.horizontalDistance(this, enemy);
    var maxDuration = distance * ENEMY_ORBIT_MAX_SWEEP_RADIANS / Math.max(0.001, enemy.orbitSpeed);
    return Math.min(Math.max(0, Number(duration) || 0), maxDuration);
  };

  Base3DDuel.prototype.setEnemyLocomotion = function setEnemyLocomotion(enemy, state, duration) {
    var previous = enemy.locomotionState;
    if (state === "jump_reposition" && (!enemy.grounded || enemy.jumpCooldown > 0)) state = "orbit";
    if (state === "orbit" && previous === "orbit") {
      state = "hold";
      duration = enemy.behaviorRng.range(
        ENEMY_ORBIT_RECENTER_MIN_SECONDS,
        ENEMY_ORBIT_RECENTER_MAX_SECONDS,
      );
    }
    if (state === "orbit") duration = this.limitEnemyOrbitDuration(enemy, duration);
    enemy.locomotionState = state;
    enemy.locomotionRemaining = duration;
    if (previous === state) return;
    if (state === "orbit") this.enemyOrbits += 1;
    if (state === "return") this.enemyReturns += 1;
    if (state === "orbit" || state === "jump_reposition") {
      enemy.evadedSinceLastHit = true;
    }
    if (state === "jump_reposition") {
      enemy.verticalVelocity = ENEMY_JUMP_SPEED;
      enemy.grounded = false;
      enemy.jumpCooldown = enemy.behaviorRng.range(1.15, 1.8);
      this.enemyJumps += 1;
    }
  };

  Base3DDuel.prototype.chooseEnemyLocomotion = function chooseEnemyLocomotion(enemy, reason) {
    var roll = enemy.behaviorRng.next();
    if (reason === "hit") {
      if (roll < enemy.jumpWeight) {
        this.setEnemyLocomotion(enemy, "jump_reposition", enemy.behaviorRng.range(0.58, 0.82));
      } else {
        enemy.strafeSign = enemy.behaviorRng.next() < 0.5 ? -1 : 1;
        this.setEnemyLocomotion(enemy, "orbit", enemy.behaviorRng.range(0.36, 0.58));
      }
      return;
    }
    if (enemy.jumpCooldown <= 0 && roll < enemy.jumpWeight * 0.42) {
      this.setEnemyLocomotion(enemy, "jump_reposition", enemy.behaviorRng.range(0.58, 0.82));
    } else if (roll < 0.72) {
      enemy.strafeSign = enemy.behaviorRng.next() < 0.5 ? -1 : 1;
      this.setEnemyLocomotion(enemy, "orbit", enemy.behaviorRng.range(0.58, 1.05));
    } else {
      this.setEnemyLocomotion(enemy, "hold", enemy.behaviorRng.range(0.42, 0.78));
    }
  };

  Base3DDuel.prototype.updateEnemyVertical = function updateEnemyVertical(enemy, dt) {
    enemy.jumpCooldown = Math.max(0, enemy.jumpCooldown - dt);
    if (enemy.grounded) return;
    enemy.verticalVelocity -= ENEMY_GRAVITY * dt;
    enemy.y += enemy.verticalVelocity * dt;
    if (enemy.y <= FLOOR_Y) {
      enemy.y = FLOOR_Y;
      enemy.verticalVelocity = 0;
      enemy.grounded = true;
    }
  };

  Base3DDuel.prototype.updateEnemyLocomotion = function updateEnemyLocomotion(enemy, dt) {
    var toPlayer = normalizedDirection(this.x - enemy.x, this.z - enemy.z);
    if (enemy.locomotionState === "return") {
      var returnDistance = Math.min(enemy.returnDistance, this.enemySpearReachLimit(enemy));
      var distanceToRecover = toPlayer.length - returnDistance;
      if (distanceToRecover <= ENEMY_RETURN_TOLERANCE) {
        this.chooseEnemyLocomotion(enemy, "returned");
        enemy.moving = !enemy.grounded;
        return;
      }
      var returnStep = Math.min(ENEMY_RETURN_SPEED * dt, distanceToRecover);
      this.moveEnemy(enemy, toPlayer.x * returnStep, toPlayer.z * returnStep);
      enemy.moving = enemy.moving || !enemy.grounded;
      return;
    }
    if (enemy.jumpDecisionRemaining !== null) {
      enemy.jumpDecisionRemaining = Math.max(0, enemy.jumpDecisionRemaining - dt);
      if (enemy.jumpDecisionRemaining <= 0 && enemy.grounded && enemy.jumpCooldown <= 0 && toPlayer.length <= 3.1) {
        enemy.jumpDecisionRemaining = enemy.behaviorRng.range(1.8, 2.8);
        this.setEnemyLocomotion(enemy, "jump_reposition", enemy.behaviorRng.range(0.62, 0.82));
      }
    }
    var canAttack = enemy.grounded
      && (enemy.locomotionState === "hold" || enemy.locomotionState === "orbit")
      && toPlayer.length <= ENEMY_ATTACK_TRIGGER_DISTANCE
      && enemy.attackCooldown <= 0
      && !this.lineBlocked(enemy, this);
    if (canAttack) {
      this.startEnemyWindup(enemy);
      return;
    }

    enemy.locomotionRemaining = Math.max(0, enemy.locomotionRemaining - dt);
    if (enemy.locomotionRemaining <= 0 || (enemy.locomotionState === "jump_reposition" && enemy.grounded)) {
      this.chooseEnemyLocomotion(enemy, "cycle");
    }
    if (enemy.locomotionState === "hold") {
      this.enemyHoldMs += dt * 1000;
      enemy.moving = !enemy.grounded;
      return;
    }
    var speed = 0;
    if (enemy.locomotionState === "orbit") {
      speed = enemy.orbitSpeed;
    } else if (enemy.locomotionState === "jump_reposition") {
      speed = enemy.orbitSpeed;
    }
    var step = speed * dt;
    var result = this.moveEnemyAlongOrbit(enemy, step);
    if (result.blocked) {
      enemy.strafeSign *= -1;
      var alternate = this.moveEnemyAlongOrbit(enemy, step);
      if (alternate.blocked) this.setEnemyLocomotion(enemy, "hold", enemy.behaviorRng.range(0.4, 0.7));
    }
    enemy.moving = enemy.moving || !enemy.grounded;
  };

  Base3DDuel.prototype.updateEnemy = function updateEnemy(enemy, dt) {
    if (!enemy.alive) return true;
    enemy.attackCooldown = Math.max(0, enemy.attackCooldown - dt);
    this.updateEnemyVertical(enemy, dt);
    this.turnEnemyTowardPlayer(enemy, dt);

    if (enemy.knockbackRemaining > 0) {
      this.moveEnemy(
        enemy,
        enemy.knockbackVelocity.x * ENEMY_KNOCKBACK_SPEED * dt,
        enemy.knockbackVelocity.z * ENEMY_KNOCKBACK_SPEED * dt,
      );
      enemy.knockbackRemaining = Math.max(0, enemy.knockbackRemaining - dt);
    }

    if (enemy.combatState === "stagger") {
      enemy.moving = false;
      enemy.phaseRemaining = Math.max(0, enemy.phaseRemaining - dt);
      if (enemy.phaseRemaining <= 0) {
        enemy.combatState = "ready";
        enemy.attackCooldown = enemy.behaviorRng.range(0.28, 0.52);
        var shouldReturn = enemy.pendingLocomotionReason === "hit"
          && U.geometry3d.horizontalDistance(this, enemy) > enemy.returnDistance + ENEMY_RETURN_TOLERANCE;
        if (shouldReturn) this.setEnemyLocomotion(enemy, "return", 0);
        else this.chooseEnemyLocomotion(enemy, enemy.pendingLocomotionReason || "hit");
        enemy.pendingLocomotionReason = null;
      }
      return true;
    }

    if (enemy.combatState === "windup") {
      enemy.phaseRemaining = Math.max(0, enemy.phaseRemaining - dt);
      if (enemy.phaseRemaining <= 0) {
        enemy.combatState = "active";
        enemy.phaseDuration = ENEMY_ATTACK_ACTIVE_SECONDS;
        enemy.phaseRemaining = ENEMY_ATTACK_ACTIVE_SECONDS;
        enemy.attackApplied = false;
      }
      return true;
    }

    if (enemy.combatState === "active") {
      if (!enemy.attackApplied) {
        this.resolveEnemyAttack(enemy);
        if (this.terminal.isTerminal) return false;
      }
      enemy.phaseRemaining = Math.max(0, enemy.phaseRemaining - dt);
      if (enemy.phaseRemaining <= 0) {
        enemy.combatState = "recovery";
        enemy.phaseDuration = enemy.recoverySeconds;
        enemy.phaseRemaining = enemy.recoverySeconds;
      }
      return true;
    }

    if (enemy.combatState === "recovery") {
      enemy.phaseRemaining = Math.max(0, enemy.phaseRemaining - dt);
      if (enemy.phaseRemaining <= 0) {
        enemy.combatState = "ready";
        enemy.attackCooldown = enemy.behaviorRng.range(0.24, 0.5);
        this.chooseEnemyLocomotion(enemy, "recovery");
      }
      return true;
    }

    this.updateEnemyLocomotion(enemy, dt);
    return true;
  };

  Base3DDuel.prototype.updateEnemies = function updateEnemies(dt) {
    // Defeated opponents leave combat immediately; their stagger clock finishes the hit visual.
    this.enemies = this.enemies.filter(function retainHitVisual(enemy) {
      if (enemy.alive) return true;
      enemy.phaseRemaining = Math.max(0, enemy.phaseRemaining - dt);
      return enemy.phaseRemaining > 0;
    });
    var terminalBefore = Core.terminal.generation(this);
    for (var i = 0; i < this.enemies.length; i += 1) {
      if (!this.updateEnemy(this.enemies[i], dt)) return false;
      if (Core.terminal.generatedSince(this, terminalBefore)) return false;
    }
    return true;
  };

  Base3DDuel.prototype.updateRespawns = function updateRespawns(dt) {
    var pending = [];
    for (var i = 0; i < this.respawnQueue.length; i += 1) {
      this.respawnQueue[i].remaining -= dt;
      if (this.respawnQueue[i].remaining <= 0) this.spawnEnemy(true, null);
      else pending.push(this.respawnQueue[i]);
    }
    this.respawnQueue = pending;
  };

  Base3DDuel.prototype.update = function update(dt) {
    if (this.terminal.isTerminal || this.mode !== "playing" || this.paused) return;
    this.stepCount += 1;
    this.gameTimeMs += dt * 1000;
    this.dodgeRemaining = Math.max(0, this.dodgeRemaining - dt);
    this.dodgeCooldown = Math.max(0, this.dodgeCooldown - dt);
    this.invulnerableRemaining = Math.max(0, this.invulnerableRemaining - dt);
    this.playerStaggerRemaining = Math.max(0, this.playerStaggerRemaining - dt);
    this.updatePlayerMotion(dt);
    this.updateChargedSpear(dt);
    if (!this.updateEnemies(dt)) return;
    this.updateRespawns(dt);
    var nearestSurface = this.nearestEnemySurfaceDistance();
    if (nearestSurface !== null && nearestSurface > PLAYER_SPEAR_REACH) this.enemyOutOfRangeMs += dt * 1000;
    this.updateBestMetrics();
  };

  Base3DDuel.prototype.advanceTime = function advanceTime(ms, options) {
    var opts = typeof options === "object" && options !== null ? options : { render: options !== false };
    this.ensureSimulationRunner().advance(ms, opts);
    if (opts.returnState === false) return null;
    return this.getStatePayload();
  };

  Base3DDuel.prototype.normalizeAction = function normalizeAction(action) {
    var normalized = G3D.input.readAction(action, {
      controlAliases: {
        dodge: ["space", "Space", " "],
      },
    });
    return {
      id: normalized.id,
      args: normalized.args,
      forward: normalized.controls.forward,
      back: normalized.controls.back,
      left: normalized.controls.left,
      right: normalized.controls.right,
      dodge: normalized.controls.dodge,
      pointerInput: normalized.pointerInput,
      chargeHeld: normalized.mouseLeftHold,
    };
  };

  Base3DDuel.prototype.applyAction = function applyAction(normalized) {
    this.controls.forward = normalized.forward;
    this.controls.back = normalized.back;
    this.controls.left = normalized.left;
    this.controls.right = normalized.right;
    this.applyRelativePointerInput(normalized.pointerInput);
    if (normalized.dodge) this.startDodge();
    // Browser-owned holds are omitted from API actions until the native mouseup.
    this.setChargeHeld(normalized.chargeHeld || this.nativeChargeHeld);
    if (this.mode === "paused" && !this.paused) this.mode = "playing";
  };

  Base3DDuel.prototype.clearTransientControls = function clearTransientControls() {
    this.controls = { forward: false, back: false, left: false, right: false };
  };

  Base3DDuel.prototype.advanceSimulation = function advanceSimulation(ms) {
    var state = this.advanceTime(ms, { render: false });
    this.clearTransientControls();
    return state;
  };

  Base3DDuel.prototype.rewardMetrics = function rewardMetrics() {
    return {
      spear_hits: this.spearHits,
      damage_taken: this.damageTaken,
    };
  };

  Base3DDuel.prototype.rewardPayload = function rewardPayload() {
    var metrics = this.rewardMetrics();
    return {
      env_reward_step: this.envRewardStep,
      env_reward_episode: this.envRewardEpisode,
      primary_positive_score: rewardConfig.computePrimaryPositiveScore(metrics),
      primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(metrics),
      primary_score: rewardConfig.computePrimaryScore(metrics),
    };
  };

  Base3DDuel.prototype.getPrimaryScore = function getPrimaryScore() {
    return rewardConfig.computePrimaryScore(this.rewardMetrics());
  };

  Base3DDuel.prototype.chargeRatio = function chargeRatio() {
    return U.math.clamp(this.chargeElapsed / PLAYER_SPEAR_CHARGE_SECONDS, 0, 1);
  };

  Base3DDuel.prototype.chargeState = function chargeState() {
    if (this.playerAttackState !== "ready") return this.playerAttackState;
    if (this.chargeButton.down && this.chargeElapsed + 0.000001 >= PLAYER_SPEAR_CHARGE_SECONDS) {
      return "charged";
    }
    if (this.chargeButton.down) return "charging";
    return "ready";
  };

  Base3DDuel.prototype.enemyAttackAccuracy = function enemyAttackAccuracy() {
    return this.enemyAttacks > 0 ? this.enemyHits / this.enemyAttacks : 0;
  };

  Base3DDuel.prototype.nearestEnemyDistance = function nearestEnemyDistance() {
    var nearest = Infinity;
    for (var i = 0; i < this.enemies.length; i += 1) {
      if (this.enemies[i].alive) nearest = Math.min(nearest, U.geometry3d.horizontalDistance(this, this.enemies[i]));
    }
    return Number.isFinite(nearest) ? nearest : null;
  };

  Base3DDuel.prototype.nearestEnemySurfaceDistance = function nearestEnemySurfaceDistance() {
    var nearest = Infinity;
    for (var i = 0; i < this.enemies.length; i += 1) {
      var enemy = this.enemies[i];
      if (!enemy.alive) continue;
      nearest = Math.min(nearest, U.geometry3d.horizontalDistance(this, enemy) - enemy.radius);
    }
    return Number.isFinite(nearest) ? Math.max(0, nearest) : null;
  };

  Base3DDuel.prototype.activeOpponent = function activeOpponent() {
    for (var i = 0; i < this.enemies.length; i += 1) {
      if (this.enemies[i].alive) return this.enemies[i];
    }
    return null;
  };

  Base3DDuel.prototype.threateningEnemyCount = function threateningEnemyCount() {
    return this.enemies.filter(function threatening(enemy) {
      return enemy.alive && (enemy.combatState === "windup" || enemy.combatState === "active");
    }).length;
  };

  Base3DDuel.prototype.metricsPayload = function metricsPayload() {
    var rewards = this.rewardPayload();
    var opponent = this.activeOpponent();
    var aimErrors = this.enemyAimErrors(opponent);
    var crosshairTrace = this.playerSpearTrace();
    return {
      env_reward_step: rewards.env_reward_step,
      env_reward_episode: rewards.env_reward_episode,
      primary_positive_score: rewards.primary_positive_score,
      primary_penalty_score: rewards.primary_penalty_score,
      primary_score: rewards.primary_score,
      kills: this.kills,
      health: this.health,
      max_health: this.maxHealth,
      health_unlimited: this.healthUnlimited,
      damage_dealt: this.damageDealt,
      damage_taken: this.damageTaken,
      spear_hits: this.spearHits,
      spear_thrusts: this.spearThrusts,
      spear_whiffs: this.spearWhiffs,
      spear_blocked_thrusts: this.spearBlockedThrusts,
      charge_state: this.chargeState(),
      charge_button_down: this.chargeButton.down,
      charge_button_held_ms: Math.round(this.chargeButton.held_ms),
      charge_starts: this.chargeStarts,
      charge_releases: this.chargeReleases,
      charged_releases: this.chargedReleases,
      undercharged_releases: this.underchargedReleases,
      charge_interruptions: this.chargeInterruptions,
      charge_held_ms: Math.round(this.chargeHeldMs),
      charge_progress_ms: Math.round(this.chargeElapsed * 1000),
      charge_ratio: this.chargeRatio(),
      charge_ready: this.chargeElapsed + 0.000001 >= PLAYER_SPEAR_CHARGE_SECONDS,
      dodges: this.dodges,
      dodge_remaining_ms: Math.round(this.dodgeRemaining * 1000),
      dodge_cooldown_ms: Math.round(this.dodgeCooldown * 1000),
      invulnerable_remaining_ms: Math.round(this.invulnerableRemaining * 1000),
      attacks_dodged: this.attacksDodged,
      enemy_attacks: this.enemyAttacks,
      enemy_hits: this.enemyHits,
      enemy_attacks_interrupted: this.enemyAttacksInterrupted,
      enemy_attack_accuracy: this.enemyAttackAccuracy(),
      enemy_telegraphs: this.enemyTelegraphs,
      enemy_staggers: this.enemyStaggers,
      enemy_knockbacks: this.enemyKnockbacks,
      player_knockbacks: this.playerKnockbacks,
      enemies_alive: this.enemies.filter(function alive(enemy) { return enemy.alive; }).length,
      enemies_spawned: this.enemiesSpawned,
      enemy_respawns: this.enemyRespawns,
      respawns_pending: this.respawnQueue.length,
      opponent_profile: opponent ? opponent.type : null,
      opponent_combat_state: opponent ? opponent.combatState : null,
      opponent_locomotion_state: opponent ? opponent.locomotionState : null,
      opponent_airborne: opponent ? !opponent.grounded : false,
      enemy_orbits: this.enemyOrbits,
      enemy_returns: this.enemyReturns,
      enemy_jumps: this.enemyJumps,
      enemy_hold_ms: Math.round(this.enemyHoldMs),
      hits_after_evade: this.hitsAfterEvade,
      enemy_distance_travelled: this.enemyDistanceTravelled,
      max_enemy_spawn_distance: this.maxEnemySpawnDistance,
      enemy_out_of_range_ms: Math.round(this.enemyOutOfRangeMs),
      nearest_enemy_distance: this.nearestEnemyDistance(),
      aim_yaw_error: aimErrors.yaw,
      aim_pitch_error: aimErrors.pitch,
      opponent_under_crosshair: !!opponent && crosshairTrace.enemy === opponent,
      opponent_spear_blocked: !!opponent && crosshairTrace.blocked,
      threatening_enemies: this.threateningEnemyCount(),
      player_collisions: this.playerCollisions,
      enemy_collisions: this.enemyCollisions,
      step_count: this.stepCount,
      episode_count: this.runtime.episodeCount,
      best_primary_score: this.bestMetrics.bestPrimaryScore,
      difficulty: this.difficulty,
    };
  };

  Base3DDuel.prototype.serializeEnemies = function serializeEnemies() {
    var self = this;
    var crosshairTrace = this.playerSpearTrace();
    return this.enemies.filter(function alive(enemy) { return enemy.alive; }).map(function serialize(enemy) {
      return {
        id: enemy.id,
        type: "enemy",
        archetype: enemy.type,
        x: enemy.x,
        y: enemy.y,
        z: enemy.z,
        radius: enemy.radius,
        heading: enemy.heading,
        health: enemy.health,
        max_health: enemy.maxHealth,
        combat_state: enemy.combatState,
        locomotion_state: enemy.locomotionState,
        locomotion_remaining_ms: Math.round(enemy.locomotionRemaining * 1000),
        vertical_velocity: enemy.verticalVelocity,
        grounded: enemy.grounded,
        return_distance: enemy.returnDistance,
        phase_remaining_ms: Math.round(enemy.phaseRemaining * 1000),
        windup_ms: Math.round(enemy.windupSeconds * 1000),
        attacks: enemy.attacks,
        hits: enemy.hits,
        dodged_attacks: enemy.dodgedAttacks,
        distance: U.geometry3d.horizontalDistance(self, enemy),
        spawn_distance: enemy.spawnDistance,
        aim_errors: self.enemyAimErrors(enemy),
        under_crosshair: crosshairTrace.enemy === enemy,
        within_spear_range: U.geometry3d.horizontalDistance(self, enemy) - enemy.radius <= PLAYER_SPEAR_REACH,
        line_of_sight: !self.lineBlocked(self, enemy),
      };
    });
  };

  Base3DDuel.prototype.entityPayload = function entityPayload() {
    var entities = [
      {
        id: "player",
        type: "player",
        x: this.x,
        y: FLOOR_Y,
        z: this.z,
        radius: PLAYER_RADIUS,
        yaw: this.yaw,
        health: this.health,
        max_health: this.maxHealth,
        health_unlimited: this.healthUnlimited,
        charge_state: this.chargeState(),
        charge_button: this.chargeButton.payload(),
        charge_progress_ms: Math.round(this.chargeElapsed * 1000),
        dodging: this.dodgeRemaining > 0,
      },
    ].concat(this.serializeEnemies());
    for (var i = 0; i < this.covers.length; i += 1) {
      entities.push({
        id: this.covers[i].id,
        type: "cover",
        x: this.covers[i].x,
        y: FLOOR_Y,
        z: this.covers[i].z,
        width: this.covers[i].width,
        depth: this.covers[i].depth,
        height: this.covers[i].height,
      });
    }
    return entities;
  };

  Base3DDuel.prototype.visualPayload = function visualPayload() {
    return G3D.visuals.payload(this);
  };

  Base3DDuel.prototype.getStatePayload = function getStatePayload() {
    var latched = Core.terminal.consume(this);
    if (latched) return latched;
    G3D.visuals.sync(this);
    var metrics = this.metricsPayload();
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
        score: metrics.primary_score,
        level: null,
        player: {
          x: this.x,
          y: FLOOR_Y,
          z: this.z,
          yaw: this.yaw,
          camera_pitch: this.pitch,
          aim_pitch: this.playerAimPitch(),
          health: this.health,
          max_health: this.maxHealth,
          health_unlimited: this.healthUnlimited,
          charge_state: this.chargeState(),
          charge_button: this.chargeButton.payload(),
          charge_progress_ms: Math.round(this.chargeElapsed * 1000),
          dodging: this.dodgeRemaining > 0,
          staggered: this.playerStaggerRemaining > 0,
        },
        environment: {
          phase: this.terminal.isTerminal ? "terminal" : this.mode,
          viewport_width: viewport.width,
          viewport_height: viewport.height,
          logic_width: viewport.width,
          logic_height: viewport.height,
          base_logic_width: LOGIC_WIDTH,
          base_logic_height: LOGIC_HEIGHT,
          fullscreen: viewport,
          camera_fov: viewport.fov,
          camera_mode: "first_person",
          camera_eye_height: PLAYER_EYE_HEIGHT,
          camera_initialization: this.cameraInitialization,
          map: { id: this.map.id, revision: this.map.revision, regions: this.map.regions },
          arena_bounds: {
            min_x: ARENA_MIN_X,
            max_x: ARENA_MAX_X,
            min_z: ARENA_MIN_Z,
            max_z: ARENA_MAX_Z,
          },
          no_obstacles: this.noObstacles,
          covers: this.covers,
          active_enemy_count: this.targetEnemyCount,
          enemy_profiles: ENEMY_PROFILES.map(function profileName(profile) { return profile.id; }),
          enemy_spawn_distance: {
            min: ENEMY_SPAWN_MIN_DISTANCE,
            max: ENEMY_SPAWN_MAX_DISTANCE,
          },
          enemy_spawn_strategy: "bounded_annulus_with_side_preference",
          enemy_spawn_side_angle_degrees: {
            min: Math.round(ENEMY_SPAWN_SIDE_ANGLE_MIN * 180 / Math.PI),
            max: Math.round(ENEMY_SPAWN_SIDE_ANGLE_MAX * 180 / Math.PI),
          },
          enemy_return_after_knockback: true,
          enemy_return_speed: ENEMY_RETURN_SPEED,
          enemy_return_tolerance: ENEMY_RETURN_TOLERANCE,
          enemy_lateral_speed_scale: ENEMY_LATERAL_SPEED_SCALE,
          enemy_orbit_max_sweep_degrees: Math.round(ENEMY_ORBIT_MAX_SWEEP_RADIANS * 180 / Math.PI),
          enemy_orbit_recenter_ms: {
            min: Math.round(ENEMY_ORBIT_RECENTER_MIN_SECONDS * 1000),
            max: Math.round(ENEMY_ORBIT_RECENTER_MAX_SECONDS * 1000),
          },
          enemy_jump_speed: ENEMY_JUMP_SPEED,
          enemy_gravity: ENEMY_GRAVITY,
          enemy_hit_reaction: {
            stagger_ms: Math.round(ENEMY_STAGGER_SECONDS * 1000),
            knockback_seconds: ENEMY_KNOCKBACK_SECONDS,
            knockback_speed: ENEMY_KNOCKBACK_SPEED,
          },
          move_speed: PLAYER_MOVE_SPEED * this.controlResponse.applied.move_scale,
          weapon_type: "charged_spear",
          charged_spear: {
            reach: PLAYER_SPEAR_REACH,
            minimum_charge_ms: Math.round(PLAYER_SPEAR_CHARGE_SECONDS * 1000),
            thrust_ms: Math.round(PLAYER_SPEAR_THRUST_SECONDS * 1000),
            recovery_ms: Math.round(PLAYER_SPEAR_RECOVERY_SECONDS * 1000),
            damage: PLAYER_SPEAR_DAMAGE,
          },
          dodge_seconds: DODGE_SECONDS,
          asset_pack: this.assetContext ? this.assetContext.id : null,
          asset: this.assetContext ? this.assetContext.payload() : null,
          difficulty: this.difficulty,
          perturb_active: Core.perturbations.isActive(this),
          visual_perturbations: this.visualPayload(),
        },
        entities: this.entityPayload(),
      },
      metrics: metrics,
      debug: {
        mode: this.mode,
        last_action: this.lastAction,
        last_damage_source: this.lastDamageSource,
        last_reset_method: this.runtime.lastResetMethod,
        reset_count: this.runtime.resetCount,
        paused: this.paused,
        runtime_paused: this.paused,
        enemy_mesh_count: this.enemyRegistry ? this.enemyRegistry.size() : 0,
      },
    };
  };

  Base3DDuel.prototype.getObservation = function getObservation() {
    return {
      player: {
        x: this.x,
        z: this.z,
        yaw: this.yaw,
        camera_pitch: this.pitch,
        aim_pitch: this.playerAimPitch(),
        health: this.health,
        health_unlimited: this.healthUnlimited,
        charge_state: this.chargeState(),
        charge_button_down: this.chargeButton.down,
        charge_progress_ms: Math.round(this.chargeElapsed * 1000),
        dodging: this.dodgeRemaining > 0,
      },
      enemies: this.serializeEnemies(),
      covers: this.covers.map(function copyCover(cover) { return Object.assign({}, cover); }),
      nearest_enemy_distance: this.nearestEnemyDistance(),
      threatening_enemies: this.threateningEnemyCount(),
    };
  };

  Base3DDuel.prototype.infoPayload = function infoPayload() {
    return this.metricsPayload();
  };

  Base3DDuel.prototype.buildStepInfo = function buildStepInfo(state, stepOptions, normalized) {
    var info = Core.terminal.withInfo(this, state, this.infoPayload());
    info.action = { type: "game_step_action", id: normalized.id, args: normalized.args };
    info.durationMs = stepOptions.durationMs;
    info.source = stepOptions.source;
    return info;
  };

  Base3DDuel.prototype.resetGym = function resetGym(options) {
    this.resetFromAPI(options || {});
    return { observation: this.getObservation(), reward: 0, done: false, info: this.infoPayload() };
  };

  Base3DDuel.prototype.renderGameToText = function renderGameToText() {
    return JSON.stringify({
      coordinate_system: "first-person x/z arena coordinates; mouse changes yaw and pitch",
      status: this.mode,
      player: {
        x: this.x,
        z: this.z,
        yaw: this.yaw,
        aim_pitch: this.playerAimPitch(),
        health: this.health,
        health_unlimited: this.healthUnlimited,
        charge_state: this.chargeState(),
        charge_button_down: this.chargeButton.down,
        charge_progress_ms: Math.round(this.chargeElapsed * 1000),
        dodge_ready: this.dodgeCooldown <= 0,
      },
      enemies: this.serializeEnemies(),
      covers: this.covers,
      combat: this.metricsPayload(),
      visual_perturbations: this.visualPayload(),
    });
  };

  Base3DDuel.prototype.updateBestMetrics = function updateBestMetrics() {
    this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, this.getPrimaryScore());
  };



  Base3DDuel.prototype.makeEnemyMesh = function makeEnemyMesh(enemy) {
    return window.SpearCourtyardScene.createEnemy(this, enemy, PLAYER_HEIGHT * profileById(enemy.type).scale);
  };

  Base3DDuel.prototype.attachEnemyMesh = function attachEnemyMesh(enemy) {
    if (!enemy || !enemy.alive || !this.enemyRegistry || this.enemyRegistry.get(enemy.id)) return;
    this.enemyRegistry.set(enemy.id, this.makeEnemyMesh(enemy));
  };

  Base3DDuel.prototype.rebuildScene3D = function rebuildScene3D() {
    if (!this.world3d) return;
    this.sceneReady = false;
    this.world3d.clear();
    this.sceneMeshes = window.SpearCourtyardScene.build(this);
    this.enemyRegistry = G3D.entities.createRegistry(this.world3d);
    this.setupViewSpear();
    if (this.chargeIndicator) G3D.entities.remove(this.chargeIndicator, this.world3d.camera);
    this.chargeIndicator = window.SpearCourtyardScene.createChargeIndicator(this);
    this.sceneReady = true;
    for (var i = 0; i < this.enemies.length; i += 1) this.attachEnemyMesh(this.enemies[i]);
  };

  Base3DDuel.prototype.syncEnemyVisual = function syncEnemyVisual(mesh, enemy) {
    window.SpearCourtyardScene.syncEnemy(this, mesh, enemy);
  };

  Base3DDuel.prototype.syncViewSpear = function syncViewSpear() {
    window.SpearCourtyardScene.syncWeapon(this);
  };

  Base3DDuel.prototype.syncScene3D = function syncScene3D() {
    if (!this.world3d) return;
    var self = this;
    this.enemyRegistry.sync(this.enemies.filter(function visible(enemy) {
      return enemy.alive || enemy.phaseRemaining > 0;
    }), {
      create: function create(enemy) { return self.makeEnemyMesh(enemy); },
      update: function update(mesh, enemy, index) { self.syncEnemyVisual(mesh, enemy, index); },
    });
    this.world3d.setFirstPersonCamera({
      x: this.x,
      height: FLOOR_Y,
      z: this.z,
      yaw: this.yaw,
      pitch: this.pitch,
      eyeHeight: PLAYER_EYE_HEIGHT,
    });
    this.syncViewSpear();
    window.SpearCourtyardScene.syncChargeIndicator(this);
  };

  Base3DDuel.prototype.render = function render() {
    G3D.visuals.sync(this, { sceneReady: true });
    if (!this.world3d) return;
    this.syncScene3D();
    this.world3d.render();
    if (this.infoPanel) this.infoPanel.update();
  };

  Base3DDuel.prototype.resetFromAPI = function resetFromAPI(options) {
    return this.beginEpisode(options || {}, true);
  };

  async function start() {
    await G3D.assets.preload(ASSET_PACK, ASSET_REQUIREMENTS);
    await document.fonts.ready;
    var game = new Base3DDuel();
    await game.world3d.prepare();
    Core.createRuntime({
      game: game,
      presentation: {
        title: "3D Spear Duel",
        controls: "WASD moves. Move the mouse to look. Hold left mouse for 0.4s, then release to thrust. Space dodges.",
        read: function readPresentation() {
          var opponent = game.activeOpponent();
          return {
            status: game.paused ? "paused" : game.mode,
            primaryScore: game.getPrimaryScore(),
            stepReward: game.envRewardStep,
            episodeReward: game.envRewardEpisode,
            difficulty: game.difficulty,
            seed: game.seed,
            perturbation: Core.perturbations.label(game),
            details: [
              ["Health", (game.healthUnlimited ? "Unlimited" : game.health + " / " + game.maxHealth)],
              ["Kills", game.kills],
              ["Enemies", game.enemies.filter(function alive(enemy) { return enemy.alive; }).length],
              ["Opponent", (opponent ? opponent.type : "Respawning")],
              ["Movement", (opponent ? opponent.locomotionState.replace(/_/g, " ") : "—")],
              ["Spear", game.chargeState()],
              ["Charge", Math.round(game.chargeRatio() * 100) + "%"],
              ["Dodge", (game.dodgeCooldown > 0 ? (Math.ceil(game.dodgeCooldown * 10) / 10) + "s" : "Ready")],
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
      capabilities: {
        supports_no_obstacles: true,
      },
    });
  }

  Core.lifecycle.boot(start);
})();
