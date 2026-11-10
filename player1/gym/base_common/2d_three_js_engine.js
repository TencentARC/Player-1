(function threeJs2DEngineModule() {
  "use strict";

  // Three.js is only the rasterizer here: logical coordinates remain flat x/y pixels.
  // The orthographic camera, unlit materials, and zero-thickness shapes are intentional.
  var Core = window.GameEngineCore;
  var AssetEngine = window.GameAssetEngine2D;
  if (!AssetEngine) throw new Error("2d_asset_engine.js must load before 2d_three_js_engine.js");
  var STAGE_VIEWS = typeof WeakMap === "function" ? new WeakMap() : null;
  var ORTHOGRAPHIC_ZOOM_MIN = 0.8;
  var ORTHOGRAPHIC_ZOOM_MAX = 1;
  var WIDESCREEN_ASPECT = 16 / 9;
  var PRESENTATION_WIDTH = 960;
  var PRESENTATION_HEIGHT = 540;
  var ENVIRONMENT_ROLES = Object.freeze({
    background: true,
    sky: true,
    surface: true,
    surfaceAccent: true,
    grid: true,
    road: true,
    roadEdge: true,
    lane: true,
    verge: true,
    platform: true,
  });
  var REQUIRED_THREE_REVISION = "185";

  function hasThree() {
    return typeof window.THREE !== "undefined"
      && String(window.THREE.REVISION) === REQUIRED_THREE_REVISION;
  }

  function stableHash(value) {
    var text = String(value === undefined || value === null ? "" : value);
    var hash = 2166136261;
    for (var i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function seededUnit(seed, salt) {
    var state = (Number(seed) >>> 0) ^ stableHash(salt);
    state += 0x6d2b79f5;
    var mixed = state;
    mixed = Math.imul(mixed ^ (mixed >>> 15), mixed | 1);
    mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61);
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
  }

  function resolveDomainAppearanceSeed(options) {
    return Core.seeds.forDomain(options || {}, "appearance", 42);
  }

  function assetUsesIsolatedDomain(options) {
    var source = options || {};
    if (source.domainMode === "isolated") return true;
    if (source.domainMode === "legacy") return false;
    return Object.prototype.hasOwnProperty.call(source, "domainAppearanceSeed")
      || Object.prototype.hasOwnProperty.call(source, "domainAppearanceSeeds")
      || Object.prototype.hasOwnProperty.call(source, "domainAppearanceSamples");
  }

  function createAssetContext(options) {
    options = options || {};
    var pack = AssetEngine.getManifest(options.assetPack || options.pack || options.id || "gym-light-default");
    var flags = Object.assign({ entityColor: false }, options.visualFlags || options.flags || {});
    var isolated = assetUsesIsolatedDomain(options);
    var baseSeed = Number(options.seed) >>> 0;
    var seed = isolated ? resolveDomainAppearanceSeed(options) : Number(options.seed) >>> 0;
    var samples = isolated ? options.domainAppearanceSamples || {} : {};
    var streamSeeds = isolated ? options.domainAppearanceSeeds || {} : {};
    var paletteSample = samples.palette || null;
    var backgroundSample = samples.background || null;
    var profileSignature = JSON.stringify(samples);
    var assetSeed = streamSeeds.assets === undefined ? seed : streamSeeds.assets;
    var selection = Core.perturbations.resolveAssetVariations(pack, assetSeed, !!(samples.assets && samples.assets.enabled));
    var palette = Object.assign({}, pack.palette, selection.theme.palette);
    var surfaces = Object.assign({}, pack.surfaces, selection.theme.surfaces);
    function contextColor(role, fallback) {
      var source = flags.entityColor && pack.alternatePalette[role] !== undefined ? pack.alternatePalette : palette;
      var value = source[role];
      if (value === undefined) value = palette[role];
      if (value === undefined) value = fallback === undefined ? 0xffffff : fallback;
      var environment = !!ENVIRONMENT_ROLES[role];
      if ((environment && flags.bgColor)
        || (!environment && flags.entityColor && pack.alternatePalette[role] === undefined)) {
        value = Core.perturbations.transformColor(value, Core.visuals.colorSample(seed, environment));
      }
      if (isolated && backgroundSample && backgroundSample.theme === "dark") {
        if (role === "text") return 0xf1f5f9;
        if (role === "neutral") return 0x94a3b8;
      }
      return isolated
        ? Core.perturbations.transformColor(
          value,
          ENVIRONMENT_ROLES[role] ? backgroundSample : paletteSample
        )
        : value;
    }
    function contextColorChannels(role, fallback) {
      var value = Number(contextColor(role, fallback)) >>> 0;
      return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
    }
    return {
      id: pack.id,
      pack: pack,
      baseSeed: baseSeed,
      seed: seed,
      visualFlags: flags,
      domainAppearanceSamples: samples,
      domainAppearanceSeeds: streamSeeds,
      domainMode: isolated ? "isolated" : "legacy",
      profileSignature: profileSignature,
      theme: selection.theme.id,
      assetId: function assetId(id) { return selection.assets[id] || id; },
      color: contextColor,
      colorChannels: contextColorChannels,
      surface: function surface(role, fallback) { return surfaces[role] || fallback || "panels"; },
      variation: function variation(role) {
        var roleSeed = ENVIRONMENT_ROLES[role]
          ? (streamSeeds.background === undefined ? seed : streamSeeds.background)
          : (streamSeeds.palette === undefined ? seed : streamSeeds.palette);
        return seededUnit(roleSeed, pack.id + ":" + role);
      },
      payload: function payload() {
        if (!isolated) {
          return { id: pack.id, theme: selection.theme.id, asset_variants: Object.assign({}, selection.assets) };
        }
        return {
          id: pack.id,
          theme: selection.theme.id,
          asset_variants: Object.assign({}, selection.assets),
          domain_appearance_seed: seed,
          stream_seeds: Object.assign({}, streamSeeds),
          samples: JSON.parse(JSON.stringify(samples)),
        };
      },
    };
  }

  function configureGameAssets(game, defaultPack) {
    if (!game) return createAssetContext({ assetPack: defaultPack });
    var config = Object.assign({}, game.currentConfig || game.urlConfig || {}, game.visualConfig || {});
    var flags = game.visualPerturbations && game.visualPerturbations.active;
    var isolated = Core.domains.isActive(game, "appearance");
    var assetOptions = {
      assetPack: defaultPack || "gym-light-default",
      seed: game.seed === undefined ? config.seed : game.seed,
      domainMode: isolated ? "isolated" : "legacy",
      visualFlags: flags,
    };
    if (isolated) {
      assetOptions.domainAppearanceSeed = Core.seeds.forDomain(game, "appearance", config.seed);
      assetOptions.domainAppearanceSeeds = game.rng && game.rng.appearance ? {
        palette: game.rng.appearance.palette && game.rng.appearance.palette.seed,
        lighting: game.rng.appearance.lighting && game.rng.appearance.lighting.seed,
        background: game.rng.appearance.background && game.rng.appearance.background.seed,
        assets: game.rng.appearance.assets && game.rng.appearance.assets.seed,
      } : {};
      assetOptions.domainAppearanceSamples = game.domainState && game.domainState.applied
        ? game.domainState.applied.appearance
        : {};
    }
    game.assetContext = createAssetContext(assetOptions);
    game.assetPack = game.assetContext.id;
    return game.assetContext;
  }

  function assetPayload(game) {
    if (game && game.assetContext && typeof game.assetContext.payload === "function") return game.assetContext.payload();
    var fixedPack = game && game.visualDimensions ? game.visualDimensions.defaultAssetPack : "gym-light-default";
    return createAssetContext({ assetPack: fixedPack }).payload();
  }

  function applyVisualState(payload, dimensions) {
    var size = dimensions || {};
    var baseWidth = Number(size.baseWidth) || 640;
    var baseHeight = Number(size.baseHeight) || 640;
    Core.visuals.applyLayout(payload && payload.active, baseWidth, baseHeight);
    return {
      active: false,
      css_width: baseWidth,
      css_height: baseHeight,
      backing_width: Number(size.backingWidth) || baseWidth,
      backing_height: Number(size.backingHeight) || baseHeight,
    };
  }

  function configureGameVisuals(game, config, options) {
    var source = config || {};
    game.visualConfig = {
      seed: source.seed,
      visualFlags: Core.visuals.cloneFlags(source.visualFlags),
    };
    var dimensions = options || {};
    game.visualDimensions = {
      baseWidth: Number(dimensions.baseWidth) || 640,
      baseHeight: Number(dimensions.baseHeight) || 640,
      backingWidth: Number(dimensions.backingWidth) || Number(dimensions.baseWidth) || 640,
      backingHeight: Number(dimensions.backingHeight) || Number(dimensions.baseHeight) || 640,
      defaultAssetPack: dimensions.defaultAssetPack || "gym-light-default",
    };
    if (dimensions.view) game.visualView = dimensions.view;
    game.visualPerturbations = {
      active: Core.visuals.cloneFlags(),
    };
    return syncGameVisuals(game);
  }

  function syncGameVisuals(game) {
    if (!game || !game.visualConfig) {
      return Core.perturbations.visualPayload(
        game,
        Core.visuals.buildPayload({ asset: assetPayload(game) }),
      );
    }
    var next = Core.perturbations.visualPayload(
      game,
      Core.visuals.state(game.visualConfig, {}),
    );
    var previousLabel = Core.visuals.label(game.visualPerturbations && game.visualPerturbations.active);
    var visualChanged = previousLabel !== Core.visuals.label(next.active);
    var appearanceActive = Core.domains.isActive(game, "appearance");
    var appearanceChanged = !game.assetContext;
    if (appearanceActive) {
      var domainAppearanceSeed = Core.seeds.forDomain(game, "appearance", game.visualConfig.seed);
      var sampleSignature = JSON.stringify(
        game.domainState && game.domainState.applied ? game.domainState.applied.appearance : {}
      );
      appearanceChanged = appearanceChanged
        || game.assetContext.domainMode !== "isolated"
        || game.assetContext.seed !== domainAppearanceSeed
        || game.assetContext.profileSignature !== sampleSignature;
    } else {
      appearanceChanged = appearanceChanged || game.assetContext.domainMode !== "legacy";
    }
    game.visualPerturbations = {
      active: Core.visuals.cloneFlags(next.active),
    };
    if (visualChanged || appearanceChanged) {
      configureGameAssets(game, game.visualDimensions.defaultAssetPack);
    }
    applyVisualState(next, game.visualDimensions);
    syncOrthographicCamera(game.visualView, game);
    next.asset = assetPayload(game);
    return next;
  }

  function sampleOrthographicProjection(context) {
    if (!context || context.profile === "default") return { orthographic_zoom: 1 };
    return {
      orthographic_zoom: context.rng.range(ORTHOGRAPHIC_ZOOM_MIN, ORTHOGRAPHIC_ZOOM_MAX),
    };
  }

  function validateOrthographicProjection(context) {
    var projection = context && context.value;
    var zoom = projection && Number(projection.orthographic_zoom);
    if (!Number.isFinite(zoom)) return false;
    if (context.profile === "default") return zoom === 1;
    return zoom >= ORTHOGRAPHIC_ZOOM_MIN && zoom <= ORTHOGRAPHIC_ZOOM_MAX;
  }

  function syncOrthographicCamera(view, game) {
    if (!view || typeof view.setOrthographicZoom !== "function") return 1;
    var projection = Core.domains.sample(
      game,
      "camera",
      "projection",
      { orthographic_zoom: 1 }
    ) || {};
    return view.setOrthographicZoom(projection.orthographic_zoom);
  }

  function parseColor(value, fallback) {
    var picked = value === undefined || value === null ? fallback : value;
    if (picked === undefined || picked === null) return { color: 0x000000, alpha: 1 };
    if (typeof picked === "number") return { color: picked >>> 0, alpha: 1 };
    if (typeof picked === "object" && picked.color !== undefined) {
      return { color: Number(picked.color) >>> 0, alpha: picked.alpha === undefined ? 1 : Number(picked.alpha) };
    }
    var text = String(picked).trim().toLowerCase();
    var rgbaMatch = text.match(/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)$/);
    if (rgbaMatch) {
      return {
        color: ((Number(rgbaMatch[1]) & 255) << 16) | ((Number(rgbaMatch[2]) & 255) << 8) | (Number(rgbaMatch[3]) & 255),
        alpha: rgbaMatch[4] === undefined ? 1 : Number(rgbaMatch[4]),
      };
    }
    if (text.charAt(0) === "#") {
      var hex = text.slice(1);
      if (hex.length === 3) hex = hex.replace(/(.)/g, "$1$1");
      if (/^[0-9a-f]{6}$/.test(hex)) return { color: parseInt(hex, 16), alpha: 1 };
    }
    var names = { black: 0x000000, white: 0xffffff, red: 0xff0000, green: 0x008000, blue: 0x0000ff, transparent: 0x000000 };
    if (names[text] !== undefined) return { color: names[text], alpha: text === "transparent" ? 0 : 1 };
    return { color: fallback === undefined ? 0x000000 : Number(fallback) >>> 0, alpha: 1 };
  }

  function createStage(canvas, options) {
    if (!hasThree()) return null;
    options = options || {};
    var width = Math.max(1, Math.round(Number(options.width) || canvas.width || 640));
    var height = Math.max(1, Math.round(Number(options.height) || canvas.height || 640));
    var viewportWidth = width;
    var viewportHeight = height;
    var renderer;
    try {
      renderer = new THREE.WebGLRenderer({
        canvas: canvas,
        antialias: options.antialias !== false,
        alpha: false,
        preserveDrawingBuffer: options.preserveDrawingBuffer !== false,
        powerPreference: options.powerPreference || "low-power",
      });
    } catch (error) {
      return null;
    }
    renderer.setPixelRatio(1);
    renderer.setSize(width, height, false);
    renderer.setClearColor(options.background === undefined ? 0xffffff : options.background, 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;

    var scene = new THREE.Scene();
    var camera = new THREE.OrthographicCamera(0, width, 0, height, -10, 10);
    var nativeViewHeight = options.cameraViewHeight === undefined ? null : Number(options.cameraViewHeight);
    if (nativeViewHeight !== null && (!Number.isFinite(nativeViewHeight) || nativeViewHeight <= 0)) {
      throw new Error("cameraViewHeight must be a positive finite number");
    }
    function syncCameraBounds() {
      var viewHeight = nativeViewHeight === null ? height : nativeViewHeight;
      var viewWidth = viewHeight * width / height;
      camera.left = (width - viewWidth) / 2;
      camera.right = (width + viewWidth) / 2;
      camera.top = (height - viewHeight) / 2;
      camera.bottom = (height + viewHeight) / 2;
      camera.updateProjectionMatrix();
    }
    syncCameraBounds();
    camera.position.z = 1;
    scene.add(camera);
    var root = new THREE.Group();
    scene.add(root);

    var rectGeometry = new THREE.PlaneGeometry(1, 1);
    var circleGeometry = new THREE.CircleGeometry(1, 48);
    var triangleGeometry = new THREE.BufferGeometry();
    var trianglePositions = new THREE.BufferAttribute(new Float32Array(9), 3);
    triangleGeometry.setAttribute("position", trianglePositions);
    var pools = { rect: [], circle: [], triangle: [], geometry: [], image: [] };
    var cursors = { rect: 0, circle: 0, triangle: 0, geometry: 0, image: 0 };
    var pathGeometryCache = new WeakMap();
    var pathGeometries = new Set();
    var textPool = [];
    var textCursor = 0;
    var order = 0;
    var assetLayerOffset = 0;
    var disposed = false;

    function applyViewportTransform() {
      var scale = Math.min(viewportWidth / width, viewportHeight / height);
      var fittedWidth = Math.max(1, Math.round(width * scale));
      var fittedHeight = Math.max(1, Math.round(height * scale));
      renderer.setViewport(
        Math.floor((viewportWidth - fittedWidth) / 2),
        Math.floor((viewportHeight - fittedHeight) / 2),
        fittedWidth,
        fittedHeight
      );
    }

    function setOrthographicZoom(value) {
      var next = Number(value);
      if (!Number.isFinite(next) || next <= 0) next = 1;
      camera.zoom = next;
      camera.updateProjectionMatrix();
      return camera.zoom;
    }

    function getOrthographicZoom() {
      return camera.zoom;
    }

    function getVisibleBounds() {
      var zoom = getOrthographicZoom();
      var visibleWidth = (camera.right - camera.left) / zoom;
      var visibleHeight = (camera.bottom - camera.top) / zoom;
      var centerX = (camera.left + camera.right) / 2;
      var centerY = (camera.top + camera.bottom) / 2;
      return {
        left: centerX - visibleWidth / 2,
        top: centerY - visibleHeight / 2,
        right: centerX + visibleWidth / 2,
        bottom: centerY + visibleHeight / 2,
        width: visibleWidth,
        height: visibleHeight,
      };
    }

    function projectPoint(x, y) {
      var bounds = getVisibleBounds();
      return {
        x: (Number(x) - bounds.left) * width / bounds.width,
        y: (Number(y) - bounds.top) * height / bounds.height,
      };
    }

    function unprojectPoint(x, y) {
      var bounds = getVisibleBounds();
      return {
        x: bounds.left + Number(x) * bounds.width / width,
        y: bounds.top + Number(y) * bounds.height / height,
      };
    }

    function makeMaterial() {
      return new THREE.MeshBasicMaterial({
        color: 0xffffff,
        transparent: true,
        opacity: 1,
        depthTest: false,
        depthWrite: false,
        side: THREE.DoubleSide,
        forceSinglePass: true,
      });
    }

    function pooledMesh(kind) {
      if (disposed) throw new Error("2D stage has been disposed");
      var cursor = cursors[kind]++;
      var pool = pools[kind];
      var mesh = pool[cursor];
      if (!mesh) {
        var geometry = kind === "image" ? rectGeometry.clone() : (kind === "circle" ? circleGeometry
          : (kind === "triangle" ? triangleGeometry.clone() : rectGeometry));
        mesh = new THREE.Mesh(geometry, makeMaterial());
        pool.push(mesh);
        root.add(mesh);
      }
      mesh.visible = true;
      mesh.renderOrder = order++ + assetLayerOffset;
      return mesh;
    }

    function pooledGeometryMesh(geometry, style) {
      var mesh = pooledMesh("geometry");
      mesh.geometry = geometry;
      mesh.position.set(0, 0, 0);
      mesh.scale.set(1, 1, 1);
      mesh.rotation.z = 0;
      return applyStyle(mesh, style, 0x000000);
    }

    function applyStyle(mesh, style, fallback) {
      var parsed = parseColor(style, fallback);
      mesh.material.color.setHex(parsed.color);
      mesh.material.opacity = Math.max(0, Math.min(1, parsed.alpha));
      // Keep every immediate-mode primitive in one render queue so renderOrder
      // matches Canvas 2D draw order even when opaque and translucent assets overlap.
      mesh.material.transparent = true;
      return mesh;
    }

    function rawRect(x, y, w, h, fill) {
      if (!(w > 0 && h > 0)) return null;
      var mesh = pooledMesh("rect");
      mesh.position.set(x + w / 2, y + h / 2, 0);
      mesh.scale.set(w, h, 1);
      mesh.rotation.z = 0;
      return applyStyle(mesh, fill, 0x000000);
    }

    function rawRotatedRect(cx, cy, w, h, angle, fill) {
      if (!(w > 0 && h > 0)) return null;
      var mesh = pooledMesh("rect");
      mesh.position.set(cx, cy, 0);
      mesh.scale.set(w, h, 1);
      mesh.rotation.z = Number(angle) || 0;
      return applyStyle(mesh, fill, 0x000000);
    }

    function fillRect(x, y, w, h, fill, stroke, lineWidth) {
      var parsedFill = parseColor(fill, 0x000000);
      if (x <= 0 && y <= 0 && w >= width && h >= height && parsedFill.alpha >= 1) {
        clear(fill);
        return null;
      }
      var border = Math.max(0, Number(lineWidth) || 0);
      if (stroke !== undefined && stroke !== null && border > 0) rawRect(x - border, y - border, w + border * 2, h + border * 2, stroke);
      return rawRect(x, y, w, h, fill);
    }

    function strokeRect(x, y, w, h, stroke, lineWidth) {
      var size = Math.max(1, Number(lineWidth) || 1);
      rawRect(x, y, w, size, stroke);
      rawRect(x, y + h - size, w, size, stroke);
      rawRect(x, y + size, size, Math.max(0, h - size * 2), stroke);
      rawRect(x + w - size, y + size, size, Math.max(0, h - size * 2), stroke);
    }

    function fillCircle(x, y, radius, fill, stroke, lineWidth) {
      var border = Math.max(0, Number(lineWidth) || 0);
      if (stroke !== undefined && stroke !== null && border > 0) {
        var outer = pooledMesh("circle");
        outer.position.set(x, y, 0);
        outer.scale.set(radius + border, radius + border, 1);
        applyStyle(outer, stroke, 0x000000);
      }
      var mesh = pooledMesh("circle");
      mesh.position.set(x, y, 0);
      mesh.scale.set(radius, radius, 1);
      return applyStyle(mesh, fill, 0x000000);
    }

    function fillEllipse(x, y, radiusX, radiusY, angle, fill, stroke, lineWidth) {
      var border = Math.max(0, Number(lineWidth) || 0);
      if (stroke !== undefined && stroke !== null && border > 0) {
        var outer = pooledMesh("circle");
        outer.position.set(x, y, 0);
        outer.scale.set(radiusX + border, radiusY + border, 1);
        outer.rotation.z = Number(angle) || 0;
        applyStyle(outer, stroke, 0x000000);
      }
      var mesh = pooledMesh("circle");
      mesh.position.set(x, y, 0);
      mesh.scale.set(radiusX, radiusY, 1);
      mesh.rotation.z = Number(angle) || 0;
      return applyStyle(mesh, fill, 0x000000);
    }

    function fillRoundedRect(x, y, w, h, radius, fill, stroke, lineWidth) {
      var cornerRadius = Math.max(0, Math.min(Number(radius) || 0, Math.min(w, h) / 2));
      if (cornerRadius <= 0.01) return fillRect(x, y, w, h, fill, stroke, lineWidth);
      var points = [];
      var corners = [
        { x: x + w - cornerRadius, y: y + cornerRadius, start: -Math.PI / 2 },
        { x: x + w - cornerRadius, y: y + h - cornerRadius, start: 0 },
        { x: x + cornerRadius, y: y + h - cornerRadius, start: Math.PI / 2 },
        { x: x + cornerRadius, y: y + cornerRadius, start: Math.PI },
      ];
      corners.forEach(function addCorner(corner) {
        for (var step = 0; step <= 4; step += 1) {
          var angle = corner.start + step / 4 * Math.PI / 2;
          points.push({
            x: corner.x + Math.cos(angle) * cornerRadius,
            y: corner.y + Math.sin(angle) * cornerRadius,
          });
        }
      });
      return polygon(points, fill, stroke, lineWidth);
    }

    function line(points, stroke, lineWidth, opts) {
      if (!points || points.length < 2) return false;
      var widthValue = Math.max(0.5, Number(lineWidth) || 1);
      opts = opts || {};
      for (var index = 1; index < points.length; index += 1) {
        var start = points[index - 1];
        var end = points[index];
        var dx = end.x - start.x;
        var dy = end.y - start.y;
        var length = Math.sqrt(dx * dx + dy * dy);
        if (length <= 0.0001) continue;
        rawRotatedRect((start.x + end.x) / 2, (start.y + end.y) / 2, length, widthValue, Math.atan2(dy, dx), stroke);
        if (opts.cap === "round") {
          fillCircle(start.x, start.y, widthValue / 2, stroke);
          if (index === points.length - 1) fillCircle(end.x, end.y, widthValue / 2, stroke);
        }
      }
      return true;
    }

    function dashedPolyline(points, stroke, lineWidth, dash, opts) {
      var pattern = Array.isArray(dash) && dash.length ? dash : [12, 10];
      for (var segment = 1; segment < points.length; segment += 1) {
        var start = points[segment - 1];
        var end = points[segment];
        var dx = end.x - start.x;
        var dy = end.y - start.y;
        var length = Math.sqrt(dx * dx + dy * dy);
        if (length <= 0.0001) continue;
        var distance = 0;
        var patternIndex = 0;
        while (distance < length) {
          var step = Math.min(Math.max(0.5, Number(pattern[patternIndex % pattern.length]) || 0.5), length - distance);
          if (patternIndex % 2 === 0) {
            var t0 = distance / length;
            var t1 = (distance + step) / length;
            line([
              { x: start.x + dx * t0, y: start.y + dy * t0 },
              { x: start.x + dx * t1, y: start.y + dy * t1 },
            ], stroke, lineWidth, opts);
          }
          distance += step;
          patternIndex += 1;
        }
      }
      return true;
    }

    function createGeometry(positions, indices) {
      var geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
      geometry.setIndex(indices);
      geometry.computeBoundingSphere();
      pathGeometries.add(geometry);
      return geometry;
    }

    function miteredPathGeometry(points, lineWidth, options) {
      options = options || {};
      var halfWidth = Math.max(0.25, Number(lineWidth) || 1) / 2;
      var miterLimit = Math.max(1, Number(options.miterLimit) || 2.5);
      var hasRepeatedClosure = points.length > 2 && Math.hypot(
          points[0].x - points[points.length - 1].x,
          points[0].y - points[points.length - 1].y
        ) <= 0.0001;
      var closed = options.closed === true || hasRepeatedClosure;
      var pointCount = hasRepeatedClosure ? points.length - 1 : points.length;
      var positions = [];
      var indices = [];

      function direction(a, b) {
        var dx = b.x - a.x;
        var dy = b.y - a.y;
        var length = Math.max(0.0001, Math.sqrt(dx * dx + dy * dy));
        return { x: dx / length, y: dy / length };
      }

      for (var index = 0; index < pointCount; index += 1) {
        var current = points[index];
        var previousIndex = closed ? (index + pointCount - 1) % pointCount : Math.max(0, index - 1);
        var nextIndex = closed ? (index + 1) % pointCount : Math.min(pointCount - 1, index + 1);
        var incoming = direction(points[previousIndex], current);
        var outgoing = direction(current, points[nextIndex]);
        if (!closed && index === 0) incoming = outgoing;
        if (!closed && index === pointCount - 1) outgoing = incoming;
        var incomingNormal = { x: -incoming.y, y: incoming.x };
        var outgoingNormal = { x: -outgoing.y, y: outgoing.x };
        var miterX = incomingNormal.x + outgoingNormal.x;
        var miterY = incomingNormal.y + outgoingNormal.y;
        var miterLength = Math.sqrt(miterX * miterX + miterY * miterY);
        if (miterLength <= 0.0001) {
          miterX = outgoingNormal.x;
          miterY = outgoingNormal.y;
          miterLength = 1;
        }
        miterX /= miterLength;
        miterY /= miterLength;
        var denominator = Math.abs(miterX * outgoingNormal.x + miterY * outgoingNormal.y);
        var offset = halfWidth / Math.max(0.0001, denominator);
        offset = Math.min(offset, halfWidth * miterLimit);
        positions.push(
          current.x + miterX * offset, current.y + miterY * offset, 0,
          current.x - miterX * offset, current.y - miterY * offset, 0
        );
      }

      var connectionCount = closed ? pointCount : pointCount - 1;
      for (var connection = 0; connection < connectionCount; connection += 1) {
        var currentBase = connection * 2;
        var nextBase = ((connection + 1) % pointCount) * 2;
        indices.push(
          currentBase, currentBase + 1, nextBase,
          currentBase + 1, nextBase + 1, nextBase
        );
      }
      return createGeometry(positions, indices);
    }

    function thickPathGeometry(points, lineWidth, options) {
      if (options && options.join === "miter") return miteredPathGeometry(points, lineWidth, options);
      var halfWidth = Math.max(0.25, Number(lineWidth) || 1) / 2;
      var positions = [];
      var indices = [];
      for (var index = 0; index < points.length; index += 1) {
        var previous = points[Math.max(0, index - 1)];
        var next = points[Math.min(points.length - 1, index + 1)];
        var dx = next.x - previous.x;
        var dy = next.y - previous.y;
        var length = Math.max(0.0001, Math.sqrt(dx * dx + dy * dy));
        var normalX = -dy / length;
        var normalY = dx / length;
        positions.push(
          points[index].x + normalX * halfWidth, points[index].y + normalY * halfWidth, 0,
          points[index].x - normalX * halfWidth, points[index].y - normalY * halfWidth, 0
        );
        if (index > 0) {
          var base = index * 2;
          indices.push(base - 2, base - 1, base, base - 1, base + 1, base);
        }
      }
      return createGeometry(positions, indices);
    }

    function dashedPathGeometry(points, lineWidth, dash) {
      var pattern = Array.isArray(dash) && dash.length ? dash : [12, 10];
      var halfWidth = Math.max(0.25, Number(lineWidth) || 1) / 2;
      var positions = [];
      var indices = [];
      var patternIndex = 0;
      var patternRemaining = Math.max(0.5, Number(pattern[0]) || 0.5);
      var drawing = true;
      for (var segment = 1; segment < points.length; segment += 1) {
        var start = points[segment - 1];
        var end = points[segment];
        var dx = end.x - start.x;
        var dy = end.y - start.y;
        var length = Math.sqrt(dx * dx + dy * dy);
        if (length <= 0.0001) continue;
        var normalX = -dy / length * halfWidth;
        var normalY = dx / length * halfWidth;
        var distance = 0;
        while (distance < length) {
          var step = Math.min(patternRemaining, length - distance);
          if (drawing && step > 0.0001) {
            var t0 = distance / length;
            var t1 = (distance + step) / length;
            var x0 = start.x + dx * t0;
            var y0 = start.y + dy * t0;
            var x1 = start.x + dx * t1;
            var y1 = start.y + dy * t1;
            var base = positions.length / 3;
            positions.push(
              x0 + normalX, y0 + normalY, 0,
              x0 - normalX, y0 - normalY, 0,
              x1 + normalX, y1 + normalY, 0,
              x1 - normalX, y1 - normalY, 0
            );
            indices.push(base, base + 1, base + 2, base + 1, base + 3, base + 2);
          }
          distance += step;
          patternRemaining -= step;
          if (patternRemaining <= 0.0001) {
            patternIndex = (patternIndex + 1) % pattern.length;
            patternRemaining = Math.max(0.5, Number(pattern[patternIndex]) || 0.5);
            drawing = patternIndex % 2 === 0;
          }
        }
      }
      return createGeometry(positions, indices);
    }

    function cachedPathGeometry(points, cacheKey, factory) {
      var cached = pathGeometryCache.get(points);
      if (!cached) {
        cached = Object.create(null);
        pathGeometryCache.set(points, cached);
      }
      if (!cached[cacheKey] || !pathGeometries.has(cached[cacheKey])) cached[cacheKey] = factory();
      return cached[cacheKey];
    }

    function thickPath(points, stroke, lineWidth, options) {
      if (!points || points.length < 2) return false;
      options = options || {};
      var key = "solid:" + Number(lineWidth || 1).toFixed(4)
        + ":" + String(options.join || "legacy")
        + ":" + String(options.closed === true)
        + ":" + Number(options.miterLimit || 0).toFixed(2);
      var geometry = cachedPathGeometry(points, key, function buildSolidPath() {
        return thickPathGeometry(points, lineWidth, options);
      });
      pooledGeometryMesh(geometry, stroke);
      return true;
    }

    function dashedPath(points, stroke, lineWidth, dash) {
      if (!points || points.length < 2) return false;
      var key = "dash:" + Number(lineWidth || 1).toFixed(4) + ":" + (dash || []).join(",");
      var geometry = cachedPathGeometry(points, key, function buildDashedPath() {
        return dashedPathGeometry(points, lineWidth, dash);
      });
      pooledGeometryMesh(geometry, stroke);
      return true;
    }

    function polygon(points, fill, stroke, lineWidth) {
      if (!points || points.length < 3) return null;
      // Triangulate the contour so concave shapes keep their notches. Copy it
      // because ShapeUtils removes a repeated closing point in place.
      var contour = points.map(function vertex(point) { return new THREE.Vector2(point.x, point.y); });
      var triangles = THREE.ShapeUtils.triangulateShape(contour, []);
      for (var index = 0; index < triangles.length; index += 1) {
        var face = triangles[index];
        fillTriangle([contour[face[0]], contour[face[1]], contour[face[2]]], fill, null, 0);
      }
      if (stroke !== undefined && stroke !== null && Number(lineWidth) > 0) {
        line(points.concat([points[0]]), stroke, lineWidth, { cap: "round" });
      }
      return true;
    }

    function rotatePoint(cx, cy, angle, x, y) {
      var cosine = Math.cos(angle);
      var sine = Math.sin(angle);
      return {
        x: cx + x * cosine - y * sine,
        y: cy + x * sine + y * cosine,
      };
    }

    function fillTriangle(points, fill, stroke, lineWidth) {
      if (!points || points.length < 3) return null;
      var border = Math.max(0, Number(lineWidth) || 0);
      if (stroke !== undefined && stroke !== null && border > 0) {
        var centerX = (points[0].x + points[1].x + points[2].x) / 3;
        var centerY = (points[0].y + points[1].y + points[2].y) / 3;
        var expanded = points.map(function expand(point) {
          var dx = point.x - centerX;
          var dy = point.y - centerY;
          var length = Math.max(0.001, Math.sqrt(dx * dx + dy * dy));
          return { x: point.x + dx / length * border, y: point.y + dy / length * border };
        });
        fillTriangle(expanded, stroke, null, 0);
      }
      var mesh = pooledMesh("triangle");
      var positions = mesh.geometry.attributes.position.array;
      for (var i = 0; i < 3; i += 1) {
        positions[i * 3] = points[i].x;
        positions[i * 3 + 1] = points[i].y;
        positions[i * 3 + 2] = 0;
      }
      mesh.geometry.attributes.position.needsUpdate = true;
      mesh.geometry.computeBoundingSphere();
      mesh.position.set(0, 0, 0);
      mesh.scale.set(1, 1, 1);
      return applyStyle(mesh, fill, 0x000000);
    }

    function clear(fill) {
      if (disposed) throw new Error("2D stage has been disposed");
      Object.keys(cursors).forEach(function resetCursor(key) { cursors[key] = 0; });
      textCursor = 0;
      order = 0;
      textPool.forEach(function hideText(entry) { entry.mesh.visible = false; });
      if (fill !== undefined && fill !== null) {
        var parsed = parseColor(fill, 0xffffff);
        if (parsed.alpha >= 1) renderer.setClearColor(parsed.color, 1);
        rawRect(0, 0, width, height, fill);
      }
    }

    function hideUnused() {
      Object.keys(pools).forEach(function hidePool(key) {
        for (var i = cursors[key]; i < pools[key].length; i += 1) pools[key][i].visible = false;
      });
    }

    function render() {
      if (disposed) throw new Error("2D stage has been disposed");
      hideUnused();
      var activePaths = new Set(pools.geometry.slice(0, cursors.geometry).map(function geometryOf(mesh) { return mesh.geometry; }));
      pathGeometries.forEach(function retireUnusedPath(geometry) {
        if (!activePaths.has(geometry)) {
          geometry.dispose();
          pathGeometries.delete(geometry);
          pools.geometry.forEach(function clearRetiredReference(mesh) {
            if (mesh.geometry === geometry) mesh.geometry = rectGeometry;
          });
        }
      });
      renderer.render(scene, camera);
    }

    function resize(nextWidth, nextHeight) {
      width = Math.max(1, Math.round(Number(nextWidth) || width));
      height = Math.max(1, Math.round(Number(nextHeight) || height));
      viewportWidth = width;
      viewportHeight = height;
      renderer.setSize(viewportWidth, viewportHeight, false);
      syncCameraBounds();
      applyViewportTransform();
    }

    function resizeViewport(nextWidth, nextHeight) {
      viewportWidth = Math.max(1, Math.round(Number(nextWidth) || viewportWidth));
      viewportHeight = Math.max(1, Math.round(Number(nextHeight) || viewportHeight));
      renderer.setSize(viewportWidth, viewportHeight, false);
      applyViewportTransform();
      return {
        width: viewportWidth,
        height: viewportHeight,
        aspect: viewportWidth / viewportHeight,
        logical_width: width,
        logical_height: height,
      };
    }

    function fontSizeFrom(font, fallback) {
      var match = String(font || "").match(/(\d+(?:\.\d+)?)px/i);
      return match ? Number(match[1]) : fallback;
    }

    function text(label, x, y, opts) {
      if (disposed) throw new Error("2D stage has been disposed");
      opts = opts || {};
      var font = opts.font || "15px monospace";
      var fontSize = Number(opts.fontSize) || fontSizeFrom(font, 15);
      var weight = String(font).toLowerCase().indexOf("bold") >= 0 ? "700" : "400";
      var fontFamily = opts.fontFamily || "monospace";
      var scale = 2;
      var parsed = parseColor(opts.fill || "#111827", 0x111827);
      var signature = [
        String(label),
        weight,
        fontSize,
        fontFamily,
        parsed.color,
        parsed.alpha,
      ].join(":");
      var entry = textPool[textCursor++];
      if (entry && entry.signature === signature) {
        entry.mesh.visible = true;
        entry.mesh.renderOrder = order++ + assetLayerOffset;
        positionTextMesh(entry.mesh, entry.drawWidth, entry.drawHeight, x, y, opts);
        return entry.mesh;
      }
      if (entry) {
        root.remove(entry.mesh);
        entry.mesh.material.map.dispose();
        entry.mesh.material.dispose();
        entry.mesh.geometry.dispose();
      }
      var textCanvas = document.createElement("canvas");
      var context = textCanvas.getContext("2d");
      context.font = weight + " " + (fontSize * scale) + "px " + fontFamily;
      var metrics = context.measureText(String(label));
      var pixelWidth = Math.max(2, Math.ceil(metrics.width + 4 * scale));
      var pixelHeight = Math.max(2, Math.ceil(fontSize * 1.45 * scale));
      textCanvas.width = pixelWidth;
      textCanvas.height = pixelHeight;
      context.font = weight + " " + (fontSize * scale) + "px " + fontFamily;
      context.textBaseline = "top";
      context.fillStyle = "rgba(" + ((parsed.color >> 16) & 255) + "," + ((parsed.color >> 8) & 255) + "," + (parsed.color & 255) + "," + parsed.alpha + ")";
      context.fillText(String(label), 2 * scale, 0);
      var texture = new THREE.CanvasTexture(textCanvas);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.minFilter = THREE.LinearFilter;
      texture.magFilter = THREE.LinearFilter;
      var material = new THREE.MeshBasicMaterial({
        map: texture,
        transparent: true,
        depthTest: false,
        depthWrite: false,
        side: THREE.DoubleSide,
        forceSinglePass: true,
      });
      var geometry = new THREE.PlaneGeometry(pixelWidth / scale, pixelHeight / scale);
      var mesh = new THREE.Mesh(geometry, material);
      var drawWidth = pixelWidth / scale;
      var drawHeight = pixelHeight / scale;
      positionTextMesh(mesh, drawWidth, drawHeight, x, y, opts);
      mesh.renderOrder = order++ + assetLayerOffset;
      root.add(mesh);
      entry = { signature: signature, mesh: mesh, drawWidth: drawWidth, drawHeight: drawHeight };
      textPool[textCursor - 1] = entry;
      return mesh;
    }

    function positionTextMesh(mesh, drawWidth, drawHeight, x, y, opts) {
      var left = x;
      if (opts.align === "center") left -= drawWidth / 2;
      else if (opts.align === "right" || opts.align === "end") left -= drawWidth;
      var top = y;
      if (opts.baseline === "middle") top -= drawHeight / 2;
      else if (opts.baseline === "bottom") top -= drawHeight;
      mesh.position.set(left + drawWidth / 2, top + drawHeight / 2, 0);
      mesh.scale.set(1, -1, 1);
      mesh.rotation.z = 0;
    }

    function rgba(value, alpha) {
      var parsed = parseColor(value, 0x000000);
      return { color: parsed.color, alpha: alpha === undefined ? parsed.alpha : alpha };
    }

    function crosshair(x, y, opts) {
      opts = opts || {};
      var radius = Math.max(2, Number(opts.radius) || 10);
      var gap = Math.max(1, Number(opts.gap) || radius * 0.28);
      var stroke = opts.stroke === undefined ? 0x111827 : opts.stroke;
      var lineWidth = Math.max(1, Number(opts.lineWidth) || 2);
      line([{ x: x - radius, y: y }, { x: x - gap, y: y }], stroke, lineWidth);
      line([{ x: x + gap, y: y }, { x: x + radius, y: y }], stroke, lineWidth);
      line([{ x: x, y: y - radius }, { x: x, y: y - gap }], stroke, lineWidth);
      line([{ x: x, y: y + gap }, { x: x, y: y + radius }], stroke, lineWidth);
    }

    function overlay(opts) {
      opts = opts || {};
      fillRect(opts.x || 0, opts.y || 0, opts.w || width, opts.h || 58, opts.fill || "rgba(255,255,255,0.86)", opts.stroke, opts.lineWidth);
      if (opts.label !== undefined && opts.label !== null) {
        text(String(opts.label), opts.textX === undefined ? (opts.x || 0) + 20 : opts.textX, opts.textY === undefined ? (opts.y || 0) + (opts.h || 58) / 2 : opts.textY, {
          fill: opts.textFill || "#111827",
          font: opts.font || "17px monospace",
          align: opts.align || "left",
          baseline: opts.baseline || "middle",
        });
      }
    }

    function resolveAssetContext(spec, fallbackPack) {
      spec = spec || {};
      return spec.assetContext || createAssetContext({
        assetPack: spec.assetPack || fallbackPack || "gym-light-default",
        seed: spec.seed,
        visualFlags: spec.visualFlags,
      });
    }

    function drawSurface(spec) {
      var context = resolveAssetContext(spec);
      var role = spec.role || "background";
      var x = Number(spec.x) || 0;
      var y = Number(spec.y) || 0;
      var w = spec.w === undefined ? width : Number(spec.w);
      var h = spec.h === undefined ? height : Number(spec.h);
      var fill = spec.fill === undefined ? context.color(role === "background" ? "surface" : role, context.color("background")) : spec.fill;
      fillRect(x, y, w, h, fill, spec.stroke, spec.lineWidth);
      if (spec.texture) {
        var spacing = Math.max(14, Number(spec.spacing) || Math.round(20 + context.variation(role) * 10));
        var gridColor = { color: context.color("surfaceAccent", context.color("grid")), alpha: 0.32 };
        for (var gx = x + spacing; gx < x + w; gx += spacing) fillRect(gx, y, 1, h, gridColor);
        for (var gy = y + spacing; gy < y + h; gy += spacing) fillRect(x, gy, w, 1, gridColor);
      }
    }

    function drawActor(spec) {
      var context = resolveAssetContext(spec);
      var w = Number(spec.w) || 24;
      var h = Number(spec.h) || w;
      var left = spec.centered === false ? Number(spec.x) : Number(spec.x) - w / 2;
      var top = spec.centered === false ? Number(spec.y) : Number(spec.y) - h / 2;
      var fill = spec.fill === undefined ? context.color(spec.hostile ? "hostile" : "friendly") : spec.fill;
      var accent = spec.accent === undefined
        ? context.color(spec.hostile ? "hostileAccent" : "friendlyAccent")
        : spec.accent;
      var stroke = spec.stroke === undefined ? context.color("text") : spec.stroke;
      if (spec.shadow !== false) {
        fillEllipse(
          left + w * 0.52,
          top + h * 0.94,
          w * 0.44,
          Math.max(2, h * 0.09),
          0,
          rgba(stroke, 0.16)
        );
      }
      var shape = spec.shape || "roundRect";
      if (spec.kind === "runner" && shape !== "diamond") {
        var crouching = spec.pose === "crouching";
        var frame = Number(spec.frame) % 2;
        if (crouching) {
          fillRoundedRect(left + w * 0.1, top + h * 0.2, w * 0.62, h * 0.62, Math.max(2, h * 0.12), fill, stroke, spec.lineWidth || 2);
          fillRoundedRect(left + w * 0.58, top + h * 0.08, w * 0.38, h * 0.56, Math.max(2, h * 0.12), fill, stroke, spec.lineWidth || 2);
          polygon([
            { x: left + w * 0.12, y: top + h * 0.28 },
            { x: left - w * 0.14, y: top + h * 0.5 },
            { x: left + w * 0.14, y: top + h * 0.7 },
          ], fill, stroke, spec.lineWidth || 2);
          fillRect(left + w * 0.28, top + h * 0.78, w * 0.16, h * 0.22, fill, stroke, 1);
          fillRect(left + w * 0.68, top + h * 0.7, w * 0.16, h * 0.3, fill, stroke, 1);
          fillCircle(left + w * 0.82, top + h * 0.25, Math.max(1.5, w * 0.035), context.color("surface"));
        } else {
          fillRoundedRect(left + w * 0.22, top + h * 0.34, w * 0.5, h * 0.48, Math.max(2, w * 0.08), fill, stroke, spec.lineWidth || 2);
          fillRoundedRect(left + w * 0.52, top, w * 0.46, h * 0.48, Math.max(2, w * 0.08), fill, stroke, spec.lineWidth || 2);
          polygon([
            { x: left + w * 0.24, y: top + h * 0.42 },
            { x: left - w * 0.18, y: top + h * 0.6 },
            { x: left + w * 0.24, y: top + h * 0.72 },
          ], fill, stroke, spec.lineWidth || 2);
          fillRect(left + w * 0.32, top + h * 0.76, w * 0.18, frame ? h * 0.24 : h * 0.14, fill, stroke, 1);
          fillRect(left + w * 0.62, top + h * 0.76, w * 0.18, frame ? h * 0.14 : h * 0.24, fill, stroke, 1);
          fillCircle(left + w * 0.82, top + h * 0.16, Math.max(1.5, w * 0.04), context.color("surface"));
        }
        return;
      }
      if (spec.kind === "flyer") {
        if (shape === "diamond") {
          polygon([
            { x: left + w / 2, y: top },
            { x: left + w, y: top + h / 2 },
            { x: left + w / 2, y: top + h },
            { x: left, y: top + h / 2 },
          ], fill, stroke, spec.lineWidth || 2);
        } else {
          fillEllipse(left + w / 2, top + h / 2, w / 2, h * 0.42, 0, fill, stroke, spec.lineWidth || 2);
        }
        fillEllipse(left + w * 0.38, top + h * 0.58, w * 0.24, h * 0.2, -0.35, accent, stroke, 1);
        fillCircle(left + w * 0.68, top + h * 0.38, Math.max(2, w * 0.07), context.color("surface"), stroke, 1);
        polygon([
          { x: left + w * 0.92, y: top + h * 0.43 },
          { x: left + w * 1.18, y: top + h * 0.53 },
          { x: left + w * 0.92, y: top + h * 0.62 },
        ], context.color("hazard"), stroke, 1);
        return;
      }
      if (shape === "circle") {
        fillCircle(left + w / 2, top + h / 2, Math.min(w, h) / 2, fill, stroke, spec.lineWidth || 2);
      } else if (shape === "diamond") {
        polygon([
          { x: left + w / 2, y: top },
          { x: left + w, y: top + h / 2 },
          { x: left + w / 2, y: top + h },
          { x: left, y: top + h / 2 },
        ], fill, stroke, spec.lineWidth || 2);
      } else {
        fillRoundedRect(
          left,
          top,
          w,
          h,
          spec.radius === undefined ? Math.min(7, Math.min(w, h) * 0.22) : spec.radius,
          fill,
          stroke,
          spec.lineWidth || 2
        );
      }
      if (accent !== false) {
        fillRoundedRect(
          left + w * 0.16,
          top + h * 0.14,
          Math.max(3, w * 0.22),
          Math.max(3, h * 0.18),
          2,
          accent
        );
      }
      if (Number.isFinite(spec.angle)) {
        var nose = Math.max(5, Math.min(w, h) * 0.32);
        line([
          { x: Number(spec.x), y: Number(spec.y) },
          {
            x: Number(spec.x) + Math.cos(spec.angle) * nose,
            y: Number(spec.y) + Math.sin(spec.angle) * nose,
          },
        ], spec.directionFill === undefined ? accent : spec.directionFill, Math.max(2, spec.directionWidth || 3), { cap: "round" });
      }
    }

    function drawAimTarget(spec) {
      var context = resolveAssetContext(spec);
      var radius = Number(spec.radius || spec.r) || 20;
      var fill = spec.fill === undefined ? context.color("target") : spec.fill;
      var light = spec.lightFill === undefined ? context.color("hostileAccent", 0xffd5d8) : spec.lightFill;
      var dark = spec.darkFill === undefined ? context.color("text", 0x54121b) : spec.darkFill;
      var stroke = spec.stroke === undefined ? context.color("text") : spec.stroke;
      if (spec.shape === "diamond") {
        polygon([
          { x: spec.x, y: spec.y - radius },
          { x: spec.x + radius, y: spec.y },
          { x: spec.x, y: spec.y + radius },
          { x: spec.x - radius, y: spec.y },
        ], fill, stroke, spec.lineWidth || 2);
        fillCircle(spec.x, spec.y, radius * 0.34, dark);
      } else {
        fillCircle(spec.x, spec.y, radius, fill, stroke, spec.lineWidth || 2);
        fillCircle(spec.x, spec.y, radius * 0.68, light);
        fillCircle(spec.x, spec.y, radius * 0.47, fill);
        fillCircle(spec.x, spec.y, radius * 0.2, dark);
      }
    }

    function drawCollectible(spec) {
      var context = resolveAssetContext(spec);
      var radius = Number(spec.radius || spec.r) || 10;
      var fill = spec.fill === undefined ? context.color("coin") : spec.fill;
      var stroke = spec.stroke === undefined ? context.color("text") : spec.stroke;
      if (spec.shape === "diamond") {
        fillTriangle([
          { x: spec.x, y: spec.y - radius },
          { x: spec.x + radius, y: spec.y },
          { x: spec.x, y: spec.y + radius },
        ], fill, stroke, spec.lineWidth || 2);
        fillTriangle([
          { x: spec.x, y: spec.y - radius },
          { x: spec.x, y: spec.y + radius },
          { x: spec.x - radius, y: spec.y },
        ], fill, stroke, spec.lineWidth || 2);
      } else {
        fillCircle(spec.x, spec.y, radius, fill, stroke, spec.lineWidth || 2);
        fillCircle(spec.x, spec.y, Math.max(2, radius * 0.48), context.color("surface"), null, 0);
      }
    }

    function drawHazard(spec) {
      var context = resolveAssetContext(spec);
      var fill = spec.fill === undefined ? context.color("hazard") : spec.fill;
      var stroke = spec.stroke === undefined ? context.color("text") : spec.stroke;
      var hazardWidth = spec.w || 24;
      var hazardHeight = spec.h || 24;
      if (spec.kind === "cactus") {
        var clustered = Number(spec.variant) === 1;
        var stemWidth = clustered ? hazardWidth * 0.3 : hazardWidth * 0.48;
        var stemX = clustered ? spec.x + hazardWidth * 0.56 : spec.x + hazardWidth * 0.3;
        fillRoundedRect(stemX, spec.y, stemWidth, hazardHeight, Math.max(2, stemWidth * 0.18), fill, stroke, spec.lineWidth || 2);
        fillRoundedRect(spec.x + hazardWidth * 0.04, spec.y + hazardHeight * 0.42, hazardWidth * 0.5, hazardHeight * 0.18, Math.max(2, hazardWidth * 0.06), fill, stroke, 1);
        fillRoundedRect(spec.x + hazardWidth * 0.05, spec.y + hazardHeight * 0.25, hazardWidth * 0.22, hazardHeight * 0.36, Math.max(2, hazardWidth * 0.06), fill, stroke, 1);
        if (clustered) {
          fillRoundedRect(spec.x + hazardWidth * 0.12, spec.y + hazardHeight * 0.18, hazardWidth * 0.28, hazardHeight * 0.82, Math.max(2, hazardWidth * 0.06), fill, stroke, 1);
          fillRoundedRect(spec.x + hazardWidth * 0.38, spec.y + hazardHeight * 0.52, hazardWidth * 0.54, hazardHeight * 0.16, Math.max(2, hazardWidth * 0.06), fill, stroke, 1);
        }
        return;
      }
      if (spec.kind === "bird") {
        var wingUp = Number(spec.frame) % 2 === 0;
        fillEllipse(spec.x + hazardWidth * 0.46, spec.y + hazardHeight * 0.58, hazardWidth * 0.34, hazardHeight * 0.34, 0, fill, stroke, spec.lineWidth || 2);
        fillCircle(spec.x + hazardWidth * 0.78, spec.y + hazardHeight * 0.36, Math.max(3, hazardHeight * 0.25), fill, stroke, 1);
        polygon([
          { x: spec.x + hazardWidth * 0.9, y: spec.y + hazardHeight * 0.32 },
          { x: spec.x + hazardWidth * 1.06, y: spec.y + hazardHeight * 0.46 },
          { x: spec.x + hazardWidth * 0.9, y: spec.y + hazardHeight * 0.54 },
        ], context.color("interactive"), stroke, 1);
        polygon(wingUp ? [
          { x: spec.x + hazardWidth * 0.22, y: spec.y + hazardHeight * 0.54 },
          { x: spec.x + hazardWidth * 0.52, y: spec.y - hazardHeight * 0.2 },
          { x: spec.x + hazardWidth * 0.62, y: spec.y + hazardHeight * 0.58 },
        ] : [
          { x: spec.x + hazardWidth * 0.22, y: spec.y + hazardHeight * 0.5 },
          { x: spec.x + hazardWidth * 0.54, y: spec.y + hazardHeight * 1.18 },
          { x: spec.x + hazardWidth * 0.62, y: spec.y + hazardHeight * 0.56 },
        ], fill, stroke, 1);
        fillCircle(spec.x + hazardWidth * 0.82, spec.y + hazardHeight * 0.28, Math.max(1, hazardHeight * 0.05), context.color("surface"));
        return;
      }
      if (spec.triangle) {
        var triangle = spec.triangle;
        var cameraX = Number(spec.cameraX) || 0;
        fillTriangle([
          { x: triangle.x - cameraX, y: triangle.y + triangle.h },
          { x: triangle.x + triangle.w / 2 - cameraX, y: triangle.y },
          { x: triangle.x + triangle.w - cameraX, y: triangle.y + triangle.h },
        ], fill, stroke, spec.lineWidth || 2);
        return;
      }
      if (spec.points && spec.points.length >= 3) {
        fillTriangle(spec.points.slice(0, 3).map(function point(value) {
          return Array.isArray(value) ? { x: value[0], y: value[1] } : value;
        }), fill, stroke, spec.lineWidth || 2);
        return;
      }
      fillRect(spec.x, spec.y, spec.w || 24, spec.h || 24, fill, stroke, spec.lineWidth || 2);
      if (spec.texture) {
        var stripe = { color: context.color("hostileAccent"), alpha: 0.42 };
        for (var stripeX = spec.x + 8; stripeX < spec.x + hazardWidth; stripeX += 8) {
          fillRect(stripeX, spec.y, 1, hazardHeight, stripe);
        }
      }
    }

    function drawTrail(spec) {
      line(spec.points || [], spec.stroke, spec.lineWidth || 1, { cap: spec.cap || "round" });
    }

    function drawGoalMarker(spec) {
      var context = resolveAssetContext(spec);
      var w = Number(spec.w) || (Number(spec.radius || spec.r) || 12) * 2;
      var h = Number(spec.h) || w;
      var centered = spec.centered !== false;
      var left = centered ? spec.x - w / 2 : spec.x;
      var top = centered ? spec.y - h / 2 : spec.y;
      var fill = spec.fill === undefined ? context.color("goal") : spec.fill;
      var stroke = spec.stroke === undefined ? context.color("text") : spec.stroke;
      if (spec.shape === "circle") fillCircle(left + w / 2, top + h / 2, Math.min(w, h) / 2, fill, stroke, spec.lineWidth || 2);
      else if (spec.shape === "diamond") {
        polygon([
          { x: left + w / 2, y: top },
          { x: left + w, y: top + h / 2 },
          { x: left + w / 2, y: top + h },
          { x: left, y: top + h / 2 },
        ], fill, stroke, spec.lineWidth || 2);
      } else fillRect(left, top, w, h, fill, stroke, spec.lineWidth || 2);
    }

    function drawMazeWall(spec) {
      var board = spec.board || {};
      var cell = spec.cell || {};
      var context = resolveAssetContext(spec, "gym-light-default");
      var inset = Number(spec.inset) || 1;
      var overdraw = Math.max(0, Number(spec.overdraw) || 0);
      var cellSize = Number(board.cellSize) || 32;
      var rect = {
        x: (Number(board.x) || 0) + (Number(cell.x) || 0) * cellSize + inset - overdraw,
        y: (Number(board.y) || 0) + (Number(cell.y) || 0) * cellSize + inset - overdraw,
        w: cellSize - inset * 2 + overdraw * 2,
        h: cellSize - inset * 2 + overdraw * 2,
      };
      var fill = spec.fill === undefined ? context.color("neutral") : spec.fill;
      var stroke = spec.stroke === undefined ? rgba(context.color("text"), 0.34) : spec.stroke;
      fillRect(rect.x, rect.y, rect.w, rect.h, fill);
      if (stroke !== false && stroke !== null) {
        strokeRect(rect.x, rect.y, rect.w, rect.h, stroke, spec.lineWidth || 1);
      }
      return rect;
    }

    function drawPathRoad(spec) {
      var points = spec.points || spec.route || [];
      if (points.length < 2) return;
      var roadWidth = Number(spec.width) || 42;
      var pathOptions = {
        join: spec.join,
        closed: spec.closed,
        miterLimit: spec.miterLimit,
      };
      if (spec.shoulderWidth) thickPath(
        points,
        spec.shoulderFill || "rgba(15,23,42,0.22)",
        roadWidth + Number(spec.shoulderWidth) * 2,
        pathOptions
      );
      thickPath(points, spec.roadFill || spec.fill || "#475569", roadWidth, pathOptions);
      if (spec.centerLine) {
        if (spec.dash) dashedPath(points, spec.centerLine, spec.centerLineWidth || 2, spec.dash);
        else thickPath(points, spec.centerLine, spec.centerLineWidth || 2, pathOptions);
      }
    }

    function drawCheckpointLine(spec) {
      var angle = Number(spec.tangentAngle);
      if (!Number.isFinite(angle)) angle = Number(spec.angle) || 0;
      var halfWidth = Math.max(0, Number(spec.halfWidth) || 28);
      var normalX = -Math.sin(angle);
      var normalY = Math.cos(angle);
      line([
        { x: spec.x + normalX * halfWidth, y: spec.y + normalY * halfWidth },
        { x: spec.x - normalX * halfWidth, y: spec.y - normalY * halfWidth },
      ], spec.stroke === undefined ? resolveAssetContext(spec, "gym-light-default").color("goal") : spec.stroke, spec.lineWidth || 6);
    }

    function drawArenaVehicle(spec) {
      var context = resolveAssetContext(spec, "gym-light-default");
      var x = Number(spec.x) || 0;
      var y = Number(spec.y) || 0;
      var angle = Number(spec.angle) || 0;
      var w = Number(spec.w || spec.width) || 38;
      var h = Number(spec.h || spec.height) || 22;
      var body = spec.bodyFill === undefined
        ? (spec.fill === undefined ? context.color("vehicle") : spec.fill)
        : spec.bodyFill;
      var trim = spec.cabinFill === undefined
        ? (spec.trim === undefined ? context.color("text") : spec.trim)
        : spec.cabinFill;
      var wheel = spec.wheelFill === undefined ? context.color("text") : spec.wheelFill;
      var headLight = spec.headLightFill === undefined ? context.color("headLight", 0xffef9c) : spec.headLightFill;
      var tailLight = spec.tailLightFill === undefined ? context.color("tailLight", 0xff2d3a) : spec.tailLightFill;
      var wheelW = w * 0.23;
      var wheelH = Math.max(4, h * 0.18);

      function rotatedLocalRect(localX, localY, rectWidth, rectHeight, fill) {
        var center = rotatePoint(x, y, angle, localX + rectWidth / 2, localY + rectHeight / 2);
        return rawRotatedRect(center.x, center.y, rectWidth, rectHeight, angle, fill);
      }

      if (spec.shadow !== false) {
        rotatedLocalRect(
          -w * 0.47,
          -h * 0.365,
          w,
          h * 0.92,
          { color: context.color("text"), alpha: 0.18 }
        );
      }
      rotatedLocalRect(-w * 0.35, -h * 0.5 - wheelH * 0.55, wheelW, wheelH, wheel);
      rotatedLocalRect(w * 0.125, -h * 0.5 - wheelH * 0.55, wheelW, wheelH, wheel);
      rotatedLocalRect(-w * 0.35, h * 0.5 - wheelH * 0.45, wheelW, wheelH, wheel);
      rotatedLocalRect(w * 0.125, h * 0.5 - wheelH * 0.45, wheelW, wheelH, wheel);
      var bodyPoints = [
        rotatePoint(x, y, angle, -w / 2, -h / 2),
        rotatePoint(x, y, angle, w * 0.36, -h / 2),
        rotatePoint(x, y, angle, w / 2, -h * 0.34),
        rotatePoint(x, y, angle, w / 2, h * 0.34),
        rotatePoint(x, y, angle, w * 0.36, h / 2),
        rotatePoint(x, y, angle, -w / 2, h / 2),
      ];
      polygon(bodyPoints, body, spec.stroke === undefined ? context.color("text") : spec.stroke, spec.lineWidth === undefined ? 2 : spec.lineWidth);
      rotatedLocalRect(-w * 0.32, -h * 0.34, w * 0.34, h * 0.68, trim);
      rotatedLocalRect(w * 0.38, -h * 0.32, w * 0.1, h * 0.2, headLight);
      rotatedLocalRect(w * 0.38, h * 0.12, w * 0.1, h * 0.2, headLight);
      rotatedLocalRect(w * 0.45, -h * 0.16, Math.max(2, w * 0.03), h * 0.32, context.color("text"));
      rotatedLocalRect(-w * 0.48 - 1, -h * 0.28 - 1, w * 0.07 + 2, h * 0.56 + 2, context.color("text"));
      rotatedLocalRect(-w * 0.48, -h * 0.28, w * 0.07, h * 0.56, tailLight);
    }

    function drawPlatform(spec) {
      var rect = spec.rect || spec;
      var cameraX = Number(spec.cameraX) || 0;
      var x = rect.x - cameraX;
      fillRect(x, rect.y, rect.w, rect.h, spec.fill === undefined ? resolveAssetContext(spec).color("platform") : spec.fill, spec.stroke, spec.lineWidth);
      if (spec.topFill !== undefined && Number(spec.topHeight) > 0) {
        fillRect(x, rect.y, rect.w, Number(spec.topHeight), spec.topFill);
      }
    }

    function drawGoalFlag(spec) {
      var flag = spec.flag || spec;
      var x = flag.x - (Number(spec.cameraX) || 0);
      var context = resolveAssetContext(spec);
      var fill = spec.fill === undefined ? context.color("goal") : spec.fill;
      fillRect(x, flag.y, Math.max(3, flag.w * 0.18), flag.h, context.color("text"));
      polygon([
        { x: x + flag.w * 0.18, y: flag.y },
        { x: x + flag.w, y: flag.y + flag.h * 0.18 },
        { x: x + flag.w * 0.18, y: flag.y + flag.h * 0.38 },
      ], fill, context.color("text"), 1);
    }

    function drawLaneRoad(spec) {
      var context = resolveAssetContext(spec, "gym-light-default");
      var roadX = spec.x === undefined ? Math.round(width * 0.18) : spec.x;
      var roadY = spec.y || 0;
      var roadW = spec.w === undefined ? Math.round(width * 0.64) : spec.w;
      var roadH = spec.h || height;
      var lanes = spec.lanes || 4;
      var shoulderWidth = spec.shoulderWidth === undefined ? 30 : spec.shoulderWidth;
      var edgeWidth = spec.edgeWidth === undefined ? 8 : spec.edgeWidth;
      var stripeWidth = spec.stripeWidth === undefined ? 6 : spec.stripeWidth;
      var stripeHeight = spec.stripeHeight || 52;
      var stripeGap = spec.stripeGap || 40;
      var stripePeriod = stripeHeight + stripeGap;
      var stripeOffset = spec.stripeOffset || 0;
      var roadTop = roadY;
      var roadBottom = roadY + roadH;
      if (spec.repeatY) {
        var visibleBounds = getVisibleBounds();
        roadTop = Math.min(roadTop, visibleBounds.top);
        roadBottom = Math.max(roadBottom, visibleBounds.bottom);
      }
      var renderedRoadHeight = roadBottom - roadTop;
      fillRect(0, 0, width, height, spec.vergeFill === undefined ? context.color("verge") : spec.vergeFill);
      fillRect(roadX - shoulderWidth, roadTop, roadW + shoulderWidth * 2, renderedRoadHeight, spec.shoulderFill === undefined ? context.color("neutral") : spec.shoulderFill);
      fillRect(roadX, roadTop, roadW, renderedRoadHeight, spec.roadFill === undefined ? context.color("road") : spec.roadFill);
      fillRect(roadX, roadTop, edgeWidth, renderedRoadHeight, spec.edgeFill === undefined ? context.color("roadEdge") : spec.edgeFill);
      fillRect(roadX + roadW - edgeWidth, roadTop, edgeWidth, renderedRoadHeight, spec.edgeFill === undefined ? context.color("roadEdge") : spec.edgeFill);
      if (spec.texture) {
        var textureOrigin = roadY + 10;
        var firstTextureY = textureOrigin + Math.ceil((roadTop - textureOrigin) / 22) * 22;
        for (var textureY = firstTextureY; textureY < roadBottom; textureY += 22) {
          fillRect(roadX + edgeWidth, textureY, roadW - edgeWidth * 2, 1, { color: context.color("surfaceAccent"), alpha: 0.15 });
        }
      }
      for (var laneIndex = 1; laneIndex < lanes; laneIndex += 1) {
        var laneX = roadX + roadW / lanes * laneIndex;
        var stripeOrigin = roadY - stripeHeight + (stripeOffset % stripePeriod);
        var firstStripeY = stripeOrigin + Math.floor((roadTop - stripeOrigin) / stripePeriod) * stripePeriod;
        for (
          var stripeY = firstStripeY;
          stripeY < roadBottom;
          stripeY += stripePeriod
        ) {
          var clippedTop = Math.max(roadTop, stripeY);
          var clippedBottom = Math.min(roadBottom, stripeY + stripeHeight);
          if (clippedBottom > clippedTop) {
            fillRect(
              laneX - stripeWidth / 2,
              clippedTop,
              stripeWidth,
              clippedBottom - clippedTop,
              spec.laneFill === undefined ? context.color("lane") : spec.laneFill
            );
          }
        }
      }
    }

    function drawLaneVehicle(spec) {
      var context = resolveAssetContext(spec, "gym-light-default");
      var x = Number(spec.x) || 0;
      var y = Number(spec.y) || 0;
      var w = Number(spec.w) || 36;
      var h = Number(spec.h) || 64;
      var body = spec.fill === undefined ? context.color(spec.hostile ? "hostile" : "vehicle") : spec.fill;
      var trim = spec.trim === undefined ? context.color("text") : spec.trim;
      if (spec.shape === "triangle") {
        fillTriangle([
          { x: x + w / 2, y: y },
          { x: x + w, y: y + h },
          { x: x, y: y + h },
        ], body, trim, spec.lineWidth || 2);
        fillRect(x + w * 0.36, y + h * 0.34, w * 0.28, h * 0.18, context.color("friendlyAccent"));
        return;
      }
      fillRect(x - w * 0.08, y + h * 0.16, w * 0.12, h * 0.2, trim);
      fillRect(x + w * 0.96, y + h * 0.16, w * 0.12, h * 0.2, trim);
      fillRect(x - w * 0.08, y + h * 0.66, w * 0.12, h * 0.2, trim);
      fillRect(x + w * 0.96, y + h * 0.66, w * 0.12, h * 0.2, trim);
      fillRect(x, y, w, h, body, trim, spec.lineWidth || 2);
      fillRect(x + w * 0.18, y + h * 0.16, w * 0.64, h * 0.24, spec.windowFill === undefined ? context.color("friendlyAccent") : spec.windowFill);
      fillRect(x + w * 0.18, y + h * 0.7, w * 0.64, h * 0.09, trim);
      fillRect(x + w * 0.22, y + h * 0.86, w * 0.18, h * 0.06, spec.lightFill || 0xfef3c7);
      fillRect(x + w * 0.6, y + h * 0.86, w * 0.18, h * 0.06, spec.lightFill || 0xfef3c7);
    }

    function withAssetLayer(spec, draw) {
      var previousOffset = assetLayerOffset;
      assetLayerOffset = (Number(spec && spec.layer) || 0) * 10000;
      try {
        return draw();
      } finally {
        assetLayerOffset = previousOffset;
      }
    }

    function drawPrimitiveAsset(type, spec) {
      spec = spec || {};
      return withAssetLayer(spec, function drawPrimitive() {
        if (type === "surface") return drawSurface(spec);
        if (type === "target" || type === "aim_target") return drawAimTarget(spec);
        if (type === "actor") return drawActor(spec);
        if (type === "collectible") return drawCollectible(spec);
        if (type === "hazard") return drawHazard(spec);
        if (type === "trail") return drawTrail(spec);
        if (type === "goal_marker") return drawGoalMarker(spec);
        if (type === "maze_wall") return drawMazeWall(spec);
        if (type === "path_road") return drawPathRoad(spec);
        if (type === "checkpoint_line") return drawCheckpointLine(spec);
        if (type === "arena_vehicle") return drawArenaVehicle(spec);
        if (type === "platform") return drawPlatform(spec);
        if (type === "goal_flag") return drawGoalFlag(spec);
        if (type === "lane_road") return drawLaneRoad(spec);
        if (type === "lane_vehicle" || type === "vehicle") return drawLaneVehicle(spec);
        return null;
      });
    }

    function drawImageAsset(definition, resource, spec) {
      spec = spec || {};
      var size = Array.isArray(definition.size) ? definition.size : [];
      var frame = resource.frame;
      var w = Number(spec.w === undefined ? spec.width : spec.w) || Number(size[0]) || frame[2];
      var h = Number(spec.h === undefined ? spec.height : spec.h) || Number(size[1]) || frame[3];
      var anchor = Array.isArray(spec.anchor) ? spec.anchor : (Array.isArray(definition.anchor) ? definition.anchor : [0.5, 0.5]);
      var x = Number(spec.x) || 0;
      var y = Number(spec.y) || 0;
      return withAssetLayer(spec, function drawImage() {
        var mesh = pooledMesh("image");
        mesh.position.set(x + (0.5 - Number(anchor[0] || 0)) * w, y + (0.5 - Number(anchor[1] || 0)) * h, 0);
        // The camera uses screen coordinates (y down); source images use top-left origin.
        mesh.scale.set(w, -h, 1);
        mesh.rotation.z = Number(spec.rotation === undefined ? spec.angle : spec.rotation) || 0;
        var inset = definition.type === "atlas" && definition.filter === "linear" ? 0.5 : 0;
        var left = (frame[0] + inset) / resource.image.naturalWidth;
        var right = (frame[0] + frame[2] - inset) / resource.image.naturalWidth;
        var top = 1 - (frame[1] + inset) / resource.image.naturalHeight;
        var bottom = 1 - (frame[1] + frame[3] - inset) / resource.image.naturalHeight;
        var uv = mesh.geometry.attributes.uv;
        uv.setXY(0, left, top); uv.setXY(1, right, top);
        uv.setXY(2, left, bottom); uv.setXY(3, right, bottom);
        uv.needsUpdate = true;
        if (mesh.material.map !== resource.texture) {
          mesh.material.map = resource.texture;
          mesh.material.needsUpdate = true;
        }
        mesh.material.color.setHex(parseColor(spec.tint, 0xffffff).color);
        mesh.material.opacity = spec.alpha === undefined ? 1 : Math.max(0, Math.min(1, Number(spec.alpha)));
        mesh.material.transparent = true;
        mesh.userData.assetId = definition.asset_id;
        mesh.userData.assetFrameIndex = resource.frameIndex;
        return mesh;
      });
    }

    function dispose() {
      if (disposed) return;
      disposed = true;
      window.removeEventListener("pagehide", dispose);
      var geometries = new Set([rectGeometry, circleGeometry, triangleGeometry]);
      var materials = new Set();
      var textures = new Set();
      root.traverse(function collect(child) {
        if (child.geometry) geometries.add(child.geometry);
        if (child.material) materials.add(child.material);
      });
      pathGeometries.forEach(function collectGeometry(geometry) { geometries.add(geometry); });
      materials.forEach(function disposeMaterial(material) {
        if (material.map && !AssetEngine.ownsTexture(material.map)) textures.add(material.map);
        material.dispose();
      });
      geometries.forEach(function disposeGeometry(geometry) { geometry.dispose(); });
      textures.forEach(function disposeTexture(texture) { texture.dispose(); });
      pathGeometries.clear();
      root.clear();
      renderer.dispose();
      if (STAGE_VIEWS && STAGE_VIEWS.get(canvas) === stageApi) STAGE_VIEWS.delete(canvas);
    }

    var stageApi = {
      clear: clear,
      render: render,
      dispose: dispose,
      resize: resize,
      resizeViewport: resizeViewport,
      setOrthographicZoom: setOrthographicZoom,
      getOrthographicZoom: getOrthographicZoom,
      getVisibleBounds: getVisibleBounds,
      projectPoint: projectPoint,
      unprojectPoint: unprojectPoint,
      rgba: rgba,
      fillRect: fillRect,
      fillCircle: fillCircle,
      line: line,
      fillPolygon: polygon,
      strokeRect: strokeRect,
      text: text,
      crosshair: crosshair,
      overlay: overlay,
      __drawPrimitiveAsset: drawPrimitiveAsset,
      __drawImageAsset: drawImageAsset,
      renderer: renderer,
      scene: scene,
      camera: camera,
      canvas: canvas,
    };
    if (STAGE_VIEWS) STAGE_VIEWS.set(canvas, stageApi);
    window.addEventListener("pagehide", dispose, { once: true });
    return stageApi;
  }

  function widescreenWidth(height) {
    return Math.max(1, Math.round((Number(height) || 1) * WIDESCREEN_ASPECT));
  }

  function fullscreenRequestedFromUrl() {
    var params;
    try {
      params = new URLSearchParams(window.location.search || "");
    } catch (error) {
      return false;
    }
    var value = String(params.get("fullscreen") || "").trim().toLowerCase();
    return value === "1" || value === "true" || value === "yes" || value === "on";
  }

  function createFullscreenViewport(options) {
    options = options || {};
    var game = options.game || null;
    var canvas = options.canvas || document.querySelector("canvas");
    var root = options.root || document.getElementById("app") || document.querySelector("main.app") || document.querySelector("main") || document.body;
    var shell = options.shell || document.querySelector(".shell") || document.getElementById("layout") || root;
    var stage = options.stage || document.querySelector(".stage") || document.getElementById("stage-frame") || document.getElementById("frame") || (canvas && canvas.parentElement) || root;
    var baseWidth = Math.max(1, Math.round(Number(options.baseWidth) || (canvas && canvas.width) || 640));
    var baseHeight = Math.max(1, Math.round(Number(options.baseHeight) || (canvas && canvas.height) || 640));
    var nativeBaseWidth = baseWidth;
    var nativeBaseHeight = baseHeight;
    var key = String(options.key || "f").toLowerCase();
    var className = options.className || "gamelet-three2d-fullscreen";
    var background = options.background || "#e2e8f0";
    var layoutFullscreen = false;
    var hiddenElements = [];
    var styledElements = [];
    var lastState = {};

    function isolatedDomain() {
      return Core.domains.isActive(game, "camera");
    }

    function activeBaseWidth() {
      return isolatedDomain() ? baseWidth : nativeBaseWidth;
    }

    function activeBaseHeight() {
      return isolatedDomain() ? baseHeight : nativeBaseHeight;
    }

    function rememberStyles(element, styles) {
      if (!element) return;
      var entry = null;
      for (var i = 0; i < styledElements.length; i += 1) {
        if (styledElements[i].element === element) entry = styledElements[i];
      }
      if (!entry) {
        entry = { element: element, styles: {}, previous: {} };
        styledElements.push(entry);
      }
      Object.keys(styles).forEach(function rememberStyle(name) {
        if (!Object.prototype.hasOwnProperty.call(entry.previous, name)) entry.previous[name] = element.style[name] || "";
        entry.styles[name] = styles[name];
      });
    }

    rememberStyles(document.documentElement, { width: "100%", height: "100%", overflow: "hidden", background: background });
    rememberStyles(document.body, { width: "100%", height: "100%", overflow: "hidden", margin: "0", padding: "0", display: "block", background: background });
    rememberStyles(root, { width: "100vw", height: "100vh", minWidth: "0", minHeight: "0", margin: "0", padding: "0", display: "grid", placeItems: "center", background: background });
    rememberStyles(shell, { width: "100vw", height: "100vh", maxWidth: "none", margin: "0", padding: "0", display: "grid", gridTemplateColumns: "1fr", gridTemplateRows: "1fr", placeItems: "center", gap: "0" });
    rememberStyles(stage, { width: "", height: "", margin: "0", padding: "0", maxWidth: "none", maxHeight: "none", outline: "0", alignSelf: "center", justifySelf: "center" });
    rememberStyles(canvas, { width: "", height: "", display: "block", maxWidth: "none", maxHeight: "none", objectFit: "contain" });

    function addHiddenElement(element) {
      if (!element) return;
      for (var i = 0; i < hiddenElements.length; i += 1) {
        if (hiddenElements[i].element === element) return;
      }
      hiddenElements.push({ element: element, display: element.style.display || "" });
    }

    var hideSelectors = options.hideSelectors || [".hud", "#sidebar", ".spacer", "#side-spacer"];
    for (var selectorIndex = 0; selectorIndex < hideSelectors.length; selectorIndex += 1) {
      var matches = document.querySelectorAll(hideSelectors[selectorIndex]);
      for (var matchIndex = 0; matchIndex < matches.length; matchIndex += 1) addHiddenElement(matches[matchIndex]);
    }

    function browserFullscreenElement() {
      return document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement || null;
    }

    function browserFullscreenActive() {
      var element = browserFullscreenElement();
      return !!element && (element === root || element === shell || element === stage || element === canvas || (root && root.contains && root.contains(element)));
    }

    function active() {
      return layoutFullscreen || browserFullscreenActive();
    }

    function fitSize() {
      var logicalWidth = activeBaseWidth();
      var logicalHeight = activeBaseHeight();
      var viewportWidth = Math.max(1, Number(window.innerWidth) || logicalWidth);
      var viewportHeight = Math.max(1, Number(window.innerHeight) || logicalHeight);
      var scale = Math.min(viewportWidth / logicalWidth, viewportHeight / logicalHeight);
      var fittedWidth = Math.max(1, Math.floor(logicalWidth * scale));
      var fittedHeight = Math.max(1, Math.floor(logicalHeight * scale));
      if (viewportWidth - fittedWidth <= 1) fittedWidth = viewportWidth;
      if (viewportHeight - fittedHeight <= 1) fittedHeight = viewportHeight;
      return {
        width: fittedWidth,
        height: fittedHeight,
      };
    }

    function classTargets() {
      return [document.documentElement, document.body, root, shell, stage, canvas];
    }

    function applyLayout(isActive) {
      var targets = classTargets();
      for (var i = 0; i < targets.length; i += 1) {
        if (!targets[i] || !targets[i].classList) continue;
        targets[i].classList.toggle(className, isActive);
      }
      for (var entryIndex = 0; entryIndex < styledElements.length; entryIndex += 1) {
        var entry = styledElements[entryIndex];
        Object.keys(entry.styles).forEach(function applyStyle(name) {
          entry.element.style[name] = isActive ? entry.styles[name] : entry.previous[name];
        });
      }
      for (var hiddenIndex = 0; hiddenIndex < hiddenElements.length; hiddenIndex += 1) {
        hiddenElements[hiddenIndex].element.style.display = isActive ? "none" : hiddenElements[hiddenIndex].display;
      }
    }

    function updateViewport() {
      var isActive = active();
      var logicalWidth = activeBaseWidth();
      var logicalHeight = activeBaseHeight();
      var size = isActive ? fitSize() : { width: logicalWidth, height: logicalHeight };
      if (isActive) {
        stage.style.width = size.width + "px";
        stage.style.height = size.height + "px";
        canvas.style.width = size.width + "px";
        canvas.style.height = size.height + "px";
      }
      var state = {
        active: isActive,
        browser_fullscreen: browserFullscreenActive(),
        layout_fullscreen: layoutFullscreen,
        width: isolatedDomain() ? logicalWidth : size.width,
        height: isolatedDomain() ? logicalHeight : size.height,
        aspect: isolatedDomain() ? logicalWidth / logicalHeight : size.width / size.height,
        base_width: logicalWidth,
        base_height: logicalHeight,
        key: key,
      };
      if (isolatedDomain()) {
        state.display_width = size.width;
        state.display_height = size.height;
      }
      lastState = state;
      return lastState;
    }

    function applyActiveState(isActive) {
      layoutFullscreen = !!isActive;
      applyLayout(layoutFullscreen || browserFullscreenActive());
      return updateViewport();
    }

    function requestBrowserFullscreen() {
      var target = root || shell || stage || canvas;
      var request = target && (target.requestFullscreen || target.webkitRequestFullscreen || target.mozRequestFullScreen || target.msRequestFullscreen);
      if (typeof request !== "function") return null;
      try {
        return request.call(target);
      } catch (error) {
        return null;
      }
    }

    function exitBrowserFullscreen() {
      var exitMethod = document.exitFullscreen || document.webkitExitFullscreen || document.mozCancelFullScreen || document.msExitFullscreen;
      if (typeof exitMethod !== "function") return null;
      try {
        return exitMethod.call(document);
      } catch (error) {
        return null;
      }
    }

    function enter() {
      applyActiveState(true);
      var request = requestBrowserFullscreen();
      if (request && typeof request.catch === "function") {
        request.catch(function keepLayoutFullscreen() { applyActiveState(true); });
      }
      return getState();
    }

    function enterLayout() {
      return applyActiveState(true);
    }

    function exit() {
      layoutFullscreen = false;
      if (browserFullscreenActive()) exitBrowserFullscreen();
      return applyActiveState(false);
    }

    function toggle() {
      return active() ? exit() : enter();
    }

    function onKeyDown(event) {
      if (event.defaultPrevented || event.repeat) return;
      var tag = event && event.target && event.target.tagName ? String(event.target.tagName).toLowerCase() : "";
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      if (String(event.key || "").toLowerCase() !== key) return;
      event.preventDefault();
      toggle();
    }

    function onFullscreenChange() {
      layoutFullscreen = browserFullscreenActive();
      applyLayout(layoutFullscreen);
      updateViewport();
    }

    function onWindowResize() {
      if (active()) updateViewport();
    }

    function getState() {
      return Object.assign({}, lastState);
    }

    function configure(viewport) {
      var next = viewport || {};
      baseWidth = Math.max(1, Math.round(Number(next.width) || baseWidth));
      baseHeight = Math.max(1, Math.round(Number(next.height) || baseHeight));
      return updateViewport();
    }

    function destroy() {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onWindowResize);
      document.removeEventListener("fullscreenchange", onFullscreenChange);
      document.removeEventListener("webkitfullscreenchange", onFullscreenChange);
      document.removeEventListener("mozfullscreenchange", onFullscreenChange);
      document.removeEventListener("MSFullscreenChange", onFullscreenChange);
      applyActiveState(false);
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onWindowResize);
    document.addEventListener("fullscreenchange", onFullscreenChange);
    document.addEventListener("webkitfullscreenchange", onFullscreenChange);
    document.addEventListener("mozfullscreenchange", onFullscreenChange);
    document.addEventListener("MSFullscreenChange", onFullscreenChange);
    updateViewport();
    if (options.startFullscreen) enterLayout();

    return {
      enter: enter,
      enterLayout: enterLayout,
      exit: exit,
      toggle: toggle,
      resize: updateViewport,
      configure: configure,
      isActive: active,
      getState: getState,
      destroy: destroy,
    };
  }

  function viewportPayload(game, fallback) {
    if (game && game.fullscreenViewport && typeof game.fullscreenViewport.getState === "function") {
      return game.fullscreenViewport.getState();
    }
    fallback = fallback || {};
    var width = fallback.baseWidth || 640;
    var height = fallback.baseHeight || 640;
    return {
      active: false,
      browser_fullscreen: false,
      layout_fullscreen: false,
      width: width,
      height: height,
      aspect: width / height,
      base_width: width,
      base_height: height,
      key: fallback.key || "f",
    };
  }

  function installFullscreenForGame(game, options) {
    options = options || {};
    if (!game) return null;
    if (game.fullscreenViewport && typeof game.fullscreenViewport.getState === "function") {
      return game.fullscreenViewport;
    }
    var canvas = options.canvas || game.canvas || document.querySelector("canvas");
    var baseWidth = options.baseWidth || (canvas && canvas.width) || 640;
    var baseHeight = options.baseHeight || (canvas && canvas.height) || 640;
    var controller = createFullscreenViewport({
      game: game,
      canvas: canvas,
      root: options.root,
      shell: options.shell,
      stage: options.stage,
      baseWidth: baseWidth,
      baseHeight: baseHeight,
      key: options.key || "f",
      background: options.background,
      hideSelectors: options.hideSelectors,
      startFullscreen: options.startFullscreen === undefined ? fullscreenRequestedFromUrl() : !!options.startFullscreen,
    });
    game.fullscreenViewport = controller;
    game.viewportPayload = function gameViewportPayload() {
      return viewportPayload(game, { baseWidth: baseWidth, baseHeight: baseHeight, key: options.key || "f" });
    };
    game.toggleFullscreen = function toggleFullscreen() { return controller.toggle(); };
    game.enterFullscreen = function enterFullscreen() { return controller.enter(); };
    game.exitFullscreen = function exitFullscreen() { return controller.exit(); };
    return controller;
  }

  function addFullscreenAPI(api, game) {
    if (!api || !game) return api;
    api.toggleFullscreen = function toggleFullscreen() {
      return typeof game.toggleFullscreen === "function" ? game.toggleFullscreen() : viewportPayload(game);
    };
    api.enterFullscreen = function enterFullscreen() {
      return typeof game.enterFullscreen === "function" ? game.enterFullscreen() : viewportPayload(game);
    };
    api.exitFullscreen = function exitFullscreen() {
      return typeof game.exitFullscreen === "function" ? game.exitFullscreen() : viewportPayload(game);
    };
    api.getFullscreenState = function getFullscreenState() { return viewportPayload(game); };
    return api;
  }

  function getCaptureCanvas(game) {
    if (game && game.canvas && typeof game.canvas.toDataURL === "function") return game.canvas;
    var canvas = document.getElementById("display") || document.querySelector("canvas");
    return canvas && typeof canvas.toDataURL === "function" ? canvas : null;
  }

  function attachRuntime(runtime, game) {
    if (!runtime || !game) return runtime;
    installFullscreenForGame(game);
    runtime.capabilities.supports_fullscreen = true;
    addFullscreenAPI(runtime.gameGymAPI, game);
    addFullscreenAPI(runtime.gameAPI, game);
    return runtime;
  }

  function clientToLogic(canvas, clientX, clientY, logicWidth, logicHeight) {
    var rect = canvas.getBoundingClientRect();
    var width = Math.max(1, Number(logicWidth) || 640);
    var height = Math.max(1, Number(logicHeight) || 640);
    var scale = Math.min(rect.width / width, rect.height / height);
    var offsetX = (rect.width - width * scale) / 2;
    var offsetY = (rect.height - height * scale) / 2;
    var point = {
      x: (clientX - rect.left - offsetX) / scale,
      y: (clientY - rect.top - offsetY) / scale,
    };
    var stage = STAGE_VIEWS && STAGE_VIEWS.get(canvas);
    if (stage && typeof stage.unprojectPoint === "function") point = stage.unprojectPoint(point.x, point.y);
    return {
      x: Math.max(0, Math.min(width, point.x)),
      y: Math.max(0, Math.min(height, point.y)),
    };
  }

  function relativeDeltaToLogic(stage, value, axis) {
    if (!stage || typeof stage.getVisibleBounds !== "function") {
      throw new Error("relative pointer input requires the active 2D stage visible bounds");
    }
    var numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric < -1000 || numeric > 1000) {
      throw new Error("relative pointer delta must be in [-1000, 1000]");
    }
    var bounds = stage.getVisibleBounds();
    var span = axis === "y" ? Number(bounds.height) : Number(bounds.width);
    if (!Number.isFinite(span) || span <= 0) {
      throw new Error("relative pointer input requires positive visible game dimensions");
    }
    return numeric / 1000 * span;
  }

  function clampPointToVisibleBounds(stage, x, y, logicWidth, logicHeight) {
    if (!stage || typeof stage.getVisibleBounds !== "function") {
      throw new Error("pointer position requires the active 2D stage visible bounds");
    }
    var bounds = stage.getVisibleBounds();
    var left = Math.max(0, Number(bounds.left));
    var top = Math.max(0, Number(bounds.top));
    var right = Math.min(Math.max(1, Number(logicWidth)), Number(bounds.right));
    var bottom = Math.min(Math.max(1, Number(logicHeight)), Number(bounds.bottom));
    if (![left, top, right, bottom].every(Number.isFinite) || right < left || bottom < top) {
      throw new Error("pointer position requires valid visible game bounds");
    }
    return {
      x: Math.max(left, Math.min(right, Number(x))),
      y: Math.max(top, Math.min(bottom, Number(y))),
    };
  }

  function renderViewportState(game, logicalWidth, logicalHeight) {
    var fallbackWidth = Math.max(1, Math.round(Number(logicalWidth) || 640));
    var fallbackHeight = Math.max(1, Math.round(Number(logicalHeight) || 640));
    var current = game && game.renderViewport ? game.renderViewport : {};
    var width = Math.max(1, Math.round(Number(current.width) || fallbackWidth));
    var height = Math.max(1, Math.round(Number(current.height) || fallbackHeight));
    return {
      width: width,
      height: height,
      aspect: width / height,
      displayWidth: Math.max(1, Math.round(Number(current.display_width) || width)),
      displayHeight: Math.max(1, Math.round(Number(current.display_height) || height)),
      logicalWidth: Math.max(1, Math.round(Number(current.logical_width) || fallbackWidth)),
      logicalHeight: Math.max(1, Math.round(Number(current.logical_height) || fallbackHeight)),
    };
  }

  function bindAssetView(viewSource) {
    if (!viewSource) throw new Error("2D asset binding requires a view or view provider");
    return function createBoundAsset(assetId, options) {
      var view = typeof viewSource === "function" ? viewSource() : viewSource;
      return AssetEngine.api.create(assetId, Object.assign({ view: view }, options || {}));
    };
  }

  AssetEngine.bindAdapter({
    createPrimitive: function createPrimitive(definition, options) {
      if (!options.view || typeof options.view.__drawPrimitiveAsset !== "function") {
        throw new Error("2D asset creation requires options.view");
      }
      return options.view.__drawPrimitiveAsset(definition.primitive, options);
    },
    createImage: function createImage(definition, resource, options) {
      if (!options.view || typeof options.view.__drawImageAsset !== "function") {
        throw new Error("2D image asset creation requires options.view");
      }
      return options.view.__drawImageAsset(definition, resource, options);
    },
  });

  var assetsApi = Object.freeze(Object.assign({}, AssetEngine.api, {
    bindView: bindAssetView,
  }));

  window.BaseGameletThree2D = Object.freeze({
    threeRevision: REQUIRED_THREE_REVISION,
    createStage: createStage,
    attachRuntime: attachRuntime,
    getCaptureCanvas: getCaptureCanvas,
    assets: assetsApi,
    visuals: Object.freeze({
      configure: configureGameVisuals,
      sync: syncGameVisuals,
      assetPayload: assetPayload,
    }),
    camera: Object.freeze({
      minZoom: ORTHOGRAPHIC_ZOOM_MIN,
      maxZoom: ORTHOGRAPHIC_ZOOM_MAX,
      projectionSampler: sampleOrthographicProjection,
      projectionValidator: validateOrthographicProjection,
      sync: syncOrthographicCamera,
    }),
    input: Object.freeze({
      relativeDeltaToLogic: relativeDeltaToLogic,
      clampPointToVisibleBounds: clampPointToVisibleBounds,
    }),
    viewport: Object.freeze({
      aspect: WIDESCREEN_ASPECT,
      baseWidth: PRESENTATION_WIDTH,
      baseHeight: PRESENTATION_HEIGHT,
      widthForHeight: widescreenWidth,
      clientToLogic: clientToLogic,
      state: renderViewportState,
    }),
  });
})();
