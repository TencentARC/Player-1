(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var T2D = window.BaseGameletThree2D;
  var Scene = window.GardenCircuitScene;
  var rewardConfig = window.Base2DDrivePlanarWasdRewardConfig;
  var GAME_ID = "base_2d_drive_planar_wasd";
  var PERTURBATION_CONTRACT = Core.perturbations.defineContract({
    game_id: GAME_ID,
    control_response: {
      drive_scale: Core.controlResponse.ranges.drive_scale,
    },
    capabilities: {
      appearance: ["palette", "background", "assets"],
      camera: ["projection"],
      scene: ["layout"],
    },
    samplers: {
      camera: { projection: T2D.camera.projectionSampler },
      scene: { layout: Core.perturbations.templateSampler("grand-circuit", ["compact-circuit", "long-circuit", "club-circuit"]) },
    },
    validators: {
      camera: { projection: T2D.camera.projectionValidator },
      scene: { layout: Core.perturbations.templateValidator(["grand-circuit", "compact-circuit", "long-circuit", "club-circuit"]) },
    },
  });
  var LOGIC_HEIGHT = 900;
  var LOGIC_WIDTH = T2D.viewport.widthForHeight(LOGIC_HEIGHT);
  var DISPLAY_WIDTH = T2D.viewport.baseWidth;
  var DISPLAY_HEIGHT = T2D.viewport.baseHeight;
  var STEP_MS = 1000 / 60;
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 5;
  var ASSET_REQUIREMENTS = Scene.assets;
  var ROUTE_CHECKPOINT_COUNT = 19;
  var TRACK_CENTER_JITTER = 3;
  var TRACK_HALF_WIDTH = Math.floor(LOGIC_WIDTH / 2) - 70;
  var TRACK_HALF_HEIGHT = 375;
  var CAR_RADIUS = 16;
  var ROAD_WIDTH = 108;
  var TRACK_SAMPLE_SPACING = 4;
  var TRACK_MIN_TURN_RADIUS = 50;
  var TRACK_MIN_SEPARATION = ROAD_WIDTH + 12;
  var TRACK_BUILD_ATTEMPTS = 24;
  var TRACK_CONTROL_SMOOTHING = 0;
  var TRACK_SMOOTHING_PASSES = 0;
  var ROAD_HALF_WIDTH = ROAD_WIDTH / 2;
  var ROAD_DRIVABLE_HALF_WIDTH = ROAD_HALF_WIDTH - CAR_RADIUS * 0.8;
  var CHECKPOINT_LINE_HALF_WIDTH = ROAD_HALF_WIDTH;
  var FENCE_WIDTH = 8;
  var FENCE_COLLISION_INSET = 0.5;
  var FENCE_CONTACT_RELEASE_INSET = CAR_RADIUS * 0.25;
  var FENCE_TANGENT_RETENTION = 0.5;
  var FENCE_IMPACT_TANGENT_TRANSFER = 0.25;
  var FENCE_NORMAL_BOUNCE = 0.35;
  var DIRECT_VELOCITY_RETENTION = 0.8;
  var DIRECT_BASE_ACCELERATION = 4000;
  var DIRECT_ACCELERATION_PER_DIFFICULTY = 1000;
  var DIRECT_BASE_MAX_SPEED = 400;
  var DIRECT_MAX_SPEED_PER_DIFFICULTY = 100;
  var VISUAL_TURN_RATE = 18;

  // Smooth harmonic profiles preserve explicit track topology without point jitter.
  var TRACK_CONTROL_COUNT = 48;
  var TRACK_ARCHETYPES = Object.freeze([
    Object.freeze({
      id: "ess",
      coefficients: Object.freeze([
        0.000367, 0.161220, -0.306228, 0.107462,
        0.103836, 0.014037, -0.023046, 0.160220,
        -0.011443, 0.072846, -0.144094, 0.112325,
        -0.052941, -0.013478, -0.057283, -0.069792,
      ]),
    }),
    Object.freeze({
      id: "hairpin",
      coefficients: Object.freeze([
        -0.171534, 0.066383, -0.028745, 0.303892,
        0.031206, -0.016264, -0.061828, 0.043643,
        0.004208, -0.018726, 0.017531, -0.132326,
        0.013030, 0.043540, -0.030138, 0.058691,
      ]),
    }),
    Object.freeze({
      id: "mixed",
      coefficients: Object.freeze([
        0.135631, -0.107693, 0.303983, -0.141448,
        -0.016348, -0.115708, 0.198965, 0.095789,
        -0.000469, -0.038791, -0.052853, 0.060942,
        -0.017839, -0.030305, 0.004591, 0.075006,
      ]),
    }),
    Object.freeze({
      id: "chicane",
      coefficients: Object.freeze([
        0.099390, 0.307691, -0.002155, 0.098886,
        0.029946, -0.069751, 0.024505, -0.061197,
        0.158471, 0.069602, -0.013667, 0.145692,
        0.051207, 0.063141, -0.018490, -0.030336,
      ]),
    }),
  ]);

  function numberTrackOption(options, name, fallback) {
    return U.math.finiteNumber(options[name], fallback);
  }

  function turnTowardAngle(currentAngle, targetAngle, maxTurn) {
    var angleDelta = U.math.normalizeAngle(targetAngle - currentAngle);
    return U.math.normalizeAngle(currentAngle + U.math.clamp(angleDelta, -maxTurn, maxTurn));
  }

  function buildArchetypeControls(archetype, rng, variationRetention) {
    var harmonicJitter = [0.012, 0.009, 0.006, 0.0035];
    var coefficients = variationRetention <= 0
      ? archetype.coefficients
      : archetype.coefficients.map(function varyCoefficient(value, index) {
        var harmonicIndex = Math.floor(index / 4);
        return value + rng.range(-harmonicJitter[harmonicIndex], harmonicJitter[harmonicIndex]) * variationRetention;
      });
    var controls = [];
    for (var index = 0; index < TRACK_CONTROL_COUNT; index += 1) {
      var angle = index / TRACK_CONTROL_COUNT * Math.PI * 2;
      var x = Math.cos(angle);
      var y = Math.sin(angle);
      for (var harmonic = 2; harmonic <= 5; harmonic += 1) {
        var offset = (harmonic - 2) * 4;
        x += coefficients[offset] * Math.cos(harmonic * angle)
          + coefficients[offset + 1] * Math.sin(harmonic * angle);
        y += coefficients[offset + 2] * Math.cos(harmonic * angle)
          + coefficients[offset + 3] * Math.sin(harmonic * angle);
      }
      controls.push({ x: x, y: y });
    }
    return controls;
  }

  function fitTrackControls(controls, options) {
    var minX = Infinity;
    var maxX = -Infinity;
    var minY = Infinity;
    var maxY = -Infinity;
    controls.forEach(function measureControl(point) {
      minX = Math.min(minX, point.x);
      maxX = Math.max(maxX, point.x);
      minY = Math.min(minY, point.y);
      maxY = Math.max(maxY, point.y);
    });
    var profileCenterX = (minX + maxX) * 0.5;
    var profileCenterY = (minY + maxY) * 0.5;
    var profileHalfX = Math.max(1e-9, (maxX - minX) * 0.5);
    var profileHalfY = Math.max(1e-9, (maxY - minY) * 0.5);
    var cosRotation = Math.cos(options.rotation);
    var sinRotation = Math.sin(options.rotation);
    return controls.map(function placeControl(point) {
      var normalizedX = (point.x - profileCenterX) / profileHalfX;
      var normalizedY = (point.y - profileCenterY) / profileHalfY;
      var shearedX = normalizedX + normalizedY * options.shearX;
      var shearedY = normalizedY + normalizedX * options.shearY;
      var localX = shearedX * options.halfWidth * options.scaleX * options.mirrorX;
      var localY = shearedY * options.halfHeight * options.scaleY * options.mirrorY;
      return {
        x: options.centerX + localX * cosRotation - localY * sinRotation,
        y: options.centerY + localX * sinRotation + localY * cosRotation,
      };
    });
  }

  function buildPlanarTrack(rng, options) {
    options = options || {};
    if (!rng || typeof rng.range !== "function" || typeof rng.next !== "function") {
      throw new Error("buildPlanarTrack requires BaseGameletCommon.Rng");
    }
    var centerX = numberTrackOption(options, "centerX", 320);
    var centerY = numberTrackOption(options, "centerY", 320);
    var halfWidth = Math.max(1, numberTrackOption(options, "halfWidth", 270));
    var halfHeight = Math.max(1, numberTrackOption(options, "halfHeight", 250));
    var scaleVariation = U.math.clamp(numberTrackOption(options, "scaleVariation", 0.035), 0, 0.2);
    var rotationRange = Math.max(0, numberTrackOption(options, "rotationRange", 0.025));
    var orientationCount = Math.max(1, Math.round(numberTrackOption(options, "orientationCount", 4)));
    var shearVariation = U.math.clamp(numberTrackOption(options, "shearVariation", 0.045), 0, 0.12);
    var attempts = Math.max(1, Math.round(numberTrackOption(options, "buildAttempts", TRACK_BUILD_ATTEMPTS)));
    var requiredTurnRadius = numberTrackOption(options, "minTurnRadius", TRACK_MIN_TURN_RADIUS);
    var requiredSeparation = numberTrackOption(options, "minSeparation", TRACK_MIN_SEPARATION);
    var archetypeIndex = rng.randint(0, TRACK_ARCHETYPES.length);
    var archetype = TRACK_ARCHETYPES[archetypeIndex];
    var best = null;

    for (var attempt = 0; attempt < attempts; attempt += 1) {
      var variationRetention = 1 - attempt / Math.max(1, attempts - 1);
      var targetHalfX = 0.9 * (1 + rng.range(-scaleVariation, scaleVariation) * variationRetention);
      var targetHalfY = 0.94 * (1 + rng.range(-scaleVariation, scaleVariation) * variationRetention);
      var mirrorX = rng.next() < 0.5 ? -1 : 1;
      var mirrorY = rng.next() < 0.5 ? -1 : 1;
      var rotation = rng.randint(0, orientationCount) * Math.PI * 2 / orientationCount
        + rng.range(-rotationRange, rotationRange) * variationRetention;
      var shearX = rng.range(-shearVariation, shearVariation) * variationRetention;
      var shearY = rng.range(-shearVariation, shearVariation) * variationRetention;
      var vertices = fitTrackControls(buildArchetypeControls(archetype, rng, variationRetention), {
        centerX: centerX,
        centerY: centerY,
        halfWidth: halfWidth,
        halfHeight: halfHeight,
        scaleX: targetHalfX,
        scaleY: targetHalfY,
        mirrorX: mirrorX,
        mirrorY: mirrorY,
        rotation: rotation,
        shearX: shearX,
        shearY: shearY,
      });
      var candidate = U.track.buildClosedSpline(vertices, {
        spacing: numberTrackOption(options, "spacing", TRACK_SAMPLE_SPACING),
        alpha: 0.5,
        controlSmoothing: numberTrackOption(options, "controlSmoothing", TRACK_CONTROL_SMOOTHING),
        smoothingPasses: numberTrackOption(options, "smoothingPasses", TRACK_SMOOTHING_PASSES),
        preserveControlBounds: true,
        minTurnRadius: requiredTurnRadius,
        minSeparation: requiredSeparation,
      });
      var validation = candidate.validation;
      var radiusDeficit = Math.max(0, requiredTurnRadius - validation.minTurnRadius);
      var separationDeficit = Math.max(0, requiredSeparation - validation.minSeparation);
      var score = validation.selfIntersections * 10000 + radiusDeficit * 10 + separationDeficit;
      if (!best || score < best.score) best = { route: candidate, score: score, attempt: attempt + 1 };
      if (validation.valid) break;
    }

    if (!best.route.validation.valid) {
      // Compressed layouts can make one profile too tight. Try the existing profiles without consuming more RNG.
      for (var fallbackIndex = 0; fallbackIndex < TRACK_ARCHETYPES.length; fallbackIndex += 1) {
        var fallbackArchetype = TRACK_ARCHETYPES[(archetypeIndex + fallbackIndex) % TRACK_ARCHETYPES.length];
        var fallbackVertices = fitTrackControls(buildArchetypeControls(fallbackArchetype, rng, 0), {
          centerX: centerX,
          centerY: centerY,
          halfWidth: halfWidth,
          halfHeight: halfHeight,
          scaleX: 0.9,
          scaleY: 0.94,
          mirrorX: 1,
          mirrorY: 1,
          rotation: 0,
          shearX: 0,
          shearY: 0,
        });
        var fallbackRoute = U.track.buildClosedSpline(fallbackVertices, {
          spacing: numberTrackOption(options, "spacing", TRACK_SAMPLE_SPACING),
          alpha: 0.5,
          controlSmoothing: numberTrackOption(options, "controlSmoothing", TRACK_CONTROL_SMOOTHING),
          smoothingPasses: numberTrackOption(options, "smoothingPasses", TRACK_SMOOTHING_PASSES),
          preserveControlBounds: true,
          minTurnRadius: requiredTurnRadius,
          minSeparation: requiredSeparation,
        });
        if (fallbackRoute.validation.valid) {
          archetype = fallbackArchetype;
          best = { route: fallbackRoute, score: 0, attempt: attempts + fallbackIndex + 1 };
          break;
        }
      }
      if (!best.route.validation.valid) {
        throw new Error("Spline track constraints are incompatible with the configured viewport");
      }
    }

    var route = best.route;
    var routeValidation = route.validation;
    var controlPoints = route.controlPoints;
    if (rng.next() < 0.5) route.reverse();
    if (options.randomizeStart !== false) {
      route = U.track.randomizeClosedStart(rng, route, {
        searchRadius: numberTrackOption(options, "startSearchRadius", 32),
        searchStep: numberTrackOption(options, "startSearchStep", 4),
        tangentSpan: numberTrackOption(options, "startTangentSpan", 18),
        forwardStraightDistanceMin: numberTrackOption(options, "startStraightDistanceMin", 0),
        forwardStraightDistanceMax: numberTrackOption(options, "startStraightDistanceMax", 0),
        forwardStraightSearchStep: numberTrackOption(options, "startStraightSearchStep", 4),
        forwardStraightSamples: numberTrackOption(options, "startStraightSamples", 4),
        forwardStraightMaxTurn: numberTrackOption(options, "startStraightMaxTurn", 0.08),
      });
    }
    route.validation = routeValidation;
    route.controlPoints = controlPoints;
    route.generationAttempts = best.attempt;
    route.archetype = archetype.id;
    return route;
  }

  var canvas = document.getElementById("display");
  var view = null;
  var presentation = null;


  var createAsset = T2D.assets.bindView(function currentView() { return view; });

  function Base2DDrivePlanarWasd() {
    this.defaults = {
      seed: DEFAULT_SEED,
      difficulty: DEFAULT_DIFFICULTY,
      maxDifficulty: MAX_DIFFICULTY,
    };
    this.urlConfig = Core.config.readUrl(this.defaults);
    this.controls = { left: false, right: false, up: false, down: false };
    this.paused = false;
    this.runtime = { resetCount: 0, episodeCount: 0, lastResetMethod: null };
    Core.terminal.initialize(this);
    this.bindInput();
    Core.lifecycle.bindResetKeys(this);
    this.beginEpisode({}, false);
    this.startLoop();
  }

  Base2DDrivePlanarWasd.prototype.beginEpisode = function beginEpisode(options, countReset, flags) {
    var episodeFlags = flags || {};
    var normalized = Core.config.normalizeOptions(options || {}, MAX_DIFFICULTY);
    var config = Core.config.mergeEpisode(this.urlConfig, normalized);
    Core.lifecycle.resetEpisode(this, { controls: { up: false, down: false, left: false, right: false } });
    this.currentConfig = Core.config.cloneEpisode(config);
    Core.terminal.clear(this, episodeFlags);
    Core.domains.beginEpisode(this, config, PERTURBATION_CONTRACT, DEFAULT_SEED);
    this.difficulty = config.difficulty;
    this.level = this.buildLevel();
    this.x = this.level.start.x;
    this.y = this.level.start.y;
    this.vx = 0;
    this.vy = 0;
    this.angle = this.level.start.angle;
    this.checkpointsPassed = 0;
    this.routeCheckpointIndex = 0;
    this.routesCompleted = 0;
    this.bestCheckpointDistance = this.distanceToCheckpoint();
    this.distanceDriven = 0;
    this.collisions = 0;
    this.offRoadHits = 0;
    this.outOfBounds = 0;
    this.fenceContact = false;
    this.stepCount = 0;
    this.gameTimeMs = 0;
    Core.reward.resetEpisode(this);
    this.lastAction = "reset";
    this.mode = config.autostart ? "playing" : "paused";
    this.terminal = { isTerminal: false, outcome: null, reason: null };
    this.controls = { left: false, right: false, up: false, down: false };
    if (countReset) this.runtime.resetCount += 1;
    this.runtime.episodeCount += 1;
    this.runtime.lastResetMethod = countReset ? "inplace_reset" : "init";
    T2D.visuals.configure(this, config, {
      defaultAssetPack: Scene.pack,
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
      view: view,
    });
    presentation.prepare(this);
    this.render();
    return { accepted: normalized, applied: config, notes: [] };
  };

  Base2DDrivePlanarWasd.prototype.buildLevel = function buildLevel() {
    var layoutRng = Core.domains.gameplayRng(this, "scene", "layout");
    var layout = Core.domains.sample(this, "scene", "layout", { template: "grand-circuit" });
    var scale = {
      "grand-circuit": [1, 1], "compact-circuit": [0.87, 0.9],
      "long-circuit": [1, 0.86], "club-circuit": [0.92, 0.98],
    }[layout.template];
    var route = buildPlanarTrack(layoutRng, {
      centerX: LOGIC_WIDTH / 2 + layoutRng.range(-TRACK_CENTER_JITTER, TRACK_CENTER_JITTER),
      centerY: LOGIC_HEIGHT / 2 + layoutRng.range(-TRACK_CENTER_JITTER, TRACK_CENTER_JITTER),
      halfWidth: TRACK_HALF_WIDTH * scale[0],
      halfHeight: TRACK_HALF_HEIGHT * scale[1],
      orientationCount: 2,
      spacing: TRACK_SAMPLE_SPACING,
      minTurnRadius: TRACK_MIN_TURN_RADIUS,
      minSeparation: TRACK_MIN_SEPARATION,
      buildAttempts: TRACK_BUILD_ATTEMPTS,
      controlSmoothing: TRACK_CONTROL_SMOOTHING,
      smoothingPasses: TRACK_SMOOTHING_PASSES,
    });
    var start = {
      x: route[0].x,
      y: route[0].y,
      angle: Math.atan2(route[1].y - route[0].y, route[1].x - route[0].x),
    };
    var routeLength = U.track.polylineLength(route);
    var checkpointSpacing = routeLength / ROUTE_CHECKPOINT_COUNT;
    var checkpoints = [];
    for (var c = 0; c < ROUTE_CHECKPOINT_COUNT; c += 1) {
      var routeDistance = checkpointSpacing * (c + 1);
      var sample = U.track.sampleAtDistance(route, routeDistance);
      checkpoints.push({
        id: "checkpoint_" + c,
        x: sample.x,
        y: sample.y,
        tangentAngle: sample.angle,
        lineHalfWidth: CHECKPOINT_LINE_HALF_WIDTH,
        routeDistance: routeDistance,
        passed: false,
      });
    }
    return {
      template: layout.template,
      start: start,
      route: route,
      routeLength: routeLength,
      trackValidation: route.validation,
      trackGenerationAttempts: route.generationAttempts,
      trackArchetype: route.archetype,
      roadWidth: ROAD_WIDTH,
      drivableHalfWidth: ROAD_DRIVABLE_HALF_WIDTH,
      checkpoints: checkpoints,
      obstacles: [],
      velocityRetention: DIRECT_VELOCITY_RETENTION,
      maxSpeed: (DIRECT_BASE_MAX_SPEED + this.difficulty * DIRECT_MAX_SPEED_PER_DIFFICULTY) * this.controlResponse.applied.drive_scale,
      acceleration: (DIRECT_BASE_ACCELERATION + this.difficulty * DIRECT_ACCELERATION_PER_DIFFICULTY) * this.controlResponse.applied.drive_scale,
    };
  };

  Base2DDrivePlanarWasd.prototype.bindInput = function bindInput() {
    var self = this;
    function setKey(event, value) {
      var key = event.key;
      var handled = true;
      if (key === "ArrowLeft" || key === "a" || key === "A") self.controls.left = value;
      else if (key === "ArrowRight" || key === "d" || key === "D") self.controls.right = value;
      else if (key === "ArrowUp" || key === "w" || key === "W") self.controls.up = value;
      else if (key === "ArrowDown" || key === "s" || key === "S") self.controls.down = value;
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

  Base2DDrivePlanarWasd.prototype.ensureSimulationRunner = function ensureSimulationRunner() {
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

  Base2DDrivePlanarWasd.prototype.startLoop = function startLoop() {
    this.ensureSimulationRunner().start();
  };

  Base2DDrivePlanarWasd.prototype.pause = function pause() {
    var pauseState = Core.lifecycle.pause(this);
    this.render();
    return pauseState;
  };

  Base2DDrivePlanarWasd.prototype.resume = function resume() {
    var pauseState = Core.lifecycle.resume(this);
    this.render();
    return pauseState;
  };

  Base2DDrivePlanarWasd.prototype.speed = function speed() {
    return Math.sqrt(this.vx * this.vx + this.vy * this.vy);
  };

  Base2DDrivePlanarWasd.prototype.resolveFenceCollision = function resolveFenceCollision(roadInfo) {
    var normalX = this.x - roadInfo.x;
    var normalY = this.y - roadInfo.y;
    var normalLength = Math.sqrt(normalX * normalX + normalY * normalY);
    if (normalLength <= 1e-6) {
      this.vx *= FENCE_TANGENT_RETENTION;
      this.vy *= FENCE_TANGENT_RETENTION;
      return;
    }
    normalX /= normalLength;
    normalY /= normalLength;
    var route = this.level.route;
    var segmentIndex = Math.max(0, Math.min(
      route.length - 2,
      Math.floor(U.math.finiteNumber(roadInfo.segmentIndex, 0))
    ));
    var tangentX = route[segmentIndex + 1].x - route[segmentIndex].x;
    var tangentY = route[segmentIndex + 1].y - route[segmentIndex].y;
    var tangentLength = Math.sqrt(tangentX * tangentX + tangentY * tangentY);
    if (tangentLength <= 1e-6) {
      tangentX = -normalY;
      tangentY = normalX;
    } else {
      tangentX /= tangentLength;
      tangentY /= tangentLength;
    }
    var normalSpeed = this.vx * normalX + this.vy * normalY;
    var outwardSpeed = Math.max(0, normalSpeed);
    var inwardSpeed = Math.max(0, -normalSpeed);
    var signedTangentSpeed = this.vx * tangentX + this.vy * tangentY;
    var tangentDirection = signedTangentSpeed < -1e-6 ? -1 : 1;
    var redirectedTangentSpeed = Math.abs(signedTangentSpeed) * FENCE_TANGENT_RETENTION
      + outwardSpeed * FENCE_IMPACT_TANGENT_TRANSFER;
    var redirectedInwardSpeed = outwardSpeed > 0
      ? outwardSpeed * FENCE_NORMAL_BOUNCE
      : inwardSpeed * FENCE_TANGENT_RETENTION;
    this.vx = tangentX * tangentDirection * redirectedTangentSpeed - normalX * redirectedInwardSpeed;
    this.vy = tangentY * tangentDirection * redirectedTangentSpeed - normalY * redirectedInwardSpeed;
    var correctedDistance = Math.max(0, this.level.drivableHalfWidth - FENCE_COLLISION_INSET);
    this.x = roadInfo.x + normalX * correctedDistance;
    this.y = roadInfo.y + normalY * correctedDistance;
  };

  Base2DDrivePlanarWasd.prototype.currentCheckpoint = function currentCheckpoint() {
    return this.level.checkpoints[this.routeCheckpointIndex] || null;
  };

  Base2DDrivePlanarWasd.prototype.distanceToCheckpoint = function distanceToCheckpoint() {
    var checkpoint = this.currentCheckpoint();
    if (!checkpoint) return 0;
    var line = U.track.crossSection(checkpoint, checkpoint.tangentAngle, checkpoint.lineHalfWidth);
    return U.geometry2d.distanceToSegment({ x: this.x, y: this.y }, line.a, line.b);
  };

  Base2DDrivePlanarWasd.prototype.roadDistance = function roadDistance() {
    return U.track.distanceToPolyline({ x: this.x, y: this.y }, this.level.route).distance;
  };

  Base2DDrivePlanarWasd.prototype.addReward = function addReward(value) {
    return Core.reward.add(this, value);
  };

  Base2DDrivePlanarWasd.prototype.startNextRoute = function startNextRoute() {
    this.level = this.buildLevel();
    this.x = this.level.start.x;
    this.y = this.level.start.y;
    this.vx = 0;
    this.vy = 0;
    this.angle = this.level.start.angle;
    this.routeCheckpointIndex = 0;
    this.fenceContact = false;
    this.bestCheckpointDistance = this.distanceToCheckpoint();
    this.lastAction = "route_completed";
    presentation.prepare(this);
  };

  Base2DDrivePlanarWasd.prototype.update = function update(dt) {
    if (this.terminal.isTerminal || this.mode !== "playing") return;
    Core.reward.resetStep(this);
    var beforeDistance = this.distanceToCheckpoint();
    var inputX = (this.controls.right ? 1 : 0) - (this.controls.left ? 1 : 0);
    var inputY = (this.controls.down ? 1 : 0) - (this.controls.up ? 1 : 0);
    var inputMagnitude = Math.sqrt(inputX * inputX + inputY * inputY);
    var speed = this.speed();
    if (inputMagnitude > 0) {
      inputX /= inputMagnitude;
      inputY /= inputMagnitude;
      this.angle = turnTowardAngle(this.angle, Math.atan2(inputY, inputX), VISUAL_TURN_RATE * dt);
      this.vx += inputX * this.level.acceleration * dt;
      this.vy += inputY * this.level.acceleration * dt;
    }
    this.vx *= this.level.velocityRetention;
    this.vy *= this.level.velocityRetention;
    speed = this.speed();
    if (speed > this.level.maxSpeed) {
      var scale = this.level.maxSpeed / speed;
      this.vx *= scale;
      this.vy *= scale;
    }
    var oldX = this.x;
    var oldY = this.y;
    this.x += this.vx * dt;
    this.y += this.vy * dt;
    this.gameTimeMs += dt * 1000;
    this.stepCount += 1;
    this.lastAction = [
      inputY < 0 ? "up" : inputY > 0 ? "down" : null,
      inputX < 0 ? "left" : inputX > 0 ? "right" : null,
    ].filter(Boolean).join("+") || "coast";

    var roadInfo = U.track.distanceToPolyline({ x: this.x, y: this.y }, this.level.route);
    var hitFence = roadInfo.distance > this.level.drivableHalfWidth;
    var distanceMoved = 0;
    if (hitFence) {
      this.resolveFenceCollision(roadInfo);
      distanceMoved = Math.sqrt(Math.pow(this.x - oldX, 2) + Math.pow(this.y - oldY, 2));
      this.distanceDriven += distanceMoved;
      if (!this.fenceContact) {
        this.collisions += 1;
        this.offRoadHits += 1;
        this.outOfBounds += 1;
        this.addReward(-rewardConfig.constants.roadCollisionPenalty);
      }
      this.fenceContact = true;
    } else {
      this.fenceContact = this.fenceContact
        && roadInfo.distance >= this.level.drivableHalfWidth - FENCE_CONTACT_RELEASE_INSET;
      distanceMoved = Math.sqrt(Math.pow(this.x - oldX, 2) + Math.pow(this.y - oldY, 2));
      this.distanceDriven += distanceMoved;
    }

    var afterDistance = this.distanceToCheckpoint();
    if (!Number.isFinite(this.bestCheckpointDistance)) this.bestCheckpointDistance = beforeDistance;
    if (!hitFence && distanceMoved > 1e-6 && afterDistance < this.bestCheckpointDistance) {
      var checkpointProgressPx = this.bestCheckpointDistance - afterDistance;
      this.bestCheckpointDistance = afterDistance;
      this.addReward((checkpointProgressPx / Math.max(1, this.level.routeLength)) * rewardConfig.constants.closerRewardScale);
    }
    this.checkCheckpoint(oldX, oldY);
  };

  Base2DDrivePlanarWasd.prototype.checkCheckpoint = function checkCheckpoint(oldX, oldY) {
    var checkpoint = this.currentCheckpoint();
    if (!checkpoint) return;
    var movementStart = { x: Number.isFinite(oldX) ? oldX : this.x, y: Number.isFinite(oldY) ? oldY : this.y };
    var movementEnd = { x: this.x, y: this.y };
    var line = U.track.crossSection(checkpoint, checkpoint.tangentAngle, checkpoint.lineHalfWidth);
    if (U.track.sweptCircleIntersectsSegment(movementStart, movementEnd, CAR_RADIUS, line.a, line.b)) {
      checkpoint.passed = true;
      this.checkpointsPassed += 1;
      this.routeCheckpointIndex += 1;
      this.addReward(rewardConfig.constants.checkpointReward);
      if (this.routeCheckpointIndex >= this.level.checkpoints.length) {
        this.routesCompleted += 1;
        this.startNextRoute();
      } else {
        this.bestCheckpointDistance = this.distanceToCheckpoint();
      }
    }
  };

  Base2DDrivePlanarWasd.prototype.advanceTime = function advanceTime(ms, options) {
    var duration = Number(ms);
    if (!Number.isFinite(duration) || duration <= 0) duration = STEP_MS;
    var steps = Math.max(1, Math.round(duration / STEP_MS));
    var rewardTotal = 0;
    for (var i = 0; i < steps; i += 1) {
      this.update(STEP_MS / 1000);
      rewardTotal += this.envRewardStep;
      if (this.terminal.isTerminal) break;
    }
    this.envRewardStep = rewardTotal;
    if (!options || options.render !== false) this.render();
    return this.getStatePayload();
  };

  Base2DDrivePlanarWasd.prototype.normalizeAction = function normalizeAction(action) {
    var actionId = Core.actions.readId(action, { lowercase: true });
    var moveX = 0;
    if (Core.actions.hasKey(action, ["ArrowLeft", "KeyA", "a"])) moveX -= 1;
    if (Core.actions.hasKey(action, ["ArrowRight", "KeyD", "d"])) moveX += 1;
    var moveY = 0;
    if (Core.actions.hasKey(action, ["ArrowUp", "KeyW", "w"])) moveY -= 1;
    if (Core.actions.hasKey(action, ["ArrowDown", "KeyS", "s"])) moveY += 1;
    moveX = U.math.clamp(moveX, -1, 1);
    moveY = U.math.clamp(moveY, -1, 1);
    return { id: actionId || "wait", args: {}, moveX: moveX, moveY: moveY };
  };

  Base2DDrivePlanarWasd.prototype.clearTransientControls = function clearTransientControls() {
    this.controls = { left: false, right: false, up: false, down: false };
  };

  Base2DDrivePlanarWasd.prototype.applyAction = function applyAction(normalized) {
    this.controls.left = normalized.moveX < -0.1;
    this.controls.right = normalized.moveX > 0.1;
    this.controls.up = normalized.moveY < -0.1;
    this.controls.down = normalized.moveY > 0.1;
    if (this.mode === "paused") this.mode = "playing";
  };

  Base2DDrivePlanarWasd.prototype.advanceSimulation = function advanceSimulation(ms) {
    var state = this.advanceTime(ms, { render: false });
    this.clearTransientControls();
    return state;
  };

  Base2DDrivePlanarWasd.prototype.buildStepInfo = function buildStepInfo(state, stepOptions, normalized) {
    var info = Core.terminal.withInfo(this, state, this.infoPayload());
    info.action = { type: "game_step_action", id: normalized.id, args: normalized.args };
    info.durationMs = stepOptions.durationMs;
    info.source = stepOptions.source;
    return info;
  };

  Base2DDrivePlanarWasd.prototype.resetGym = function resetGym(options) {
    this.resetFromAPI(options || {});
    return { observation: this.getObservation(), reward: 0, done: false, info: this.infoPayload() };
  };

  Base2DDrivePlanarWasd.prototype.getObservation = function getObservation() {
    return {
      player: { x: this.x, y: this.y, angle: this.angle, speed: this.speed() },
      current_checkpoint: this.currentCheckpoint(),
      checkpoints: this.level.checkpoints.map(function (checkpoint) {
        return {
          id: checkpoint.id,
          x: checkpoint.x,
          y: checkpoint.y,
          tangent_angle: checkpoint.tangentAngle,
          line_half_width: checkpoint.lineHalfWidth,
          route_distance: checkpoint.routeDistance,
          passed: checkpoint.passed,
        };
      }),
      road: {
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

  Base2DDrivePlanarWasd.prototype.infoPayload = function infoPayload() {
    return {
      score: this.getPrimaryScore(),
      checkpoints_passed: this.checkpointsPassed,
      routes_completed: this.routesCompleted,
      total_checkpoints: this.level.checkpoints.length,
      speed: this.speed(),
      distance_to_checkpoint: this.distanceToCheckpoint(),
      road_distance: this.roadDistance(),
      collisions: this.collisions,
      off_road_hits: this.offRoadHits,
      out_of_bounds: this.outOfBounds,
      track_min_turn_radius: this.level.trackValidation.minTurnRadius,
      track_min_separation: this.level.trackValidation.minSeparation,
      track_generation_attempts: this.level.trackGenerationAttempts,
      track_archetype: this.level.trackArchetype,
      acceleration: this.level.acceleration,
      max_speed: this.level.maxSpeed,
      velocity_retention: this.level.velocityRetention,
      env_reward_step: this.envRewardStep,
      env_reward_episode: this.envRewardEpisode,
      time_steps: this.stepCount,
    };
  };

  Base2DDrivePlanarWasd.prototype.getPrimaryScore = function getPrimaryScore() {
    return rewardConfig.computePrimaryScore(this);
  };

  Base2DDrivePlanarWasd.prototype.rewardPayload = function rewardPayload() {
    return {
      env_reward_step: this.envRewardStep,
      env_reward_episode: this.envRewardEpisode,
      primary_positive_score: rewardConfig.computePrimaryPositiveScore(this),
      primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(this),
      primary_score: this.getPrimaryScore(),
    };
  };

  Base2DDrivePlanarWasd.prototype.entityPayload = function entityPayload() {
    var entities = [{ id: "player", type: "vehicle", x: this.x, y: this.y, angle: this.angle, speed: this.speed(), r: CAR_RADIUS }];
    for (var i = 0; i < this.level.checkpoints.length; i += 1) {
      entities.push({
        id: this.level.checkpoints[i].id,
        type: "checkpoint",
        x: this.level.checkpoints[i].x,
        y: this.level.checkpoints[i].y,
        tangent_angle: this.level.checkpoints[i].tangentAngle,
        line_half_width: this.level.checkpoints[i].lineHalfWidth,
        route_distance: this.level.checkpoints[i].routeDistance,
        index: i,
        active: i === this.routeCheckpointIndex,
        passed: this.level.checkpoints[i].passed,
      });
    }
    return entities;
  };

  Base2DDrivePlanarWasd.prototype.visualPayload = function visualPayload() {
    return T2D.visuals.sync(this);
  };

  Base2DDrivePlanarWasd.prototype.getStatePayload = function getStatePayload() {
    var latched = Core.terminal.consume(this);
    if (latched) return latched;
    T2D.visuals.sync(this);
    var rewards = this.rewardPayload();
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
      terminal: {
        isTerminal: this.terminal.isTerminal,
        outcome: this.terminal.outcome,
        reason: this.terminal.reason,
      },
      game_state: {
        score: this.getPrimaryScore(),
        level: null,
        player: { x: this.x, y: this.y, angle: this.angle, speed: this.speed() },
        environment: {
          phase: this.terminal.isTerminal ? "terminal" : this.mode,
          viewport_width: viewport.width,
          viewport_height: viewport.height,
          logic_width: LOGIC_WIDTH,
          logic_height: LOGIC_HEIGHT,
          difficulty: this.difficulty,
          scene_version: Scene.version,
          asset_pack: this.assetPack,
          asset: T2D.visuals.assetPayload(this),
          current_checkpoint_index: this.routeCheckpointIndex,
          current_checkpoint: this.currentCheckpoint(),
          route_points: this.level.route.map(U.geometry2d.clonePoint),
          road_width: this.level.roadWidth,
          road_drivable_half_width: this.level.drivableHalfWidth,
          road_route_length: this.level.routeLength,
          road_distance: this.roadDistance(),
          track_validation: this.level.trackValidation,
          track_generation_attempts: this.level.trackGenerationAttempts,
          track_archetype: this.level.trackArchetype,
          acceleration: this.level.acceleration,
          velocity_retention: this.level.velocityRetention,
          max_speed: this.level.maxSpeed,
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
        total_checkpoints: this.level.checkpoints.length,
        speed: this.speed(),
        distance_to_checkpoint: this.distanceToCheckpoint(),
        road_distance: this.roadDistance(),
        distance_driven: this.distanceDriven,
        collisions: this.collisions,
        off_road_hits: this.offRoadHits,
        out_of_bounds: this.outOfBounds,
        track_min_turn_radius: this.level.trackValidation.minTurnRadius,
        track_min_separation: this.level.trackValidation.minSeparation,
        track_generation_attempts: this.level.trackGenerationAttempts,
        track_archetype: this.level.trackArchetype,
        acceleration: this.level.acceleration,
        max_speed: this.level.maxSpeed,
        velocity_retention: this.level.velocityRetention,
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

  Base2DDrivePlanarWasd.prototype.renderGameToText = function renderGameToText() {
    return JSON.stringify({
      coordinate_system: "origin=(0,0) top-left, +x right, +y down, angle radians with 0 facing right",
      status: this.mode,
      player: { x: this.x, y: this.y, angle: this.angle, speed: this.speed(), vx: this.vx, vy: this.vy },
      current_checkpoint: this.currentCheckpoint(),
      checkpoints: this.level.checkpoints,
      road: {
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
        total_checkpoints: this.level.checkpoints.length,
        distance_to_checkpoint: this.distanceToCheckpoint(),
        road_distance: this.roadDistance(),
        off_road_hits: this.offRoadHits,
      },
      difficulty: this.difficulty,
      visual_perturbations: this.visualPayload(),
    });
  };


  Base2DDrivePlanarWasd.prototype.render = function render() {
    T2D.visuals.sync(this);
    presentation.render(this);
    if (this.infoPanel) this.infoPanel.update();
  };

  Base2DDrivePlanarWasd.prototype.resetFromAPI = function resetFromAPI(options) {
    return this.beginEpisode(options || {}, true);
  };

  async function start() {
    await T2D.assets.preload(Scene.pack, ASSET_REQUIREMENTS);
    view = await T2D.createStage(canvas, { width: LOGIC_WIDTH, height: LOGIC_HEIGHT, background: 0xffffff });
    if (!view) throw new Error("Three.js 2D engine unavailable");
    presentation = Scene.create(view, createAsset, LOGIC_WIDTH, LOGIC_HEIGHT, FENCE_WIDTH);
    var game = new Base2DDrivePlanarWasd();
    Core.createRuntime({
      game: game,
      presentation: {
        title: "2D Circuit Driving",
        controls: "WASD or arrows accelerate in screen directions. Cross checkpoint lines in order; stay within the fences.",
        read: function readPresentation() {
          return {
            status: game.paused ? "paused" : game.mode,
            primaryScore: game.getPrimaryScore(),
            stepReward: game.envRewardStep,
            episodeReward: game.envRewardEpisode,
            difficulty: game.difficulty,
            seed: game.seed,
            perturbation: Core.perturbations.label(game),
            details: [["Checkpoints", game.checkpointsPassed],
              ["Next checkpoint", (game.routeCheckpointIndex + 1) + " / " + game.level.checkpoints.length],
              ["Routes completed", game.routesCompleted], ["Speed", game.speed().toFixed(1) + " px/s"],
              ["To checkpoint", Math.round(game.distanceToCheckpoint()) + " px"], ["Fence contacts", game.collisions]],
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
