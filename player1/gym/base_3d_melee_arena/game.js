(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var G3D = window.BaseGamelet3D;
  var MonasteryLevel = window.MeleeMonasteryLevel;
  var MeleeScene = window.MeleeArenaScene;
  var rewardConfig = window.Base3DMeleeArenaRewardConfig;
  var GAME_ID = "base_3d_melee_arena";
  var LOGIC_WIDTH = 640;
  var LOGIC_HEIGHT = 640;
  var DISPLAY_WIDTH = G3D.viewport.baseWidth;
  var DISPLAY_HEIGHT = G3D.viewport.baseHeight;
  var STEP_MS = 1000 / 60;
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 5;
  var ASSET_REQUIREMENTS = MeleeScene.requirements;
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
      scene: { layout: MonasteryLevel.sample },
      camera: {
        orientation: Core.perturbations.cameraOrientationSampler("combat"),
      },
    },
  });

  var FLOOR_Y = 0;
  var ARENA_MIN_X = -9;
  var ARENA_MAX_X = 9;
  var ARENA_MIN_Z = -9;
  var ARENA_MAX_Z = 9;
  var PLAYER_RADIUS = 0.34;
  var PLAYER_ENEMY_COLLISION_PADDING = 0.08;
  var PLAYER_HEIGHT = 1.64;
  var PLAYER_MOVE_SPEED = 5;
  var PLAYER_STAGGER_SECONDS = 0.18;
  var PLAYER_KNOCKBACK_SECONDS = 0.14;
  var PLAYER_KNOCKBACK_SPEED = 3.4;
  var PLAYER_START_YAW = -Math.PI / 2;
  var LOOK_SENSITIVITY = G3D.input.CAMERA_SENSITIVITY;
  var CAMERA_BACK_DISTANCE = 3.0;
  var CAMERA_HEIGHT_OFFSET = 1.49;
  var CAMERA_SHOULDER_OFFSET = 0.52;
  var CAMERA_LOOK_HEIGHT = 0.92;
  var CAMERA_FORWARD_LOOK = 0.88;
  var CAMERA_DISTANCE = Math.hypot(CAMERA_BACK_DISTANCE + CAMERA_FORWARD_LOOK, CAMERA_HEIGHT_OFFSET);
  var CAMERA_PITCH_MIN = 0.22;
  var CAMERA_PITCH_MAX = 0.54;
  var CAMERA_INITIAL_PITCHES = [0.43, 0.47, 0.51];

  var PLAYER_ATTACK_WINDUP_SECONDS = 0.045;
  var PLAYER_ATTACK_ACTIVE_SECONDS = 0.03;
  var PLAYER_ATTACK_RECOVERY_SECONDS = 0.075;
  var PLAYER_ATTACK_RANGE = 1.48;
  var PLAYER_ATTACK_HALF_ANGLE = Math.PI / 3;
  var PLAYER_ATTACK_DAMAGE = 1;
  var ENEMY_STAGGER_SECONDS = 0.28;
  var ENEMY_KNOCKBACK_SECONDS = 0.18;
  var ENEMY_KNOCKBACK_SPEED = 3.2;

  var DODGE_SPEED = 10.5;
  var DODGE_SECONDS = 0.28;
  var DODGE_COOLDOWN_SECONDS = 1.05;

  var ENEMY_RADIUS = 0.38;
  var ENEMY_ATTACK_TRIGGER_DISTANCE = 1.52;
  var ENEMY_ATTACK_RANGE = 1.36;
  var ENEMY_ATTACK_HALF_ANGLE = Math.PI * 0.28;
  var ENEMY_ATTACK_ACTIVE_SECONDS = 0.16;
  var ENEMY_SPAWN_MIN_DISTANCE = 3.2;
  var ENEMY_SPAWN_MAX_DISTANCE = 4.8;
  var ENEMY_SPAWN_SIDE_ANGLE_MIN = Math.PI * 0.46;
  var ENEMY_SPAWN_SIDE_ANGLE_MAX = Math.PI * 0.68;
  var ENEMY_STARTER_DISTANCE_MIN = 3.1;
  var ENEMY_STARTER_DISTANCE_MAX = 3.7;
  var ENEMY_STARTER_SIDE_ANGLE_MIN = Math.PI * 0.43;
  var ENEMY_STARTER_SIDE_ANGLE_MAX = Math.PI * 0.56;
  var RESPAWN_MIN_SECONDS = 0.7;
  var RESPAWN_JITTER_SECONDS = 0.5;

  var ENEMY_PROFILES = Object.freeze([
    Object.freeze({
      id: "raider",
      health: 3,
      moveSpeed: 2.15,
      windupSeconds: 0.72,
      recoverySeconds: 0.54,
      scale: 1,
      strafeWeight: 0.18,
    }),
    Object.freeze({
      id: "skirmisher",
      health: 3,
      moveSpeed: 2.55,
      windupSeconds: 0.6,
      recoverySeconds: 0.48,
      scale: 0.92,
      strafeWeight: 0.32,
    }),
    Object.freeze({
      id: "brute",
      health: 3,
      moveSpeed: 1.82,
      windupSeconds: 0.86,
      recoverySeconds: 0.68,
      scale: 1.12,
      strafeWeight: 0.1,
    }),
  ]);

  var canvas = document.getElementById("display");

  function sampleInitialCamera(game) {
    var rng = new U.Rng((Core.seeds.forDomain(game, "camera") ^ 0x63616d32) >>> 0,
      DEFAULT_SEED, { allowZeroSeed: true });
    var pitchBand = rng.randint(0, 3);
    var yawSide = rng.randint(0, 3) - 1;
    var pitch = CAMERA_INITIAL_PITCHES[pitchBand] + (pitchBand === 1 ? 0 : rng.range(-0.015, 0.015));
    var searchStart = yawSide !== 0 && rng.next() < 0.25;
    var canonicalYawResidual = yawSide === 0 ? 0 : yawSide * rng.range(
      searchStart ? 1.15 : 0.12, searchStart ? 1.55 : 0.26);
    return {
      reference_pitch: CAMERA_INITIAL_PITCHES[1],
      canonical_yaw_residual: canonicalYawResidual,
      search_start: searchStart,
      yaw_residual: game.sceneMirrorSign * canonicalYawResidual,
      pitch_residual: pitch - CAMERA_INITIAL_PITCHES[1],
      pitch_band: ["shallow", "center", "steep"][pitchBand],
      pitch: pitch,
      mirror_sign: game.sceneMirrorSign,
      shoulder_offset: game.cameraShoulderOffset,
    };
  }

  function readOptionalBoolean(object, snakeKey, camelKey) {
    if (U.object.hasOwn(object, snakeKey)) return Core.config.normalizeBoolean(object[snakeKey], null);
    if (U.object.hasOwn(object, camelKey)) return Core.config.normalizeBoolean(object[camelKey], null);
    return null;
  }

  function readMeleeArenaUrlConfig(defaults) {
    var config = Core.config.readUrl(defaults);
    var params = new URLSearchParams(window.location.search || "");
    config.noObstacles = Core.config.normalizeBoolean(params.get("no_obstacles"), false);
    return config;
  }

  function mergeMeleeArenaEpisodeConfig(urlConfig, normalized, rawOptions) {
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

  function Base3DMeleeArena() {
    this.defaults = {
      seed: DEFAULT_SEED,
      difficulty: DEFAULT_DIFFICULTY,
      maxDifficulty: MAX_DIFFICULTY,
    };
    this.urlConfig = readMeleeArenaUrlConfig(this.defaults);
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

  Base3DMeleeArena.prototype.setup3D = function setup3D() {
    this.world3d = G3D.createWorld(canvas, {
      width: DISPLAY_WIDTH,
      height: DISPLAY_HEIGHT,
      fov: 66,
      clearColor: 0xc7d8e8,
      fogColor: 0xc7d8e8,
      fogNear: 16,
      fogFar: 34,
      ambient: 0.52,
      sun: 0.98,
      visualProfile: "stylized",
    });
    this.sceneReady = false;
    this.sceneMeshes = {};
    G3D.viewport.install(this, {
      canvas: canvas,
      world: this.world3d,
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
      baseFov: 66,
    });
  };

  Base3DMeleeArena.prototype.beginEpisode = function beginEpisode(options, countReset, flags) {
    var episodeFlags = flags || {};
    var rawOptions = options || {};
    var normalized = Core.config.normalizeOptions(rawOptions, MAX_DIFFICULTY);
    var config = mergeMeleeArenaEpisodeConfig(this.urlConfig, normalized, rawOptions);
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
      defaultAssetPack: "gym-melee",
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
    });
    var mirrorRng = new U.Rng((Core.seeds.forDomain(this, "scene") ^ 0x6d697232) >>> 0,
      DEFAULT_SEED, { allowZeroSeed: true });
    this.sceneMirrorSign = mirrorRng.next() < 0.5 ? -1 : 1;
    this.cameraShoulderOffset = this.sceneMirrorSign * CAMERA_SHOULDER_OFFSET;
    this.sceneLayout = Object.assign({}, Core.domains.sample(this, "scene", "layout", MonasteryLevel.sample({ profile: "default" })), {
      mirror_sign: this.sceneMirrorSign,
    });
    this.map = MonasteryLevel.build(Object.assign({}, this.sceneLayout, { mirror_sign: 1 }), this.noObstacles);
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
    this.z = playerRng.range(5.65, 6.25);
    this.sceneStartYaw = PLAYER_START_YAW + cameraRng.range(-0.14, 0.14);
    this.yaw = this.sceneStartYaw + cameraOrientation.yaw_offset_radians;
    // Preserve the legacy draw without adding it to the bounded reset distribution.
    cameraRng.range(-0.025, 0.025);
    this.cameraInitialization = sampleInitialCamera(this);
    this.cameraPitch = this.cameraInitialization.pitch;
    this.health = null;
    this.maxHealth = null;
    this.healthUnlimited = true;
    this.attackState = "idle";
    this.attackPhaseRemaining = 0;
    this.attackPhaseDuration = 0;
    this.attackHitIds = Object.create(null);
    this.attackConnectedThisSwing = false;
    this.attackBlockedThisSwing = false;
    this.dodgeRemaining = 0;
    this.dodgeCooldown = 0;
    this.invulnerableRemaining = 0;
    this.dodgeVelocity = { x: 0, z: 0 };
    this.playerStaggerRemaining = 0;
    this.playerKnockbackRemaining = 0;
    this.playerKnockbackVelocity = { x: 0, z: 0 };
    this.playerHitFlashRemaining = 0;
    this.playerMoving = false;
    this.starterPoint = this.buildStarterPoint();
    this.covers = this.map.colliders;
    this.enemies = [];
    this.respawnQueue = [];
    this.enemySerial = 0;
    this.targetEnemyCount = Math.min(4, 2 + Math.floor((this.difficulty - 1) / 2));

    this.kills = 0;
    this.damageDealt = 0;
    this.damageTaken = 0;
    this.attackAttempts = 0;
    this.attacksLanded = 0;
    this.attackHits = 0;
    this.attackWhiffs = 0;
    this.blockedSwings = 0;
    this.dodges = 0;
    this.attacksDodged = 0;
    this.enemyAttacks = 0;
    this.enemyHits = 0;
    this.enemyTelegraphs = 0;
    this.enemyStaggers = 0;
    this.enemyKnockbacks = 0;
    this.playerKnockbacks = 0;
    this.enemiesSpawned = 0;
    this.enemyRespawns = 0;
    this.playerCollisions = 0;
    this.enemyCollisions = 0;
    this.stepCount = 0;
    this.gameTimeMs = 0;
    this.visualStride = 0;
    this.visualHits = [];
    this.lastSlash = null;
    this.lastPlayerHitMs = null;
    this.lastDamageSource = null;
    this.lastAction = "reset";
    this.mode = config.autostart ? "playing" : "paused";
    this.terminal = { isTerminal: false, outcome: null, reason: null };
    this.controls = { forward: false, back: false, left: false, right: false };

    this.spawnEnemy(false, this.starterPoint);
    while (this.enemies.length < this.targetEnemyCount) {
      this.spawnEnemy(false, null, this.sceneStartYaw);
    }
    if (this.sceneMirrorSign < 0) {
      this.x = -this.x;
      this.starterPoint.x = -this.starterPoint.x;
      this.sceneStartYaw = U.math.normalizeAngle(Math.PI - this.sceneStartYaw);
      this.enemies.forEach(function mirror(enemy) {
        enemy.x = -enemy.x;
        enemy.heading = U.math.normalizeAngle(Math.PI - enemy.heading);
        enemy.strafeSign = -enemy.strafeSign;
      });
      this.map = MonasteryLevel.build(this.sceneLayout, this.noObstacles);
      this.covers = this.map.colliders;
    }
    this.cameraInitialization.reference_yaw = Math.atan2(this.enemies[0].z - this.z, this.enemies[0].x - this.x);
    this.yaw = U.math.normalizeAngle(this.cameraInitialization.reference_yaw + this.cameraInitialization.yaw_residual);
    if (countReset) this.runtime.resetCount += 1;
    this.runtime.episodeCount += 1;
    this.runtime.lastResetMethod = countReset ? "inplace_reset" : "init";
    this.rebuildScene3D();
    this.updateBestMetrics();
    this.render();
    return { accepted: normalized, applied: config, notes: [] };
  };

  Base3DMeleeArena.prototype.buildStarterPoint = function buildStarterPoint() {
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

  Base3DMeleeArena.prototype.coverBounds = function coverBounds(cover, padding) {
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

  Base3DMeleeArena.prototype.bindInput = function bindInput() {
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
        if (event.button === 0) this.startAttack();
      },
    });
    var app = document.getElementById("app");
    if (app) app.focus();
    canvas.focus();
  };

  Base3DMeleeArena.prototype.ensureSimulationRunner = function ensureSimulationRunner() {
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

  Base3DMeleeArena.prototype.startLoop = function startLoop() {
    this.ensureSimulationRunner().start();
  };

  Base3DMeleeArena.prototype.pause = function pause() {
    return Core.lifecycle.pause(this);
  };

  Base3DMeleeArena.prototype.resume = function resume() {
    return Core.lifecycle.resume(this);
  };

  Base3DMeleeArena.prototype.cameraLookOptions = function cameraLookOptions() {
    return {
      sensitivity: LOOK_SENSITIVITY * this.controlResponse.applied.look_gain_scale,
      pitchKey: "cameraPitch",
      pitchSign: 1,
      pitchMin: CAMERA_PITCH_MIN,
      pitchMax: CAMERA_PITCH_MAX,
    };
  };

  Base3DMeleeArena.prototype.applyMouse = function applyMouse(dx, dy) {
    if (this.terminal.isTerminal) return;
    if (this.mode === "paused") this.mode = "playing";
    G3D.input.applyPointerLook(this, dx, dy, this.cameraLookOptions());
    this.lastAction = "orbit(" + dx.toFixed(1) + "," + dy.toFixed(1) + ")";
  };

  Base3DMeleeArena.prototype.applyRelativePointerInput = function applyRelativePointerInput(pointerInput) {
    if (this.terminal.isTerminal || !pointerInput) return;
    if (this.mode === "paused") this.mode = "playing";
    G3D.input.applyRelativePointerInput(this, pointerInput, this.cameraLookOptions());
    this.lastAction = "relative_pointer(" + pointerInput.dx + "," + pointerInput.dy + ")";
  };

  Base3DMeleeArena.prototype.addReward = function addReward(value) {
    Core.reward.add(this, value);
  };

  Base3DMeleeArena.prototype.difficultyRatio = function difficultyRatio() {
    return U.math.clamp((this.difficulty - 1) / Math.max(1, MAX_DIFFICULTY - 1), 0, 1);
  };

  Base3DMeleeArena.prototype.circleOverlapsCover = function circleOverlapsCover(x, z, radius) {
    for (var i = 0; i < this.covers.length; i += 1) {
      if (U.geometry3d.circleOverlapsAabbXZ(x, z, radius, this.coverBounds(this.covers[i]))) return true;
    }
    return false;
  };

  Base3DMeleeArena.prototype.lineBlocked = function lineBlocked(from, to) {
    var start = { x: from.x, y: 0.78, z: from.z };
    var end = { x: to.x, y: 0.78, z: to.z };
    var segmentLength = U.geometry3d.distance(start, end);
    for (var i = 0; i < this.covers.length; i += 1) {
      var hit = U.geometry3d.segmentAabbHitDistance(start, end, this.coverBounds(this.covers[i]), 0.02);
      if (hit !== null && hit < segmentLength - 0.08) return true;
    }
    return false;
  };

  Base3DMeleeArena.prototype.enemySpawnBlocked = function enemySpawnBlocked(point) {
    if (!this.map.contains(point.x, point.z, ENEMY_RADIUS * 1.12 + 0.12)) return true;
    for (var i = 0; i < this.enemies.length; i += 1) {
      if (!this.enemies[i].alive) continue;
      if (U.geometry3d.horizontalDistance(point, this.enemies[i]) < ENEMY_RADIUS * 2 + 0.55) return true;
    }
    return false;
  };

  Base3DMeleeArena.prototype.sampleEnemySpawnPoint = function sampleEnemySpawnPoint(referenceYaw) {
    var self = this;
    var spawnYaw = Number.isFinite(referenceYaw) ? referenceYaw : this.yaw;
    var point = U.geometry3d.sampleOpenPointXZ(
      Core.domains.gameplayRng(this, "scene", "entity_spawn"),
      {
      bounds: this.map.bounds,
      radius: ENEMY_RADIUS + 0.12,
      colliders: this.covers,
      reference: { x: this.x, z: this.z },
      minDistance: ENEMY_SPAWN_MIN_DISTANCE,
      maxAttempts: 192,
      accept: function accept(candidate) {
        var dx = candidate.x - self.x;
        var dz = candidate.z - self.z;
        var distance = Math.sqrt(dx * dx + dz * dz);
        var angle = Math.abs(U.math.normalizeAngle(Math.atan2(dz, dx) - spawnYaw));
        return distance <= ENEMY_SPAWN_MAX_DISTANCE
          && angle >= ENEMY_SPAWN_SIDE_ANGLE_MIN
          && angle <= ENEMY_SPAWN_SIDE_ANGLE_MAX
          && !self.enemySpawnBlocked(candidate);
      },
      }
    );
    if (point) return point;
    var fallback = this.map.spawnAnchors;
    for (var i = 0; i < fallback.length; i += 1) {
      var candidate = fallback[(i + this.enemySerial) % fallback.length];
      if (!this.enemySpawnBlocked(candidate) && Math.hypot(candidate.x - this.x, candidate.z - this.z) > 2) return candidate;
    }
    throw new Error("No clear melee enemy spawn");
  };

  Base3DMeleeArena.prototype.spawnEnemy = function spawnEnemy(isRespawn, explicitPoint, referenceYaw) {
    var entitySpawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var point = explicitPoint && !this.enemySpawnBlocked(explicitPoint) ? explicitPoint : this.sampleEnemySpawnPoint(referenceYaw);
    var profile = entitySpawnRng.choice(ENEMY_PROFILES);
    var behaviorRng = Core.domains.createEntityRng(this, entitySpawnRng, DEFAULT_SEED);
    var ratio = this.difficultyRatio();
    var heading = Math.atan2(this.z - point.z, this.x - point.x);
    var enemy = {
      id: "enemy_" + (this.enemySerial + 1),
      type: profile.id,
      x: point.x,
      z: point.z,
      radius: ENEMY_RADIUS * profile.scale,
      heading: heading,
      health: profile.health,
      maxHealth: profile.health,
      moveSpeed: profile.moveSpeed * (1 + ratio * 0.22) * behaviorRng.range(0.94, 1.06),
      windupSeconds: profile.windupSeconds * (1 - ratio * 0.24),
      recoverySeconds: profile.recoverySeconds * (1 - ratio * 0.16),
      strafeWeight: profile.strafeWeight,
      strafeSign: behaviorRng.next() < 0.5 ? -1 : 1,
      behaviorRemaining: behaviorRng.range(0.7, 1.6),
      attackCooldown: behaviorRng.range(0.35, 0.78),
      combatState: "approach",
      phaseRemaining: 0,
      phaseDuration: 0,
      attackApplied: false,
      attacks: 0,
      hits: 0,
      dodgedAttacks: 0,
      staggerRemaining: 0,
      knockbackRemaining: 0,
      knockbackVelocity: { x: 0, z: 0 },
      hitFlashRemaining: 0,
      alive: true,
      moving: false,
      visualStride: 0,
    };
    enemy.behaviorRng = behaviorRng;
    this.enemySerial += 1;
    this.enemiesSpawned += 1;
    if (isRespawn) this.enemyRespawns += 1;
    this.enemies.push(enemy);
    if (this.sceneReady) this.attachEnemyMesh(enemy);
    return enemy;
  };

  Base3DMeleeArena.prototype.controlDirection = function controlDirection() {
    var move = G3D.input.moveDelta(this.yaw, this.controls, 1, 1);
    var direction = normalizedDirection(move.x, move.z);
    if (direction.length <= 0) return { x: Math.cos(this.yaw), z: Math.sin(this.yaw) };
    return direction;
  };

  Base3DMeleeArena.prototype.cancelAttack = function cancelAttack() {
    this.attackState = "idle";
    this.attackPhaseRemaining = 0;
    this.attackPhaseDuration = 0;
    this.attackHitIds = Object.create(null);
    this.attackConnectedThisSwing = false;
    this.attackBlockedThisSwing = false;
  };

  Base3DMeleeArena.prototype.startAttack = function startAttack() {
    if (this.terminal.isTerminal || this.dodgeRemaining > 0 || this.playerStaggerRemaining > 0) return false;
    if (this.mode === "paused") this.mode = "playing";
    if (this.attackState !== "idle") {
      this.lastAction = "attack_blocked_recovery";
      return false;
    }
    this.attackAttempts += 1;
    this.attackState = "windup";
    this.attackPhaseRemaining = PLAYER_ATTACK_WINDUP_SECONDS;
    this.attackPhaseDuration = PLAYER_ATTACK_WINDUP_SECONDS;
    this.attackHitIds = Object.create(null);
    this.attackConnectedThisSwing = false;
    this.attackBlockedThisSwing = false;
    this.lastAction = "attack_windup";
    return true;
  };

  Base3DMeleeArena.prototype.startDodge = function startDodge() {
    if (this.terminal.isTerminal || this.dodgeCooldown > 0 || this.playerStaggerRemaining > 0) return false;
    if (this.mode === "paused") this.mode = "playing";
    var direction = this.controlDirection();
    this.dodgeVelocity = { x: direction.x, z: direction.z };
    this.dodgeRemaining = DODGE_SECONDS;
    this.invulnerableRemaining = DODGE_SECONDS;
    this.dodgeCooldown = DODGE_COOLDOWN_SECONDS;
    this.dodges += 1;
    this.cancelAttack();
    this.lastAction = "dodge";
    return true;
  };

  Base3DMeleeArena.prototype.tryMovePlayer = function tryMovePlayer(dx, dz) {
    var movement = U.geometry3d.moveCircleWithAabbs(
      { x: this.x, z: this.z },
      { x: dx, z: dz },
      {
        radius: PLAYER_RADIUS,
        bounds: this.map.bounds,
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

  Base3DMeleeArena.prototype.updatePlayerMotion = function updatePlayerMotion(dt) {
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
      var speedScale = this.playerStaggerRemaining > 0 ? 0.35 : (this.attackState === "idle" ? 1 : 0.62);
      var move = G3D.input.moveDelta(this.yaw, this.controls, PLAYER_MOVE_SPEED * this.controlResponse.applied.move_scale * speedScale, dt);
      if (move.forward && move.strafe) {
        move.x *= Math.SQRT1_2;
        move.z *= Math.SQRT1_2;
      }
      if (move.x || move.z) this.tryMovePlayer(move.x, move.z);
    }
    this.playerMoving = Math.abs(this.x - beforeX) + Math.abs(this.z - beforeZ) > 0.000001;
    this.visualStride += Math.hypot(this.x - beforeX, this.z - beforeZ);
  };

  Base3DMeleeArena.prototype.playerAttackCanHit = function playerAttackCanHit(enemy) {
    return U.geometry3d.circleIntersectsSectorXZ(
      { x: this.x, z: this.z },
      this.yaw,
      enemy,
      {
        range: PLAYER_ATTACK_RANGE,
        halfAngle: PLAYER_ATTACK_HALF_ANGLE,
        targetRadius: enemy.radius,
      }
    );
  };

  Base3DMeleeArena.prototype.damageEnemy = function damageEnemy(enemy, damage) {
    if (!enemy || !enemy.alive) return false;
    var applied = Math.min(enemy.health, Math.max(0, damage));
    enemy.health -= applied;
    enemy.lastVisualHitMs = this.gameTimeMs;
    this.visualHits.push({ timeMs: this.gameTimeMs, x: enemy.x, y: PLAYER_HEIGHT * 0.6, z: enemy.z,
      killed: enemy.health <= 0, enemy: enemy.health <= 0 ? enemy : null });
    if (this.visualHits.length > 8) this.visualHits.shift();
    this.damageDealt += applied;
    enemy.hitFlashRemaining = 0.14;
    var push = normalizedDirection(enemy.x - this.x, enemy.z - this.z);
    enemy.knockbackVelocity = { x: push.x, z: push.z };
    enemy.knockbackRemaining = ENEMY_KNOCKBACK_SECONDS;
    enemy.staggerRemaining = ENEMY_STAGGER_SECONDS;
    enemy.combatState = "stagger";
    enemy.phaseDuration = ENEMY_STAGGER_SECONDS;
    enemy.phaseRemaining = ENEMY_STAGGER_SECONDS;
    this.enemyStaggers += 1;
    this.enemyKnockbacks += 1;
    if (enemy.health > 0) {
      this.lastAction = "attack_hit";
      return false;
    }
    enemy.alive = false;
    this.kills += 1;
    this.addReward(rewardConfig.constants.killReward);
    this.respawnQueue.push({
      remaining: enemy.behaviorRng.range(
        RESPAWN_MIN_SECONDS,
        RESPAWN_MIN_SECONDS + RESPAWN_JITTER_SECONDS
      ),
    });
    this.lastAction = "melee_kill";
    return true;
  };

  Base3DMeleeArena.prototype.resolvePlayerAttack = function resolvePlayerAttack() {
    if (this.lastSlash) {
      this.lastSlash.x = this.x;
      this.lastSlash.z = this.z;
      this.lastSlash.yaw = this.yaw;
    }
    for (var i = 0; i < this.enemies.length; i += 1) {
      var enemy = this.enemies[i];
      if (!enemy.alive || this.attackHitIds[enemy.id] || !this.playerAttackCanHit(enemy)) continue;
      if (this.lineBlocked(this, enemy)) {
        if (!this.attackBlockedThisSwing) {
          this.blockedSwings += 1;
          this.attackBlockedThisSwing = true;
        }
        continue;
      }
      this.attackHitIds[enemy.id] = true;
      this.attackHits += 1;
      this.addReward(rewardConfig.constants.hitReward);
      if (!this.attackConnectedThisSwing) {
        this.attacksLanded += 1;
        this.attackConnectedThisSwing = true;
      }
      this.damageEnemy(enemy, PLAYER_ATTACK_DAMAGE);
    }
  };

  Base3DMeleeArena.prototype.updatePlayerAttack = function updatePlayerAttack(dt) {
    if (this.attackState === "idle") return;
    this.attackPhaseRemaining = Math.max(0, this.attackPhaseRemaining - dt);
    if (this.attackState === "windup" && this.attackPhaseRemaining <= 0) {
      this.attackState = "active";
      this.lastSlash = { timeMs: this.gameTimeMs, x: this.x, z: this.z, yaw: this.yaw };
      this.attackPhaseRemaining = PLAYER_ATTACK_ACTIVE_SECONDS;
      this.attackPhaseDuration = PLAYER_ATTACK_ACTIVE_SECONDS;
      this.lastAction = "attack_active";
    }
    if (this.attackState === "active") {
      this.resolvePlayerAttack();
      if (this.attackPhaseRemaining <= 0) {
        this.attackState = "recovery";
        this.attackPhaseRemaining = PLAYER_ATTACK_RECOVERY_SECONDS;
        this.attackPhaseDuration = PLAYER_ATTACK_RECOVERY_SECONDS;
        if (!this.attackConnectedThisSwing) this.attackWhiffs += 1;
        this.lastAction = this.attackConnectedThisSwing ? "attack_recovery" : "attack_whiff";
      }
    } else if (this.attackState === "recovery" && this.attackPhaseRemaining <= 0) {
      this.cancelAttack();
      this.lastAction = "attack_ready";
    }
  };

  Base3DMeleeArena.prototype.turnEnemyTowardPlayer = function turnEnemyTowardPlayer(enemy, dt) {
    var target = Math.atan2(this.z - enemy.z, this.x - enemy.x);
    var error = U.math.normalizeAngle(target - enemy.heading);
    var maxTurn = (enemy.combatState === "windup" ? 2.2 : 4.5) * dt;
    enemy.heading = U.math.normalizeAngle(enemy.heading + U.math.clamp(error, -maxTurn, maxTurn));
  };

  Base3DMeleeArena.prototype.enemyPositionAvailable = function enemyPositionAvailable(enemy, x, z) {
    if (U.geometry3d.horizontalDistance({ x: x, z: z }, this) < PLAYER_RADIUS + enemy.radius + 0.08) return false;
    for (var i = 0; i < this.enemies.length; i += 1) {
      var other = this.enemies[i];
      if (other === enemy || !other.alive) continue;
      if (U.geometry3d.horizontalDistance({ x: x, z: z }, other) < enemy.radius + other.radius + 0.12) return false;
    }
    return true;
  };

  Base3DMeleeArena.prototype.moveEnemy = function moveEnemy(enemy, dx, dz) {
    var movement = U.geometry3d.moveCircleWithAabbs(
      { x: enemy.x, z: enemy.z },
      { x: dx, z: dz },
      {
        radius: enemy.radius,
        bounds: this.map.bounds,
        colliders: this.covers,
      }
    );
    var moved = false;
    if (this.enemyPositionAvailable(enemy, movement.x, movement.z)) {
      moved = movement.movedX || movement.movedZ;
      enemy.visualStride += Math.hypot(movement.x - enemy.x, movement.z - enemy.z);
      enemy.x = movement.x;
      enemy.z = movement.z;
    }
    if (movement.blockedX || movement.blockedZ || !moved) this.enemyCollisions += 1;
    enemy.moving = moved;
    return { moved: moved, blocked: movement.blockedX || movement.blockedZ || !moved };
  };

  Base3DMeleeArena.prototype.startEnemyWindup = function startEnemyWindup(enemy) {
    enemy.combatState = "windup";
    enemy.phaseDuration = enemy.windupSeconds;
    enemy.phaseRemaining = enemy.windupSeconds;
    enemy.attackApplied = false;
    enemy.moving = false;
    this.enemyTelegraphs += 1;
  };

  Base3DMeleeArena.prototype.takePlayerDamage = function takePlayerDamage(enemy) {
    this.lastPlayerHitMs = this.gameTimeMs;
    this.damageTaken += 1;
    this.enemyHits += 1;
    this.lastDamageSource = enemy.id;
    this.lastAction = "player_hit";
    this.playerHitFlashRemaining = 0.18;
    this.playerStaggerRemaining = PLAYER_STAGGER_SECONDS;
    var push = normalizedDirection(this.x - enemy.x, this.z - enemy.z);
    this.playerKnockbackVelocity = { x: push.x, z: push.z };
    this.playerKnockbackRemaining = PLAYER_KNOCKBACK_SECONDS;
    this.playerKnockbacks += 1;
    this.addReward(-rewardConfig.constants.hitPenalty);
  };

  Base3DMeleeArena.prototype.resolveEnemyAttack = function resolveEnemyAttack(enemy) {
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

  Base3DMeleeArena.prototype.navigationGoal = function navigationGoal(enemy) {
    if (this.map.contains(this.x, this.z, enemy.radius)) return { x: this.x, z: this.z };
    var bearing = Math.atan2(enemy.z - this.z, enemy.x - this.x);
    for (var i = 0; i < 8; i += 1) {
      var angle = bearing + i * Math.PI / 4;
      var point = { x: this.x + Math.cos(angle) * 0.85, z: this.z + Math.sin(angle) * 0.85 };
      if (this.map.contains(point.x, point.z, enemy.radius) && !this.lineBlocked(point, this)) return point;
    }
    return { x: enemy.x, z: enemy.z };
  };

  Base3DMeleeArena.prototype.updateEnemyApproach = function updateEnemyApproach(enemy, dt) {
    var toPlayer = normalizedDirection(this.x - enemy.x, this.z - enemy.z);
    if (toPlayer.length <= ENEMY_ATTACK_TRIGGER_DISTANCE && enemy.attackCooldown <= 0 && !this.lineBlocked(enemy, this)) {
      this.startEnemyWindup(enemy);
      return;
    }
    if (!this.map.segmentClear(enemy, this, enemy.radius)) {
      if (!enemy.navigationPath || this.gameTimeMs >= enemy.repathAt) {
        enemy.navigationPath = this.map.findPath(enemy, this.navigationGoal(enemy), enemy.radius);
        enemy.navigationIndex = 1; enemy.repathAt = this.gameTimeMs + 550;
      }
      var target = enemy.navigationPath[enemy.navigationIndex];
      while (target && Math.hypot(target.x - enemy.x, target.z - enemy.z) < 0.18) target = enemy.navigationPath[++enemy.navigationIndex];
      if (target) {
        var directionToNode = normalizedDirection(target.x - enemy.x, target.z - enemy.z);
        var distanceToNode = Math.min(enemy.moveSpeed * dt, directionToNode.length);
        this.moveEnemy(enemy, directionToNode.x * distanceToNode, directionToNode.z * distanceToNode);
      }
      return;
    }
    enemy.navigationPath = null;
    enemy.behaviorRemaining -= dt;
    if (enemy.behaviorRemaining <= 0) {
      enemy.strafeSign = enemy.behaviorRng.next() < 0.5 ? -1 : 1;
      enemy.behaviorRemaining = enemy.behaviorRng.range(0.65, 1.55);
    }
    var retreat = toPlayer.length < 1.0 ? -0.7 : 1;
    var moveX = toPlayer.x * retreat + -toPlayer.z * enemy.strafeSign * enemy.strafeWeight;
    var moveZ = toPlayer.z * retreat + toPlayer.x * enemy.strafeSign * enemy.strafeWeight;
    for (var i = 0; i < this.enemies.length; i += 1) {
      var other = this.enemies[i];
      if (other === enemy || !other.alive) continue;
      var separation = normalizedDirection(enemy.x - other.x, enemy.z - other.z);
      if (separation.length > 0 && separation.length < 1.15) {
        var strength = (1.15 - separation.length) * 0.7;
        moveX += separation.x * strength;
        moveZ += separation.z * strength;
      }
    }
    var direction = normalizedDirection(moveX, moveZ);
    var step = enemy.moveSpeed * dt;
    var result = this.moveEnemy(enemy, direction.x * step, direction.z * step);
    if (result.blocked) {
      enemy.strafeSign *= -1;
      enemy.behaviorRemaining = enemy.behaviorRng.range(0.35, 0.75);
      this.moveEnemy(enemy, -toPlayer.z * enemy.strafeSign * step, toPlayer.x * enemy.strafeSign * step);
    }
  };

  Base3DMeleeArena.prototype.updateEnemy = function updateEnemy(enemy, dt) {
    if (!enemy.alive) return true;
    enemy.hitFlashRemaining = Math.max(0, enemy.hitFlashRemaining - dt);
    enemy.attackCooldown = Math.max(0, enemy.attackCooldown - dt);
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
      enemy.phaseRemaining = Math.max(0, enemy.phaseRemaining - dt);
      if (enemy.phaseRemaining <= 0) {
        enemy.combatState = "approach";
        enemy.attackCooldown = enemy.behaviorRng.range(0.28, 0.52);
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
        enemy.combatState = "approach";
        enemy.attackCooldown = enemy.behaviorRng.range(0.24, 0.5);
      }
      return true;
    }

    this.updateEnemyApproach(enemy, dt);
    return true;
  };

  Base3DMeleeArena.prototype.updateEnemies = function updateEnemies(dt) {
    this.enemies = this.enemies.filter(function keepAlive(enemy) { return enemy.alive; });
    var terminalBefore = Core.terminal.generation(this);
    for (var i = 0; i < this.enemies.length; i += 1) {
      if (!this.updateEnemy(this.enemies[i], dt)) return false;
      if (Core.terminal.generatedSince(this, terminalBefore)) return false;
    }
    return true;
  };

  Base3DMeleeArena.prototype.updateRespawns = function updateRespawns(dt) {
    var pending = [];
    for (var i = 0; i < this.respawnQueue.length; i += 1) {
      this.respawnQueue[i].remaining -= dt;
      if (this.respawnQueue[i].remaining <= 0) this.spawnEnemy(true, null);
      else pending.push(this.respawnQueue[i]);
    }
    this.respawnQueue = pending;
  };

  Base3DMeleeArena.prototype.update = function update(dt) {
    if (this.terminal.isTerminal || this.mode !== "playing" || this.paused) return;
    this.stepCount += 1;
    this.gameTimeMs += dt * 1000;
    this.dodgeRemaining = Math.max(0, this.dodgeRemaining - dt);
    this.dodgeCooldown = Math.max(0, this.dodgeCooldown - dt);
    this.invulnerableRemaining = Math.max(0, this.invulnerableRemaining - dt);
    this.playerStaggerRemaining = Math.max(0, this.playerStaggerRemaining - dt);
    this.playerHitFlashRemaining = Math.max(0, this.playerHitFlashRemaining - dt);
    this.updatePlayerMotion(dt);
    this.updatePlayerAttack(dt);
    if (!this.updateEnemies(dt)) return;
    this.updateRespawns(dt);
    this.updateBestMetrics();
  };

  Base3DMeleeArena.prototype.advanceTime = function advanceTime(ms, options) {
    var opts = typeof options === "object" && options !== null ? options : { render: options !== false };
    this.ensureSimulationRunner().advance(ms, opts);
    if (opts.returnState === false) return null;
    return this.getStatePayload();
  };

  Base3DMeleeArena.prototype.normalizeAction = function normalizeAction(action) {
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
      attack: normalized.mouseLeft,
    };
  };

  Base3DMeleeArena.prototype.applyAction = function applyAction(normalized) {
    this.controls.forward = normalized.forward;
    this.controls.back = normalized.back;
    this.controls.left = normalized.left;
    this.controls.right = normalized.right;
    this.applyRelativePointerInput(normalized.pointerInput);
    if (normalized.dodge) this.startDodge();
    if (normalized.attack) this.startAttack();
    if (this.mode === "paused" && !this.paused) this.mode = "playing";
  };

  Base3DMeleeArena.prototype.clearTransientControls = function clearTransientControls() {
    this.controls = { forward: false, back: false, left: false, right: false };
  };

  Base3DMeleeArena.prototype.advanceSimulation = function advanceSimulation(ms) {
    var state = this.advanceTime(ms, { render: false });
    this.clearTransientControls();
    return state;
  };

  Base3DMeleeArena.prototype.rewardMetrics = function rewardMetrics() {
    return {
      attack_hits: this.attackHits,
      kills: this.kills,
      damage_taken: this.damageTaken,
    };
  };

  Base3DMeleeArena.prototype.rewardPayload = function rewardPayload() {
    var metrics = this.rewardMetrics();
    return {
      env_reward_step: this.envRewardStep,
      env_reward_episode: this.envRewardEpisode,
      primary_positive_score: rewardConfig.computePrimaryPositiveScore(metrics),
      primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(metrics),
      primary_score: rewardConfig.computePrimaryScore(metrics),
    };
  };

  Base3DMeleeArena.prototype.getPrimaryScore = function getPrimaryScore() {
    return rewardConfig.computePrimaryScore(this.rewardMetrics());
  };

  Base3DMeleeArena.prototype.attackAccuracy = function attackAccuracy() {
    return this.attackAttempts > 0 ? this.attacksLanded / this.attackAttempts : 0;
  };

  Base3DMeleeArena.prototype.enemyAttackAccuracy = function enemyAttackAccuracy() {
    return this.enemyAttacks > 0 ? this.enemyHits / this.enemyAttacks : 0;
  };

  Base3DMeleeArena.prototype.nearestEnemyDistance = function nearestEnemyDistance() {
    var nearest = Infinity;
    for (var i = 0; i < this.enemies.length; i += 1) {
      if (this.enemies[i].alive) nearest = Math.min(nearest, U.geometry3d.horizontalDistance(this, this.enemies[i]));
    }
    return Number.isFinite(nearest) ? nearest : null;
  };

  Base3DMeleeArena.prototype.threateningEnemyCount = function threateningEnemyCount() {
    return this.enemies.filter(function threatening(enemy) {
      return enemy.alive && (enemy.combatState === "windup" || enemy.combatState === "active");
    }).length;
  };

  Base3DMeleeArena.prototype.metricsPayload = function metricsPayload() {
    var rewards = this.rewardPayload();
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
      attack_attempts: this.attackAttempts,
      attacks_landed: this.attacksLanded,
      attack_hits: this.attackHits,
      attack_whiffs: this.attackWhiffs,
      attack_accuracy: this.attackAccuracy(),
      blocked_swings: this.blockedSwings,
      attack_state: this.attackState,
      attack_phase_remaining_ms: Math.round(this.attackPhaseRemaining * 1000),
      dodges: this.dodges,
      dodge_remaining_ms: Math.round(this.dodgeRemaining * 1000),
      dodge_cooldown_ms: Math.round(this.dodgeCooldown * 1000),
      invulnerable_remaining_ms: Math.round(this.invulnerableRemaining * 1000),
      attacks_dodged: this.attacksDodged,
      enemy_attacks: this.enemyAttacks,
      enemy_hits: this.enemyHits,
      enemy_attack_accuracy: this.enemyAttackAccuracy(),
      enemy_telegraphs: this.enemyTelegraphs,
      enemy_staggers: this.enemyStaggers,
      enemy_knockbacks: this.enemyKnockbacks,
      player_knockbacks: this.playerKnockbacks,
      enemies_alive: this.enemies.filter(function alive(enemy) { return enemy.alive; }).length,
      enemies_spawned: this.enemiesSpawned,
      enemy_respawns: this.enemyRespawns,
      respawns_pending: this.respawnQueue.length,
      nearest_enemy_distance: this.nearestEnemyDistance(),
      threatening_enemies: this.threateningEnemyCount(),
      player_collisions: this.playerCollisions,
      enemy_collisions: this.enemyCollisions,
      step_count: this.stepCount,
      episode_count: this.runtime.episodeCount,
      best_primary_score: this.bestMetrics.bestPrimaryScore,
      difficulty: this.difficulty,
    };
  };

  Base3DMeleeArena.prototype.serializeEnemies = function serializeEnemies() {
    var self = this;
    return this.enemies.filter(function alive(enemy) { return enemy.alive; }).map(function serialize(enemy) {
      return {
        id: enemy.id,
        type: "enemy",
        archetype: enemy.type,
        x: enemy.x,
        y: FLOOR_Y,
        z: enemy.z,
        radius: enemy.radius,
        heading: enemy.heading,
        health: enemy.health,
        max_health: enemy.maxHealth,
        combat_state: enemy.combatState,
        phase_remaining_ms: Math.round(enemy.phaseRemaining * 1000),
        windup_ms: Math.round(enemy.windupSeconds * 1000),
        attacks: enemy.attacks,
        hits: enemy.hits,
        dodged_attacks: enemy.dodgedAttacks,
        distance: U.geometry3d.horizontalDistance(self, enemy),
        line_of_sight: !self.lineBlocked(self, enemy),
      };
    });
  };

  Base3DMeleeArena.prototype.entityPayload = function entityPayload() {
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
        attack_state: this.attackState,
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

  Base3DMeleeArena.prototype.visualPayload = function visualPayload() {
    return G3D.visuals.payload(this);
  };

  Base3DMeleeArena.prototype.getStatePayload = function getStatePayload() {
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
          camera_pitch: this.cameraPitch,
          health: this.health,
          max_health: this.maxHealth,
          health_unlimited: this.healthUnlimited,
          attack_state: this.attackState,
          attack_phase_remaining_ms: Math.round(this.attackPhaseRemaining * 1000),
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
          camera_mode: "third_person_optical_chase",
          camera_shoulder_offset: this.cameraShoulderOffset,
          camera_initialization: this.cameraInitialization,
          arena_bounds: {
            min_x: this.map.bounds.minX,
            max_x: this.map.bounds.maxX,
            min_z: this.map.bounds.minZ,
            max_z: this.map.bounds.maxZ,
          },
          no_obstacles: this.noObstacles,
          covers: this.covers,
          scene_layout: this.sceneLayout,
          level_area: this.map.area,
          level_regions: this.map.rooms,
          level_links: this.map.links,
          active_enemy_count: this.targetEnemyCount,
          enemy_profiles: ENEMY_PROFILES.map(function profileName(profile) { return profile.id; }),
          enemy_spawn_distance: {
            min: ENEMY_SPAWN_MIN_DISTANCE,
            max: ENEMY_SPAWN_MAX_DISTANCE,
          },
          enemy_spawn_side_angle_degrees: {
            min: Math.round(ENEMY_SPAWN_SIDE_ANGLE_MIN * 180 / Math.PI),
            max: Math.round(ENEMY_SPAWN_SIDE_ANGLE_MAX * 180 / Math.PI),
          },
          move_speed: PLAYER_MOVE_SPEED * this.controlResponse.applied.move_scale,
          attack_timing_ms: {
            windup: Math.round(PLAYER_ATTACK_WINDUP_SECONDS * 1000),
            active: Math.round(PLAYER_ATTACK_ACTIVE_SECONDS * 1000),
            recovery: Math.round(PLAYER_ATTACK_RECOVERY_SECONDS * 1000),
          },
          attack_range: PLAYER_ATTACK_RANGE,
          attack_arc_degrees: Math.round(PLAYER_ATTACK_HALF_ANGLE * 2 * 180 / Math.PI),
          dodge_seconds: DODGE_SECONDS,
          asset_pack: this.assetContext ? this.assetContext.id : null,
          scene_version: MeleeScene.version,
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

  Base3DMeleeArena.prototype.getObservation = function getObservation() {
    return {
      player: {
        x: this.x,
        z: this.z,
        yaw: this.yaw,
        camera_pitch: this.cameraPitch,
        health: this.health,
        health_unlimited: this.healthUnlimited,
        attack_state: this.attackState,
        dodging: this.dodgeRemaining > 0,
      },
      enemies: this.serializeEnemies(),
      covers: this.covers.map(function copyCover(cover) { return Object.assign({}, cover); }),
      nearest_enemy_distance: this.nearestEnemyDistance(),
      threatening_enemies: this.threateningEnemyCount(),
    };
  };

  Base3DMeleeArena.prototype.infoPayload = function infoPayload() {
    return this.metricsPayload();
  };

  Base3DMeleeArena.prototype.buildStepInfo = function buildStepInfo(state, stepOptions, normalized) {
    var info = Core.terminal.withInfo(this, state, this.infoPayload());
    info.action = { type: "game_step_action", id: normalized.id, args: normalized.args };
    info.durationMs = stepOptions.durationMs;
    info.source = stepOptions.source;
    return info;
  };

  Base3DMeleeArena.prototype.resetGym = function resetGym(options) {
    this.resetFromAPI(options || {});
    return { observation: this.getObservation(), reward: 0, done: false, info: this.infoPayload() };
  };

  Base3DMeleeArena.prototype.renderGameToText = function renderGameToText() {
    return JSON.stringify({
      coordinate_system: "third-person x/z arena coordinates; yaw radians; mouse changes camera-relative facing",
      status: this.mode,
      player: {
        x: this.x,
        z: this.z,
        yaw: this.yaw,
        health: this.health,
        health_unlimited: this.healthUnlimited,
        attack_state: this.attackState,
        attack_phase_remaining_ms: Math.round(this.attackPhaseRemaining * 1000),
        dodge_ready: this.dodgeCooldown <= 0,
      },
      enemies: this.serializeEnemies(),
      covers: this.covers,
      combat: this.metricsPayload(),
      visual_perturbations: this.visualPayload(),
    });
  };

  Base3DMeleeArena.prototype.updateBestMetrics = function updateBestMetrics() {
    this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, this.getPrimaryScore());
  };

  Base3DMeleeArena.prototype.makeEnemyMesh = function makeEnemyMesh(enemy) {
    return MeleeScene.character(this, "melee_" + enemy.type, PLAYER_HEIGHT * profileById(enemy.type).scale, false);
  };

  Base3DMeleeArena.prototype.attachEnemyMesh = function attachEnemyMesh(enemy) {
    if (!enemy || !enemy.alive || !this.enemyRegistry || this.enemyRegistry.get(enemy.id)) return;
    this.enemyRegistry.set(enemy.id, this.makeEnemyMesh(enemy));
  };

  Base3DMeleeArena.prototype.rebuildScene3D = function rebuildScene3D() {
    if (!this.world3d) return;
    this.sceneReady = false;
    this.world3d.clear();
    this.enemyRegistry = G3D.entities.createRegistry(this.world3d);
    this.sceneMeshes = MeleeScene.build(this);
    this.sceneReady = true;
    this.syncScene3D();
  };

  Base3DMeleeArena.prototype.syncScene3D = function syncScene3D() {
    if (!this.world3d) return;
    var optical = this.world3d.setOpticalChaseCamera({
      x: this.x, z: this.z, yaw: this.yaw, pitch: this.cameraPitch,
      distance: CAMERA_DISTANCE, shoulderOffset: this.cameraShoulderOffset,
      lookHeight: CAMERA_LOOK_HEIGHT, forwardLook: CAMERA_FORWARD_LOOK,
      bounds: this.map.bounds,
    });
    MeleeScene.constrainCamera(this, optical);
    MeleeScene.sync(this);
  };

  Base3DMeleeArena.prototype.render = function render() {
    G3D.visuals.sync(this, { sceneReady: true });
    if (!this.world3d) return;
    this.syncScene3D();
    this.world3d.render();
    if (this.infoPanel) this.infoPanel.update();
  };

  Base3DMeleeArena.prototype.resetFromAPI = function resetFromAPI(options) {
    return this.beginEpisode(options || {}, true);
  };

  async function start() {
    await G3D.assets.preload("gym-melee", ASSET_REQUIREMENTS);
    if (document.fonts) await document.fonts.ready;
    var game = new Base3DMeleeArena();
    await game.world3d.prepare();
    Core.createRuntime({
      game: game,
      presentation: {
        title: "3D Melee Combat",
        controls: "WASD moves relative to the camera. Move the mouse to orbit. Left-click slashes. Space dodges.",
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
              ["Health", (game.healthUnlimited ? "Unlimited" : game.health + " / " + game.maxHealth)],
              ["Kills", game.kills],
              ["Enemies", game.enemies.filter(function alive(enemy) { return enemy.alive; }).length],
              ["Attack", (game.attackState === "idle" ? "Ready" : game.attackState)],
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
