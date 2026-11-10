(function () {
  "use strict";

  var T2D = window.BaseGameletThree2D;
  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var Gallery = window.PrecisionGalleryScene;
  var rewardConfig = window.Base2DAimRewardConfig;

  var GAME_ID = "base_2d_aim";
  var LOGIC_HEIGHT = 640;
  var LOGIC_WIDTH = T2D.viewport.widthForHeight(LOGIC_HEIGHT);
  var DISPLAY_WIDTH = T2D.viewport.baseWidth;
  var DISPLAY_HEIGHT = T2D.viewport.baseHeight;
  var STEP_MS = 1000 / 60;
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 5;
  var ASSET_REQUIREMENTS = Gallery.assets;
  var TARGET_BASE_SPEED_PER_FIXED_STEP = 0.8;
  var TARGET_DIFFICULTY_SPEED_PER_FIXED_STEP = 0.22;
  var TARGET_VERTICAL_SPEED_RATIO = 0.7;
  var TARGET_MAX_RADII_PER_SECOND = 4;
  var FIRE_INTERVAL_MS = 100;
  var SCENE_LAYOUT_TEMPLATES = Object.freeze(["range_lanes", "split_panels", "corner_bays"]);
  var SCENE_LAYOUT_NAMES = Object.freeze(["open"].concat(SCENE_LAYOUT_TEMPLATES));
  var PERTURBATION_CONTRACT = Core.perturbations.defineContract({
    game_id: GAME_ID,
    capabilities: {
      appearance: ["palette", "background", "assets"],
      camera: ["projection"],
      scene: ["layout", "entity_spawn"],
    },
    samplers: {
      camera: { projection: T2D.camera.projectionSampler },
      scene: { layout: Core.perturbations.templateSampler("open", SCENE_LAYOUT_TEMPLATES) },
    },
    validators: {
      camera: { projection: T2D.camera.projectionValidator },
      scene: { layout: Core.perturbations.templateValidator(SCENE_LAYOUT_NAMES) },
    },
  });

  function finiteRoundedInt(value) {
    return Number.isFinite(value) ? Math.round(value) : null;
  }

  function distanceXY(x1, y1, x2, y2) {
    var dx = x1 - x2;
    var dy = y1 - y2;
    return Math.sqrt(dx * dx + dy * dy);
  }

  var canvas = document.getElementById("display");
  var view = null;
  var presentation = null;


  var createAsset = T2D.assets.bindView(function currentView() { return view; });

  function targetVelocityForDifficulty(rng, difficulty, kind, radius) {
    if (kind !== "target" || difficulty < 2) return { vx: 0, vy: 0 };
    var speedX = TARGET_BASE_SPEED_PER_FIXED_STEP + difficulty * TARGET_DIFFICULTY_SPEED_PER_FIXED_STEP;
    var speedY = speedX * TARGET_VERTICAL_SPEED_RATIO;
    var speed = Math.sqrt(speedX * speedX + speedY * speedY);
    var maxSpeed = radius * TARGET_MAX_RADII_PER_SECOND * STEP_MS / 1000;
    var radiusScale = speed > maxSpeed ? maxSpeed / speed : 1;
    return {
      vx: rng.choice([-1, 1]) * speedX * radiusScale,
      vy: rng.choice([-1, 1]) * speedY * radiusScale,
    };
  }

  function Base2DAim() {
    this.defaults = {
      seed: DEFAULT_SEED,
      difficulty: DEFAULT_DIFFICULTY,
      maxDifficulty: MAX_DIFFICULTY,
    };
    this.urlConfig = Core.config.readUrl(this.defaults);
    this.mouse = {
      x: LOGIC_WIDTH / 2,
      y: LOGIC_HEIGHT / 2,
      dx: 0,
      dy: 0,
      left: false,
      right: false,
    };
    this.paused = false;
    this.runtime = {
      resetCount: 0,
      episodeCount: 0,
      lastResetMethod: null,
    };
    this.bestMetrics = {
      bestPrimaryScore: 0,
      bestPrecision: 0,
    };
    Core.terminal.initialize(this);
    this.bindInput();
    Core.lifecycle.bindResetKeys(this);
    this.beginEpisode({}, false);
    this.startLoop();
  }

  Base2DAim.prototype.normalizeOptions = function normalizeOptions(options) {
    return Core.config.normalizeOptions(options || {}, MAX_DIFFICULTY);
  };

  Base2DAim.prototype.resolveEpisodeConfig = function resolveEpisodeConfig(normalized) {
    return Core.config.mergeEpisode(this.urlConfig, normalized);
  };

  Base2DAim.prototype.beginEpisode = function beginEpisode(options, countAsReset, flags) {
    var episodeFlags = flags || {};
    var normalized = this.normalizeOptions(options || {});
    var resolved = this.resolveEpisodeConfig(normalized);

    Core.lifecycle.resetEpisode(this);
    this.currentConfig = Core.config.cloneEpisode(resolved);
    Core.terminal.clear(this, episodeFlags);
    Core.domains.beginEpisode(this, resolved, PERTURBATION_CONTRACT, DEFAULT_SEED);
    this.sceneLayout = Core.domains.sample(this, "scene", "layout", { template: "open" });
    this.targetBays = Gallery.buildBays(this.sceneLayout, LOGIC_WIDTH, LOGIC_HEIGHT,
      Core.domains.gameplayRng(this, "scene", "layout"));
    this.difficulty = resolved.difficulty;
    this.mode = resolved.autostart ? "playing" : "paused";
    this.targets = [];
    this.targetsCollected = 0;
    this.clicks = 0;
    this.misclicks = 0;
    this.precisionTotal = 0;
    this.precisionSamples = 0;
    Core.reward.resetEpisode(this);
    this.stepCount = 0;
    T2D.visuals.configure(this, resolved, {
      defaultAssetPack: Gallery.pack,
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
      view: view,
    });
    this.gameTimeMs = 0;
    this.nextFireTimeMs = 0;
    this.actionFireHeld = false;
    this.terminal = { isTerminal: false, outcome: null, reason: null };
    this.taskEvents = [];
    this.visualShots = [];
    this.lastAction = "reset";
    this.mouse.left = false;
    this.mouse.right = false;
    this.mouse.dx = 0;
    this.mouse.dy = 0;
    this.spawnTargetSet();

    this.runtime.episodeCount += 1;
    if (countAsReset !== false) this.runtime.resetCount += 1;
    this.runtime.lastResetMethod = countAsReset === false ? "init" : "inplace_reset";

    this.render();

    return {
      accepted: normalized,
      applied: {
        seed: this.seed,
        difficulty: this.difficulty,
        autostart: resolved.autostart,
        asset_pack: this.assetPack,
        perturb: resolved.perturb,
        perturb_entity_color: this.visualPerturbations.active.entityColor,

      },
      notes: [],
    };
  };

  Base2DAim.prototype.spawnTargetSet = function spawnTargetSet() {
    this.targets = [];
    var targetRadiusMin = Math.max(16, 38 - Math.floor(this.difficulty * 3));
    var targetRadiusMax = Math.max(targetRadiusMin + 2, 50 - Math.floor(this.difficulty * 2));
    this.targets.push(this.createTarget("target", targetRadiusMin, targetRadiusMax));
  };

  Base2DAim.prototype.createTarget = function createTarget(kind, minRadius, maxRadius) {
    var entitySpawnRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    var radius = entitySpawnRng.randint(minRadius, maxRadius + 1);
    var velocity = targetVelocityForDifficulty(entitySpawnRng, this.difficulty, kind, radius);
    var bay = this.targetBays[entitySpawnRng.randint(0, this.targetBays.length)];
    return {
      id: entitySpawnRng.randint(100000, 999999),
      kind: kind,
      x: entitySpawnRng.randint(bay.x + radius + 6, bay.x + bay.w - radius - 6),
      y: entitySpawnRng.randint(bay.y + radius + 6, bay.y + bay.h - radius - 6),
      bay: bay,
      radius: radius,
      vx: velocity.vx,
      vy: velocity.vy,
      age: 0,
    };
  };

  Base2DAim.prototype.addEvent = function addEvent(type, detail) {
    this.taskEvents.push({
      step: this.stepCount,
      type: type,
      detail: detail || null,
    });
    if (this.taskEvents.length > 24) this.taskEvents.shift();
  };

  Base2DAim.prototype.startPlaying = function startPlaying(actionLabel) {
    if (this.paused || this.mode !== "paused") return false;
    this.mode = "playing";
    this.lastAction = actionLabel || "start";

    this.render();
    return true;
  };

  Base2DAim.prototype.step = function step() {
    if (this.mode !== "playing") return false;
    this.stepCount += 1;
    this.gameTimeMs = this.stepCount * STEP_MS;
    this.updateTargets();
    if ((this.mouse.left || this.actionFireHeld) && this.gameTimeMs + 1e-6 >= this.nextFireTimeMs) {
      this.handleClick(0);
    }
    this.updateBestMetrics();
    return true;
  };

  Base2DAim.prototype.updateTargets = function updateTargets() {
    for (var i = 0; i < this.targets.length; i += 1) {
      var target = this.targets[i];
      target.age += 1;
      target.x += target.vx;
      target.y += target.vy;
      var bay = target.bay;
      var left = bay.x + target.radius + 6, right = bay.x + bay.w - target.radius - 6;
      var top = bay.y + target.radius + 6, bottom = bay.y + bay.h - target.radius - 6;
      if (target.x < left || target.x > right) {
        target.x = U.math.clamp(target.x, left, right); target.vx *= -1;
      }
      if (target.y < top || target.y > bottom) {
        target.y = U.math.clamp(target.y, top, bottom); target.vy *= -1;
      }
    }
  };

  Base2DAim.prototype.updateBestMetrics = function updateBestMetrics() {
    this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, this.getPrimaryScore());
    this.bestMetrics.bestPrecision = Math.max(this.bestMetrics.bestPrecision, this.getAveragePrecision());
  };

  Base2DAim.prototype.handleClick = function handleClick(button) {
    if (button !== 0) return;
    if (this.mode === "paused") this.startPlaying("mouse_left");
    if (this.mode !== "playing") return;

    this.nextFireTimeMs = this.gameTimeMs + FIRE_INTERVAL_MS;
    this.clicks += 1;
    this.recordVisualShot({ x: this.mouse.x, y: this.mouse.y });
    this.lastAction = "mouse_left";
    var hitIndex = -1;
    for (var i = this.targets.length - 1; i >= 0; i -= 1) {
      var target = this.targets[i];
      if (distanceXY(this.mouse.x, this.mouse.y, target.x, target.y) <= target.radius) {
        hitIndex = i;
        break;
      }
    }

    if (hitIndex < 0) {
      this.misclicks += 1;

      Core.reward.add(this, -rewardConfig.constants.misclickPenalty);
      this.addEvent("misclick", { x: finiteRoundedInt(this.mouse.x), y: finiteRoundedInt(this.mouse.y) });
      this.updateBestMetrics();

      this.render();
      return;
    }

    var hit = this.targets[hitIndex];
    var precision = 1 - U.math.clamp(distanceXY(this.mouse.x, this.mouse.y, hit.x, hit.y) / Math.max(1, hit.radius), 0, 1);

    this.precisionTotal += precision;
    this.precisionSamples += 1;
    this.targetsCollected += 1;
    Core.reward.add(this, rewardConfig.constants.correctClickReward + precision * rewardConfig.constants.centerPrecisionReward);
    this.addEvent("target_click", {
      target_id: hit.id,
      precision: Number(precision.toFixed(3)),
      x: finiteRoundedInt(hit.x),
      y: finiteRoundedInt(hit.y),
    });

    this.spawnTargetSet();
    this.updateBestMetrics();

    this.render();
  };

  Base2DAim.prototype.getAveragePrecision = function getAveragePrecision() {
    if (this.precisionSamples <= 0) return 0;
    return this.precisionTotal / this.precisionSamples;
  };

  Base2DAim.prototype.getPrimaryScore = function getPrimaryScore() {
    return rewardConfig.computePrimaryScore(this);
  };

  Base2DAim.prototype.canvasPoint = function canvasPoint(event) {
    return T2D.viewport.clientToLogic(canvas, event.clientX, event.clientY, LOGIC_WIDTH, LOGIC_HEIGHT);
  };

  Base2DAim.prototype.bindInput = function bindInput() {
    var self = this;

    window.addEventListener("keydown", function onKeyDown(event) {
      if (self.mode === "paused") {
        event.preventDefault();
        self.startPlaying("key");
      }
    });

    canvas.addEventListener("mousemove", function onMouseMove(event) {
      var point = self.canvasPoint(event);
      self.mouse.dx += point.x - self.mouse.x;
      self.mouse.dy += point.y - self.mouse.y;
      self.mouse.x = point.x;
      self.mouse.y = point.y;
    });

    canvas.addEventListener("mousedown", function onMouseDown(event) {
      var point = self.canvasPoint(event);
      self.mouse.x = point.x;
      self.mouse.y = point.y;
      if (event.button === 0) self.mouse.left = true;
      if (event.button === 2) self.mouse.right = true;
      self.handleClick(event.button);
      event.preventDefault();
    });

    window.addEventListener("mouseup", function onMouseUp(event) {
      if (event.button === 0) self.mouse.left = false;
      if (event.button === 2) self.mouse.right = false;
    });
    window.addEventListener("blur", function onBlur() {
      self.mouse.left = false;
      self.mouse.right = false;
    });

    canvas.addEventListener("contextmenu", function onContextMenu(event) {
      event.preventDefault();
    });
  };

  Base2DAim.prototype.advanceTime = function advanceTime(ms, render) {
    var duration = Number(ms);
    if (!Number.isFinite(duration) || duration <= 0) {

      if (render !== false) this.render();
      return this.getStatePayload();
    }
    if (this.paused) {

      if (render !== false) this.render();
      return this.getStatePayload();
    }
    var steps = Math.max(1, Math.round(duration / STEP_MS));
    for (var i = 0; i < steps; i += 1) {
      this.step();
    }
    this.mouse.dx = 0;
    this.mouse.dy = 0;

    if (render !== false) this.render();
    return this.getStatePayload();
  };

  Base2DAim.prototype.ensureSimulationRunner = function ensureSimulationRunner() {
    if (this.simulationRunner) return this.simulationRunner;
    var self = this;
    this.simulationRunner = Core.createFixedStepRunner({
      game: this,
      stepMs: STEP_MS,
      update: function update() { self.step(); },
      render: function render() {
        self.render();
      },
      isActive: function isActive() { return self.mode === "playing" && !self.paused; },
    });
    return this.simulationRunner;
  };

  Base2DAim.prototype.startLoop = function startLoop() {
    this.ensureSimulationRunner().start();
  };

  Base2DAim.prototype.pause = function pause() {
    Core.lifecycle.pause(this);

    this.render();
    return this.getPauseState();
  };

  Base2DAim.prototype.resume = function resume() {
    Core.lifecycle.resume(this);

    this.render();
    return this.getPauseState();
  };

  Base2DAim.prototype.getPauseState = function getPauseState() {
    return {
      ok: true,
      source: "game",
      paused: this.paused,
      runtime_paused: this.paused,
    };
  };

  Base2DAim.prototype.normalizeAction = function normalizeAction(action) {
    var id = Core.actions.readId(action, { lowercase: true });
    var dx = 0;
    var dy = 0;
    var controlRelativeMouse = id === "control" && Core.actions.readMouseMode(action) === "relative";
    if (id === "move_pointer" || controlRelativeMouse) {
      var normalizedDx = controlRelativeMouse
        ? Core.actions.readMouseNumber(action, "dx", 0)
        : Core.actions.readNumber(action, "dx", 0);
      var normalizedDy = controlRelativeMouse
        ? Core.actions.readMouseNumber(action, "dy", 0)
        : Core.actions.readNumber(action, "dy", 0);
      dx = T2D.input.relativeDeltaToLogic(view, normalizedDx, "x");
      dy = T2D.input.relativeDeltaToLogic(view, normalizedDy, "y");
    }
    var pointerClick = (id === "mouse_left" && Core.actions.readButton(action, "left") === "left")
      || (id === "control" && Core.actions.hasMouseClick(action, "left"));
    var pointerHold = id === "control" && Core.actions.hasMouseHold(action, "left");
    var pointerMove = id === "move_pointer" || controlRelativeMouse;
    return {
      id: id || "wait",
      dx: dx,
      dy: dy,
      move: pointerMove,
      click: !!pointerClick,
      hold: pointerHold,
      wait: !pointerMove && !pointerClick && !pointerHold,
    };
  };

  Base2DAim.prototype.applyAction = function applyAction(normalized) {
    Core.reward.resetStep(this);
    this.actionFireHeld = !!normalized.hold;
    if (normalized.move) {
      var nextX = this.mouse.x + normalized.dx;
      var nextY = this.mouse.y + normalized.dy;
      var pointer = T2D.input.clampPointToVisibleBounds(view, nextX, nextY, LOGIC_WIDTH, LOGIC_HEIGHT);
      this.mouse.dx += pointer.x - this.mouse.x;
      this.mouse.dy += pointer.y - this.mouse.y;
      this.mouse.x = pointer.x;
      this.mouse.y = pointer.y;
      this.lastAction = normalized.click ? "fire" : normalized.wait ? "wait" : "move_pointer";
    } else if (normalized.click) {
      this.lastAction = "fire";
    } else if (normalized.wait) {
      this.lastAction = "wait";
    }
    if (normalized.click || (normalized.hold && this.gameTimeMs + 1e-6 >= this.nextFireTimeMs)) {
      this.handleClick(0);
    } else if (this.mode === "paused") {
      this.startPlaying("step_action");
    }
  };

  Base2DAim.prototype.advanceSimulation = function advanceSimulation(ms) {
    var state = this.advanceTime(ms, false);
    this.actionFireHeld = false;
    return state;
  };

  Base2DAim.prototype.buildStepInfo = function buildStepInfo(state, stepOptions, normalized) {
    var info = this.buildInfo(state);
    info.action = { type: "game_step_action", id: normalized.id, args: normalized.args || {} };
    info.durationMs = stepOptions.durationMs;
    info.source = stepOptions.source;
    return info;
  };

  Base2DAim.prototype.resetGym = function resetGym(options) {
    this.beginEpisode(options || {}, true);
    var state = this.getStatePayload();
    return {
      observation: this.getObservation(),
      reward: 0,
      done: false,
      info: this.buildInfo(state),
    };
  };

  Base2DAim.prototype.getObservation = function getObservation() {
    return {
      type: "rgb_screenshot",
      width: DISPLAY_WIDTH,
      height: DISPLAY_HEIGHT,
      text: JSON.parse(this.renderGameToText()),
    };
  };

  Base2DAim.prototype.buildInfo = function buildInfo(state) {
    return {
      score: state.metrics.primary_score,
      time_steps: state.metrics.step_count,
      collisions: 0,
      misclicks: state.metrics.misclicks,
      targets_collected: state.metrics.targets_collected,
      task_events: this.taskEvents.slice(),
    };
  };

  Base2DAim.prototype.targetPayload = function targetPayload() {
    return this.targets.map(function (target) {
      return {
        id: target.id,
        type: target.kind,
        bay_id: target.bay.id,
        x: finiteRoundedInt(target.x),
        y: finiteRoundedInt(target.y),
        radius: finiteRoundedInt(target.radius),
        vx: U.math.finiteNumber(target.vx),
        vy: U.math.finiteNumber(target.vy),
      };
    });
  };

  Base2DAim.prototype.getVisualPayload = function getVisualPayload() {
    return T2D.visuals.sync(this);
  };

  Base2DAim.prototype.buildStatePayload = function buildStatePayload(isTerminalSnapshot) {
    T2D.visuals.sync(this);
    var viewport = T2D.viewport.state(this, LOGIC_WIDTH, LOGIC_HEIGHT);
    return {
      schemaVersion: "2.0",
      gameId: GAME_ID,
      seed: this.seed,
      timestampMs: Date.now(),
      gameTimeMs: U.math.finiteNumber(this.gameTimeMs),
      status: isTerminalSnapshot ? "terminal" : this.mode,
      paused: this.mode === "paused" || this.paused,
      runtime_paused: this.paused,
      is_actionable: !isTerminalSnapshot && (this.mode === "paused" || this.mode === "playing"),
      terminal: {
        isTerminal: isTerminalSnapshot ? this.terminal.isTerminal : false,
        outcome: isTerminalSnapshot ? this.terminal.outcome : null,
        reason: isTerminalSnapshot ? this.terminal.reason : null,
      },
      game_state: {
        score: this.getPrimaryScore(),
        level: null,
        player: {
          cursor_x: finiteRoundedInt(this.mouse.x),
          cursor_y: finiteRoundedInt(this.mouse.y),
          mouse_left: this.mouse.left,
        },
        environment: {
          phase: isTerminalSnapshot ? "terminal" : this.mode,
          viewport_width: viewport.width,
          viewport_height: viewport.height,
          logic_width: LOGIC_WIDTH,
          logic_height: LOGIC_HEIGHT,
          difficulty: this.difficulty,
          scene_version: Gallery.version,
          asset_pack: this.assetPack,
          asset: T2D.visuals.assetPayload(this),
          target_count: this.targets.length,
          scene_layout: this.sceneLayout,
          target_bays: this.targetBays,
          perturb_active: Core.perturbations.isActive(this),
          visual_perturbations: this.getVisualPayload(),
        },
        entities: this.targetPayload(),
      },
      metrics: {
        env_reward_step: this.envRewardStep,
        env_reward_episode: this.envRewardEpisode,
        primary_positive_score: rewardConfig.computePrimaryPositiveScore(this),
        primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(this),
        primary_score: this.getPrimaryScore(),
        targets_collected: this.targetsCollected,
        clicks: this.clicks,
        misclicks: this.misclicks,
        precision_total: this.precisionTotal,
        average_precision: this.getAveragePrecision(),
        best_primary_score: this.bestMetrics.bestPrimaryScore,
        best_precision: this.bestMetrics.bestPrecision,
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
        visible_status: this.mode,
      },
    };
  };

  Base2DAim.prototype.getStatePayload = function getStatePayload() {
    return this.buildStatePayload(false);
  };

  Base2DAim.prototype.renderGameToText = function renderGameToText() {
    return JSON.stringify({
      coordinate_system: "origin=(0,0) top-left, +x right, +y down, logic_size="
        + LOGIC_WIDTH + "x" + LOGIC_HEIGHT,
      status: this.mode,
      cursor: {
        x: finiteRoundedInt(this.mouse.x),
        y: finiteRoundedInt(this.mouse.y),
      },
      targets: this.targetPayload(),
      rewards: {
        env_reward_step: this.envRewardStep,
        env_reward_episode: this.envRewardEpisode,
        primary_positive_score: rewardConfig.computePrimaryPositiveScore(this),
        primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(this),
        primary_score: this.getPrimaryScore(),
      },
      progress: {
        targets_collected: this.targetsCollected,
        precision_total: this.precisionTotal,
        average_precision: this.getAveragePrecision(),
        misclicks: this.misclicks,
      },
      difficulty: this.difficulty,
      visual_perturbations: this.getVisualPayload(),
    });
  };


  Base2DAim.prototype.recordVisualShot = function recordVisualShot(event) {
    this.visualShots.push(Object.assign({ timeMs: this.gameTimeMs }, event));
    if (this.visualShots.length > 8) this.visualShots.shift();
  };

  Base2DAim.prototype.render = function render() {
    T2D.visuals.sync(this);
    presentation.render(this);
    view.render();
    if (this.infoPanel) this.infoPanel.update();
  };

  Base2DAim.prototype.resetFromAPI = function resetFromAPI(options) {
    return this.beginEpisode(options || {}, true);
  };

  async function start() {
    await T2D.assets.preload(Gallery.pack, ASSET_REQUIREMENTS);
    view = await T2D.createStage(canvas, { width: LOGIC_WIDTH, height: LOGIC_HEIGHT, background: 0xffffff });
    if (!view) throw new Error("Three.js 2D engine unavailable");
    presentation = Gallery.create(view, createAsset, LOGIC_WIDTH, LOGIC_HEIGHT);
    var game = new Base2DAim();
    Core.createRuntime({
      game: game,
      presentation: {
        title: "2D Aiming",
        controls: "Move mouse to aim; left-click to shoot. Aim near each target's center for better precision.",
        read: function readPresentation() {
          return {
            status: game.paused ? "paused" : game.mode,
            primaryScore: game.getPrimaryScore(),
            stepReward: game.envRewardStep,
            episodeReward: game.envRewardEpisode,
            difficulty: game.difficulty,
            seed: game.seed,
            perturbation: Core.perturbations.label(game),
            details: [["Targets hit", game.targetsCollected], ["Precision", Math.round(game.getAveragePrecision() * 100) + "%"],
              ["Misses", game.misclicks], ["Clicks", game.clicks]],
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
