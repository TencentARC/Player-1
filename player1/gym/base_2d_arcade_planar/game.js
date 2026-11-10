(function () {
  "use strict";

  var rewardConfig = window.Base2DArcadePlanarRewardConfig;
  var T2D = window.BaseGameletThree2D;
  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var Scene = window.DispatchFloorScene;
  var GAME_ID = "base_2d_arcade_planar";
  var LOGIC_HEIGHT = 640;
  var LOGIC_WIDTH = T2D.viewport.widthForHeight(LOGIC_HEIGHT);
  var DISPLAY_WIDTH = T2D.viewport.baseWidth;
  var DISPLAY_HEIGHT = T2D.viewport.baseHeight;
  var LEGACY_WORLD_WIDTH = 640;
  var STEP_MS = 1000 / 60;
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 2;
  var ASSET_REQUIREMENTS = Scene.assets;
  // Probability checked once per logic step when fewer than maxCoins are active.
  // 1.0 means spawn on every eligible step; lower values make coins appear gradually.
  var COIN_SPAWN_PROBABILITY = 1.0;
  var BASE_OBSTACLE_SPAWN_PROBABILITY = 0.05;
  var PLAYER_SPEED_PER_STEP = 6;
  var OBSTACLE_SPEED = 6;
  var PERTURBATION_CONTRACT = Core.perturbations.defineContract({
    game_id: GAME_ID,
    control_response: {
      move_scale: Core.controlResponse.ranges.move_scale,
    },
    capabilities: {
      appearance: ["palette", "background", "assets"],
      camera: ["projection"],
      scene: ["layout", "player_spawn", "entity_spawn"],
    },
    samplers: { camera: { projection: T2D.camera.projectionSampler },
      scene: { layout: window.DispatchWorkzoneLayout.sample } },
    validators: { camera: { projection: T2D.camera.projectionValidator } },
  });

  function finiteInt(value) {
    return Number.isFinite(value) ? Math.trunc(value) : null;
  }

  var displayCanvas = document.getElementById("display");
  var view = null;
  var presentation = null;

  var app = document.getElementById("app");

  var createAsset = T2D.assets.bindView(function currentView() { return view; });

  function Base2DArcadePlanar() {
    this.defaults = {
      seed: DEFAULT_SEED,
      difficulty: DEFAULT_DIFFICULTY,
      maxDifficulty: MAX_DIFFICULTY,
      randInitPos: false,
    };
    this.urlConfig = Core.config.readUrl(this.defaults);
    this.keys = {
      left: false,
      right: false,
      up: false,
      down: false,
    };
    this.pendingStartAction = null;
    this.paused = false;
    this.runtime = {
      resetCount: 0,
      episodeCount: 0,
      lastResetMethod: null,
    };
    Core.terminal.initialize(this);

    this.bindInput();
    Core.lifecycle.bindResetKeys(this);
    this.beginEpisode({}, false);
    this.startLoop();
  }

  Base2DArcadePlanar.prototype.normalizeOptions = function normalizeOptions(options) {
    return Core.config.normalizeOptions(options || {}, MAX_DIFFICULTY);
  };

  Base2DArcadePlanar.prototype.resolveEpisodeConfig = function resolveEpisodeConfig(normalized) {
    return Core.config.mergeEpisode(this.urlConfig, normalized);
  };

  Base2DArcadePlanar.prototype.beginEpisode = function beginEpisode(options, countAsReset, flags) {
    var rawOptions = options || {};
    var episodeFlags = flags || {};
    var normalized = this.normalizeOptions(rawOptions);
    var resolved = this.resolveEpisodeConfig(normalized);
    var notes = [];
    var rawPerturbText = rawOptions.perturb === undefined || rawOptions.perturb === null
      ? ""
      : String(rawOptions.perturb).trim().toLowerCase();

    Core.lifecycle.resetEpisode(this);

    if (normalized.level !== null) notes.push("level_not_supported");
    if (
      U.object.hasOwn(rawOptions, "perturb") &&
      normalized.perturb === null &&
      rawPerturbText &&
      rawPerturbText !== "none" &&
      rawPerturbText !== "off"
    ) {
      notes.push("unknown_perturb_ignored");
    }

    this.currentConfig = Core.config.cloneEpisode(resolved);
    Core.terminal.clear(this, episodeFlags);
    Core.domains.beginEpisode(this, resolved, PERTURBATION_CONTRACT, DEFAULT_SEED);
    this.runtime.episodeCount += 1;
    if (countAsReset !== false) {
      this.runtime.resetCount += 1;
    }

    this.width = LOGIC_WIDTH;
    this.height = LOGIC_HEIGHT;
    this.topMargin = 0;
    this.bottomMargin = 0;
    this.playerSpeed = PLAYER_SPEED_PER_STEP * this.controlResponse.applied.move_scale;
    this.laneCount = 8;
    this.laneHeight = Math.floor((this.height - this.topMargin - this.bottomMargin) / this.laneCount);
    this.playerSize = this.laneHeight;
    this.playerWidth = this.playerSize;
    this.playerHeight = this.playerSize;
    this.itemSize = Math.floor(this.laneHeight / 2);
    this.sceneLayout = Core.domains.sample(this, "scene", "layout", { template: "cross_dock", width_scale: 1, depth_scale: 1 });
    this.workzone = window.DispatchWorkzoneLayout.build(this.sceneLayout, this.width, this.height);
    this.laneSegments = [];
    for (var laneIndex = 0; laneIndex < this.laneCount; laneIndex += 1) {
      this.laneSegments.push(this.workzone.laneSegments(this.laneY(laneIndex), this.itemSize));
    }
    this.maxCoins = 3;
    this.maxObstacles = 3;
    this.difficulty = resolved.difficulty;
    this.obstacleSpawnProbability = BASE_OBSTACLE_SPAWN_PROBABILITY * Core.config.difficultyLevel(this.difficulty);
    this.randInitPos = resolved.randInitPos;

    if (!episodeFlags.preserveTerminalLatch) this.visualFailure = null;
    this.items = [];
    this.obstacles = [];
    this.playerX = Math.floor(this.width / 2) - Math.floor(this.playerWidth / 2);
    this.playerY = Math.floor(this.height / 2) - Math.floor(this.playerHeight / 2);
    if (this.randInitPos || Core.domains.profile(this, "scene") === "perturbed") {
      var startRng = Core.domains.gameplayRng(this, "scene", "player_spawn");
      var maxPlayerX = this.width - this.playerWidth;
      var minPlayerY = this.topMargin;
      var maxPlayerY = this.height - this.bottomMargin - this.playerHeight;
      for (var attempt = 0; attempt < 32; attempt += 1) {
        var candidateX = startRng.randint(0, maxPlayerX + 1);
        var candidateY = startRng.randint(minPlayerY, maxPlayerY + 1);
        if (this.workzone.rectFits(candidateX, candidateY, this.playerWidth, this.playerHeight)
          && !this.playerStartOverlapsEntities(candidateX, candidateY)) {
          this.playerX = candidateX;
          this.playerY = candidateY;
          break;
        }
      }
    }
    this.coinsCollected = 0;
    this.collisions = 0;
    Core.reward.resetEpisode(this);
    this.stepCount = 0;
    this.gameTimeMs = 0;
    this.lastAction = "wait";
    this.pendingStartAction = null;
    this.perturb = resolved.perturb;
    T2D.visuals.configure(this, resolved, {
      defaultAssetPack: Scene.pack,
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
      view: view,
    });
    this.mode = resolved.autostart ? "playing" : "paused";
    this.terminal = {
      isTerminal: false,
      outcome: null,
      reason: null,
    };
    this.paused = false;
    this.keys.left = false;
    this.keys.right = false;
    this.keys.up = false;
    this.keys.down = false;

    this.render();

    return {
      accepted: normalized,
      applied: {
        seed: this.seed,
        level: null,
        difficulty: this.difficulty,
        autostart: resolved.autostart,
        asset_pack: this.assetPack,
        rand_init_pos: this.randInitPos,
        perturb: this.perturb,
        perturb_bg_color: this.visualPerturbations.active.bgColor,
        perturb_entity_color: this.visualPerturbations.active.entityColor,

      },
      notes: notes,
    };
  };

  Base2DArcadePlanar.prototype.playerStartOverlapsEntities = function playerStartOverlapsEntities(playerX, playerY) {
    var index;
    var playerRight = playerX + this.playerWidth;
    var playerBottom = playerY + this.playerHeight;
    for (index = 0; index < this.items.length; index += 1) {
      var item = this.items[index];
      if (
        playerX < item[0] + this.itemSize &&
        playerRight > item[0] &&
        playerY < item[1] + this.itemSize &&
        playerBottom > item[1]
      ) {
        return true;
      }
    }
    for (index = 0; index < this.obstacles.length; index += 1) {
      var obstacle = this.obstacles[index];
      if (
        playerX < obstacle[0] + this.itemSize &&
        playerRight > obstacle[0] &&
        playerY < obstacle[1] + this.itemSize &&
        playerBottom > obstacle[1]
      ) {
        return true;
      }
    }
    return false;
  };

  Base2DArcadePlanar.prototype.getPrimaryScore = function getPrimaryScore() {
    return rewardConfig.computePrimaryScore(this);
  };

  Base2DArcadePlanar.prototype.getPrimaryPositiveScore = function getPrimaryPositiveScore() {
    return rewardConfig.computePrimaryPositiveScore(this);
  };

  Base2DArcadePlanar.prototype.getPrimaryPenaltyScore = function getPrimaryPenaltyScore() {
    return rewardConfig.computePrimaryPenaltyScore(this);
  };

  Base2DArcadePlanar.prototype.laneY = function laneY(lane) {
    return this.topMargin + lane * this.laneHeight + Math.floor(this.laneHeight / 4);
  };

  Base2DArcadePlanar.prototype.isLaneEmpty = function isLaneEmpty(lane) {
    var targetY = this.laneY(lane);
    var index;
    for (index = 0; index < this.items.length; index += 1) {
      if (this.items[index][1] === targetY) return false;
    }
    for (index = 0; index < this.obstacles.length; index += 1) {
      if (this.obstacles[index][1] === targetY) return false;
    }
    return true;
  };

  Base2DArcadePlanar.prototype.pointOverlapsPlayerPickup = function pointOverlapsPlayerPickup(x, y) {
    return (
      this.playerY - this.itemSize <= y &&
      y <= this.playerY + this.playerHeight &&
      this.playerX - this.itemSize <= x &&
      x <= this.playerX + this.playerWidth
    );
  };

  Base2DArcadePlanar.prototype.spawnCoinIfNeeded = function spawnCoinIfNeeded() {
    var entitySpawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    // Keep the screen readable: at most maxCoins are active, even with spawn probability 1.0.
    if (this.items.length >= this.maxCoins) return;
    if (entitySpawnRng.next() >= COIN_SPAWN_PROBABILITY) return;

    for (var attempt = 0; attempt < 16; attempt += 1) {
      var lane = entitySpawnRng.randint(0, this.laneCount);
      if (!this.isLaneEmpty(lane)) continue;

      var playerCenterX = this.playerX + this.playerWidth / 2;
      var spawnHalfRange = (LEGACY_WORLD_WIDTH - this.itemSize * 2) / 2;
      var minX = Math.max(this.itemSize, Math.floor(playerCenterX - spawnHalfRange));
      var maxX = Math.min(this.width - this.itemSize, Math.ceil(playerCenterX + spawnHalfRange));
      var x = entitySpawnRng.randint(minX, maxX);
      var y = this.laneY(lane);
      if (this.pointOverlapsPlayerPickup(x, y) || !this.workzone.rectFits(x, y, this.itemSize, this.itemSize)) continue;

      this.items.push([x, y, 0]);
      return;
    }
  };

  Base2DArcadePlanar.prototype.spawnObstacleIfNeeded = function spawnObstacleIfNeeded() {
    var entitySpawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    if (this.obstacles.length >= this.maxObstacles) return;
    if (this.obstacleSpawnProbability <= 0) return;
    if (entitySpawnRng.next() >= this.obstacleSpawnProbability) return;

    var fromLeft = entitySpawnRng.randint(0, 2);
    var lane = entitySpawnRng.randint(0, this.laneCount);
    if (!this.isLaneEmpty(lane)) return;

    var segments = this.laneSegments[lane];
    if (!segments.length) return;
    var segment = segments[entitySpawnRng.randint(0, segments.length)];
    var x = fromLeft ? segment.start : segment.end;
    var y = this.laneY(lane);
    if (this.pointOverlapsPlayerPickup(x, y)) return;
    this.obstacles.push([x, y, fromLeft ? OBSTACLE_SPEED : -OBSTACLE_SPEED]);
  };

  Base2DArcadePlanar.prototype.getAction = function getAction() {
    return {
      moveX: (this.keys.right ? 1 : 0) - (this.keys.left ? 1 : 0),
      moveY: (this.keys.down ? 1 : 0) - (this.keys.up ? 1 : 0),
    };
  };

  Base2DArcadePlanar.prototype.consumeAction = function consumeAction() {
    if (this.pendingStartAction !== null) {
      var action = this.pendingStartAction;
      this.pendingStartAction = null;
      return action;
    }
    return this.getAction();
  };

  Base2DArcadePlanar.prototype.getActionFromKey = function getActionFromKey(key) {
    return {
      moveX: key === "left" ? -1 : key === "right" ? 1 : 0,
      moveY: key === "up" ? -1 : key === "down" ? 1 : 0,
    };
  };

  Base2DArcadePlanar.prototype.startPlaying = function startPlaying(initialAction) {
    if (this.paused) return false;
    if (this.mode !== "paused") return;
    this.mode = "playing";
    if (initialAction && typeof initialAction === "object") {
      this.pendingStartAction = {
        moveX: U.math.clamp(Number(initialAction.moveX) || 0, -1, 1),
        moveY: U.math.clamp(Number(initialAction.moveY) || 0, -1, 1),
      };
    }

    this.render();
    return true;
  };

  Base2DArcadePlanar.prototype.normalizeAction = function normalizeAction(action) {
    var id = Core.actions.readId(action, { lowercase: true });
    var left = Core.actions.hasKey(action, ["ArrowLeft", "KeyA", "a"]);
    var right = Core.actions.hasKey(action, ["ArrowRight", "KeyD", "d"]);
    var up = Core.actions.hasKey(action, ["ArrowUp", "KeyW", "w"]);
    var down = Core.actions.hasKey(action, ["ArrowDown", "KeyS", "s"]);
    var moveX = (right ? 1 : 0) - (left ? 1 : 0);
    var moveY = (down ? 1 : 0) - (up ? 1 : 0);
    return {
      id: id || (moveX === 0 && moveY === 0 ? "wait" : "key"),
      args: {},
      moveX: moveX,
      moveY: moveY,
    };
  };

  Base2DArcadePlanar.prototype.createFailTerminalLatch = function createFailTerminalLatch(action) {
    var visualPayload = this.getVisualPerturbationPayload();
    var viewport = T2D.viewport.state(this, this.width, this.height);
    return {
      id: this.terminalLatchId,
      status: "terminal",
      gameTimeMs: U.math.finiteNumber(this.gameTimeMs),
      terminal: {
        isTerminal: true,
        outcome: "fail",
        reason: "obstacle_collision",
      },
      game_state: {
        score: this.getPrimaryScore(),
        level: null,
        player: {
          x: finiteInt(this.playerX),
          y: finiteInt(this.playerY),
          width: this.playerWidth,
          height: this.playerHeight,
          speed: this.playerSpeed,
        },
        environment: {
          phase: "terminal",
          viewport_width: viewport.width,
          viewport_height: viewport.height,
          logic_width: this.width,
          logic_height: this.height,
          top_margin: this.topMargin,
          bottom_margin: this.bottomMargin,
          lane_count: this.laneCount,
          lane_height: this.laneHeight,
          max_coins: this.maxCoins,
          max_obstacles: this.maxObstacles,
          item_size: this.itemSize,
          difficulty: this.difficulty,
          scene_version: Scene.version,
          scene_layout: this.sceneLayout,
          floor_regions: this.workzone.regions,
          boundary_walls: this.workzone.walls,
          rand_init_pos: this.randInitPos,
          obstacle_spawn_probability: this.obstacleSpawnProbability,
          perturb: this.perturb,
          perturb_active: visualPayload.active_any,
          visual_perturbations: visualPayload,
        },
        entities: this.buildEntities(),
      },
      metrics: {
        env_reward_step: this.envRewardStep,
        env_reward_episode: this.envRewardEpisode,
        primary_positive_score: this.getPrimaryPositiveScore(),
        primary_penalty_score: this.getPrimaryPenaltyScore(),
        primary_score: this.getPrimaryScore(),
        coins_collected: this.coinsCollected,
        items_active: this.items.length,
        obstacles_active: this.obstacles.length,
        difficulty: this.difficulty,
        rand_init_pos: this.randInitPos,
        obstacle_spawn_probability: this.obstacleSpawnProbability,
        collisions: this.collisions,
        step_count: this.stepCount,
        episode_count: this.runtime.episodeCount,
      },
      debug: {
        mode: "terminal",
        last_action: action,
        last_reset_method: "terminal_auto_reset",
        reset_count: this.runtime.resetCount + 1,
        paused: this.paused,
        rand_init_pos: this.randInitPos,
        visual_perturbations: visualPayload,
      },
    };
  };

  Base2DArcadePlanar.prototype.step = function step(action) {
    if (this.mode !== "playing") {
      return false;
    }

    this.visualFailure = null;
    Core.reward.resetStep(this);
    var moveX = U.math.clamp(Number(action && action.moveX) || 0, -1, 1);
    var moveY = U.math.clamp(Number(action && action.moveY) || 0, -1, 1);
    var moveMagnitude = Math.sqrt(moveX * moveX + moveY * moveY);
    if (moveMagnitude > 1) {
      moveX /= moveMagnitude;
      moveY /= moveMagnitude;
    }
    var nextX = this.playerX + moveX * this.playerSpeed;
    if (this.workzone.rectFits(nextX, this.playerY, this.playerWidth, this.playerHeight)) this.playerX = nextX;
    var nextY = this.playerY + moveY * this.playerSpeed;
    if (this.workzone.rectFits(this.playerX, nextY, this.playerWidth, this.playerHeight)) this.playerY = nextY;

    var index;
    for (index = 0; index < this.obstacles.length; index += 1) {
      this.obstacles[index][0] += this.obstacles[index][2];
    }

    this.obstacles = this.obstacles.filter(function insideFloor(obstacle) {
      return this.workzone.rectFits(obstacle[0], obstacle[1], this.itemSize, this.itemSize);
    }, this);
    this.spawnCoinIfNeeded();
    this.spawnObstacleIfNeeded();

    var reward = 0;
    var done = false;

    for (index = 0; index < this.items.length; index += 1) {
      var item = this.items[index];
      if (
        this.playerY - this.itemSize <= item[1] &&
        item[1] <= this.playerY + this.playerHeight &&
        this.playerX - this.itemSize <= item[0] &&
        item[0] <= this.playerX + this.playerWidth
      ) {
        reward += rewardConfig.constants.coinReward;
        this.coinsCollected += 1;

        this.items.splice(index, 1);
      } else if (item[0] < 0 || item[0] > this.width) {
        this.items.splice(index, 1);
      }
    }

    for (index = 0; index < this.obstacles.length; index += 1) {
      var obstacle = this.obstacles[index];
      if (
        this.playerY - this.itemSize <= obstacle[1] &&
        obstacle[1] <= this.playerY + this.playerHeight &&
        this.playerX - this.itemSize <= obstacle[0] &&
        obstacle[0] <= this.playerX + this.playerWidth
      ) {
        reward -= rewardConfig.constants.obstaclePenalty;
        if (!done) {
          this.collisions += 1;
          this.visualFailure = {
            playerX: this.playerX, playerY: this.playerY, coinsCollected: this.coinsCollected,
            gameTimeMs: this.gameTimeMs, lastAction: this.lastAction,
            items: this.items.map(function (item) { return item.slice(); }),
            obstacles: this.obstacles.map(function (obstacle) { return obstacle.slice(); }),
          };
        }
        done = true;
        this.obstacles.splice(index, 1);
      } else if (obstacle[0] < 0 || obstacle[0] > this.width) {
        this.obstacles.splice(index, 1);
      }
    }

    this.items = this.items.filter(function (itemEntry) {
      return itemEntry[1] < LOGIC_HEIGHT;
    });
    this.obstacles = this.obstacles.filter(function (obstacleEntry) {
      return obstacleEntry[1] < LOGIC_HEIGHT;
    });

    Core.reward.add(this, reward);
    this.stepCount += 1;
    this.gameTimeMs = this.stepCount * STEP_MS;
    this.lastAction = [
      moveY < 0 ? "up" : moveY > 0 ? "down" : null,
      moveX < 0 ? "left" : moveX > 0 ? "right" : null,
    ].filter(Boolean).join("+") || "wait";

    if (done) {
      this.terminal = {
        isTerminal: true,
        outcome: "fail",
        reason: "obstacle_collision",
      };
      var failureSnapshot = Core.terminal.capture(this, this.createFailTerminalLatch.bind(this, this.lastAction));
      this.visualFailure.metrics = failureSnapshot.metrics;
      Core.terminal.autoReset(this, this.beginEpisode);
    }
    return true;
  };

  Base2DArcadePlanar.prototype.advanceTime = function advanceTime(ms, options) {
    var shouldRender = !options || options.render !== false;
    var duration = Number(ms);
    if (!Number.isFinite(duration) || duration <= 0) {

      if (shouldRender) this.render();
      return 0;
    }
    if (this.paused) {

      if (shouldRender) this.render();
      return 0;
    }
    var result = this.ensureSimulationRunner().advance(duration, { render: false });

    if (shouldRender) this.render();
    return result.steps;
  };

  Base2DArcadePlanar.prototype.ensureSimulationRunner = function ensureSimulationRunner() {
    if (this.simulationRunner) return this.simulationRunner;
    var self = this;
    this.simulationRunner = Core.createFixedStepRunner({
      game: this,
      stepMs: STEP_MS,
      maxFrameDeltaMs: 250,
      update: function update() { return self.step(self.consumeAction()); },
      render: function render() {

        self.render();
      },
      isActive: function isActive() { return self.mode === "playing" && !self.paused; },
    });
    return this.simulationRunner;
  };

  Base2DArcadePlanar.prototype.startLoop = function startLoop() {
    this.ensureSimulationRunner().start();
  };

  Base2DArcadePlanar.prototype.pause = function pause() {
    var wasPaused = this.paused;
    Core.lifecycle.pause(this);
    if (!wasPaused) {
      this.keys.left = false;
      this.keys.right = false;
      this.keys.up = false;
      this.keys.down = false;
      this.pendingStartAction = null;
    }

    this.render();
    return this.getPauseState();
  };

  Base2DArcadePlanar.prototype.resume = function resume() {
    Core.lifecycle.resume(this);

    this.render();
    return this.getPauseState();
  };

  Base2DArcadePlanar.prototype.getPauseState = function getPauseState() {
    return {
      ok: true,
      source: "game",
      paused: this.paused,
      runtime_paused: this.paused,
    };
  };

  Base2DArcadePlanar.prototype.drawLogicScene = function drawLogicScene() {
    presentation.render(this);
  };

  Base2DArcadePlanar.prototype.buildEntities = function buildEntities() {
    var entities = [];
    var index;
    for (index = 0; index < this.items.length; index += 1) {
      entities.push({
        type: "coin",
        x: finiteInt(this.items[index][0]),
        y: finiteInt(this.items[index][1]),
        size: finiteInt(this.itemSize),
      });
    }
    for (index = 0; index < this.obstacles.length; index += 1) {
      entities.push({
        type: "obstacle",
        x: finiteInt(this.obstacles[index][0]),
        y: finiteInt(this.obstacles[index][1]),
        size: finiteInt(this.itemSize),
        speed: U.math.finiteNumber(this.obstacles[index][2]),
      });
    }
    return entities;
  };

  Base2DArcadePlanar.prototype.getVisualPerturbationPayload = function getVisualPerturbationPayload() {
    return T2D.visuals.sync(this);
  };

  Base2DArcadePlanar.prototype.render = function render() {
    T2D.visuals.sync(this);
    this.drawLogicScene();
    view.render();
    if (this.infoPanel) this.infoPanel.update();
  };

  Base2DArcadePlanar.prototype.getStatePayload = function getStatePayload() {
    var latchedTerminal = Core.terminal.consume(this);
    var entities = this.buildEntities();
    var visualPayload = this.getVisualPerturbationPayload();
    var viewport = T2D.viewport.state(this, this.width, this.height);
    var payload = {
      schemaVersion: "2.0",
      gameId: GAME_ID,
      seed: this.seed,
      timestampMs: Date.now(),
      gameTimeMs: U.math.finiteNumber(this.gameTimeMs),
      status: this.mode,
      paused: this.mode === "paused" || this.paused,
      runtime_paused: this.paused,
      is_actionable: this.mode === "paused" || this.mode === "playing",
      terminal: {
        isTerminal: this.terminal.isTerminal,
        outcome: this.terminal.outcome,
        reason: this.terminal.reason,
      },
      game_state: {
        score: this.getPrimaryScore(),
        level: null,
        player: {
          x: finiteInt(this.playerX),
          y: finiteInt(this.playerY),
          width: this.playerWidth,
          height: this.playerHeight,
          speed: this.playerSpeed,
        },
        environment: {
          phase: this.mode,
          viewport_width: viewport.width,
          viewport_height: viewport.height,
          logic_width: this.width,
          logic_height: this.height,
          top_margin: this.topMargin,
          bottom_margin: this.bottomMargin,
          lane_count: this.laneCount,
          lane_height: this.laneHeight,
          max_coins: this.maxCoins,
          max_obstacles: this.maxObstacles,
          item_size: this.itemSize,
          difficulty: this.difficulty,
          scene_version: Scene.version,
          scene_layout: this.sceneLayout,
          floor_regions: this.workzone.regions,
          boundary_walls: this.workzone.walls,
          asset_pack: this.assetPack,
          asset: T2D.visuals.assetPayload(this),
          rand_init_pos: this.randInitPos,
          obstacle_spawn_probability: this.obstacleSpawnProbability,
          perturb: this.perturb,
          perturb_active: visualPayload.active_any,
          visual_perturbations: visualPayload,
        },
        entities: entities,
      },
      metrics: {
        env_reward_step: this.envRewardStep,
        env_reward_episode: this.envRewardEpisode,
        primary_positive_score: this.getPrimaryPositiveScore(),
        primary_penalty_score: this.getPrimaryPenaltyScore(),
        primary_score: this.getPrimaryScore(),
        coins_collected: this.coinsCollected,
        items_active: this.items.length,
        obstacles_active: this.obstacles.length,
        difficulty: this.difficulty,
        rand_init_pos: this.randInitPos,
        obstacle_spawn_probability: this.obstacleSpawnProbability,
        collisions: this.collisions,
        step_count: this.stepCount,
        episode_count: this.runtime.episodeCount,
      },
      debug: {
        mode: this.mode,
        last_action: this.lastAction,
        last_reset_method: this.runtime.lastResetMethod,
        reset_count: this.runtime.resetCount,
        paused: this.paused,
        runtime_paused: this.paused,
        rand_init_pos: this.randInitPos,
        visual_perturbations: visualPayload,
      },
    };

    if (latchedTerminal) {
      payload.gameTimeMs = latchedTerminal.gameTimeMs;
      payload.status = latchedTerminal.status;
      payload.is_actionable = false;
      payload.terminal = latchedTerminal.terminal;
      payload.game_state = latchedTerminal.game_state;
      payload.metrics = latchedTerminal.metrics;
      payload.debug = {
        mode: latchedTerminal.debug.mode,
        last_action: latchedTerminal.debug.last_action,
        last_reset_method: latchedTerminal.debug.last_reset_method,
        reset_count: latchedTerminal.debug.reset_count,
        paused: latchedTerminal.debug.paused,
        runtime_paused: latchedTerminal.debug.paused,
        rand_init_pos: latchedTerminal.debug.rand_init_pos,
        visual_perturbations: latchedTerminal.debug.visual_perturbations,
        terminal_latch_consumed: true,
        terminal_latch_id: latchedTerminal.id,
        visible_status: this.mode,
      };
    } else {
      payload.debug.terminal_latch_consumed = false;
      payload.debug.terminal_latch_id = null;
      payload.debug.visible_status = this.mode;
    }

    return payload;
  };

  Base2DArcadePlanar.prototype.getObservation = function getObservation() {
    return {
      status: this.mode,
      player: {
        x: finiteInt(this.playerX),
        y: finiteInt(this.playerY),
        width: this.playerWidth,
        height: this.playerHeight,
        speed: this.playerSpeed,
      },
      entities: this.buildEntities(),
      metrics: {
        env_reward_step: this.envRewardStep,
        env_reward_episode: this.envRewardEpisode,
        primary_positive_score: this.getPrimaryPositiveScore(),
        primary_penalty_score: this.getPrimaryPenaltyScore(),
        coins_collected: this.coinsCollected,
        collisions: this.collisions,
        step_count: this.stepCount,
      },
    };
  };

  Base2DArcadePlanar.prototype.infoPayload = function infoPayload() {
    return {
      gameId: GAME_ID,
      step_count: this.stepCount,
      episode_count: this.runtime.episodeCount,
      reset_count: this.runtime.resetCount,
      source: "game",
    };
  };

  Base2DArcadePlanar.prototype.resetGym = function resetGym(options) {
    this.runtime.lastResetMethod = "inplace_reset";
    var resetResult = this.beginEpisode(options || {}, true);
    return {
      observation: this.getObservation(),
      reward: 0,
      done: false,
      info: {
        gameId: GAME_ID,
        reset: resetResult,
      },
      state: this.getStatePayload(),
    };
  };

  Base2DArcadePlanar.prototype.applyAction = function applyAction(normalized) {
    if (!this.paused && this.mode === "paused") {
      this.startPlaying(normalized);
    }

    this.keys.left = normalized.moveX < 0;
    this.keys.right = normalized.moveX > 0;
    this.keys.up = normalized.moveY < 0;
    this.keys.down = normalized.moveY > 0;
  };

  Base2DArcadePlanar.prototype.advanceSimulation = function advanceSimulation(ms) {
    var steps = this.advanceTime(ms, { render: false });
    this.keys.left = false;
    this.keys.right = false;
    this.keys.up = false;
    this.keys.down = false;
    this.pendingStartAction = null;
    this.lastRuntimeAdvanceSteps = steps;
    return this.getStatePayload();
  };

  Base2DArcadePlanar.prototype.buildStepInfo = function buildStepInfo(state, stepOptions, normalized) {
    var info = this.infoPayload();
    info.source = stepOptions.source || "agent";
    info.durationMs = stepOptions.durationMs;
    info.steps = this.lastRuntimeAdvanceSteps || 0;
    info.action = {
      type: "game_step_action",
      id: normalized.id,
      args: {},
    };
    return info;
  };

  Base2DArcadePlanar.prototype.renderGameToText = function renderGameToText() {
    var visualPayload = this.getVisualPerturbationPayload();
    var payload = {
      coordinate_system: "origin=(0,0) top-left, +x right, +y down, logic_size="
        + LOGIC_WIDTH + "x" + LOGIC_HEIGHT,
      status: this.mode,
      player: {
        x: finiteInt(this.playerX),
        y: finiteInt(this.playerY),
        width: this.playerWidth,
        height: this.playerHeight,
      },
      coins: this.items.map(function (item) {
        return {
          x: finiteInt(item[0]),
          y: finiteInt(item[1]),
          size: finiteInt(this.itemSize),
        };
      }, this),
      obstacles: this.obstacles.map(function (obstacle) {
        return {
          x: finiteInt(obstacle[0]),
          y: finiteInt(obstacle[1]),
          speed: U.math.finiteNumber(obstacle[2]),
          size: finiteInt(this.itemSize),
        };
      }, this),
      rewards: {
        env_reward_step: this.envRewardStep,
        env_reward_episode: this.envRewardEpisode,
        primary_positive_score: this.getPrimaryPositiveScore(),
        primary_penalty_score: this.getPrimaryPenaltyScore(),
        primary_score: this.getPrimaryScore(),
      },
      difficulty: {
        value: this.difficulty,
        obstacle_spawn_probability: this.obstacleSpawnProbability,
      },
      rand_init_pos: this.randInitPos,
      perturb: {
        active: visualPayload.active_any,
        label: visualPayload.label,
      },
      visual_perturbations: visualPayload,
    };
    return JSON.stringify(payload);
  };

  Base2DArcadePlanar.prototype.bindInput = function bindInput() {
    var self = this;

    function keyFromEvent(event) {
      if (event.key === "ArrowLeft" || event.key === "Left" || event.key === "a" || event.key === "A") return "left";
      if (event.key === "ArrowRight" || event.key === "Right" || event.key === "d" || event.key === "D") return "right";
      if (event.key === "ArrowUp" || event.key === "Up" || event.key === "w" || event.key === "W") return "up";
      if (event.key === "ArrowDown" || event.key === "Down" || event.key === "s" || event.key === "S") return "down";
      return null;
    }

    function onKeyDown(event) {
      var key = keyFromEvent(event);
      var fullscreenKey = event.key === "f" || event.key === "F";
      if (self.paused) {
        if (event.key && !fullscreenKey) {
          event.preventDefault();
        }
        return;
      }
      if (fullscreenKey) {
        return;
      }
      if (self.mode === "paused") {
        self.startPlaying(key === null ? null : self.getActionFromKey(key));
      }
      if (!key) {
        if (self.mode === "playing") {
          event.preventDefault();
        }
        return;
      }
      event.preventDefault();
      self.keys[key] = true;
    }

    function onKeyUp(event) {
      var key = keyFromEvent(event);
      if (!key) return;
      event.preventDefault();
      if (self.paused) return;
      self.keys[key] = false;
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    app.addEventListener("mousedown", function () {
      app.focus();
      if (self.paused) {
        return;
      }
      if (self.mode === "paused") {
        self.startPlaying();
      }
    });

    app.focus();
  };

  async function start() {
    await T2D.assets.preload(Scene.pack, ASSET_REQUIREMENTS);
    view = await T2D.createStage(displayCanvas, { width: LOGIC_WIDTH, height: LOGIC_HEIGHT, background: 0xffffff });
    if (!view) throw new Error("Three.js 2D engine unavailable");
    presentation = Scene.create(view, createAsset);
    var game = new Base2DArcadePlanar();

    if (game.urlConfig.autostart) {
      game.startPlaying();
    }

    Core.createRuntime({
      game: game,
      presentation: {
        title: "2D Collect & Dodge",
        controls: "WASD or arrows move; combine keys for diagonals. Collect coins and avoid moving hazards.",
        read: function readPresentation() {
          var failure = game.visualFailure, metrics = failure ? failure.metrics : null;
          return {
            status: failure ? "collision" : (game.paused ? "paused" : game.mode),
            primaryScore: metrics ? metrics.primary_score : game.getPrimaryScore(),
            stepReward: metrics ? metrics.env_reward_step : game.envRewardStep,
            episodeReward: metrics ? metrics.env_reward_episode : game.envRewardEpisode,
            difficulty: game.difficulty,
            seed: game.seed,
            perturbation: Core.perturbations.label(game),
            details: [["Coins", metrics ? metrics.coins_collected : game.coinsCollected],
              ["Collisions", metrics ? metrics.collisions : game.collisions],
              ["Coins visible", (failure ? failure.items : game.items).length],
              ["Hazards", (failure ? failure.obstacles : game.obstacles).length]],
          };
        },
      },
      renderer: T2D,
      gameId: GAME_ID,
      defaultSeed: DEFAULT_SEED,
      maxDifficulty: MAX_DIFFICULTY,
      defaultStepMs: 200,
      assets: { engine: T2D.assets, requiredAssetIds: ASSET_REQUIREMENTS },
      capabilities: { supports_rand_init_pos: true },
      init: function init(config) {
        game.runtime.lastResetMethod = null;
        return game.beginEpisode(config || {}, false);
      },
      reset: function reset(options) {
        game.runtime.lastResetMethod = "inplace_reset";
        return game.beginEpisode(options || {}, true);
      },
    });
  }

  Core.lifecycle.boot(start);
})();
