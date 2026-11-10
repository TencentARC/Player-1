(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var T2D = window.BaseGameletThree2D;
  var rewardConfig = window.Base2DPlatformRewardConfig;
  var Summit = window.SummitRunScene;
  var Terrain = window.SummitTerrain;
  var GAME_ID = "base_2d_platform";
  var LOGIC_HEIGHT = 640;
  var LOGIC_WIDTH = T2D.viewport.widthForHeight(LOGIC_HEIGHT);
  var DISPLAY_WIDTH = T2D.viewport.baseWidth;
  var DISPLAY_HEIGHT = T2D.viewport.baseHeight;
  var STEP_MS = 1000 / 60;
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 5;
  var ASSET_REQUIREMENTS = Summit.assets;
  var PLAYER_W = 26;
  var PLAYER_H = 34;
  var GRAVITY = 980;
  var MAX_STEP_UP_HEIGHT = 12;
  var RESPAWN_RECOVERY_SECONDS = 0.2;
  var PERTURBATION_CONTRACT = Core.perturbations.defineContract({
    game_id: GAME_ID,
    control_response: {
      move_scale: Core.controlResponse.ranges.platform_move_scale,
      jump_scale: Core.controlResponse.ranges.jump_scale,
    },
    capabilities: {
      appearance: ["palette", "background", "assets"],
      camera: ["projection"],
      scene: ["layout", "entity_spawn"],
    },
    samplers: { camera: { projection: T2D.camera.projectionSampler }, scene: { layout: Terrain.sampleLayout } },
    validators: { camera: { projection: T2D.camera.projectionValidator } },
  });

  var canvas = document.getElementById("display");
  var view = null;
  var scene = null;


  function Base2DPlatform() {
    this.defaults = { seed: DEFAULT_SEED, difficulty: DEFAULT_DIFFICULTY, maxDifficulty: MAX_DIFFICULTY };
    this.urlConfig = Core.config.readUrl(this.defaults);
    this.controls = { left: false, right: false, jump: false, dash: false, jumpQueued: false };
    this.paused = false;
    this.runtime = { resetCount: 0, episodeCount: 0, lastResetMethod: null };
    this.bestMetrics = { bestPrimaryScore: 0 };
    Core.terminal.initialize(this);
    this.bindInput();
    Core.lifecycle.bindResetKeys(this);
    this.beginEpisode({}, false);
    this.startLoop();
  }

  Base2DPlatform.prototype.beginEpisode = function beginEpisode(options, countReset, flags) {
    var episodeFlags = flags || {};
    var normalized = Core.config.normalizeOptions(options || {}, MAX_DIFFICULTY);
    var config = Core.config.mergeEpisode(this.urlConfig, normalized);
    Core.lifecycle.resetEpisode(this, { controls: { left: false, right: false, jump: false, dash: false, jumpQueued: false } });
    this.currentConfig = Core.config.cloneEpisode(config);
    Core.terminal.clear(this, episodeFlags);
    Core.domains.beginEpisode(this, config, PERTURBATION_CONTRACT, DEFAULT_SEED);
    this.difficulty = config.difficulty;
    this.levelIndex = 0;
    this.level = this.buildLevel();
    this.x = this.level.start.x;
    this.y = this.level.start.y;
    this.vx = 0;
    this.vy = 0;
    this.onGround = true;
    this.groundPlatformId = this.level.start.platform_id;
    this.currentCheckpointIndex = 0;
    this.lastCheckpoint = Object.assign({}, this.level.checkpoints[0]);
    this.recoveryRemaining = 0;
    this.lastRespawnReason = null;
    this.coinsCollected = 0;
    this.gapsCleared = 0;
    this.spikesCleared = 0;
    this.flagsReached = 0;
    this.jumps = 0;
    this.dashes = 0;
    this.hazardHits = 0;
    this.falls = 0;
    this.respawns = 0;
    this.checkpointUpdates = 0;
    this.distanceProgress = 0;
    this.levelDistanceProgress = 0;
    this.bestX = this.x;
    this.stepCount = 0;
    this.gameTimeMs = 0;
    this.sceneState = Summit.createState();
    Core.reward.resetEpisode(this);
    this.lastAction = "reset";
    this.mode = config.autostart ? "playing" : "paused";
    this.terminal = { isTerminal: false, outcome: null, reason: null };
    this.controls = { left: false, right: false, jump: false, dash: false, jumpQueued: false };
    if (countReset) this.runtime.resetCount += 1;
    this.runtime.episodeCount += 1;
    this.runtime.lastResetMethod = countReset ? "inplace_reset" : "init";
    T2D.visuals.configure(this, config, {
      defaultAssetPack: Summit.pack,
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
      view: view,
    });
    this.updateBestMetrics();

    this.render();
    return { accepted: normalized, applied: config, notes: [] };
  };

  Base2DPlatform.prototype.buildLevel = function buildLevel() {
    return Terrain.build({
      layoutRng: Core.domains.gameplayRng(this, "scene", "layout"),
      entityRng: Core.domains.gameplayRng(this, "scene", "entity_spawn"),
      layout: Core.domains.sample(this, "scene", "layout", { template: "ridge", width_scale: 1 }),
      difficulty: this.difficulty, levelIndex: this.levelIndex,
    });
  };

  Base2DPlatform.prototype.bindInput = function bindInput() {
    var self = this;
    function setKey(event, value) {
      var key = event.key;
      var handled = true;
      if (key === "ArrowLeft" || key === "a" || key === "A") self.controls.left = value;
      else if (key === "ArrowRight" || key === "d" || key === "D") self.controls.right = value;
      else if (key === "ArrowUp" || key === "w" || key === "W" || key === " ") {
        if (value && !self.controls.jump) self.controls.jumpQueued = true;
        self.controls.jump = value;
      } else if (key === "Shift") self.controls.dash = value;
      else handled = false;
      if (handled) {
        event.preventDefault();
        if (self.mode === "paused" && value) self.mode = "playing";
      }
    }
    document.addEventListener("keydown", function onKeyDown(event) { setKey(event, true); });
    document.addEventListener("keyup", function onKeyUp(event) { setKey(event, false); });
    var app = document.getElementById("app");
    if (app) app.focus();
  };

  Base2DPlatform.prototype.ensureSimulationRunner = function ensureSimulationRunner() {
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

  Base2DPlatform.prototype.startLoop = function startLoop() {
    this.ensureSimulationRunner().start();
  };

  Base2DPlatform.prototype.pause = function pause() {
    var pauseState = Core.lifecycle.pause(this);
    this.render();
    return pauseState;
  };

  Base2DPlatform.prototype.resume = function resume() {
    var pauseState = Core.lifecycle.resume(this);
    this.render();
    return pauseState;
  };

  Base2DPlatform.prototype.playerRect = function playerRect() {
    return { x: this.x - PLAYER_W / 2, y: this.y - PLAYER_H / 2, w: PLAYER_W, h: PLAYER_H };
  };

  Base2DPlatform.prototype.addReward = function addReward(value) {
    return Core.reward.add(this, value);
  };

  Base2DPlatform.prototype.startNextLevel = function startNextLevel() {
    this.flagsReached += 1;
    this.levelIndex += 1;
    this.level = this.buildLevel();
    this.x = this.level.start.x;
    this.y = this.level.start.y;
    this.vx = 0;
    this.vy = 0;
    this.onGround = true;
    this.groundPlatformId = this.level.start.platform_id;
    this.currentCheckpointIndex = 0;
    this.lastCheckpoint = Object.assign({}, this.level.checkpoints[0]);
    this.recoveryRemaining = 0;
    this.lastRespawnReason = null;
    this.bestX = this.x;
    this.levelDistanceProgress = 0;
    this.lastAction = "flag_reached";
    this.sceneState.runDistance = 0;
    this.sceneState.events = [];
  };

  Base2DPlatform.prototype.updateCheckpoint = function updateCheckpoint() {
    if (!this.onGround || !this.groundPlatformId) return;
    for (var i = this.currentCheckpointIndex + 1; i < this.level.checkpoints.length; i += 1) {
      var checkpoint = this.level.checkpoints[i];
      if (checkpoint.x > this.x + PLAYER_W / 2) break;
      if (checkpoint.platform_id !== this.groundPlatformId) continue;
      this.currentCheckpointIndex = i;
      this.lastCheckpoint = Object.assign({}, checkpoint);
      this.checkpointUpdates += 1;
    }
  };

  Base2DPlatform.prototype.respawnFromHazard = function respawnFromHazard(reason) {
    if (reason === "spike_hit") {
      this.hazardHits += 1;
      this.addReward(-rewardConfig.constants.hazardPenalty);
    } else {
      this.falls += 1;
      this.addReward(-rewardConfig.constants.fallPenalty);
    }
    this.respawns += 1;
    this.lastRespawnReason = reason;
    this.x = this.lastCheckpoint.x;
    this.y = this.lastCheckpoint.y;
    this.vx = 0;
    this.vy = 0;
    this.onGround = true;
    this.groundPlatformId = this.lastCheckpoint.platform_id;
    this.recoveryRemaining = RESPAWN_RECOVERY_SECONDS;
    this.controls.jumpQueued = false;
    this.lastAction = "respawn_" + reason;
    this.sceneState.respawnAt = this.gameTimeMs;
    this.sceneState.events = [];
  };

  Base2DPlatform.prototype.update = function update(dt) {
    if (this.terminal.isTerminal || this.mode !== "playing") return;
    Core.reward.resetStep(this);
    this.stepCount += 1;
    this.gameTimeMs += dt * 1000;
    if (this.recoveryRemaining > 0) {
      this.recoveryRemaining = Math.max(0, this.recoveryRemaining - dt);
      this.lastAction = "recovering";
      this.updateBestMetrics();

      return;
    }
    this.lastAction = [this.controls.left ? "left" : null, this.controls.right ? "right" : null, this.controls.jump ? "jump" : null, this.controls.dash ? "dash" : null].filter(Boolean).join("+") || "idle";

    var moveMultiplier = (this.controls.dash ? 2 : 1) * this.controlResponse.applied.move_scale;
    var accel = 780 * moveMultiplier;
    var maxSpeed = 180 * moveMultiplier;
    if (this.controls.left) this.vx -= accel * dt;
    if (this.controls.right) this.vx += accel * dt;
    if (!this.controls.left && !this.controls.right) this.vx *= 0.86;
    this.vx = U.math.clamp(this.vx, -maxSpeed, maxSpeed);
    if (this.controls.dash && Math.abs(this.vx) > 190 * this.controlResponse.applied.move_scale) this.dashes += 1;
    if (this.controls.jumpQueued && this.onGround) {
      this.vy = -500 * this.controlResponse.applied.jump_scale;
      this.onGround = false;
      this.jumps += 1;
    }
    this.controls.jumpQueued = false;
    if (this.controls.jump && this.vy < 0) this.vy -= 70 * dt;
    this.vy += GRAVITY * dt;

    var previousX = this.x;
    this.x += this.vx * dt;
    this.x = U.math.clamp(this.x, PLAYER_W / 2, this.level.worldWidth - PLAYER_W / 2);
    this.resolveHorizontalPlatforms(previousX);
    var previousY = this.y;
    var wasOnGround = this.onGround;
    this.y += this.vy * dt;
    this.resolveVerticalPlatforms(previousY);
    Summit.advance(this, wasOnGround, previousX);
    if (this.x > this.bestX) {
      var deltaProgress = this.x - this.bestX;
      this.bestX = this.x;
      this.levelDistanceProgress = Math.max(this.levelDistanceProgress, this.bestX - this.level.start.x);
      this.distanceProgress += deltaProgress;
      this.addReward(deltaProgress * rewardConfig.constants.progressRewardScale);
    }
    this.updateCheckpoint();
    this.collectCoins();
    if (this.checkHazards()) {
      this.updateBestMetrics();

      return;
    }
    if (this.y > LOGIC_HEIGHT + 80) {
      this.respawnFromHazard("fell_into_pit");
      this.updateBestMetrics();

      return;
    }
    this.checkObstacleClears();
    if (this.x >= this.level.flag.x) {
      this.addReward(rewardConfig.constants.flagReward);
      this.startNextLevel();
    }
    this.updateBestMetrics();

  };

  Base2DPlatform.prototype.resolveHorizontalPlatforms = function resolveHorizontalPlatforms(previousX) {
    var playerTop = this.y - PLAYER_H / 2;
    var playerBottom = this.y + PLAYER_H / 2;
    var previousLeft = previousX - PLAYER_W / 2;
    var previousRight = previousX + PLAYER_W / 2;
    var nextLeft = this.x - PLAYER_W / 2;
    var nextRight = this.x + PLAYER_W / 2;
    for (var i = 0; i < this.level.platforms.length; i += 1) {
      var platform = this.level.platforms[i];
      if (!platform.solid_sides || playerTop >= platform.y + platform.h) continue;
      var crossedLeftEdge = this.vx > 0 && previousRight <= platform.x + 1 && nextRight > platform.x;
      var platformRight = platform.x + platform.w;
      var crossedRightEdge = this.vx < 0 && previousLeft >= platformRight - 1 && nextLeft < platformRight;
      if (!crossedLeftEdge && !crossedRightEdge) continue;
      if (playerBottom <= platform.y + 3) continue;
      if (this.onGround && playerBottom - platform.y <= MAX_STEP_UP_HEIGHT) {
        this.y = platform.y - PLAYER_H / 2;
        this.groundPlatformId = platform.id;
        return;
      }
      if (crossedLeftEdge) {
        this.x = platform.x - PLAYER_W / 2;
        this.vx = 0;
        return;
      }
      if (crossedRightEdge) {
        this.x = platformRight + PLAYER_W / 2;
        this.vx = 0;
        return;
      }
    }
  };

  Base2DPlatform.prototype.resolveVerticalPlatforms = function resolveVerticalPlatforms(previousY) {
    this.onGround = false;
    this.groundPlatformId = null;
    if (this.vy < 0) return;
    var previousBottom = previousY + PLAYER_H / 2;
    var nextBottom = this.y + PLAYER_H / 2;
    var playerLeft = this.x - PLAYER_W / 2 + 2;
    var playerRight = this.x + PLAYER_W / 2 - 2;
    var landing = null;
    for (var i = 0; i < this.level.platforms.length; i += 1) {
      var platform = this.level.platforms[i];
      if (playerRight <= platform.x || playerLeft >= platform.x + platform.w) continue;
      if (previousBottom > platform.y + 4 || nextBottom < platform.y) continue;
      if (!landing || platform.y < landing.y) landing = platform;
    }
    if (!landing) return;
    this.y = landing.y - PLAYER_H / 2;
    this.vy = 0;
    this.onGround = true;
    this.groundPlatformId = landing.id;
  };

  Base2DPlatform.prototype.collectCoins = function collectCoins() {
    var player = this.playerRect();
    for (var i = 0; i < this.level.coins.length; i += 1) {
      var coin = this.level.coins[i];
      if (!coin.collected && U.geometry2d.rectanglesOverlap(player, { x: coin.x - coin.r, y: coin.y - coin.r, w: coin.r * 2, h: coin.r * 2 })) {
        coin.collected = true;
        this.coinsCollected += 1;
        this.addReward(rewardConfig.constants.coinReward);
      }
    }
  };

  Base2DPlatform.prototype.checkHazards = function checkHazards() {
    var player = this.playerRect();
    for (var i = 0; i < this.level.spikes.length; i += 1) {
      if (U.geometry2d.rectanglesOverlap(player, this.level.spikes[i])) {
        this.respawnFromHazard("spike_hit");
        return true;
      }
    }
    return false;
  };

  Base2DPlatform.prototype.checkObstacleClears = function checkObstacleClears() {
    var playerLeft = this.x - PLAYER_W / 2;
    for (var gapIndex = 0; gapIndex < this.level.gaps.length; gapIndex += 1) {
      var gap = this.level.gaps[gapIndex];
      if (!gap.cleared && this.onGround && playerLeft >= gap.x + gap.w) {
        gap.cleared = true;
        this.gapsCleared += 1;
        this.addReward(rewardConfig.constants.gapReward);
      }
    }
    for (var spikeIndex = 0; spikeIndex < this.level.spikes.length; spikeIndex += 1) {
      var spike = this.level.spikes[spikeIndex];
      if (!spike.cleared && playerLeft >= spike.x + spike.w) {
        spike.cleared = true;
        this.spikesCleared += 1;
        this.addReward(rewardConfig.constants.spikeReward);
      }
    }
  };

  Base2DPlatform.prototype.advanceTime = function advanceTime(ms, options) {
    var opts = typeof options === "object" && options !== null ? options : { render: options !== false };
    this.ensureSimulationRunner().advance(ms, opts);
    if (opts.returnState === false) return null;
    return this.getStatePayload();
  };

  Base2DPlatform.prototype.normalizeAction = function normalizeAction(action) {
    var actionId = Core.actions.readId(action, { lowercase: true });
    return {
      id: actionId || "wait",
      args: {},
      left: Core.actions.hasKey(action, ["ArrowLeft", "KeyA", "a"]),
      right: Core.actions.hasKey(action, ["ArrowRight", "KeyD", "d"]),
      jump: Core.actions.hasKey(action, ["Space", " ", "ArrowUp", "KeyW", "w"]),
      dash: Core.actions.hasKey(action, ["ShiftLeft", "ShiftRight", "Shift"]),
    };
  };

  Base2DPlatform.prototype.clearTransientControls = function clearTransientControls() {
    this.controls = { left: false, right: false, jump: false, dash: false, jumpQueued: false };
  };

  Base2DPlatform.prototype.applyAction = function applyAction(normalized) {
    this.controls.left = normalized.left;
    this.controls.right = normalized.right;
    this.controls.dash = normalized.dash;
    if (normalized.jump) {
      this.controls.jump = true;
      this.controls.jumpQueued = true;
    }
    if (this.mode === "paused") this.mode = "playing";
  };

  Base2DPlatform.prototype.advanceSimulation = function advanceSimulation(ms) {
    var state = this.advanceTime(ms, { render: false });
    this.clearTransientControls();
    return state;
  };

  Base2DPlatform.prototype.buildStepInfo = function buildStepInfo(state) {
    var info = Core.terminal.withInfo(this, state, this.infoPayload());
    return info;
  };

  Base2DPlatform.prototype.resetGym = function resetGym(options) {
    this.resetFromAPI(options || {});
    return { observation: this.getObservation(), reward: 0, done: false, info: this.infoPayload() };
  };

  Base2DPlatform.prototype.getObservation = function getObservation() {
    return {
      player: {
        x: this.x,
        y: this.y,
        vx: this.vx,
        vy: this.vy,
        on_ground: this.onGround,
        recovering: this.recoveryRemaining > 0,
      },
      platforms: this.level.platforms,
      gaps: this.level.gaps,
      spikes: this.level.spikes,
      coins: this.level.coins.filter(function (coin) { return !coin.collected; }),
      flag: this.level.flag,
      checkpoint: Object.assign({}, this.lastCheckpoint),
      routes: this.level.routes,
    };
  };

  Base2DPlatform.prototype.infoPayload = function infoPayload() {
    return {
      score: this.getPrimaryScore(),
      distance_progress: this.distanceProgress,
      flags_reached: this.flagsReached,
      coins_collected: this.coinsCollected,
      gaps_cleared: this.gapsCleared,
      spikes_cleared: this.spikesCleared,
      jumps: this.jumps,
      hazard_hits: this.hazardHits,
      falls: this.falls,
      respawns: this.respawns,
      checkpoint_index: this.currentCheckpointIndex,
      env_reward_step: this.envRewardStep,
      env_reward_episode: this.envRewardEpisode,
      time_steps: this.stepCount,
    };
  };

  Base2DPlatform.prototype.getPrimaryScore = function getPrimaryScore() {
    return rewardConfig.computePrimaryScore(this);
  };

  Base2DPlatform.prototype.rewardPayload = function rewardPayload() {
    return {
      env_reward_step: this.envRewardStep,
      env_reward_episode: this.envRewardEpisode,
      primary_positive_score: rewardConfig.computePrimaryPositiveScore(this),
      primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(this),
      primary_score: this.getPrimaryScore(),
    };
  };

  Base2DPlatform.prototype.updateBestMetrics = function updateBestMetrics() {
    var rewards = this.rewardPayload();
    this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, rewards.primary_score);
  };

  Base2DPlatform.prototype.entityPayload = function entityPayload() {
    var entities = [{
      id: "player",
      type: "player",
      x: this.x,
      y: this.y,
      w: PLAYER_W,
      h: PLAYER_H,
      vx: this.vx,
      vy: this.vy,
      on_ground: this.onGround,
      recovering: this.recoveryRemaining > 0,
    }];
    this.level.platforms.forEach(function (platform) { entities.push(Object.assign({ type: "platform" }, platform)); });
    this.level.gaps.forEach(function (gap) { entities.push(Object.assign({ type: "gap" }, gap)); });
    this.level.spikes.forEach(function (spike) { entities.push(Object.assign({ type: "spike" }, spike)); });
    this.level.coins.forEach(function (coin) { if (!coin.collected) entities.push(Object.assign({ type: "coin" }, coin)); });
    entities.push(Object.assign({ type: "flag" }, this.level.flag));
    return entities;
  };

  Base2DPlatform.prototype.visualPayload = function visualPayload() {
    return T2D.visuals.sync(this);
  };

  Base2DPlatform.prototype.getStatePayload = function getStatePayload() {
    var latched = Core.terminal.consume(this);
    if (latched) return latched;
    T2D.visuals.sync(this);
    var rewards = this.rewardPayload();
    var viewport = T2D.viewport.state(this, LOGIC_WIDTH, LOGIC_HEIGHT);
    var cameraX = this.cameraX();
    var cameraBounds = view.getVisibleBounds();
    cameraBounds.left += cameraX;
    cameraBounds.right += cameraX;
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
        score: rewards.primary_score,
        level: null,
        player: {
          x: this.x,
          y: this.y,
          vx: this.vx,
          vy: this.vy,
          on_ground: this.onGround,
          recovering: this.recoveryRemaining > 0,
          checkpoint: Object.assign({}, this.lastCheckpoint),
        },
        environment: {
          phase: this.terminal.isTerminal ? "terminal" : this.mode,
          viewport_width: viewport.width,
          viewport_height: viewport.height,
          logic_width: LOGIC_WIDTH,
          logic_height: LOGIC_HEIGHT,
          world_width: this.level.worldWidth,
          scene_layout: this.level.layout,
          camera_x: cameraX,
          camera_zoom: view.getOrthographicZoom(),
          camera_visible_bounds: cameraBounds,
          level_index: this.levelIndex,
          route_types: this.level.routes.map(function routeType(route) { return route.type; }),
          difficulty: this.difficulty,
          asset_pack: this.assetPack,
          scene_version: Summit.version,
          asset: T2D.visuals.assetPayload(this),
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
        distance_progress: this.distanceProgress,
        level_distance_progress: this.levelDistanceProgress,
        flags_reached: this.flagsReached,
        coins_collected: this.coinsCollected,
        gaps_cleared: this.gapsCleared,
        spikes_cleared: this.spikesCleared,
        jumps: this.jumps,
        dashes: this.dashes,
        hazard_hits: this.hazardHits,
        falls: this.falls,
        respawns: this.respawns,
        checkpoint_index: this.currentCheckpointIndex,
        checkpoint_updates: this.checkpointUpdates,
        last_respawn_reason: this.lastRespawnReason,
        level_index: this.levelIndex,
        best_primary_score: this.bestMetrics.bestPrimaryScore,
        step_count: this.stepCount,
        episode_count: this.runtime.episodeCount,
        difficulty: this.difficulty,
      },
      debug: { mode: this.mode, last_action: this.lastAction, last_reset_method: this.runtime.lastResetMethod, reset_count: this.runtime.resetCount },
    };
  };

  Base2DPlatform.prototype.renderGameToText = function renderGameToText() {
    return JSON.stringify({
      coordinate_system: "world origin=(0,0) top-left, +x right, +y down",
      status: this.mode,
      player: {
        x: this.x,
        y: this.y,
        vx: this.vx,
        vy: this.vy,
        on_ground: this.onGround,
        recovering: this.recoveryRemaining > 0,
        checkpoint: Object.assign({}, this.lastCheckpoint),
      },
      platforms: this.level.platforms,
      gaps: this.level.gaps,
      spikes: this.level.spikes,
      coins: this.level.coins.filter(function (coin) { return !coin.collected; }),
      flag: this.level.flag,
      routes: this.level.routes,
      progress: {
        distance_progress: this.distanceProgress,
        level_distance_progress: this.levelDistanceProgress,
        flags_reached: this.flagsReached,
        coins_collected: this.coinsCollected,
        gaps_cleared: this.gapsCleared,
        spikes_cleared: this.spikesCleared,
        respawns: this.respawns,
      },
      rewards: this.rewardPayload(),
      difficulty: this.difficulty,
      visual_perturbations: this.visualPayload(),
    });
  };

  Base2DPlatform.prototype.cameraX = function cameraX() {
    var bounds = view.getVisibleBounds();
    return U.math.clamp(this.x - 220, 0, Math.max(0, this.level.worldWidth - bounds.width)) - bounds.left;
  };

  Base2DPlatform.prototype.render = function render() {
    T2D.visuals.sync(this);
    scene.render(this);
    if (this.infoPanel) this.infoPanel.update();
  };

  Base2DPlatform.prototype.resetFromAPI = function resetFromAPI(options) { return this.beginEpisode(options || {}, true); };

  async function start() {
    await T2D.assets.preload(Summit.pack, ASSET_REQUIREMENTS);
    view = await T2D.createStage(canvas, {
      width: LOGIC_WIDTH, height: LOGIC_HEIGHT, cameraViewHeight: 512, background: 0xffffff,
    });
    if (!view) throw new Error("Three.js 2D engine unavailable");
    scene = Summit.create(view, LOGIC_WIDTH, LOGIC_HEIGHT);
    var game = new Base2DPlatform();
    Core.createRuntime({
      game: game,
      presentation: {
        title: "2D Platforming",
        controls: "A/D or left/right arrows move; Space, W or up arrow jumps; hold Shift to sprint. Reach flags and avoid pits and spikes.",
        read: function readPresentation() {
          return {
            status: game.paused ? "paused" : game.mode,
            primaryScore: game.getPrimaryScore(),
            stepReward: game.envRewardStep,
            episodeReward: game.envRewardEpisode,
            difficulty: game.difficulty,
            seed: game.seed,
            perturbation: Core.perturbations.label(game),
            details: [["Distance", Math.round(game.distanceProgress) + " px"], ["Coins", game.coinsCollected],
              ["Flags reached", game.flagsReached],
              ["Movement", game.recoveryRemaining > 0 ? "Recovering" : (game.onGround ? "Grounded" : "Airborne")],
              ["Gaps cleared", game.gapsCleared], ["Spikes cleared", game.spikesCleared], ["Respawns", game.respawns]],
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
