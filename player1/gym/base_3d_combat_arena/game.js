(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var G3D = window.BaseGamelet3D;
  var CombatScene = window.CombatArenaScene;
  var DepotLevel = window.CombatDepotLevel;
  var rewardConfig = window.Base3DCombatArenaRewardConfig;
  var GAME_ID = "base_3d_combat_arena";
  var LOGIC_WIDTH = 640;
  var LOGIC_HEIGHT = 640;
  var DISPLAY_WIDTH = G3D.viewport.baseWidth;
  var DISPLAY_HEIGHT = G3D.viewport.baseHeight;
  var STEP_MS = 1000 / 60;
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 5;
  var ASSET_REQUIREMENTS = CombatScene.requirements;
  var PERTURBATION_CONTRACT = Core.perturbations.defineContract({
    game_id: GAME_ID,
    control_response: {
      look_gain_scale: Core.controlResponse.ranges.look_gain_scale,
      move_scale: Core.controlResponse.ranges.move_scale,
      jump_scale: Core.controlResponse.ranges.jump_scale,
    },
    capabilities: {
      appearance: ["palette", "lighting", "background", "assets"],
      camera: ["orientation", "projection"],
      scene: ["layout", "player_spawn", "entity_spawn"],
    },
    defaults: {
      appearance_profile: "default",
      camera_profile: "default",
      scene_profile: "default",
    },
    samplers: {
      camera: {
        orientation: Core.perturbations.cameraOrientationSampler("aiming"),
      },
      scene: {
        layout: DepotLevel.sample,
      },
    },
  });

  var FLOOR_Y = 0;
  var EYE_HEIGHT = 1.35;
  var PLAYER_RADIUS = 0.3;
  var PLAYER_HIT_RADIUS = 0.48;
  var PLAYER_HIT_Y = 0.88;
  var MOVE_SPEED = 5;
  var JUMP_SPEED = 6.8;
  var GRAVITY = 18;
  var GROUND_EPSILON = 0.00001;
  var SENSITIVITY = G3D.input.CAMERA_SENSITIVITY;

  var MAGAZINE_SIZE = 30;
  var INITIAL_RESERVE_AMMO = 90;
  var RELOAD_SECONDS = 0.75;
  var FIRE_COOLDOWN_SECONDS = 0.1;
  var PLAYER_PROJECTILE_SPEED = 60;
  var PLAYER_PROJECTILE_RADIUS = 0.09;
  var PROJECTILE_LIFETIME_SECONDS = 3.2;

  var ENEMY_RADIUS = 0.43;
  var ENEMY_HIT_Y = 0.78;
  var ENEMY_HEAD_HIT_Y = 1.25;
  var ENEMY_HEAD_HIT_RADIUS = 0.24;
  var ENEMY_HEALTH = 1;
  var ENEMY_PROJECTILE_SPEED = 6;
  var ENEMY_PROJECTILE_RADIUS = 0.11;
  var RESPAWN_MIN_SECONDS = 0.7;
  var RESPAWN_JITTER_SECONDS = 0.4;

  var canvas = document.getElementById("display");


  function normalizeVector(vector) {
    var length = Math.sqrt(vector.x * vector.x + vector.y * vector.y + vector.z * vector.z);
    if (length <= 0.000001) return { x: 0, y: 0, z: -1 };
    return { x: vector.x / length, y: vector.y / length, z: vector.z / length };
  }

  function readCombatArenaUrlConfig(defaults) {
    var config = Core.config.readUrl(defaults);
    var params = new URLSearchParams(window.location.search || "");
    config.noObstacles = Core.config.normalizeBoolean(params.get("no_obstacles"), false);
    config.randomEnemyLane = Core.config.normalizeBoolean(params.get("random_enemy_lane"), false);
    return config;
  }

  function readOptionalBoolean(raw, snakeName, camelName) {
    if (U.object.hasOwn(raw, snakeName)) return Core.config.normalizeBoolean(raw[snakeName], null);
    if (U.object.hasOwn(raw, camelName)) return Core.config.normalizeBoolean(raw[camelName], null);
    return null;
  }

  function mergeCombatArenaEpisodeConfig(urlConfig, normalized, rawOptions) {
    var config = Core.config.mergeEpisode(urlConfig, normalized);
    var raw = rawOptions || {};
    var noObstacles = readOptionalBoolean(raw, "no_obstacles", "noObstacles");
    var randomEnemyLane = readOptionalBoolean(raw, "random_enemy_lane", "randomEnemyLane");
    config.noObstacles = noObstacles === null ? !!urlConfig.noObstacles : noObstacles;
    config.randomEnemyLane = randomEnemyLane === null ? !!urlConfig.randomEnemyLane : randomEnemyLane;
    return config;
  }

  function Base3DCombatArena() {
    this.defaults = {
      seed: DEFAULT_SEED,
      difficulty: DEFAULT_DIFFICULTY,
      maxDifficulty: MAX_DIFFICULTY,
    };
    this.urlConfig = readCombatArenaUrlConfig(this.defaults);
    this.controls = { forward: false, back: false, left: false, right: false };
    this.paused = false;
    this.runtime = { resetCount: 0, episodeCount: 0, lastResetMethod: null };
    this.bestMetrics = { bestPrimaryScore: 0 };
    this.sceneReady = false;
    Core.terminal.initialize(this);
    this.setup3D();
    this.createAsset = G3D.assets.bindGame(this);
    this.bindInput();
    Core.lifecycle.bindResetKeys(this);
    this.beginEpisode({}, false);
    this.startLoop();
  }

  Base3DCombatArena.prototype.setup3D = function setup3D() {
    canvas.tabIndex = 0;
    this.world3d = G3D.createWorld(canvas, {
      width: DISPLAY_WIDTH,
      height: DISPLAY_HEIGHT,
      fov: 70,
      near: 0.05,
      far: 110,
      clearColor: 0xcfe4ff,
      fogColor: 0xcfe4ff,
      fogNear: 28,
      fogFar: 85,
      eyeHeight: EYE_HEIGHT,
      ambient: 0.48,
      sun: 0.95,
      visualProfile: "stylized",
    });
    this.sceneMeshes = { coversById: {} };
    G3D.viewport.install(this, {
      canvas: canvas,
      world: this.world3d,
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
      baseFov: 70,
    });
  };

  Base3DCombatArena.prototype.setupViewWeapon = function setupViewWeapon() {
    if (!this.world3d || typeof THREE === "undefined") return;
    if (this.viewWeapon) G3D.entities.remove(this.viewWeapon, this.world3d.camera);
    this.weaponRig = CombatScene.createWeapon(this);
    this.viewWeapon = this.weaponRig.root;
  };

  Base3DCombatArena.prototype.beginEpisode = function beginEpisode(options, countReset, flags) {
    var episodeFlags = flags || {};
    var normalized = Core.config.normalizeOptions(options || {}, MAX_DIFFICULTY);
    var config = mergeCombatArenaEpisodeConfig(this.urlConfig, normalized, options || {});
    this.currentConfig = Core.config.cloneEpisode(config);
    Core.terminal.clear(this, episodeFlags);
    Core.lifecycle.resetEpisode(this, { controls: { forward: false, back: false, left: false, right: false } });
    Core.reward.resetEpisode(this);
    Core.domains.beginEpisode(this, config, PERTURBATION_CONTRACT, DEFAULT_SEED);
    this.difficulty = config.difficulty;
    G3D.visuals.configure(this, config, {
      defaultAssetPack: "gym-depot",
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
    });
    this.sceneLayout = Core.domains.sample(this, "scene", "layout", DepotLevel.sample({ profile: "default" }));
    this.map = DepotLevel.build(this.sceneLayout, !!config.noObstacles);
    this.covers = this.map.colliders;
    this.setupViewWeapon();
    var playerRng = Core.domains.gameplayRng(this, "scene", "player_spawn");
    var playerX = this.map.spawn.x + playerRng.range(-0.35, 0.35);
    var playerZ = this.map.spawn.z + playerRng.range(-0.25, 0.25);
    var cameraOrientation = Core.domains.sample(this, "camera", "orientation", {
      yaw_offset_radians: 0,
      pitch_offset_radians: 0,
    });
    this.x = playerX;
    this.z = playerZ;
    this.y = FLOOR_Y;
    this.vy = 0;
    this.grounded = true;
    this.yaw = cameraOrientation.yaw_offset_radians;
    this.pitch = cameraOrientation.pitch_offset_radians;
    this.sensitivity = SENSITIVITY * this.controlResponse.applied.look_gain_scale;
    this.health = null;
    this.maxHealth = null;
    this.healthUnlimited = true;
    this.magazineAmmo = MAGAZINE_SIZE;
    this.reserveAmmo = INITIAL_RESERVE_AMMO;
    this.reloading = false;
    this.reloadRemaining = 0;
    this.fireCooldown = 0;
    this.noObstacles = !!config.noObstacles;
    this.randomEnemyLane = !!config.randomEnemyLane;
    this.enemies = [];
    this.projectiles = [];
    this.respawnQueue = [];
    this.enemySerial = 0;
    this.projectileSerial = 0;
    this.targetEnemyCount = Math.min(4, Math.max(1, Math.round(this.difficulty)));

    this.kills = 0;
    this.deaths = 0;
    this.damageDealt = 0;
    this.damageTaken = 0;
    this.fireAttempts = 0;
    this.shotsFired = 0;
    this.projectileHits = 0;
    this.shotsMissed = 0;
    this.emptyFireAttempts = 0;
    this.cooldownFireAttempts = 0;
    this.reloadBlockedFireAttempts = 0;
    this.reloadsStarted = 0;
    this.reloadsCompleted = 0;
    this.reloadAttemptsWithoutAmmo = 0;
    this.jumps = 0;
    this.enemyShotsFired = 0;
    this.enemyHits = 0;
    this.playerProjectilesBlocked = 0;
    this.enemyProjectilesBlocked = 0;
    this.enemiesSpawned = 0;
    this.enemyRespawns = 0;
    this.enemyDirectionChanges = 0;
    this.playerCollisions = 0;
    this.enemyCollisions = 0;
    this.stepCount = 0;
    this.gameTimeMs = 0;
    this.visualStride = 0;
    this.lastShot = null;
    this.lastImpact = null;
    this.lastPlayerHitMs = null;
    this.lastAction = "reset";
    this.lastDamageSource = null;
    this.mode = config.autostart ? "playing" : "paused";
    this.terminal = { isTerminal: false, outcome: null, reason: null };
    this.controls = { forward: false, back: false, left: false, right: false };
    this.sceneReady = false;
    for (var i = 0; i < this.targetEnemyCount; i += 1) this.spawnEnemy(false, false);
    this.initializeCamera();
    if (countReset) this.runtime.resetCount += 1;
    this.runtime.episodeCount += 1;
    this.runtime.lastResetMethod = countReset ? "inplace_reset" : "init";
    this.rebuildScene3D();
    this.updateBestMetrics();
    this.render();
    return { accepted: normalized, applied: config, notes: [] };
  };

  Base3DCombatArena.prototype.initializeCamera = function initializeCamera() {
    var rng = new U.Rng((Core.seeds.forDomain(this, "camera") ^ 0x63616d32) >>> 0,
      DEFAULT_SEED, { allowZeroSeed: true });
    var self = this;
    var targets = this.enemies.filter(function visible(enemy) { return self.enemyVisible(enemy); });
    targets.sort(function nearCrosshair(a, b) {
      var first = self.enemyAimError(a), second = self.enemyAimError(b);
      return Math.hypot(first.yaw, first.pitch) - Math.hypot(second.yaw, second.pitch);
    });
    var target = targets[0];
    var referenceYaw = this.yaw, referencePitch = -0.08;
    if (target) {
      var eye = { x: this.x, y: this.y + EYE_HEIGHT, z: this.z };
      var targetY = this.lineBlocked(eye, { x: target.x, y: target.y, z: target.z })
        ? target.headY : target.y;
      referenceYaw = Math.atan2(target.x - this.x, this.z - target.z);
      referencePitch = Math.atan2(targetY - eye.y, U.geometry3d.horizontalDistance(this, target));
    }
    // Signed and exact-zero residuals cover both correction directions and axis preservation.
    var yawResidual = rng.randint(-1, 2) * rng.range(0.12, 0.28);
    var pitchResidual = rng.randint(-1, 2) * rng.range(0.06, 0.12);
    this.yaw = U.math.normalizeAngle(referenceYaw + yawResidual);
    this.pitch = referencePitch + pitchResidual;
    this.cameraInitialization = {
      target_id: target ? target.id : null,
      reference_yaw: referenceYaw, reference_pitch: referencePitch,
      yaw_residual: yawResidual, pitch_residual: pitchResidual, applied_pitch: this.pitch,
    };
  };

  Base3DCombatArena.prototype.bindInput = function bindInput() {
    this.inputController = G3D.input.createController(this, {
      canvas: canvas,
      controlAliases: {
        reload: ["e", "KeyE"],
        jump: [" ", "Space", "Spacebar"],
      },
      onPress: function onPress(control) {
        if (control === "reload") this.startReload();
        else if (control === "jump") this.startJump();
      },
      onLook: function onLook(dx, dy) { this.applyMouse(dx, dy); },
      onMouseDown: function onMouseDown(event) {
        if (event.button === 0) this.fire();
      },
    });
    var app = document.getElementById("app");
    if (app) app.focus();
    canvas.focus();
  };

  Base3DCombatArena.prototype.ensureSimulationRunner = function ensureSimulationRunner() {
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

  Base3DCombatArena.prototype.startLoop = function startLoop() {
    this.ensureSimulationRunner().start();
  };

  Base3DCombatArena.prototype.pause = function pause() {
    return Core.lifecycle.pause(this);
  };

  Base3DCombatArena.prototype.resume = function resume() {
    return Core.lifecycle.resume(this);
  };

  Base3DCombatArena.prototype.cameraLookOptions = function cameraLookOptions() {
    return {
      sensitivity: this.sensitivity,
      pitchMin: -1.0,
      pitchMax: 0.9,
    };
  };

  Base3DCombatArena.prototype.applyMouse = function applyMouse(dx, dy) {
    if (this.terminal.isTerminal) return;
    if (this.mode === "paused") this.mode = "playing";
    G3D.input.applyPointerLook(this, dx, dy, this.cameraLookOptions());
    this.lastAction = "mouse(" + dx.toFixed(1) + "," + dy.toFixed(1) + ")";
  };

  Base3DCombatArena.prototype.applyRelativePointerInput = function applyRelativePointerInput(pointerInput) {
    if (this.terminal.isTerminal || !pointerInput) return;
    if (this.mode === "paused") this.mode = "playing";
    G3D.input.applyRelativePointerInput(this, pointerInput, this.cameraLookOptions());
    this.lastAction = "relative_pointer(" + pointerInput.dx + "," + pointerInput.dy + ")";
  };

  Base3DCombatArena.prototype.viewDirection = function viewDirection() {
    return G3D.input.directionFromLook(this.yaw - Math.PI / 2, this.pitch);
  };

  Base3DCombatArena.prototype.addReward = function addReward(value) {
    Core.reward.add(this, value);
  };

  Base3DCombatArena.prototype.difficultyRatio = function difficultyRatio() {
    return U.math.clamp((this.difficulty - 1) / Math.max(1, MAX_DIFFICULTY - 1), 0, 1);
  };

  Base3DCombatArena.prototype.enemyMoveSpeed = function enemyMoveSpeed() {
    return 1.55 + this.difficultyRatio() * 1.45;
  };

  Base3DCombatArena.prototype.enemyProjectileSpeed = function enemyProjectileSpeed() {
    return ENEMY_PROJECTILE_SPEED + this.difficultyRatio() * 2.2;
  };

  Base3DCombatArena.prototype.enemyTargetingAccuracy = function enemyTargetingAccuracy() {
    return 0.25 + this.difficultyRatio() * 0.25;
  };

  Base3DCombatArena.prototype.enemyFireInterval = function enemyFireInterval(rng) {
    var ratio = this.difficultyRatio();
    var min = 1.85 - ratio * 0.75;
    var max = 2.6 - ratio * 1.05;
    return rng.range(min, min + Math.max(0.15, max - min));
  };

  Base3DCombatArena.prototype.coverBounds = function coverBounds(cover, expand) {
    var amount = Number(expand) || 0;
    return {
      minX: cover.x - cover.width / 2 - amount,
      maxX: cover.x + cover.width / 2 + amount,
      minY: FLOOR_Y - amount,
      maxY: FLOOR_Y + cover.height + amount,
      minZ: cover.z - cover.depth / 2 - amount,
      maxZ: cover.z + cover.depth / 2 + amount,
    };
  };

  Base3DCombatArena.prototype.circleOverlapsCover = function circleOverlapsCover(x, z, radius) {
    if (!this.map.contains(x, z, radius)) return true;
    for (var i = 0; i < this.covers.length; i += 1) {
      if (U.geometry3d.circleOverlapsAabbXZ(x, z, radius, U.geometry3d.aabbFromBox(this.covers[i]))) return true;
    }
    return false;
  };

  Base3DCombatArena.prototype.enemySpawnBlocked = function enemySpawnBlocked(x, z) {
    var clearance = ENEMY_RADIUS + 0.08;
    if (this.circleOverlapsCover(x, z, clearance)) return true;
    for (var i = 0; i < this.enemies.length; i += 1) {
      var enemy = this.enemies[i];
      if (!enemy.alive) continue;
      var dx = enemy.x - x;
      var dz = enemy.z - z;
      if (Math.sqrt(dx * dx + dz * dz) < ENEMY_RADIUS * 2 + 0.2) return true;
    }
    return false;
  };

  Base3DCombatArena.prototype.coverHitDistance = function coverHitDistance(start, end, radius) {
    var direction = { x: end.x - start.x, y: end.y - start.y, z: end.z - start.z };
    var length = Math.sqrt(direction.x * direction.x + direction.y * direction.y + direction.z * direction.z);
    if (length <= 0.000001) return null;
    direction.x /= length;
    direction.y /= length;
    direction.z /= length;
    var nearest = null;
    for (var i = 0; i < this.covers.length; i += 1) {
      var hit = U.geometry3d.raycastAabb(start, direction, this.coverBounds(this.covers[i], radius), length);
      if (hit && (nearest === null || hit.distance < nearest)) nearest = hit.distance;
    }
    return nearest;
  };

  Base3DCombatArena.prototype.lineBlocked = function lineBlocked(start, end) {
    var hitDistance = this.coverHitDistance(start, end, 0.01);
    return hitDistance !== null && hitDistance < U.geometry3d.distance(start, end) - 0.03;
  };

  Base3DCombatArena.prototype.enemyHitDistance = function enemyHitDistance(start, end, enemy, expand) {
    var amount = Math.max(0, Number(expand) || 0);
    var bodyDistance = U.geometry3d.segmentSphereHitDistance(
      start,
      end,
      { x: enemy.x, y: enemy.y, z: enemy.z },
      enemy.radius + amount,
    );
    var headDistance = U.geometry3d.segmentSphereHitDistance(
      start,
      end,
      { x: enemy.x, y: enemy.headY, z: enemy.z },
      enemy.headRadius + amount,
    );
    if (bodyDistance === null) return headDistance;
    if (headDistance === null) return bodyDistance;
    return Math.min(bodyDistance, headDistance);
  };

  Base3DCombatArena.prototype.spawnEnemy = function spawnEnemy(isRespawn, attachMesh) {
    var rng = Core.domains.gameplayRng(this, "scene", "entity_spawn"), point = null;
    var laneIndex = this.enemySerial % this.map.patrolAnchors.length;
    if (!isRespawn) {
      var anchor = this.map.patrolAnchors[laneIndex];
      for (var initialAttempt = 0; initialAttempt < 24 && !point; initialAttempt += 1) {
        var initial = { x: anchor.x + rng.range(-0.65, 0.65), z: anchor.z + rng.range(-0.25, 0.25) };
        if (!this.enemySpawnBlocked(initial.x, initial.z)) point = initial;
      }
    }
    for (var attempt = 0; attempt < 80 && !point; attempt += 1) {
      var angle = rng.range(-Math.PI, Math.PI), distance = rng.range(6, 10.5);
      var candidate = { x: this.x + Math.cos(angle) * distance, z: this.z + Math.sin(angle) * distance };
      if (this.enemySpawnBlocked(candidate.x, candidate.z)) continue;
      var visible = !this.lineBlocked({ x: candidate.x, y: ENEMY_HIT_Y, z: candidate.z },
        { x: this.x, y: this.y + PLAYER_HIT_Y, z: this.z });
      if (!visible && attempt < 64) continue;
      if (!visible && !this.map.findPath(candidate, this.navigationGoal(candidate), ENEMY_RADIUS).length) continue;
      point = candidate;
    }
    if (!point) {
      var self = this;
      var candidates = this.map.patrolAnchors.concat(this.map.floorPatches.map(function center(rect) {
        return { x: rect.x, z: rect.z };
      })).filter(function available(candidate) {
        return !self.enemySpawnBlocked(candidate.x, candidate.z) && Math.hypot(candidate.x - self.x, candidate.z - self.z) > 2;
      }).sort(function nearest(a, b) {
        return Math.abs(Math.hypot(a.x - self.x, a.z - self.z) - 7) - Math.abs(Math.hypot(b.x - self.x, b.z - self.z) - 7);
      });
      point = candidates[0];
      if (!point) throw new Error("Combat depot has no clear enemy spawn");
    }
    var behaviorRng = Core.domains.createEntityRng(this, rng, DEFAULT_SEED);
    var direction = behaviorRng.next() < 0.5 ? -1 : 1;
    var enemy = {
      id: "enemy_" + (this.enemySerial + 1), x: point.x, z: point.z,
      y: ENEMY_HIT_Y, radius: ENEMY_RADIUS, headY: ENEMY_HEAD_HIT_Y, headRadius: ENEMY_HEAD_HIT_RADIUS,
      health: ENEMY_HEALTH, maxHealth: ENEMY_HEALTH, strafeSign: direction,
      vx: direction * this.enemyMoveSpeed(), vz: 0,
      patrolMinX: this.map.bounds.minX + ENEMY_RADIUS, patrolMaxX: this.map.bounds.maxX - ENEMY_RADIUS,
      spawnLaneIndex: laneIndex, spawnLaneZ: point.z,
      fireRemaining: behaviorRng.range(0.65, 0.65 + this.enemyFireInterval(behaviorRng)),
      navigationPath: [], navigationIndex: 1, navigationRemaining: 0,
      alive: true, shotsFired: 0, directionChanges: 0, distanceTravelled: 0, behaviorRng: behaviorRng,
    };
    this.enemySerial += 1;
    this.enemiesSpawned += 1;
    if (isRespawn) this.enemyRespawns += 1;
    this.enemies.push(enemy);
    if (attachMesh !== false && this.sceneReady) this.attachEnemyMesh(enemy);
    return enemy;
  };

  Base3DCombatArena.prototype.navigationGoal = function navigationGoal(enemy) {
    if (this.map.contains(this.x, this.z, ENEMY_RADIUS)) return { x: this.x, z: this.z };
    var clearance = ENEMY_RADIUS + 0.02;
    var candidates = [];
    for (var i = 0; i < this.covers.length; i += 1) {
      var bounds = this.coverBounds(this.covers[i]);
      if (!U.geometry3d.circleOverlapsAabbXZ(this.x, this.z, ENEMY_RADIUS, bounds)) continue;
      var projectedX = U.math.clamp(this.x, bounds.minX, bounds.maxX);
      var projectedZ = U.math.clamp(this.z, bounds.minZ, bounds.maxZ);
      candidates.push(
        { x: bounds.minX - clearance, z: projectedZ },
        { x: bounds.maxX + clearance, z: projectedZ },
        { x: projectedX, z: bounds.minZ - clearance },
        { x: projectedX, z: bounds.maxZ + clearance },
      );
    }
    var self = this;
    candidates = candidates.filter(function walkable(point) {
      return self.map.contains(point.x, point.z, ENEMY_RADIUS);
    }).sort(function nearest(a, b) {
      var playerDistance = Math.hypot(a.x - self.x, a.z - self.z) - Math.hypot(b.x - self.x, b.z - self.z);
      return Math.abs(playerDistance) > GROUND_EPSILON ? playerDistance
        : Math.hypot(a.x - enemy.x, a.z - enemy.z) - Math.hypot(b.x - enemy.x, b.z - enemy.z);
    });
    return candidates[0] || { x: enemy.x, z: enemy.z };
  };

  Base3DCombatArena.prototype.createProjectile = function createProjectile(owner, origin, direction, speed) {
    var normalized = normalizeVector(direction);
    var projectile = {
      id: (owner === "player" ? "player_shot_" : "enemy_shot_") + (this.projectileSerial + 1),
      owner: owner,
      x: origin.x,
      y: origin.y,
      z: origin.z,
      vx: normalized.x * speed,
      vy: normalized.y * speed,
      vz: normalized.z * speed,
      radius: owner === "player" ? PLAYER_PROJECTILE_RADIUS : ENEMY_PROJECTILE_RADIUS,
      life: PROJECTILE_LIFETIME_SECONDS,
      alive: true,
    };
    this.projectileSerial += 1;
    this.projectiles.push(projectile);
    if (this.sceneReady) this.attachProjectileMesh(projectile);
    return projectile;
  };

  Base3DCombatArena.prototype.fire = function fire() {
    if (this.terminal.isTerminal) return false;
    if (this.mode === "paused") this.mode = "playing";
    this.fireAttempts += 1;
    if (this.reloading) {
      this.reloadBlockedFireAttempts += 1;
      this.lastAction = "fire_blocked_reloading";
      return false;
    }
    if (this.fireCooldown > 1e-6) {
      this.cooldownFireAttempts += 1;
      this.lastAction = "fire_blocked_cooldown";
      return false;
    }
    if (this.magazineAmmo <= 0) {
      this.emptyFireAttempts += 1;
      this.lastAction = "fire_empty";
      this.startAutoReload();
      return false;
    }
    var direction = this.viewDirection();
    this.magazineAmmo -= 1;
    this.shotsFired += 1;
    this.fireCooldown = FIRE_COOLDOWN_SECONDS;
    var projectile = this.createProjectile("player", {
      x: this.x + direction.x * 0.42,
      y: this.y + EYE_HEIGHT - 0.08 + direction.y * 0.42,
      z: this.z + direction.z * 0.42,
    }, direction, PLAYER_PROJECTILE_SPEED);
    this.lastShot = { id: projectile.id, timeMs: this.gameTimeMs,
      x: projectile.x, y: projectile.y, z: projectile.z, end: null };
    this.lastAction = "fire";
    this.startAutoReload();
    return true;
  };

  Base3DCombatArena.prototype.startReload = function startReload() {
    if (this.terminal.isTerminal || this.reloading || this.magazineAmmo >= MAGAZINE_SIZE) return false;
    if (this.reserveAmmo <= 0) {
      this.reloadAttemptsWithoutAmmo += 1;
      this.lastAction = "reload_no_reserve";
      return false;
    }
    this.reloading = true;
    this.reloadRemaining = RELOAD_SECONDS;
    this.reloadsStarted += 1;
    this.lastAction = "reload_start";
    return true;
  };

  Base3DCombatArena.prototype.startAutoReload = function startAutoReload() {
    if (this.magazineAmmo > 0 || this.reserveAmmo <= 0 || this.reloading) return false;
    return this.startReload();
  };

  Base3DCombatArena.prototype.completeReload = function completeReload() {
    var needed = MAGAZINE_SIZE - this.magazineAmmo;
    var transferred = Math.min(needed, this.reserveAmmo);
    this.magazineAmmo += transferred;
    this.reserveAmmo -= transferred;
    this.reloading = false;
    this.reloadRemaining = 0;
    this.reloadsCompleted += 1;
    this.lastAction = "reload_complete";
  };

  Base3DCombatArena.prototype.startJump = function startJump() {
    if (this.terminal.isTerminal || !this.grounded) return false;
    if (this.mode === "paused") this.mode = "playing";
    this.vy = JUMP_SPEED * this.controlResponse.applied.jump_scale;
    this.grounded = false;
    this.jumps += 1;
    this.lastAction = "jump";
    return true;
  };

  Base3DCombatArena.prototype.enemyAimError = function enemyAimError(enemy) {
    var dx = enemy.x - this.x;
    var dz = enemy.z - this.z;
    var horizontalDistance = Math.max(0.001, Math.sqrt(dx * dx + dz * dz));
    var targetYaw = Math.atan2(dx, -dz);
    var targetPitch = Math.atan2(enemy.y - (this.y + EYE_HEIGHT), horizontalDistance);
    return {
      yaw: U.math.normalizeAngle(targetYaw - this.yaw),
      pitch: targetPitch - this.pitch,
      distance: horizontalDistance,
    };
  };

  Base3DCombatArena.prototype.enemyVisible = function enemyVisible(enemy) {
    if (!enemy || !enemy.alive) return false;
    var error = this.enemyAimError(enemy);
    var bodyVisible = Math.abs(error.yaw) <= 0.95 && Math.abs(error.pitch) <= 0.75 && !this.lineBlocked(
      { x: this.x, y: this.y + EYE_HEIGHT, z: this.z },
      { x: enemy.x, y: enemy.y, z: enemy.z },
    );
    if (bodyVisible) return true;
    var horizontalDistance = Math.max(0.001, U.geometry3d.horizontalDistance(this, enemy));
    var headPitch = Math.atan2(enemy.headY - (this.y + EYE_HEIGHT), horizontalDistance) - this.pitch;
    return Math.abs(error.yaw) <= 0.95 && Math.abs(headPitch) <= 0.75 && !this.lineBlocked(
      { x: this.x, y: this.y + EYE_HEIGHT, z: this.z },
      { x: enemy.x, y: enemy.headY, z: enemy.z },
    );
  };

  Base3DCombatArena.prototype.damageEnemy = function damageEnemy(enemy, damage) {
    if (!enemy || !enemy.alive) return false;
    var applied = Math.min(enemy.health, Math.max(0, damage));
    enemy.health -= applied;
    this.damageDealt += applied;
    if (enemy.health > 0) return false;
    enemy.alive = false;
    this.lastImpact = { timeMs: this.gameTimeMs, x: enemy.x, y: enemy.y, z: enemy.z };
    this.kills += 1;
    this.addReward(rewardConfig.constants.killReward);
    this.respawnQueue.push({
      remaining: enemy.behaviorRng.range(
        RESPAWN_MIN_SECONDS,
        RESPAWN_MIN_SECONDS + RESPAWN_JITTER_SECONDS
      ),
    });
    CombatScene.showDefeat(this, enemy);
    this.lastAction = "projectile_kill";
    this.startAutoReload();
    return true;
  };

  Base3DCombatArena.prototype.takePlayerDamage = function takePlayerDamage(sourceId) {
    this.damageTaken += 1;
    this.lastPlayerHitMs = this.gameTimeMs;
    this.enemyHits += 1;
    this.lastDamageSource = sourceId;
    this.lastAction = "player_hit";
    this.addReward(-rewardConfig.constants.hitPenalty);
    return true;
  };

  Base3DCombatArena.prototype.tryMove = function tryMove(dx, dz, radius) {
    var feetY = this.y;
    var movement = U.geometry3d.moveCircleWithAabbs(
      { x: this.x, z: this.z },
      { x: dx, z: dz },
      {
        radius: radius,
        bounds: this.map.bounds,
        colliders: this.covers,
        filter: function blocksPlayer(cover) {
          return cover.kind === "boundary" || feetY < FLOOR_Y + cover.height - GROUND_EPSILON;
        },
      }
    );
    this.x = movement.x;
    this.z = movement.z;
    return {
      moved: movement.movedX || movement.movedZ,
      blocked: movement.blockedX || movement.blockedZ,
    };
  };

  Base3DCombatArena.prototype.updatePlayerMovement = function updatePlayerMovement(dt) {
    var move = G3D.input.moveDelta(this.yaw - Math.PI / 2, this.controls, MOVE_SPEED * this.controlResponse.applied.move_scale, dt);
    if (move.forward || move.strafe) {
      var scale = move.forward && move.strafe ? Math.SQRT1_2 : 1;
      if (this.tryMove(move.x * scale, move.z * scale, PLAYER_RADIUS).blocked) this.playerCollisions += 1;
    }

    // Resolve the highest surface crossed while falling, using the same cover
    // footprint as horizontal collision. Walking off its edge resumes gravity.
    var previousY = this.y;
    var nextY = previousY + this.vy * dt - GRAVITY * dt * dt / 2;
    this.vy -= GRAVITY * dt;
    var supportY = FLOOR_Y;
    for (var i = 0; i < this.covers.length; i += 1) {
      var cover = this.covers[i];
      var top = FLOOR_Y + cover.height;
      if (cover.kind !== "boundary" && previousY >= top - GROUND_EPSILON
        && U.geometry3d.circleOverlapsAabbXZ(this.x, this.z, PLAYER_RADIUS, U.geometry3d.aabbFromBox(cover))) {
        supportY = Math.max(supportY, top);
      }
    }
    this.grounded = this.vy <= 0 && nextY <= supportY + GROUND_EPSILON;
    this.y = this.grounded ? supportY : nextY;
    if (this.grounded) this.vy = 0;
  };

  Base3DCombatArena.prototype.enemyHasLineOfSight = function enemyHasLineOfSight(enemy) {
    return !this.lineBlocked(
      { x: enemy.x, y: enemy.y, z: enemy.z },
      { x: this.x, y: this.y + PLAYER_HIT_Y, z: this.z },
    );
  };

  Base3DCombatArena.prototype.fireEnemyProjectile = function fireEnemyProjectile(enemy) {
    var behaviorRng = enemy.behaviorRng;
    var targetYaw = Math.atan2(this.x - enemy.x, -(this.z - enemy.z));
    var horizontalDistance = Math.max(0.01, U.geometry3d.horizontalDistance(enemy, this));
    var targetPitch = Math.atan2(this.y + PLAYER_HIT_Y - enemy.y, horizontalDistance);
    var ratio = this.difficultyRatio();
    var aimedShot = behaviorRng.next() < this.enemyTargetingAccuracy();
    var yawOffset;
    var pitchOffset;
    if (aimedShot) {
      yawOffset = behaviorRng.range(-0.008, 0.008);
      pitchOffset = behaviorRng.range(-0.006, 0.006);
    } else {
      var missSide = behaviorRng.next() < 0.5 ? -1 : 1;
      yawOffset = missSide * behaviorRng.range(0.16 - ratio * 0.06, 0.5 - ratio * 0.2);
      pitchOffset = behaviorRng.range(-(0.16 - ratio * 0.06) / 2, (0.16 - ratio * 0.06) / 2);
    }
    var yaw = targetYaw + yawOffset;
    var pitch = targetPitch + pitchOffset;
    var horizontal = Math.cos(pitch);
    var direction = {
      x: Math.sin(yaw) * horizontal,
      y: Math.sin(pitch),
      z: -Math.cos(yaw) * horizontal,
    };
    this.createProjectile("enemy", {
      x: enemy.x + direction.x * 0.5,
      y: enemy.y,
      z: enemy.z + direction.z * 0.5,
    }, direction, this.enemyProjectileSpeed());
    enemy.shotsFired += 1;
    enemy.visualShotTimeMs = this.gameTimeMs;
    this.enemyShotsFired += 1;
  };

  Base3DCombatArena.prototype.updateEnemies = function updateEnemies(dt) {
    this.enemies = this.enemies.filter(function keepAlive(enemy) { return enemy.alive; });
    for (var i = 0; i < this.enemies.length; i += 1) {
      var enemy = this.enemies[i], speed = this.enemyMoveSpeed();
      var visible = this.enemyHasLineOfSight(enemy);
      var reacquiring = !visible || Math.hypot(enemy.x - this.x, enemy.z - this.z) > 11.5;
      var dx = enemy.strafeSign * speed * dt, dz = 0;
      if (reacquiring) {
        enemy.navigationRemaining -= dt;
        if (enemy.navigationRemaining <= 0 || !enemy.navigationPath.length) {
          enemy.navigationPath = this.map.findPath(enemy, this.navigationGoal(enemy), enemy.radius);
          enemy.navigationIndex = 1;
          enemy.navigationRemaining = 0.6;
        }
        var target = enemy.navigationPath[enemy.navigationIndex];
        while (target && Math.hypot(target.x - enemy.x, target.z - enemy.z) < 0.22) {
          target = enemy.navigationPath[++enemy.navigationIndex];
        }
        if (target) {
          var distance = Math.hypot(target.x - enemy.x, target.z - enemy.z);
          dx = (target.x - enemy.x) / distance * Math.min(speed * dt, distance);
          dz = (target.z - enemy.z) / distance * Math.min(speed * dt, distance);
        }
      } else enemy.navigationRemaining = 0;
      var movement = U.geometry3d.moveCircleWithAabbs(enemy, { x: dx, z: dz },
        { radius: enemy.radius, bounds: this.map.bounds, colliders: this.covers });
      if (movement.blockedX || movement.blockedZ) {
        enemy.strafeSign *= -1; enemy.navigationRemaining = 0;
        enemy.directionChanges += 1; this.enemyDirectionChanges += 1; this.enemyCollisions += 1;
      }
      enemy.vx = (movement.x - enemy.x) / dt; enemy.vz = (movement.z - enemy.z) / dt;
      enemy.distanceTravelled += Math.hypot(movement.x - enemy.x, movement.z - enemy.z);
      enemy.x = movement.x; enemy.z = movement.z;
      enemy.fireRemaining -= dt;
      if (enemy.fireRemaining <= 0) {
        if (this.enemyHasLineOfSight(enemy)) {
          this.fireEnemyProjectile(enemy);
          enemy.fireRemaining = this.enemyFireInterval(enemy.behaviorRng);
        } else enemy.fireRemaining = enemy.behaviorRng.range(0.22, 0.4);
      }
    }
  };

  Base3DCombatArena.prototype.resolvePlayerProjectile = function resolvePlayerProjectile(projectile, start, end, coverDistance) {
    var nearestEnemy = null;
    var nearestDistance = null;
    for (var i = 0; i < this.enemies.length; i += 1) {
      var enemy = this.enemies[i];
      if (!enemy.alive) continue;
      var hitDistance = this.enemyHitDistance(start, end, enemy, projectile.radius);
      if (hitDistance !== null && (nearestDistance === null || hitDistance < nearestDistance)) {
        nearestEnemy = enemy;
        nearestDistance = hitDistance;
      }
    }
    if (nearestEnemy && (coverDistance === null || nearestDistance <= coverDistance)) {
      this.projectileHits += 1;
      this.damageEnemy(nearestEnemy, 1);
      return true;
    }
    if (coverDistance !== null) {
      this.playerProjectilesBlocked += 1;
      this.shotsMissed += 1;
      return true;
    }
    return false;
  };

  Base3DCombatArena.prototype.resolveEnemyProjectile = function resolveEnemyProjectile(projectile, start, end, coverDistance) {
    var playerDistance = U.geometry3d.segmentSphereHitDistance(
      start,
      end,
      { x: this.x, y: this.y + PLAYER_HIT_Y, z: this.z },
      PLAYER_HIT_RADIUS + projectile.radius,
    );
    if (playerDistance !== null && (coverDistance === null || playerDistance <= coverDistance)) {
      this.takePlayerDamage(projectile.id);
      return true;
    }
    if (coverDistance !== null) {
      this.enemyProjectilesBlocked += 1;
      return true;
    }
    return false;
  };

  Base3DCombatArena.prototype.updateProjectiles = function updateProjectiles(dt) {
    var active = this.projectiles;
    var kept = [];
    var terminalBefore = Core.terminal.generation(this);
    for (var i = 0; i < active.length; i += 1) {
      var projectile = active[i];
      if (!projectile.alive) continue;
      var start = { x: projectile.x, y: projectile.y, z: projectile.z };
      var end = {
        x: projectile.x + projectile.vx * dt,
        y: projectile.y + projectile.vy * dt,
        z: projectile.z + projectile.vz * dt,
      };
      var coverDistance = this.coverHitDistance(start, end, projectile.radius);
      var resolved = projectile.owner === "player"
        ? this.resolvePlayerProjectile(projectile, start, end, coverDistance)
        : this.resolveEnemyProjectile(projectile, start, end, coverDistance);
      if (this.lastShot && this.lastShot.id === projectile.id) {
        this.lastShot.end = resolved && this.lastImpact && this.lastImpact.timeMs === this.gameTimeMs
          ? { x: this.lastImpact.x, y: this.lastImpact.y, z: this.lastImpact.z }
          : coverDistance !== null ? {
            x: start.x + projectile.vx * dt * coverDistance / U.geometry3d.distance(start, end),
            y: start.y + projectile.vy * dt * coverDistance / U.geometry3d.distance(start, end),
            z: start.z + projectile.vz * dt * coverDistance / U.geometry3d.distance(start, end),
          } : end;
      }
      if (Core.terminal.generatedSince(this, terminalBefore)) return false;
      projectile.life -= dt;
      projectile.x = end.x;
      projectile.y = end.y;
      projectile.z = end.z;
      var outside = projectile.x < this.map.bounds.minX - 1 || projectile.x > this.map.bounds.maxX + 1
        || projectile.z < this.map.bounds.minZ - 1 || projectile.z > this.map.bounds.maxZ + 1
        || projectile.y < -1 || projectile.y > 5;
      if (!resolved && projectile.life > 0 && !outside) {
        kept.push(projectile);
      } else {
        if (!resolved && projectile.owner === "player") this.shotsMissed += 1;
        this.removeProjectileMesh(projectile.id);
      }
    }
    this.projectiles = kept;
    return true;
  };

  Base3DCombatArena.prototype.updateRespawns = function updateRespawns(dt) {
    var kept = [];
    for (var i = 0; i < this.respawnQueue.length; i += 1) {
      var pending = this.respawnQueue[i];
      pending.remaining -= dt;
      if (pending.remaining <= 0) this.spawnEnemy(true, true);
      else kept.push(pending);
    }
    this.respawnQueue = kept;
  };

  Base3DCombatArena.prototype.update = function update(dt) {
    if (this.terminal.isTerminal || this.mode !== "playing" || this.paused) return;
    this.stepCount += 1;
    this.gameTimeMs += dt * 1000;
    this.fireCooldown = Math.max(0, this.fireCooldown - dt);
    if (this.reloading) {
      this.reloadRemaining = Math.max(0, this.reloadRemaining - dt);
      if (this.reloadRemaining <= 0) this.completeReload();
    }
    var priorX = this.x, priorZ = this.z;
    this.updatePlayerMovement(dt);
    this.visualStride += Math.hypot(this.x - priorX, this.z - priorZ);
    this.updateEnemies(dt);
    if (!this.updateProjectiles(dt)) return;
    this.updateRespawns(dt);
    this.updateBestMetrics();
  };

  Base3DCombatArena.prototype.advanceTime = function advanceTime(ms, options) {
    var opts = typeof options === "object" && options !== null ? options : { render: options !== false };
    this.ensureSimulationRunner().advance(ms, opts);
    if (opts.returnState === false) return null;
    return this.getStatePayload();
  };

  Base3DCombatArena.prototype.normalizeAction = function normalizeAction(action) {
    var normalized = G3D.input.readAction(action, {
      controlAliases: {
        reload: ["e", "KeyE"],
        jump: ["space", "Space", " "],
      },
    });
    return {
      id: normalized.id,
      args: normalized.args,
      forward: normalized.controls.forward,
      back: normalized.controls.back,
      left: normalized.controls.left,
      right: normalized.controls.right,
      reload: normalized.controls.reload,
      jump: normalized.controls.jump,
      pointerInput: normalized.pointerInput,
      fire: normalized.mouseLeft,
    };
  };

  Base3DCombatArena.prototype.applyAction = function applyAction(normalized) {
    this.controls.forward = normalized.forward;
    this.controls.back = normalized.back;
    this.controls.left = normalized.left;
    this.controls.right = normalized.right;
    this.applyRelativePointerInput(normalized.pointerInput);
    if (normalized.reload) this.startReload();
    if (normalized.jump) this.startJump();
    if (normalized.fire) this.fire();
    if (this.mode === "paused" && !this.paused) this.mode = "playing";
  };

  Base3DCombatArena.prototype.clearTransientControls = function clearTransientControls() {
    this.controls = { forward: false, back: false, left: false, right: false };
  };

  Base3DCombatArena.prototype.advanceSimulation = function advanceSimulation(ms, context) {
    var state = this.advanceTime(ms, { render: false });
    this.clearTransientControls();
    return state;
  };

  Base3DCombatArena.prototype.rewardMetrics = function rewardMetrics() {
    return { kills: this.kills, damage_taken: this.damageTaken, deaths: this.deaths };
  };

  Base3DCombatArena.prototype.rewardPayload = function rewardPayload() {
    var metrics = this.rewardMetrics();
    return {
      env_reward_step: this.envRewardStep,
      env_reward_episode: this.envRewardEpisode,
      primary_positive_score: rewardConfig.computePrimaryPositiveScore(metrics),
      primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(metrics),
      primary_score: rewardConfig.computePrimaryScore(metrics),
    };
  };

  Base3DCombatArena.prototype.getPrimaryScore = function getPrimaryScore() {
    return rewardConfig.computePrimaryScore(this.rewardMetrics());
  };

  Base3DCombatArena.prototype.accuracy = function accuracy() {
    return this.shotsFired > 0 ? this.projectileHits / this.shotsFired : 0;
  };

  Base3DCombatArena.prototype.visibleEnemyCount = function visibleEnemyCount() {
    var count = 0;
    for (var i = 0; i < this.enemies.length; i += 1) {
      if (this.enemyVisible(this.enemies[i])) count += 1;
    }
    return count;
  };

  Base3DCombatArena.prototype.nearestEnemyDistance = function nearestEnemyDistance() {
    var nearest = Infinity;
    for (var i = 0; i < this.enemies.length; i += 1) {
      if (this.enemies[i].alive) nearest = Math.min(nearest, U.geometry3d.horizontalDistance(this, this.enemies[i]));
    }
    return Number.isFinite(nearest) ? nearest : null;
  };

  Base3DCombatArena.prototype.aimedEnemyId = function aimedEnemyId() {
    var origin = { x: this.x, y: this.y + EYE_HEIGHT, z: this.z };
    var direction = this.viewDirection();
    var end = {
      x: origin.x + direction.x * 40,
      y: origin.y + direction.y * 40,
      z: origin.z + direction.z * 40,
    };
    var coverDistance = this.coverHitDistance(origin, end, PLAYER_PROJECTILE_RADIUS);
    var best = null;
    var bestDistance = null;
    for (var i = 0; i < this.enemies.length; i += 1) {
      var enemy = this.enemies[i];
      if (!enemy.alive) continue;
      var hitDistance = this.enemyHitDistance(origin, end, enemy, PLAYER_PROJECTILE_RADIUS);
      if (hitDistance !== null && (bestDistance === null || hitDistance < bestDistance)) {
        best = enemy;
        bestDistance = hitDistance;
      }
    }
    if (!best || (coverDistance !== null && coverDistance < bestDistance)) return null;
    return best.id;
  };

  Base3DCombatArena.prototype.metricsPayload = function metricsPayload() {
    var rewards = this.rewardPayload();
    var playerProjectiles = 0;
    var enemyProjectiles = 0;
    for (var i = 0; i < this.projectiles.length; i += 1) {
      if (this.projectiles[i].owner === "player") playerProjectiles += 1;
      else enemyProjectiles += 1;
    }
    return {
      env_reward_step: rewards.env_reward_step,
      env_reward_episode: rewards.env_reward_episode,
      primary_positive_score: rewards.primary_positive_score,
      primary_penalty_score: rewards.primary_penalty_score,
      primary_score: rewards.primary_score,
      kills: this.kills,
      deaths: this.deaths,
      health: this.health,
      max_health: this.maxHealth,
      health_unlimited: this.healthUnlimited,
      damage_dealt: this.damageDealt,
      damage_taken: this.damageTaken,
      fire_attempts: this.fireAttempts,
      shots_fired: this.shotsFired,
      projectile_hits: this.projectileHits,
      shots_missed: this.shotsMissed,
      accuracy: this.accuracy(),
      magazine_ammo: this.magazineAmmo,
      magazine_size: MAGAZINE_SIZE,
      reserve_ammo: this.reserveAmmo,
      reloading: this.reloading,
      reload_remaining_ms: Math.round(this.reloadRemaining * 1000),
      reloads_started: this.reloadsStarted,
      reloads_completed: this.reloadsCompleted,
      reload_attempts_without_ammo: this.reloadAttemptsWithoutAmmo,
      empty_fire_attempts: this.emptyFireAttempts,
      cooldown_fire_attempts: this.cooldownFireAttempts,
      reload_blocked_fire_attempts: this.reloadBlockedFireAttempts,
      jumps: this.jumps,
      player_y: this.y,
      player_vertical_velocity: this.vy,
      player_grounded: this.grounded,
      enemies_alive: this.enemies.filter(function alive(enemy) { return enemy.alive; }).length,
      enemies_visible: this.visibleEnemyCount(),
      enemies_spawned: this.enemiesSpawned,
      enemy_respawns: this.enemyRespawns,
      enemy_shots_fired: this.enemyShotsFired,
      enemy_hits: this.enemyHits,
      enemy_accuracy: this.enemyShotsFired > 0 ? this.enemyHits / this.enemyShotsFired : 0,
      enemy_direction_changes: this.enemyDirectionChanges,
      player_projectiles_visible: playerProjectiles,
      enemy_projectiles_visible: enemyProjectiles,
      player_projectiles_blocked: this.playerProjectilesBlocked,
      enemy_projectiles_blocked: this.enemyProjectilesBlocked,
      player_collisions: this.playerCollisions,
      enemy_collisions: this.enemyCollisions,
      respawns_pending: this.respawnQueue.length,
      nearest_enemy_distance: this.nearestEnemyDistance(),
      aimed_enemy_id: this.aimedEnemyId(),
      step_count: this.stepCount,
      episode_count: this.runtime.episodeCount,
      best_primary_score: this.bestMetrics.bestPrimaryScore,
      difficulty: this.difficulty,
    };
  };

  Base3DCombatArena.prototype.serializeEnemies = function serializeEnemies() {
    var self = this;
    return this.enemies.filter(function alive(enemy) { return enemy.alive; }).map(function serialize(enemy) {
      return {
        id: enemy.id,
        type: "enemy",
        x: enemy.x,
        y: enemy.y,
        z: enemy.z,
        radius: enemy.radius,
        hit_regions: [
          { type: "body", y: enemy.y, radius: enemy.radius },
          { type: "head", y: enemy.headY, radius: enemy.headRadius },
        ],
        health: enemy.health,
        max_health: enemy.maxHealth,
        velocity: { x: enemy.vx, y: 0, z: enemy.vz },
        spawn_lane_index: enemy.spawnLaneIndex,
        spawn_lane_z: enemy.spawnLaneZ,
        distance: U.geometry3d.horizontalDistance(self, enemy),
        visible: self.enemyVisible(enemy),
        shots_fired: enemy.shotsFired,
        direction_changes: enemy.directionChanges,
      };
    });
  };

  Base3DCombatArena.prototype.serializeProjectiles = function serializeProjectiles() {
    return this.projectiles.map(function serialize(projectile) {
      return {
        id: projectile.id,
        type: "projectile",
        owner: projectile.owner,
        x: projectile.x,
        y: projectile.y,
        z: projectile.z,
        velocity: { x: projectile.vx, y: projectile.vy, z: projectile.vz },
        radius: projectile.radius,
        lifetime_ms: Math.round(projectile.life * 1000),
      };
    });
  };

  Base3DCombatArena.prototype.entityPayload = function entityPayload() {
    var entities = this.serializeEnemies().concat(this.serializeProjectiles());
    for (var i = 0; i < this.covers.length; i += 1) {
      var cover = this.covers[i];
      entities.push({
        id: cover.id,
        type: "cover",
        x: cover.x,
        y: FLOOR_Y,
        z: cover.z,
        width: cover.width,
        depth: cover.depth,
        height: cover.height,
      });
    }
    return entities;
  };

  Base3DCombatArena.prototype.visualPayload = function visualPayload() {
    return G3D.visuals.payload(this);
  };

  Base3DCombatArena.prototype.getStatePayload = function getStatePayload() {
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
          y: this.y,
          eye_y: this.y + EYE_HEIGHT,
          z: this.z,
          yaw: this.yaw,
          pitch: this.pitch,
          health: this.health,
          max_health: this.maxHealth,
          health_unlimited: this.healthUnlimited,
          magazine_ammo: this.magazineAmmo,
          reserve_ammo: this.reserveAmmo,
          reloading: this.reloading,
          vertical_velocity: this.vy,
          grounded: this.grounded,
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
          camera_initialization: this.cameraInitialization,
          arena_bounds: {
            min_x: this.map.bounds.minX,
            max_x: this.map.bounds.maxX,
            min_z: this.map.bounds.minZ,
            max_z: this.map.bounds.maxZ,
          },
          no_obstacles: this.noObstacles,
          random_enemy_lane: this.randomEnemyLane,
          asset_pack: this.assetContext ? this.assetContext.id : null,
          scene_version: CombatScene.version,
          asset: this.assetContext ? this.assetContext.payload() : null,
          scene_layout: this.sceneLayout,
          floor_regions: this.map.regions,
          room_links: this.map.links,
          walkable_area: this.map.area,
          covers: this.covers,
          target_enemy_count: this.targetEnemyCount,
          sensitivity: this.sensitivity,
          move_speed: MOVE_SPEED * this.controlResponse.applied.move_scale,
          jump_speed: JUMP_SPEED * this.controlResponse.applied.jump_scale,
          gravity: GRAVITY,
          eye_height: EYE_HEIGHT,
          player_projectile_speed: PLAYER_PROJECTILE_SPEED,
          enemy_projectile_speed: this.enemyProjectileSpeed(),
          enemy_targeting_accuracy: this.enemyTargetingAccuracy(),
          enemy_move_speed: this.enemyMoveSpeed(),
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
        projectile_mesh_count: this.projectileRegistry ? this.projectileRegistry.size() : 0,
      },
    };
  };

  Base3DCombatArena.prototype.getObservation = function getObservation() {
    return {
      player: {
        x: this.x,
        y: this.y,
        eye_y: this.y + EYE_HEIGHT,
        z: this.z,
        yaw: this.yaw,
        pitch: this.pitch,
        health: this.health,
        magazine_ammo: this.magazineAmmo,
        reserve_ammo: this.reserveAmmo,
        reloading: this.reloading,
        vertical_velocity: this.vy,
        grounded: this.grounded,
      },
      enemies: this.serializeEnemies(),
      projectiles: this.serializeProjectiles(),
      covers: this.covers,
      metrics: this.metricsPayload(),
    };
  };

  Base3DCombatArena.prototype.buildStepInfo = function buildStepInfo(state, stepOptions, normalized) {
    var info = Core.terminal.withInfo(this, state, {
      score: state.metrics.primary_score,
      status: state.status,
    });
    Object.keys(state.metrics).forEach(function copyMetric(key) { info[key] = state.metrics[key]; });
    info.action = { type: "game_step_action", id: normalized.id, args: normalized.args };
    info.durationMs = stepOptions.durationMs;
    info.source = stepOptions.source;
    return info;
  };

  Base3DCombatArena.prototype.infoPayload = function infoPayload() {
    var metrics = this.metricsPayload();
    var info = { score: metrics.primary_score, status: this.mode };
    Object.keys(metrics).forEach(function copyMetric(key) { info[key] = metrics[key]; });
    return info;
  };

  Base3DCombatArena.prototype.resetGym = function resetGym(options) {
    this.resetFromAPI(options || {});
    return { observation: this.getObservation(), reward: 0, done: false, info: this.infoPayload() };
  };

  Base3DCombatArena.prototype.renderGameToText = function renderGameToText() {
    var metrics = this.metricsPayload();
    return JSON.stringify({
      coordinate_system: "first-person x/z arena coordinates; player y is foot height above the floor; relative pointer input uses signed visible game displacement",
      status: this.mode,
      player: {
        x: this.x,
        y: this.y,
        eye_y: this.y + EYE_HEIGHT,
        z: this.z,
        yaw: this.yaw,
        pitch: this.pitch,
        health: this.health,
        magazine_ammo: this.magazineAmmo,
        reserve_ammo: this.reserveAmmo,
        reloading: this.reloading,
        vertical_velocity: this.vy,
        grounded: this.grounded,
      },
      enemies: this.serializeEnemies(),
      projectiles: this.serializeProjectiles(),
      covers: this.covers,
      no_obstacles: this.noObstacles,
      random_enemy_lane: this.randomEnemyLane,
      rewards: {
        env_reward_step: metrics.env_reward_step,
        env_reward_episode: metrics.env_reward_episode,
        primary_positive_score: metrics.primary_positive_score,
        primary_penalty_score: metrics.primary_penalty_score,
        primary_score: metrics.primary_score,
      },
      combat: metrics,
      difficulty: this.difficulty,
      visual_perturbations: this.visualPayload(),
    });
  };

  Base3DCombatArena.prototype.updateBestMetrics = function updateBestMetrics() {
    this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, this.getPrimaryScore());
  };

  Base3DCombatArena.prototype.makeEnemyMesh = function makeEnemyMesh(enemy) {
    return CombatScene.enemy(this, enemy);
  };

  Base3DCombatArena.prototype.makeProjectileMesh = function makeProjectileMesh(projectile) {
    return CombatScene.projectile(this, projectile);
  };

  Base3DCombatArena.prototype.attachEnemyMesh = function attachEnemyMesh(enemy) {
    if (!enemy || !enemy.alive || !this.enemyRegistry || this.enemyRegistry.get(enemy.id)) return;
    this.enemyRegistry.set(enemy.id, this.makeEnemyMesh(enemy));
  };

  Base3DCombatArena.prototype.attachProjectileMesh = function attachProjectileMesh(projectile) {
    if (!projectile || !this.projectileRegistry || this.projectileRegistry.get(projectile.id)) return;
    this.projectileRegistry.set(projectile.id, this.makeProjectileMesh(projectile));
  };

  Base3DCombatArena.prototype.removeProjectileMesh = function removeProjectileMesh(id) {
    if (this.projectileRegistry) this.projectileRegistry.remove(id);
  };

  Base3DCombatArena.prototype.rebuildScene3D = function rebuildScene3D() {
    if (!this.world3d) return;
    this.sceneReady = false;
    this.world3d.clear();
    this.enemyRegistry = G3D.entities.createRegistry(this.world3d);
    this.projectileRegistry = G3D.entities.createRegistry(this.world3d);
    this.sceneMeshes = CombatScene.build(this);
    this.sceneReady = true;
    this.syncScene3D();
  };

  Base3DCombatArena.prototype.syncScene3D = function syncScene3D() {
    if (!this.world3d) return;
    this.world3d.setFirstPersonCamera({
      x: this.x, z: this.z, height: this.y, yaw: this.yaw - Math.PI / 2, pitch: this.pitch, eyeHeight: EYE_HEIGHT,
    });
    this.world3d.camera.updateMatrixWorld(true);
    CombatScene.sync(this);
  };

  Base3DCombatArena.prototype.render = function render() {
    G3D.visuals.sync(this, { sceneReady: true });
    if (!this.world3d) return;
    this.syncScene3D();
    this.world3d.render();
    if (this.infoPanel) this.infoPanel.update();
  };

  Base3DCombatArena.prototype.resetFromAPI = function resetFromAPI(options) {
    return this.beginEpisode(options || {}, true);
  };

  async function start() {
    await G3D.assets.preload("gym-depot", ASSET_REQUIREMENTS);
    if (document.fonts) await document.fonts.ready;
    var game = new Base3DCombatArena();
    await game.world3d.prepare();
    Core.createRuntime({
      game: game,
      presentation: {
        title: "3D Shooting",
        controls: "WASD moves. Move the mouse to aim. Left-click fires. E reloads. Space jumps.",
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
              ["Ammo / reserve", game.magazineAmmo + " / " + game.reserveAmmo],
              ["Reload", (game.reloading ? (Math.ceil(game.reloadRemaining * 10) / 10) + "s" : "Ready")],
              ["Jump", game.grounded ? "Ready" : "Airborne"],
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
        supports_random_enemy_lane: true,
      },
    });
  }

  Core.lifecycle.boot(start);
})();
