(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var T2D = window.BaseGameletThree2D;
  var Scene = window.RoverHangarScene;
  var rewardConfig = window.Base2DAimArenaRewardConfig;
  var GAME_ID = "base_2d_aim_arena";
  var LOGIC_HEIGHT = 640;
  var LOGIC_WIDTH = T2D.viewport.widthForHeight(LOGIC_HEIGHT);
  var DISPLAY_WIDTH = T2D.viewport.baseWidth;
  var DISPLAY_HEIGHT = T2D.viewport.baseHeight;
  var STEP_MS = 1000 / 60;
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 5;
  var ASSET_REQUIREMENTS = Scene.assets;
  var PLAYER_R = 15;
  var ENEMY_R = 17;
  var FIRE_INTERVAL_MS = 100;
  var ACTIVE_ENEMY_COUNT = 5;
  var OBSTACLE_COUNT = 4;
  var SPAWN_ZONE_COUNT = 3;
  var OBSTACLE_MARGIN = 24;
  var PLAYER_SPAWN_CLEARANCE = 105;
  var ENEMY_SPAWN_CLEARANCE = 125;
  var PERTURBATION_CONTRACT = Core.perturbations.defineContract({
    game_id: GAME_ID,
    control_response: {
      move_scale: Core.controlResponse.ranges.move_scale,
    },
    capabilities: {
      appearance: ["palette", "background", "assets"],
      camera: ["projection"],
      scene: ["layout", "entity_spawn"],
    },
    samplers: { camera: { projection: T2D.camera.projectionSampler },
      scene: { layout: window.RoverHangarLayout.sample } },
    validators: { camera: { projection: T2D.camera.projectionValidator } },
  });

  var canvas = document.getElementById("display");
  var view = null;
  var presentation = null;


  var createAsset = T2D.assets.bindView(function currentView() { return view; });

  function Base2DAimArena() {
    this.defaults = { seed: DEFAULT_SEED, difficulty: DEFAULT_DIFFICULTY, maxDifficulty: MAX_DIFFICULTY };
    this.urlConfig = Core.config.readUrl(this.defaults);
    this.controls = { up: false, down: false, left: false, right: false };
    this.paused = false;
    this.runtime = { resetCount: 0, episodeCount: 0, lastResetMethod: null };
    this.bestMetrics = { bestPrimaryScore: 0 };
    Core.terminal.initialize(this);
    this.bindInput();
    Core.lifecycle.bindResetKeys(this);
    this.beginEpisode({}, false);
    this.startLoop();
  }

  Base2DAimArena.prototype.beginEpisode = function beginEpisode(options, countReset, flags) {
    var episodeFlags = flags || {};
    var normalized = Core.config.normalizeOptions(options || {}, MAX_DIFFICULTY);
    var config = Core.config.mergeEpisode(this.urlConfig, normalized);
    Core.lifecycle.resetEpisode(this, { controls: { up: false, down: false, left: false, right: false } });
    this.currentConfig = Core.config.cloneEpisode(config);
    Core.terminal.clear(this, episodeFlags);
    Core.domains.beginEpisode(this, config, PERTURBATION_CONTRACT, DEFAULT_SEED);
    this.sceneLayout = Core.domains.sample(this, "scene", "layout", { template: "twin_hangars", width_scale: 1, depth_scale: 1 });
    this.floorMap = window.RoverHangarLayout.build(this.sceneLayout, LOGIC_WIDTH, LOGIC_HEIGHT);
    this.difficulty = config.difficulty;
    this.x = LOGIC_WIDTH / 2;
    this.y = 320;
    this.cursor = { x: this.x + 100, y: this.y };
    this.trails = [];
    this.visualShots = [];
    this.visualHeading = 0;
    this.health = null;
    this.maxHealth = null;
    this.healthUnlimited = true;
    this.kills = 0;
    this.shots = 0;
    this.hits = 0;
    this.misses = 0;
    this.blockedShots = 0;
    this.damageTaken = 0;
    this.deaths = 0;
    this.enemySerial = 0;
    this.enemiesSpawned = 0;
    this.obstacles = this.buildObstacles();
    this.spawnZones = this.buildSpawnZones();
    this.enemies = [];
    this.replenishEnemies();
    this.stepCount = 0;
    this.gameTimeMs = 0;
    this.nextFireTimeMs = 0;
    this.mouseFireHeld = false;
    this.actionFireHeld = false;
    Core.reward.resetEpisode(this);
    this.lastAction = "reset";
    this.mode = config.autostart ? "playing" : "paused";
    this.terminal = { isTerminal: false, outcome: null, reason: null };
    this.controls = { up: false, down: false, left: false, right: false };
    if (countReset) this.runtime.resetCount += 1;
    this.runtime.episodeCount += 1;
    this.runtime.lastResetMethod = countReset ? "inplace_reset" : "init";
    T2D.visuals.configure(this, config, {
      defaultAssetPack: Scene.pack,
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
      view: view,
    });
    this.updateBestMetrics();

    this.render();
    return { accepted: normalized, applied: config, notes: [] };
  };

  Base2DAimArena.prototype.buildObstacles = function buildObstacles() {
    var rng = Core.domains.gameplayRng(this, "scene", "layout");
    var obstacles = this.floorMap.walls.map(function boundary(wall) {
      return { id: wall.id, kind: "boundary", x: wall.x - wall.width / 2,
        y: wall.z - wall.depth / 2, w: wall.width, h: wall.depth };
    });
    var count = OBSTACLE_COUNT + rng.randint(0, 4);
    for (var index = 0; index < count; index += 1) {
      for (var attempt = 0; attempt < 120; attempt += 1) {
        var w = rng.range(50, 106), h = rng.range(42, 82);
        var x = rng.range(this.floorMap.bounds.minX + w, this.floorMap.bounds.maxX - w);
        var y = rng.range(this.floorMap.bounds.minZ + h, this.floorMap.bounds.maxZ - h);
        if (!this.floorMap.contains(x, y, Math.hypot(w, h) / 2 + OBSTACLE_MARGIN)) continue;
        var obstacle = { id: "obstacle_" + index, kind: "cover", x: x - w / 2, y: y - h / 2, w: w, h: h };
        if (U.geometry2d.circleOverlapsRectangle(this.x, this.y, PLAYER_SPAWN_CLEARANCE, obstacle)) continue;
        var expanded = { x: obstacle.x - 35, y: obstacle.y - 35, w: w + 70, h: h + 70 };
        if (obstacles.some(function overlap(existing) { return U.geometry2d.rectanglesOverlap(expanded, existing); })) continue;
        obstacles.push(obstacle); break;
      }
    }
    return obstacles;
  };

  Base2DAimArena.prototype.circleHitsObstacle = function circleHitsObstacle(x, y, radius) {
    if (!this.floorMap.contains(x, y, radius)) return true;
    for (var i = 0; i < this.obstacles.length; i += 1) {
      if (U.geometry2d.circleOverlapsRectangle(x, y, radius, this.obstacles[i])) return true;
    }
    return false;
  };

  Base2DAimArena.prototype.buildSpawnZones = function buildSpawnZones() {
    var entitySpawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var zones = [];
    for (var index = 0; index < SPAWN_ZONE_COUNT; index += 1) {
      var x = this.floorMap.bounds.minX + 96;
      var y = 108;
      for (var attempt = 0; attempt < 80; attempt += 1) {
        x = entitySpawnRng.range(this.floorMap.bounds.minX + 48, this.floorMap.bounds.maxX - 48);
        y = entitySpawnRng.range(this.floorMap.bounds.minZ + 48, this.floorMap.bounds.maxZ - 48);
        if (U.geometry2d.distance({ x: x, y: y }, { x: this.x, y: this.y }) < 145) continue;
        if (this.circleHitsObstacle(x, y, 42)) continue;
        if (zones.some(function (zone) { return U.geometry2d.distance(zone, { x: x, y: y }) < 115; })) continue;
        break;
      }
      zones.push({
        id: "spawn_zone_" + index,
        x: x,
        y: y,
        radiusX: entitySpawnRng.range(68, 122),
        radiusY: entitySpawnRng.range(56, 108),
        weight: entitySpawnRng.range(0.65, 1.55),
      });
    }
    return zones;
  };

  Base2DAimArena.prototype.sampleSpawnPoint = function sampleSpawnPoint() {
    var entitySpawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var totalWeight = this.spawnZones.reduce(function (total, zone) { return total + zone.weight; }, 0);
    var roll = entitySpawnRng.range(0, totalWeight);
    var zone = this.spawnZones[this.spawnZones.length - 1];
    for (var i = 0; i < this.spawnZones.length; i += 1) {
      roll -= this.spawnZones[i].weight;
      if (roll <= 0) {
        zone = this.spawnZones[i];
        break;
      }
    }
    var offsetX = (entitySpawnRng.range(-zone.radiusX, zone.radiusX) + entitySpawnRng.range(-zone.radiusX, zone.radiusX)) * 0.5;
    var offsetY = (entitySpawnRng.range(-zone.radiusY, zone.radiusY) + entitySpawnRng.range(-zone.radiusY, zone.radiusY)) * 0.5;
    return {
      x: U.math.clamp(
        zone.x + offsetX,
        this.floorMap.bounds.minX + 32,
        this.floorMap.bounds.maxX - 32
      ),
      y: U.math.clamp(zone.y + offsetY, this.floorMap.bounds.minZ + 32, this.floorMap.bounds.maxZ - 32),
    };
  };

  Base2DAimArena.prototype.enemySpawnAvailable = function enemySpawnAvailable(x, y) {
    if (U.geometry2d.distance({ x: x, y: y }, { x: this.x, y: this.y }) < ENEMY_SPAWN_CLEARANCE) return false;
    if (this.circleHitsObstacle(x, y, ENEMY_R + 8)) return false;
    for (var i = 0; i < this.enemies.length; i += 1) {
      if (U.geometry2d.distance({ x: x, y: y }, this.enemies[i]) < ENEMY_R * 2 + 22) return false;
    }
    return true;
  };

  Base2DAimArena.prototype.spawnEnemy = function spawnEnemy() {
    var x = this.floorMap.bounds.minX + 48;
    var y = 84;
    var found = false;
    for (var attempt = 0; attempt < 120; attempt += 1) {
      var sampled = this.sampleSpawnPoint();
      x = sampled.x;
      y = sampled.y;
      if (this.enemySpawnAvailable(x, y)) {
        found = true;
        break;
      }
    }
    if (!found) {
      for (var gridY = this.floorMap.bounds.minZ + 45; gridY <= this.floorMap.bounds.maxZ - 45 && !found; gridY += 50) {
        for (var gridX = this.floorMap.bounds.minX + 45; gridX <= this.floorMap.bounds.maxX - 45; gridX += 50) {
          var centeredGridX = gridX;
          if (!this.enemySpawnAvailable(centeredGridX, gridY)) continue;
          x = centeredGridX;
          y = gridY;
          found = true;
          break;
        }
      }
    }
    var entitySpawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var behaviorRng = Core.domains.createEntityRng(this, entitySpawnRng, DEFAULT_SEED);
    if (!found) throw new Error("No free rover enemy spawn");
    var heading = behaviorRng.range(-Math.PI, Math.PI);
    var speed = (10 + this.difficulty * 2) * 3;
    var enemy = {
      id: "enemy_" + this.enemySerial,
      x: x,
      y: y,
      heading: heading,
      targetHeading: behaviorRng.range(-Math.PI, Math.PI),
      turnRate: behaviorRng.range(0.8, 1.55),
      turnTimer: behaviorRng.range(0.55, 1.75),
      behaviorRng: behaviorRng,
      speed: speed,
      vx: Math.cos(heading) * speed,
      vy: Math.sin(heading) * speed,
      r: ENEMY_R,
      touchingPlayer: false,
    };
    this.enemySerial += 1;
    this.enemiesSpawned += 1;
    return enemy;
  };

  Base2DAimArena.prototype.replenishEnemies = function replenishEnemies() {
    while (this.enemies.length < ACTIVE_ENEMY_COUNT) this.enemies.push(this.spawnEnemy());
  };

  Base2DAimArena.prototype.bindInput = function bindInput() {
    var self = this;
    function setKey(event, value) {
      var key = event.key;
      var handled = true;
      if (key === "w" || key === "W" || key === "ArrowUp") self.controls.up = value;
      else if (key === "s" || key === "S" || key === "ArrowDown") self.controls.down = value;
      else if (key === "a" || key === "A" || key === "ArrowLeft") self.controls.left = value;
      else if (key === "d" || key === "D" || key === "ArrowRight") self.controls.right = value;
      else handled = false;
      if (handled) {
        event.preventDefault();
        if (self.mode === "paused" && value) self.mode = "playing";
      }
    }
    document.addEventListener("keydown", function onKeyDown(event) { setKey(event, true); });
    document.addEventListener("keyup", function onKeyUp(event) { setKey(event, false); });
    canvas.addEventListener("mousemove", function onMouseMove(event) {
      var point = self.eventToLogic(event);
      self.cursor.x = point.x;
      self.cursor.y = point.y;
    });
    canvas.addEventListener("mousedown", function onMouseDown(event) {
      if (event.button !== 0) return;
      var point = self.eventToLogic(event);
      self.cursor.x = point.x;
      self.cursor.y = point.y;
      if (self.mode === "paused") self.mode = "playing";
      self.mouseFireHeld = true;
      self.fire();
      event.preventDefault();
    });
    window.addEventListener("mouseup", function onMouseUp(event) {
      if (event.button === 0) self.mouseFireHeld = false;
    });
    window.addEventListener("blur", function onBlur() {
      self.mouseFireHeld = false;
    });
    var app = document.getElementById("app");
    if (app) app.focus();
  };

  Base2DAimArena.prototype.eventToLogic = function eventToLogic(event) {
    return T2D.viewport.clientToLogic(canvas, event.clientX, event.clientY, LOGIC_WIDTH, LOGIC_HEIGHT);
  };

  Base2DAimArena.prototype.ensureSimulationRunner = function ensureSimulationRunner() {
    if (this.simulationRunner) return this.simulationRunner;
    var self = this;
    this.simulationRunner = Core.createFixedStepRunner({
      game: this,
      stepMs: STEP_MS,
      update: function update(stepMs) { self.update(stepMs / 1000); },
      render: function render() { self.render(); },
      isActive: function isActive() { return self.mode === "playing" && !self.paused && !self.terminal.isTerminal; },
    });
    return this.simulationRunner;
  };

  Base2DAimArena.prototype.startLoop = function startLoop() {
    this.ensureSimulationRunner().start();
  };

  Base2DAimArena.prototype.pause = function pause() {
    var pauseState = Core.lifecycle.pause(this);
    this.render();
    return pauseState;
  };

  Base2DAimArena.prototype.resume = function resume() {
    var pauseState = Core.lifecycle.resume(this);
    this.render();
    return pauseState;
  };

  Base2DAimArena.prototype.addReward = function addReward(value) {
    return Core.reward.add(this, value);
  };

  Base2DAimArena.prototype.movePlayer = function movePlayer(dx, dy) {
    var nextX = this.x + dx;
    if (!this.circleHitsObstacle(nextX, this.y, PLAYER_R)) this.x = nextX;
    var nextY = this.y + dy;
    if (!this.circleHitsObstacle(this.x, nextY, PLAYER_R)) this.y = nextY;
  };

  Base2DAimArena.prototype.updateEnemy = function updateEnemy(enemy, dt) {
    enemy.turnTimer -= dt;
    if (enemy.turnTimer <= 0) {
      enemy.targetHeading = enemy.behaviorRng.range(-Math.PI, Math.PI);
      enemy.turnRate = enemy.behaviorRng.range(0.8, 1.55);
      enemy.turnTimer += enemy.behaviorRng.range(0.55, 1.75);
    }
    var headingError = U.math.normalizeAngle(enemy.targetHeading - enemy.heading);
    enemy.heading = U.math.normalizeAngle(
      enemy.heading + U.math.clamp(headingError, -enemy.turnRate * dt, enemy.turnRate * dt)
    );

    var moveX = Math.cos(enemy.heading) * enemy.speed * dt;
    var moveY = Math.sin(enemy.heading) * enemy.speed * dt;
    var nextX = enemy.x + moveX;
    var blockedX = this.circleHitsObstacle(nextX, enemy.y, enemy.r);
    if (blockedX) {
      enemy.heading = U.math.normalizeAngle(Math.PI - enemy.heading);
      enemy.targetHeading = enemy.heading;
    } else {
      enemy.x = nextX;
    }

    var nextY = enemy.y + moveY;
    var blockedY = this.circleHitsObstacle(enemy.x, nextY, enemy.r);
    if (blockedY) {
      enemy.heading = U.math.normalizeAngle(-enemy.heading);
      enemy.targetHeading = enemy.heading;
    } else {
      enemy.y = nextY;
    }

    enemy.vx = Math.cos(enemy.heading) * enemy.speed;
    enemy.vy = Math.sin(enemy.heading) * enemy.speed;
    var touchingPlayer = U.geometry2d.distance(enemy, { x: this.x, y: this.y }) <= enemy.r + PLAYER_R;
    if (touchingPlayer && !enemy.touchingPlayer) {
      enemy.heading = Math.atan2(enemy.y - this.y, enemy.x - this.x);
      enemy.targetHeading = enemy.heading;
      enemy.vx = Math.cos(enemy.heading) * enemy.speed;
      enemy.vy = Math.sin(enemy.heading) * enemy.speed;
      this.damageTaken += 1;
      this.addReward(-rewardConfig.constants.damagePenalty);
    }
    enemy.touchingPlayer = touchingPlayer;
    return true;
  };

  Base2DAimArena.prototype.update = function update(dt) {
    if (this.terminal.isTerminal || this.mode !== "playing" || this.paused) return;
    Core.reward.resetStep(this);
    this.stepCount += 1;
    this.gameTimeMs += dt * 1000;
    var speed = 300 * this.controlResponse.applied.move_scale;
    var dx = (this.controls.right ? 1 : 0) - (this.controls.left ? 1 : 0);
    var dy = (this.controls.down ? 1 : 0) - (this.controls.up ? 1 : 0);
    if (dx || dy) {
      this.visualHeading = Math.atan2(dy, dx);
      var mag = Math.sqrt(dx * dx + dy * dy);
      this.movePlayer((dx / mag) * speed * dt, (dy / mag) * speed * dt);
    }
    this.lastAction = [this.controls.up ? "up" : null, this.controls.down ? "down" : null, this.controls.left ? "left" : null, this.controls.right ? "right" : null].filter(Boolean).join("+") || "aim";
    if ((this.mouseFireHeld || this.actionFireHeld) && this.gameTimeMs + 1e-6 >= this.nextFireTimeMs) {
      this.fire();
    }
    for (var i = 0; i < this.enemies.length; i += 1) {
      if (!this.updateEnemy(this.enemies[i], dt)) return;
    }
    for (var t = this.trails.length - 1; t >= 0; t -= 1) {
      this.trails[t].life -= dt;
      if (this.trails[t].life <= 0) this.trails.splice(t, 1);
    }
    this.updateBestMetrics();

  };

  Base2DAimArena.prototype.nearestObstacleIntersection = function nearestObstacleIntersection(start, end) {
    var nearest = null;
    for (var i = 0; i < this.obstacles.length; i += 1) {
      var intersection = U.geometry2d.segmentRectangleIntersection(start, end, this.obstacles[i], 2);
      if (intersection && (!nearest || intersection.t < nearest.t)) {
        nearest = Object.assign({ obstacleId: this.obstacles[i].id }, intersection);
      }
    }
    return nearest;
  };

  Base2DAimArena.prototype.nearestEnemyIntersection = function nearestEnemyIntersection(start, end) {
    var nearest = null;
    for (var i = 0; i < this.enemies.length; i += 1) {
      var enemy = this.enemies[i];
      var intersection = U.geometry2d.segmentCircleIntersection(start, end, enemy);
      if (intersection && (!nearest || intersection.t < nearest.t)) {
        nearest = Object.assign({ enemy: enemy }, intersection);
      }
    }
    return nearest;
  };

  Base2DAimArena.prototype.fire = function fire() {
    if (this.terminal.isTerminal) return;
    this.nextFireTimeMs = this.gameTimeMs + FIRE_INTERVAL_MS;
    Core.reward.resetStep(this);
    this.shots += 1;
    var shotStart = { x: this.x, y: this.y };
    var shotEnd = U.geometry2d.rayRectangleBoundaryIntersection(
      shotStart,
      this.cursor,
      { x: 0, y: 0, w: LOGIC_WIDTH, h: LOGIC_HEIGHT }
    ) || shotStart;
    var obstacleHit = this.nearestObstacleIntersection(shotStart, shotEnd);
    var enemyHit = this.nearestEnemyIntersection(shotStart, shotEnd);
    var blocked = !!(obstacleHit && (!enemyHit || obstacleHit.t <= enemyHit.t));
    var impact = blocked ? obstacleHit : (enemyHit || shotEnd);
    this.visualShots.push({ x1: this.x, y1: this.y, x2: impact.x, y2: impact.y,
      timeMs: this.gameTimeMs });
    if (this.visualShots.length > 8) this.visualShots.shift();
    this.trails.push({
      x1: this.x,
      y1: this.y,
      x2: impact.x,
      y2: impact.y,
      life: 0.12,
    });
    if (enemyHit && !blocked) {
      this.enemies.splice(this.enemies.indexOf(enemyHit.enemy), 1);
      this.hits += 1;
      this.kills += 1;
      this.addReward(rewardConfig.constants.hitReward);
      this.replenishEnemies();
      this.lastAction = "fire_hit";
    } else {
      this.misses += 1;
      if (blocked) this.blockedShots += 1;
      this.lastAction = blocked ? "fire_blocked" : "fire_miss";
    }
    this.updateBestMetrics();

  };

  Base2DAimArena.prototype.advanceTime = function advanceTime(ms, options) {
    var opts = typeof options === "object" && options !== null ? options : { render: options !== false };
    this.ensureSimulationRunner().advance(ms, opts);
    if (opts.returnState === false) return null;
    return this.getStatePayload();
  };

  Base2DAimArena.prototype.normalizeAction = function normalizeAction(action) {
    var actionId = Core.actions.readId(action, { lowercase: true });
    var mouseDx = 0;
    var mouseDy = 0;
    var controlRelativeMouse = actionId === "control" && Core.actions.readMouseMode(action) === "relative";
    if (actionId === "move_pointer" || controlRelativeMouse) {
      mouseDx = controlRelativeMouse
        ? Core.actions.readMouseNumber(action, "dx", 0)
        : Core.actions.readNumber(action, "dx", 0);
      mouseDy = controlRelativeMouse
        ? Core.actions.readMouseNumber(action, "dy", 0)
        : Core.actions.readNumber(action, "dy", 0);
      mouseDx = T2D.input.relativeDeltaToLogic(view, mouseDx, "x");
      mouseDy = T2D.input.relativeDeltaToLogic(view, mouseDy, "y");
    }
    var button = Core.actions.readButton(action, "left");
    return {
      id: actionId || "wait",
      args: {},
      up: Core.actions.hasKey(action, ["KeyW", "w", "ArrowUp"]),
      down: Core.actions.hasKey(action, ["KeyS", "s", "ArrowDown"]),
      left: Core.actions.hasKey(action, ["KeyA", "a", "ArrowLeft"]),
      right: Core.actions.hasKey(action, ["KeyD", "d", "ArrowRight"]),
      mouseDx: mouseDx,
      mouseDy: mouseDy,
      fire: (actionId === "mouse_left" && button === "left")
        || (actionId === "control" && Core.actions.hasMouseClick(action, "left")),
      hold: actionId === "control" && Core.actions.hasMouseHold(action, "left"),
    };
  };

  Base2DAimArena.prototype.clearTransientControls = function clearTransientControls() {
    this.controls = { up: false, down: false, left: false, right: false };
    this.actionFireHeld = false;
  };

  Base2DAimArena.prototype.applyAction = function applyAction(normalized) {
    this.actionFireHeld = !!normalized.hold;
    this.controls.up = normalized.up;
    this.controls.down = normalized.down;
    this.controls.left = normalized.left;
    this.controls.right = normalized.right;
    var nextCursorX = this.cursor.x + (Number.isFinite(normalized.mouseDx) ? normalized.mouseDx : 0);
    var nextCursorY = this.cursor.y + (Number.isFinite(normalized.mouseDy) ? normalized.mouseDy : 0);
    var cursor = T2D.input.clampPointToVisibleBounds(view, nextCursorX, nextCursorY, LOGIC_WIDTH, LOGIC_HEIGHT);
    this.cursor.x = cursor.x;
    this.cursor.y = cursor.y;
    if (this.mode === "paused") this.mode = "playing";
    if (normalized.fire || (normalized.hold && this.gameTimeMs + 1e-6 >= this.nextFireTimeMs)) this.fire();
  };

  Base2DAimArena.prototype.advanceSimulation = function advanceSimulation(ms) {
    var state = this.advanceTime(ms, { render: false });
    this.clearTransientControls();
    return state;
  };

  Base2DAimArena.prototype.buildStepInfo = function buildStepInfo(state) {
    var info = Core.terminal.withInfo(this, state, this.infoPayload());
    return info;
  };

  Base2DAimArena.prototype.resetGym = function resetGym(options) {
    this.resetFromAPI(options || {});
    return { observation: this.getObservation(), reward: 0, done: false, info: this.infoPayload() };
  };

  Base2DAimArena.prototype.accuracy = function accuracy() {
    return this.shots ? this.hits / this.shots : 0;
  };

  Base2DAimArena.prototype.getObservation = function getObservation() {
    return {
      player: {
        x: this.x,
        y: this.y,
        r: PLAYER_R,
        health: this.health,
        max_health: this.maxHealth,
        health_unlimited: this.healthUnlimited,
      },
      cursor: { x: this.cursor.x, y: this.cursor.y },
      enemies: this.enemies.map(function (enemy) {
        return { id: enemy.id, x: enemy.x, y: enemy.y, vx: enemy.vx, vy: enemy.vy, r: enemy.r };
      }),
      obstacles: this.obstacles.map(function (obstacle) { return Object.assign({}, obstacle); }),
      kills: this.kills,
    };
  };

  Base2DAimArena.prototype.infoPayload = function infoPayload() {
    return {
      score: this.getPrimaryScore(),
      kills: this.kills,
      active_enemies: this.enemies.length,
      enemies_spawned: this.enemiesSpawned,
      shots: this.shots,
      hits: this.hits,
      misses: this.misses,
      blocked_shots: this.blockedShots,
      accuracy: this.accuracy(),
      health: this.health,
      max_health: this.maxHealth,
      health_unlimited: this.healthUnlimited,
      damage_taken: this.damageTaken,
      deaths: this.deaths,
      obstacle_count: this.obstacles.length,
      env_reward_step: this.envRewardStep,
      env_reward_episode: this.envRewardEpisode,
      time_steps: this.stepCount,
    };
  };

  Base2DAimArena.prototype.getPrimaryScore = function getPrimaryScore() {
    return rewardConfig.computePrimaryScore(this);
  };

  Base2DAimArena.prototype.updateBestMetrics = function updateBestMetrics() {
    this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, this.getPrimaryScore());
  };

  Base2DAimArena.prototype.entityPayload = function entityPayload() {
    var entities = [
      {
        id: "player",
        type: "player",
        x: this.x,
        y: this.y,
        r: PLAYER_R,
        health: this.health,
        max_health: this.maxHealth,
        health_unlimited: this.healthUnlimited,
      },
      { id: "cursor", type: "cursor", x: this.cursor.x, y: this.cursor.y, r: 6 },
    ];
    for (var obstacleIndex = 0; obstacleIndex < this.obstacles.length; obstacleIndex += 1) {
      entities.push(Object.assign({ type: "obstacle" }, this.obstacles[obstacleIndex]));
    }
    for (var i = 0; i < this.enemies.length; i += 1) {
      entities.push({
        id: this.enemies[i].id,
        type: "enemy",
        x: this.enemies[i].x,
        y: this.enemies[i].y,
        vx: this.enemies[i].vx,
        vy: this.enemies[i].vy,
        r: this.enemies[i].r,
      });
    }
    return entities;
  };

  Base2DAimArena.prototype.visualPayload = function visualPayload() {
    return T2D.visuals.sync(this);
  };

  Base2DAimArena.prototype.getStatePayload = function getStatePayload() {
    var latched = Core.terminal.consume(this);
    if (latched) return latched;
    T2D.visuals.sync(this);
    var viewport = T2D.viewport.state(this, LOGIC_WIDTH, LOGIC_HEIGHT);
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
        player: {
          x: this.x,
          y: this.y,
          health: this.health,
          max_health: this.maxHealth,
          health_unlimited: this.healthUnlimited,
        },
        environment: {
          phase: this.terminal.isTerminal ? "terminal" : this.mode,
          viewport_width: viewport.width,
          viewport_height: viewport.height,
          logic_width: LOGIC_WIDTH,
          logic_height: LOGIC_HEIGHT,
          difficulty: this.difficulty,
          obstacles: this.obstacles.map(function (obstacle) { return Object.assign({}, obstacle); }),
          active_enemy_target: ACTIVE_ENEMY_COUNT,
          scene_version: Scene.version,
          scene_layout: this.sceneLayout,
          floor_regions: this.floorMap.regions,
          boundary_walls: this.floorMap.walls,
          asset_pack: this.assetPack,
          asset: T2D.visuals.assetPayload(this),
          perturb_active: Core.perturbations.isActive(this),
          visual_perturbations: this.visualPayload(),
        },
        entities: this.entityPayload(),
      },
      metrics: {
        env_reward_step: this.envRewardStep,
        env_reward_episode: this.envRewardEpisode,
        primary_positive_score: rewardConfig.computePrimaryPositiveScore(this),
        primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(this),
        primary_score: this.getPrimaryScore(),
        kills: this.kills,
        active_enemies: this.enemies.length,
        enemies_spawned: this.enemiesSpawned,
        shots: this.shots,
        hits: this.hits,
        misses: this.misses,
        blocked_shots: this.blockedShots,
        accuracy: this.accuracy(),
        health: this.health,
        max_health: this.maxHealth,
        health_unlimited: this.healthUnlimited,
        damage_taken: this.damageTaken,
        deaths: this.deaths,
        obstacle_count: this.obstacles.length,
        best_primary_score: this.bestMetrics.bestPrimaryScore,
        step_count: this.stepCount,
        episode_count: this.runtime.episodeCount,
        difficulty: this.difficulty,
      },
      debug: { mode: this.mode, last_action: this.lastAction, last_reset_method: this.runtime.lastResetMethod, reset_count: this.runtime.resetCount },
    };
  };

  Base2DAimArena.prototype.renderGameToText = function renderGameToText() {
    return JSON.stringify({
      coordinate_system: "origin=(0,0) top-left, +x right, +y down",
      status: this.mode,
      player: {
        x: this.x,
        y: this.y,
        health: this.health,
        max_health: this.maxHealth,
        health_unlimited: this.healthUnlimited,
      },
      cursor: { x: this.cursor.x, y: this.cursor.y },
      enemies: this.enemies.map(function (enemy) {
        return { id: enemy.id, x: enemy.x, y: enemy.y, vx: enemy.vx, vy: enemy.vy, r: enemy.r };
      }),
      obstacles: this.obstacles.map(function (obstacle) { return Object.assign({}, obstacle); }),
      rewards: {
        env_reward_step: this.envRewardStep,
        env_reward_episode: this.envRewardEpisode,
        primary_positive_score: rewardConfig.computePrimaryPositiveScore(this),
        primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(this),
        primary_score: this.getPrimaryScore(),
      },
      progress: {
        kills: this.kills,
        active_enemies: this.enemies.length,
        enemies_spawned: this.enemiesSpawned,
        shots: this.shots,
        hits: this.hits,
        misses: this.misses,
        blocked_shots: this.blockedShots,
        accuracy: this.accuracy(),
      },
      difficulty: this.difficulty,
      visual_perturbations: this.visualPayload(),
    });
  };


  Base2DAimArena.prototype.palette = function palette() {
    return {
      bg: this.assetContext.color("surface"),
      text: this.assetContext.color("text"),
      player: this.assetContext.color("friendly"),
      enemy: this.assetContext.color("hostile"),
      obstacle: this.assetContext.color("neutral"),
      cursor: this.assetContext.color("text"),
      trail: this.assetContext.color("projectile"),
    };
  };

  Base2DAimArena.prototype.render = function render() {
    T2D.visuals.sync(this);
    presentation.render(this);
    if (this.infoPanel) this.infoPanel.update();
  };

  Base2DAimArena.prototype.resetFromAPI = function resetFromAPI(options) { return this.beginEpisode(options || {}, true); };

  async function start() {
    await T2D.assets.preload(Scene.pack, ASSET_REQUIREMENTS);
    view = await T2D.createStage(canvas, { width: LOGIC_WIDTH, height: LOGIC_HEIGHT, background: 0xffffff });
    if (!view) throw new Error("Three.js 2D engine unavailable");
    presentation = Scene.create(view, createAsset, LOGIC_WIDTH, LOGIC_HEIGHT, PLAYER_R);
    var game = new Base2DAimArena();
    Core.createRuntime({
      game: game,
      presentation: {
        title: "2D Shooting",
        controls: "WASD or arrows move; mouse aims; left-click fires. Cover blocks movement and shots.",
        read: function readPresentation() {
          return {
            status: game.paused ? "paused" : game.mode,
            primaryScore: game.getPrimaryScore(),
            stepReward: game.envRewardStep,
            episodeReward: game.envRewardEpisode,
            difficulty: game.difficulty,
            seed: game.seed,
            perturbation: Core.perturbations.label(game),
            details: [["Kills", game.kills], ["Accuracy", Math.round(game.accuracy() * 100) + "%"],
              ["Contacts", game.damageTaken], ["Health", game.healthUnlimited ? "Unlimited" : game.health],
              ["Blocked shots", game.blockedShots]],
          };
        },
      },
      renderer: T2D,
      gameId: GAME_ID,
      defaultSeed: DEFAULT_SEED,
      maxDifficulty: MAX_DIFFICULTY,
      defaultStepMs: 200,
      assets: { engine: T2D.assets, requiredAssetIds: ASSET_REQUIREMENTS },
    });
  }

  Core.lifecycle.boot(start);
})();
