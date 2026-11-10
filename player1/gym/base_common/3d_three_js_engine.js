(function threeJs3DEngineModule() {
  "use strict";

  var Engine = window.BaseGameletCommon;
  var EngineMath = Engine.math;
  var Core = window.GameEngineCore;
  var AssetEngine = window.GameAssetEngine3D;
  var PRESENTATION_WIDTH = 960;
  var PRESENTATION_HEIGHT = 540;
  if (!AssetEngine) throw new Error("3d_asset_engine.js must load before 3d_three_js_engine.js");
  var REQUIRED_THREE_REVISION = "185";
  // r185 removed legacy-light mode. This calibrated scale preserves the r83
  // no-perturbation appearance while retaining the modern renderer.
  var LEGACY_LIGHT_INTENSITY_SCALE = Math.PI;

  function finiteNumber(value, fallback) {
    var numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : fallback;
  }

  function computeOpticalChasePose(pose, rigDomain) {
    pose = pose || {};
    rigDomain = rigDomain || {};
    var yaw = finiteNumber(pose.yaw, 0);
    var pitchDown = finiteNumber(pose.pitch, 0) + finiteNumber(rigDomain.pitch_offset_radians, 0);
    var heightScale = finiteNumber(rigDomain.height_scale, 1);
    var distanceScale = finiteNumber(rigDomain.distance_scale, 1);
    var distance = Math.max(0, finiteNumber(pose.distance, 3.2) * distanceScale);
    var x = finiteNumber(pose.x, 0);
    var z = finiteNumber(pose.z, 0);
    var lookHeight = finiteNumber(pose.lookHeight, 0.7) * heightScale;
    var forwardLook = finiteNumber(pose.forwardLook, 0.8);
    var shoulderOffset = finiteNumber(pose.shoulderOffset, 0);
    var cosYaw = Math.cos(yaw);
    var sinYaw = Math.sin(yaw);
    var cosPitch = Math.cos(pitchDown);
    var direction = {
      x: cosYaw * cosPitch,
      y: -Math.sin(pitchDown),
      z: sinYaw * cosPitch,
    };
    var anchor = {
      x: x + cosYaw * forwardLook - sinYaw * shoulderOffset,
      y: lookHeight,
      z: z + sinYaw * forwardLook + cosYaw * shoulderOffset,
    };
    var bounds = pose.bounds || null;
    if (bounds) {
      anchor.x = EngineMath.clamp(anchor.x, finiteNumber(bounds.minX, anchor.x), finiteNumber(bounds.maxX, anchor.x));
      anchor.z = EngineMath.clamp(anchor.z, finiteNumber(bounds.minZ, anchor.z), finiteNumber(bounds.maxZ, anchor.z));
    }

    var appliedDistance = distance;
    if (bounds) {
      var cameraDeltaX = -direction.x;
      var cameraDeltaZ = -direction.z;
      if (cameraDeltaX > 1e-9) {
        appliedDistance = Math.min(appliedDistance, (finiteNumber(bounds.maxX, anchor.x) - anchor.x) / cameraDeltaX);
      } else if (cameraDeltaX < -1e-9) {
        appliedDistance = Math.min(appliedDistance, (finiteNumber(bounds.minX, anchor.x) - anchor.x) / cameraDeltaX);
      }
      if (cameraDeltaZ > 1e-9) {
        appliedDistance = Math.min(appliedDistance, (finiteNumber(bounds.maxZ, anchor.z) - anchor.z) / cameraDeltaZ);
      } else if (cameraDeltaZ < -1e-9) {
        appliedDistance = Math.min(appliedDistance, (finiteNumber(bounds.minZ, anchor.z) - anchor.z) / cameraDeltaZ);
      }
      appliedDistance = Math.max(0, appliedDistance);
    }

    return {
      yaw: yaw,
      pitchDown: pitchDown,
      anchor: anchor,
      direction: direction,
      camera: {
        x: anchor.x - direction.x * appliedDistance,
        y: anchor.y - direction.y * appliedDistance,
        z: anchor.z - direction.z * appliedDistance,
      },
      requestedDistance: distance,
      appliedDistance: appliedDistance,
      distanceClipped: appliedDistance < distance - 1e-9,
    };
  }

  function hasThree() {
    return typeof window.THREE !== "undefined"
      && String(window.THREE.REVISION) === REQUIRED_THREE_REVISION;
  }

  function legacyLightIntensity(value, scale) {
    return Number(value || 0) * (Number(scale) || LEGACY_LIGHT_INTENSITY_SCALE);
  }

  var INDOOR_FLOOR_COLOR = 0xd8d8d8;
  var ENVIRONMENT_ROLES = Object.freeze({
    sky: true,
    background: true,
    floor: true,
    floorAccent: true,
    floorLine: true,
    wall: true,
    wallAccent: true,
    trim: true,
    metal: true,
    darkMetal: true,
    glass: true,
    cover: true,
    coverAccent: true,
    road: true,
    roadEdge: true,
    lane: true,
    verge: true,
    vergeAccent: true,
    vergeDark: true,
    vergeDarkAccent: true,
    sea: true,
    sand: true,
  });

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

  function mixColor(a, b, amount) {
    var t = Math.max(0, Math.min(1, Number(amount) || 0));
    var ar = (a >> 16) & 255;
    var ag = (a >> 8) & 255;
    var ab = a & 255;
    var br = (b >> 16) & 255;
    var bg = (b >> 8) & 255;
    var bb = b & 255;
    return (
      (Math.round(ar + (br - ar) * t) << 16)
      | (Math.round(ag + (bg - ag) * t) << 8)
      | Math.round(ab + (bb - ab) * t)
    ) >>> 0;
  }

  function colorCss(color) {
    return "#" + (Number(color) >>> 0).toString(16).padStart(6, "0").slice(-6);
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
    function color(role, fallback) {
      var source = flags.entityColor && pack.alternatePalette[role] !== undefined
        ? pack.alternatePalette
        : palette;
      var value = source[role];
      if (value === undefined) value = palette[role];
      if (value === undefined) value = fallback === undefined ? 0xffffff : fallback;
      var environment = !!ENVIRONMENT_ROLES[role];
      if ((environment && flags.bgColor)
        || (!environment && flags.entityColor && pack.alternatePalette[role] === undefined)) {
        value = Core.perturbations.transformColor(value, Core.visuals.colorSample(seed, environment));
      }
      return isolated
        ? Core.perturbations.transformColor(
          value,
          ENVIRONMENT_ROLES[role] ? backgroundSample : paletteSample
        )
        : value >>> 0;
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
      color: color,
      surface: function surface(role, fallback) {
        return surfaces[role] || fallback || "concrete";
      },
      textureUrl: function textureUrl(role) { return pack.textures[role] || null; },
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
    if (!game) return createAssetContext({ assetPack: defaultPack || "gym-light-default" });
    var config = Object.assign({}, game.currentConfig || game.urlConfig || {}, game.visualConfig || {});
    var visualFlags = game.visualPerturbations && game.visualPerturbations.active;
    var isolated = Core.domains.isActive(game, "appearance");
    var assetOptions = {
      assetPack: defaultPack || "gym-light-default",
      seed: game.seed === undefined ? config.seed : game.seed,
      domainMode: isolated ? "isolated" : "legacy",
      visualFlags: visualFlags,
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
    if (game.world3d) applyAssetContextToWorld(game.world3d, game.assetContext);
    return game.assetContext;
  }

  function configureGameVisuals(game, config, options) {
    if (!game) return null;
    var source = config || {};
    var dimensions = options || {};
    game.visualConfig = {
      seed: source.seed,
      visualFlags: Core.visuals.cloneFlags(source.visualFlags),
    };
    game.visualDimensions = {
      baseWidth: Number(dimensions.baseWidth) || 640,
      baseHeight: Number(dimensions.baseHeight) || 640,
      defaultAssetPack: dimensions.defaultAssetPack || "gym-light-default",
    };
    game.visualPerturbations = {
      active: Core.visuals.cloneFlags(),
    };
    game.__visualSceneReady = false;
    return syncGameVisuals(game, { forceAssets: true, rebuild: false, stepCount: 0 });
  }

  function applyDomainCamera(game) {
    if (!game || !game.world3d || !Core.domains.isActive(game, "camera")) return null;
    var world = game.world3d;
    var projection = Core.domains.sample(game, "camera", "projection", { fov_offset_degrees: 0 }) || {};
    var rig = Core.domains.sample(game, "camera", "rig", {
      height_scale: 1,
      distance_scale: 1,
      pitch_offset_radians: 0,
    });
    var fovOffset = Number(projection.fov_offset_degrees) || 0;
    var controller = game.fullscreenViewport || null;
    var signature = JSON.stringify({
      fov_offset_degrees: fovOffset,
      rig: rig,
    });

    if (
      game.__domainCameraSignature === signature
      && game.__domainCameraWorld === world
      && game.__domainCameraController === controller
    ) {
      return game.renderViewport;
    }
    if (typeof world.setCameraRigDomain === "function") world.setCameraRigDomain(rig);
    if (controller && typeof controller.configureCameraDomain === "function") {
      game.renderViewport = controller.configureCameraDomain({
        fov_offset_degrees: fovOffset,
      }, { render: false });
    } else {
      var baseFov = typeof world.getBaseFov === "function" ? world.getBaseFov() : world.getFov();
      world.setFov(Math.max(20, Math.min(120, baseFov + fovOffset)));
      var size = typeof world.getSize === "function" ? world.getSize() : { width: 640, height: 640, aspect: 1 };
      game.renderViewport = {
        active: false,
        width: size.width,
        height: size.height,
        aspect: size.aspect,
        fov: world.getFov(),
      };
    }
    game.__domainCameraSignature = signature;
    game.__domainCameraWorld = world;
    game.__domainCameraController = controller;
    return game.renderViewport;
  }

  function restoreLegacyDomains(game) {
    if (!game || !game.world3d || !game.__domainCameraSignature) return;
    if (typeof game.world3d.setCameraRigDomain === "function") {
      game.world3d.setCameraRigDomain(null);
    }
    if (game.fullscreenViewport && typeof game.fullscreenViewport.configureCameraDomain === "function") {
      game.fullscreenViewport.configureCameraDomain(null, { render: false });
    } else if (typeof game.world3d.setFov === "function" && typeof game.world3d.getBaseFov === "function") {
      game.world3d.setFov(game.world3d.getBaseFov());
    }
    game.renderViewport = null;
    game.__domainCameraSignature = null;
    game.__domainCameraWorld = null;
    game.__domainCameraController = null;
  }

  function syncGameVisuals(game, options) {
    if (!game || !game.visualConfig) return visualPayload(game);
    var opts = options || {};
    var next = Core.perturbations.visualPayload(game, Core.visuals.state(game.visualConfig, {}));
    var previousLabel = Core.visuals.label(game.visualPerturbations && game.visualPerturbations.active);
    var visualChanged = previousLabel !== Core.visuals.label(next.active);
    var appearanceActive = Core.domains.isActive(game, "appearance");
    var cameraActive = Core.domains.isActive(game, "camera");
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

    if (opts.forceAssets || visualChanged || appearanceChanged) {
      configureGameAssets(game, game.visualDimensions.defaultAssetPack);
    }

    Core.visuals.applyLayout(
      next.active,
      game.visualDimensions.baseWidth,
      game.visualDimensions.baseHeight,
    );
    if (cameraActive) applyDomainCamera(game);
    else restoreLegacyDomains(game);

    if (visualChanged && game.__visualSceneReady && opts.rebuild !== false && typeof game.rebuildScene3D === "function") {
      game.rebuildScene3D();
    }
    if (opts.sceneReady) game.__visualSceneReady = true;
    next.asset = game.assetContext ? game.assetContext.payload() : null;
    return next;
  }

  function visualPayload(game) {
    if (!game || !game.visualConfig) {
      return Core.perturbations.visualPayload(game, Core.visuals.buildPayload({}));
    }
    return Core.perturbations.visualPayload(game, Core.visuals.state(game.visualConfig, {
      asset: game.assetContext ? game.assetContext.payload() : null,
    }));
  }

  function createSurfaceTexture(context, role, options) {
    if (!hasThree() || typeof document === "undefined") return null;
    context = context || createAssetContext();
    options = options || {};
    var preloadedTexture = AssetEngine.getTexture(context.id, role);
    var texture;
    if (preloadedTexture) {
      // Share image data while keeping repeat/wrap descriptors local to this surface.
      texture = preloadedTexture.clone();
      texture.needsUpdate = true;
    } else {
      var canvas = document.createElement("canvas");
      var size = Math.max(32, Math.round(Number(options.size) || 128));
      canvas.width = size;
      canvas.height = size;
      var ctx = canvas.getContext("2d");
      var base = options.baseColor === undefined ? context.color(role, 0x808080) : options.baseColor;
      var accent = options.accentColor === undefined ? context.color(role + "Accent", mixColor(base, 0xffffff, 0.22)) : options.accentColor;
      var dark = mixColor(base, 0x000000, 0.24);
      var pattern = options.pattern || context.surface(role, role === "road" ? "asphalt" : "concrete");
      ctx.fillStyle = colorCss(base);
      ctx.fillRect(0, 0, size, size);
      var surfaceSeed = context.baseSeed;
      var randomState = (
        (Number(surfaceSeed) >>> 0)
        ^ stableHash(context.id + ":" + role + ":standard")
      ) >>> 0;
      function random() {
        randomState = (Math.imul(randomState, 1664525) + 1013904223) >>> 0;
        return randomState / 4294967296;
      }
      var speckleCount = 130;
      for (var i = 0; i < speckleCount; i += 1) {
        var shade = random() > 0.48 ? accent : dark;
        ctx.globalAlpha = 0.12;
        ctx.fillStyle = colorCss(shade);
        var radius = 0.6 + random() * 1.4;
        ctx.fillRect(random() * size, random() * size, radius, radius);
      }
      ctx.globalAlpha = 1;
      if (pattern === "panels" || pattern === "metal") {
        ctx.strokeStyle = colorCss(pattern === "metal" ? dark : accent);
        ctx.globalAlpha = 0.32;
        ctx.lineWidth = 2;
        var panel = size / 4;
        for (var p = panel; p < size; p += panel) {
          ctx.beginPath(); ctx.moveTo(p, 0); ctx.lineTo(p, size); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(0, p); ctx.lineTo(size, p); ctx.stroke();
        }
      } else if (pattern === "asphalt") {
        ctx.strokeStyle = colorCss(mixColor(base, accent, 0.45));
        ctx.globalAlpha = 0.24;
        ctx.lineWidth = 1;
        for (var crack = 0; crack < 9; crack += 1) {
          var x = random() * size;
          var y = random() * size;
          ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + (random() - 0.5) * 20, y + random() * 22); ctx.stroke();
        }
      } else if (pattern === "ground") {
        ctx.strokeStyle = colorCss(accent);
        ctx.globalAlpha = 0.28;
        for (var blade = 0; blade < 90; blade += 1) {
          var bx = random() * size;
          var by = random() * size;
          ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(bx + (random() - 0.5) * 3, by - 2 - random() * 4); ctx.stroke();
        }
      } else if (pattern === "stone") {
        ctx.strokeStyle = colorCss(dark);
        ctx.globalAlpha = 0.3;
        ctx.lineWidth = 2;
        for (var row = 0; row < 4; row += 1) {
          var rowY = (row + 1) * size / 4;
          ctx.beginPath(); ctx.moveTo(0, rowY); ctx.lineTo(size, rowY); ctx.stroke();
          for (var joint = row % 2 ? size / 4 : size / 8; joint < size; joint += size / 2) {
            ctx.beginPath(); ctx.moveTo(joint, rowY - size / 4); ctx.lineTo(joint, rowY); ctx.stroke();
          }
        }
      } else if (pattern === "tiles") {
        ctx.strokeStyle = colorCss(mixColor(base, 0x6b7280, 0.58));
        ctx.globalAlpha = 0.18;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0.5, 0);
        ctx.lineTo(0.5, size);
        ctx.moveTo(0, 0.5);
        ctx.lineTo(size, 0.5);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      texture = new THREE.CanvasTexture(canvas);
    }
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(
      Math.max(0.01, Number(options.repeatX) || 1),
      Math.max(0.01, Number(options.repeatY) || 1)
    );
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.needsUpdate = true;
    return texture;
  }

  function material(options) {
    options = options || {};
    return new THREE.MeshPhongMaterial({
      color: options.color === undefined ? 0xffffff : options.color,
      emissive: options.emissive === undefined ? 0x000000 : options.emissive,
      shininess: options.shininess === undefined ? 24 : options.shininess,
      specular: options.specular === undefined ? 0x1f2937 : options.specular,
      side: options.side || THREE.FrontSide,
      map: options.map || null,
      transparent: options.transparent === true || (options.opacity !== undefined && options.opacity < 1),
      opacity: options.opacity === undefined ? 1 : options.opacity,
      depthWrite: options.depthWrite !== false,
      flatShading: options.flatShading === true,
    });
  }

  function standardMaterial(options) {
    options = options || {};
    return new THREE.MeshStandardMaterial({
      color: options.color === undefined ? 0xffffff : options.color,
      emissive: options.emissive === undefined ? 0x000000 : options.emissive,
      emissiveIntensity: options.emissiveIntensity === undefined ? 1 : options.emissiveIntensity,
      roughness: options.roughness === undefined ? 0.78 : options.roughness,
      metalness: options.metalness === undefined ? 0.05 : options.metalness,
      side: options.side === undefined ? THREE.FrontSide : options.side,
      map: options.map || null,
      transparent: options.transparent === true || (options.opacity !== undefined && options.opacity < 1),
      opacity: options.opacity === undefined ? 1 : options.opacity,
      depthWrite: options.depthWrite !== false,
      flatShading: options.flatShading === true,
    });
  }

  // A small, fixed studio environment gives GLB metals and rough surfaces a
  // stable reflection source without a network dependency or dynamic capture.
  function createStudioEnvironment(renderer) {
    var width = 128;
    var height = 64;
    var pixels = new Uint8Array(width * height * 4);
    for (var y = 0; y < height; y += 1) {
      var sky = 1 - y / (height - 1);
      for (var x = 0; x < width; x += 1) {
        var panel = y > 10 && y < 25 && ((x > 18 && x < 37) || (x > 85 && x < 104));
        var offset = (y * width + x) * 4;
        pixels[offset] = panel ? 255 : Math.round(72 + sky * 132);
        pixels[offset + 1] = panel ? 250 : Math.round(80 + sky * 138);
        pixels[offset + 2] = panel ? 238 : Math.round(88 + sky * 147);
        pixels[offset + 3] = 255;
      }
    }
    var source = new THREE.DataTexture(pixels, width, height, THREE.RGBAFormat);
    source.colorSpace = THREE.SRGBColorSpace;
    source.mapping = THREE.EquirectangularReflectionMapping;
    source.needsUpdate = true;
    var generator = new THREE.PMREMGenerator(renderer);
    var environment = generator.fromEquirectangular(source);
    source.dispose();
    generator.dispose();
    return environment;
  }

  function setShadow(mesh) {
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    return mesh;
  }

  function disposeMaterial(materialValue, resources) {
    if (Array.isArray(materialValue)) {
      for (var i = 0; i < materialValue.length; i += 1) disposeMaterial(materialValue[i], resources);
      return;
    }
    if (!materialValue || AssetEngine.ownsResource(materialValue)) return;
    resources = resources || { textures: [], materials: [], geometries: [] };
    if (resources.materials.indexOf(materialValue) >= 0) return;
    resources.materials.push(materialValue);
    Object.keys(materialValue).forEach(function disposeTextureProperty(name) {
      var value = materialValue[name];
      if (!value || value.isTexture !== true || AssetEngine.ownsResource(value) || resources.textures.indexOf(value) >= 0) return;
      resources.textures.push(value);
      if (typeof value.dispose === "function") value.dispose();
    });
    if (typeof materialValue.dispose === "function") materialValue.dispose();
  }

  function disposeObject(object, resources) {
    if (!object) return;
    resources = resources || { textures: [], materials: [], geometries: [] };
    function disposeChild(child) {
      AssetEngine.releaseInstance(child);
      // Instance attributes are owned by the mesh, independently of geometry/materials.
      if (child.isInstancedMesh && typeof child.dispose === "function") child.dispose();
      if (child.geometry && !AssetEngine.ownsResource(child.geometry) && resources.geometries.indexOf(child.geometry) < 0) {
        resources.geometries.push(child.geometry);
        if (typeof child.geometry.dispose === "function") child.geometry.dispose();
      }
      disposeMaterial(child.material, resources);
    }
    if (typeof object.traverse === "function") object.traverse(disposeChild);
    else disposeChild(object);
  }

  function removeObject(object, parent) {
    if (!object) return false;
    var owner = parent || object.parent;
    if (owner && typeof owner.remove === "function") owner.remove(object);
    disposeObject(object);
    return true;
  }

  function createWorld(canvas, options) {
    if (!hasThree()) return null;
    options = options || {};
    var stylized = options.visualProfile === "stylized";
    THREE.ColorManagement.enabled = stylized;
    var lightIntensityScale = stylized ? 1 : (Number(options.legacyLightScale) || LEGACY_LIGHT_INTENSITY_SCALE);
    var width = options.width || 640;
    var height = options.height || 640;
    var renderWidth = width;
    var renderHeight = height;
    var baseFov = options.fov || 68;
    var cameraRigDomain = {
      height_scale: 1,
      distance_scale: 1,
      pitch_offset_radians: 0,
    };
    var renderer;
    try {
      renderer = new THREE.WebGLRenderer({
        canvas: canvas,
        antialias: true,
        alpha: false,
        preserveDrawingBuffer: true,
      });
    } catch (error) {
      return null;
    }
    renderer.setPixelRatio(1);
    renderer.setSize(width, height, false);
    renderer.setClearColor(options.clearColor === undefined ? 0xdbeafe : options.clearColor, 1);
    renderer.outputColorSpace = stylized ? THREE.SRGBColorSpace : THREE.LinearSRGBColorSpace;
    if (stylized) {
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = options.exposure === undefined ? 1.05 : Number(options.exposure);
    }
    if (renderer.shadowMap) {
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    }

    var scene = new THREE.Scene();
    var studioEnvironment = stylized ? createStudioEnvironment(renderer) : null;
    if (studioEnvironment) {
      scene.environment = studioEnvironment.texture;
      scene.environmentIntensity = 0.65;
    }

    var camera = new THREE.PerspectiveCamera(baseFov, width / height, options.near || 0.05, options.far || 80);
    scene.add(camera);
    var root = new THREE.Group();
    scene.add(root);

    var ambient = new THREE.AmbientLight(
      0xffffff,
      legacyLightIntensity(options.ambient === undefined ? 0.48 : options.ambient, lightIntensityScale)
    );
    scene.add(ambient);

    var sun = new THREE.DirectionalLight(
      0xffffff,
      legacyLightIntensity(options.sun === undefined ? 0.92 : options.sun, lightIntensityScale)
    );
    sun.position.set(-4, 8, -5);
    if (Array.isArray(options.sunPosition)) sun.position.fromArray(options.sunPosition);
    sun.castShadow = true;
    if (sun.shadow && sun.shadow.camera) {
      sun.shadow.camera.left = -16;
      sun.shadow.camera.right = 16;
      sun.shadow.camera.top = 16;
      sun.shadow.camera.bottom = -16;
      sun.shadow.camera.near = 0.5;
      sun.shadow.camera.far = 40;
      sun.shadow.mapSize.width = 1024;
      sun.shadow.mapSize.height = 1024;
      if (stylized) {
        sun.shadow.normalBias = 0.035;
        sun.shadow.bias = -0.00015;
        sun.shadow.intensity = 0.65;
      }
    }
    scene.add(sun);

    var target = new THREE.Vector3();
    var cameraDirection = new THREE.Vector3();

    function worldMaterial(materialOptions) {
      return stylized ? standardMaterial(materialOptions) : material(materialOptions);
    }

    function setCameraRigDomain(sample) {
      var source = sample || {};
      cameraRigDomain = {
        height_scale: Number.isFinite(Number(source.height_scale)) ? Number(source.height_scale) : 1,
        distance_scale: Number.isFinite(Number(source.distance_scale)) ? Number(source.distance_scale) : 1,
        pitch_offset_radians: Number.isFinite(Number(source.pitch_offset_radians))
          ? Number(source.pitch_offset_radians)
          : 0,
      };
      return Object.assign({}, cameraRigDomain);
    }

    function clear() {
      var resources = { textures: [], materials: [], geometries: [] };
      while (root.children.length) {
        var child = root.children[0];
        root.remove(child);
        disposeObject(child, resources);
      }
      if (renderer.renderLists && typeof renderer.renderLists.dispose === "function") renderer.renderLists.dispose();
    }

    function render() {
      renderer.render(scene, camera);
    }

    function prepare() {
      return renderer.compileAsync(scene, camera).then(render);
    }

    window.addEventListener("pagehide", function releaseWorld() {
      clear();
      while (camera.children.length) {
        var attachment = camera.children[0];
        camera.remove(attachment);
        disposeObject(attachment);
      }
      if (studioEnvironment) studioEnvironment.dispose();
      if (sun.shadow) sun.shadow.dispose();
      renderer.dispose();
    }, { once: true });

    function resize(nextWidth, nextHeight) {
      var normalizedWidth = Math.max(1, Math.round(Number(nextWidth) || width));
      var normalizedHeight = Math.max(1, Math.round(Number(nextHeight) || height));
      renderWidth = normalizedWidth;
      renderHeight = normalizedHeight;
      renderer.setSize(renderWidth, renderHeight, false);
      camera.aspect = renderWidth / renderHeight;
      camera.updateProjectionMatrix();
      return getSize();
    }

    function getSize() {
      return { width: renderWidth, height: renderHeight, aspect: renderWidth / renderHeight };
    }

    function setFov(nextFov) {
      var normalizedFov = Number(nextFov);
      if (!Number.isFinite(normalizedFov) || normalizedFov <= 0) normalizedFov = baseFov;
      camera.fov = normalizedFov;
      camera.updateProjectionMatrix();
      return camera.fov;
    }

    function getFov() {
      return camera.fov;
    }

    function setFirstPersonCamera(pose) {
      pose = pose || {};
      var eyeY = (pose.height || 0) + (pose.eyeHeight || options.eyeHeight || 1.35) * cameraRigDomain.height_scale;
      var pitch = (pose.pitch || 0) + cameraRigDomain.pitch_offset_radians;
      var yaw = pose.yaw || 0;
      var cosPitch = Math.cos(pitch);
      camera.position.set(pose.x || 0, eyeY, pose.z || 0);
      target.set(
        (pose.x || 0) + Math.cos(yaw) * cosPitch,
        eyeY + Math.sin(pitch),
        (pose.z || 0) + Math.sin(yaw) * cosPitch,
      );
      camera.lookAt(target);
    }

    function setLookCamera(pose) {
      pose = pose || {};
      var eyeY = (pose.eyeHeight || options.eyeHeight || 1.35) * cameraRigDomain.height_scale;
      var pitch = (pose.pitch || 0) + cameraRigDomain.pitch_offset_radians;
      var yaw = pose.yaw || 0;
      var cosPitch = Math.cos(pitch);
      camera.position.set(pose.x || 0, eyeY, pose.z || 0);
      target.set(
        (pose.x || 0) + Math.sin(yaw) * cosPitch,
        eyeY + Math.sin(pitch),
        (pose.z || 0) - Math.cos(yaw) * cosPitch,
      );
      camera.lookAt(target);
    }

    function setChaseCamera(pose) {
      pose = pose || {};
      var yaw = pose.yaw || 0;
      var distance = (pose.distance || 3.2) * cameraRigDomain.distance_scale;
      var lookHeight = (pose.lookHeight || 0.7) * cameraRigDomain.height_scale;
      var pitch = Number(pose.pitch);
      var hasPitch = Number.isFinite(pitch);
      if (hasPitch) pitch += cameraRigDomain.pitch_offset_radians;
      var horizontalDistance = hasPitch ? Math.cos(pitch) * distance : distance;
      var height = hasPitch
        ? lookHeight + Math.sin(pitch) * distance
        : (pose.height || 2.0) * cameraRigDomain.height_scale;
      var x = pose.x || 0;
      var z = pose.z || 0;
      var shoulderOffset = Number(pose.shoulderOffset) || 0;
      var cameraX = x - Math.cos(yaw) * horizontalDistance - Math.sin(yaw) * shoulderOffset;
      var cameraZ = z - Math.sin(yaw) * horizontalDistance + Math.cos(yaw) * shoulderOffset;
      if (pose.bounds) {
        cameraX = Math.max(pose.bounds.minX, Math.min(pose.bounds.maxX, cameraX));
        cameraZ = Math.max(pose.bounds.minZ, Math.min(pose.bounds.maxZ, cameraZ));
      }
      camera.position.set(cameraX, height, cameraZ);
      target.set(x + Math.cos(yaw) * (pose.forwardLook || 0.8), lookHeight, z + Math.sin(yaw) * (pose.forwardLook || 0.8));
      camera.lookAt(target);
    }

    function setOpticalChaseCamera(pose) {
      var opticalPose = computeOpticalChasePose(pose, cameraRigDomain);
      camera.position.set(opticalPose.camera.x, opticalPose.camera.y, opticalPose.camera.z);
      target.set(
        opticalPose.camera.x + opticalPose.direction.x,
        opticalPose.camera.y + opticalPose.direction.y,
        opticalPose.camera.z + opticalPose.direction.z,
      );
      camera.lookAt(target);
      return opticalPose;
    }

    function getCameraOpticalPose() {
      camera.updateMatrixWorld(true);
      camera.getWorldDirection(cameraDirection);
      var horizontal = Math.hypot(cameraDirection.x, cameraDirection.z);
      return {
        yaw: EngineMath.normalizeAngle(Math.atan2(cameraDirection.z, cameraDirection.x)),
        pitchDown: Math.atan2(-cameraDirection.y, horizontal),
        direction: {
          x: cameraDirection.x,
          y: cameraDirection.y,
          z: cameraDirection.z,
        },
        position: {
          x: camera.position.x,
          y: camera.position.y,
          z: camera.position.z,
        },
      };
    }

    function addFloor(spec) {
      spec = spec || {};
      var mesh = new THREE.Mesh(
        new THREE.PlaneGeometry(spec.width || 10, spec.depth || 10),
        worldMaterial({
          color: spec.color === undefined ? 0xe5e7eb : spec.color,
          emissive: spec.emissive,
          emissiveIntensity: spec.emissiveIntensity,
          roughness: spec.roughness,
          metalness: spec.metalness,
          shininess: spec.shininess === undefined ? 8 : spec.shininess,
          specular: spec.specular === undefined ? 0x94a3b8 : spec.specular,
          map: spec.map,
          transparent: spec.transparent,
          opacity: spec.opacity,
          depthWrite: spec.depthWrite,
          side: spec.side,
        }),
      );
      mesh.rotation.x = -Math.PI / 2;
      mesh.position.set(spec.x || 0, spec.y || 0, spec.z || 0);
      mesh.receiveShadow = true;
      root.add(mesh);
      return mesh;
    }

    function addSurfaceFloor(spec) {
      spec = spec || {};
      var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
      var role = spec.surfaceRole || "floor";
      var surfaceColor = spec.color === undefined
        ? context.color(role, role === "floor" ? INDOOR_FLOOR_COLOR : 0x808080)
        : spec.color;
      var surfaceMap = spec.map;
      if (surfaceMap === undefined && spec.texture !== false) {
        var textureOptions = Object.assign({}, spec.textureOptions || {});
        if (textureOptions.baseColor === undefined) textureOptions.baseColor = surfaceColor;
        if (textureOptions.accentColor === undefined && spec.accentColor !== undefined) textureOptions.accentColor = spec.accentColor;
        if (textureOptions.pattern === undefined && spec.pattern !== undefined) textureOptions.pattern = spec.pattern;
        if (textureOptions.repeatX === undefined) textureOptions.repeatX = spec.repeatX;
        if (textureOptions.repeatY === undefined) textureOptions.repeatY = spec.repeatY;
        surfaceMap = createSurfaceTexture(context, role, textureOptions);
      }
      var mesh = addFloor(Object.assign({}, spec, {
        color: surfaceMap
          ? (spec.tintColor === undefined ? 0xffffff : spec.tintColor)
          : surfaceColor,
        map: surfaceMap || null,
      }));
      mesh.userData = mesh.userData || {};
      mesh.userData.surfaceRole = role;
      mesh.userData.surfaceColor = surfaceColor;
      return mesh;
    }

    function addGrid(spec) {
      spec = spec || {};
      var grid = new THREE.GridHelper(spec.size || 10, spec.divisions || 10, spec.color1 || 0x64748b, spec.color2 || 0xcbd5e1);
      grid.position.set(spec.x || 0, spec.y || 0.012, spec.z || 0);
      root.add(grid);
      return grid;
    }

    function addBox(spec) {
      spec = spec || {};
      var geometry = new THREE.BoxGeometry(spec.width || 1, spec.height || 1, spec.depth || 1);
      var mesh = new THREE.Mesh(
        geometry,
        worldMaterial({
          color: spec.color === undefined ? 0xcbd5e1 : spec.color,
          emissive: spec.emissive,
          emissiveIntensity: spec.emissiveIntensity,
          roughness: spec.roughness,
          metalness: spec.metalness,
          shininess: spec.shininess === undefined ? 18 : spec.shininess,
          specular: spec.specular,
          map: spec.map,
          transparent: spec.transparent,
          opacity: spec.opacity,
          depthWrite: spec.depthWrite,
          side: spec.side,
          flatShading: spec.flatShading,
        }),
      );
      setShadow(mesh);
      if (spec.edgeColor === undefined) {
        mesh.position.set(spec.x || 0, (spec.baseY || 0) + (spec.height || 1) / 2, spec.z || 0);
        mesh.rotation.set(spec.rotationX || 0, spec.rotationY || 0, spec.rotationZ || 0);
        root.add(mesh);
        return mesh;
      }
      var group = new THREE.Group();
      var edgeMaterial = new THREE.LineBasicMaterial({
        color: spec.edgeColor,
        transparent: spec.edgeOpacity !== undefined && spec.edgeOpacity < 1,
        opacity: spec.edgeOpacity === undefined ? 1 : spec.edgeOpacity,
      });
      var edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), edgeMaterial);
      group.add(mesh);
      group.add(edges);
      group.position.set(spec.x || 0, (spec.baseY || 0) + (spec.height || 1) / 2, spec.z || 0);
      group.rotation.set(spec.rotationX || 0, spec.rotationY || 0, spec.rotationZ || 0);
      root.add(group);
      return group;
    }

    function addCylinder(spec) {
      spec = spec || {};
      var mesh = new THREE.Mesh(
        new THREE.CylinderGeometry(spec.radiusTop || spec.radius || 0.4, spec.radiusBottom || spec.radius || 0.4, spec.height || 1, spec.segments || 32),
        worldMaterial({
          color: spec.color === undefined ? 0x94a3b8 : spec.color,
          emissive: spec.emissive,
          emissiveIntensity: spec.emissiveIntensity,
          roughness: spec.roughness,
          metalness: spec.metalness,
          shininess: spec.shininess === undefined ? 20 : spec.shininess,
          specular: spec.specular,
          map: spec.map,
          transparent: spec.transparent,
          opacity: spec.opacity,
          depthWrite: spec.depthWrite,
          side: spec.side,
          flatShading: spec.flatShading,
        }),
      );
      mesh.position.set(spec.x || 0, (spec.baseY || 0) + (spec.height || 1) / 2, spec.z || 0);
      setShadow(mesh);
      root.add(mesh);
      return mesh;
    }

    function addSphere(spec) {
      spec = spec || {};
      var mesh = new THREE.Mesh(
        new THREE.SphereGeometry(spec.radius || 0.35, spec.widthSegments || 32, spec.heightSegments || 16),
        worldMaterial({
          color: spec.color === undefined ? 0xef4444 : spec.color,
          emissive: spec.emissive === undefined ? 0x000000 : spec.emissive,
          emissiveIntensity: spec.emissiveIntensity,
          roughness: spec.roughness,
          metalness: spec.metalness,
          shininess: spec.shininess === undefined ? 34 : spec.shininess,
          specular: spec.specular,
          map: spec.map,
          transparent: spec.transparent,
          opacity: spec.opacity,
          depthWrite: spec.depthWrite,
          side: spec.side,
          flatShading: spec.flatShading,
        }),
      );
      mesh.position.set(spec.x || 0, spec.y || 0, spec.z || 0);
      setShadow(mesh);
      root.add(mesh);
      return mesh;
    }

    function addDiamond(spec) {
      spec = spec || {};
      var mesh = new THREE.Mesh(
        new THREE.OctahedronGeometry(spec.radius || 0.28, 0),
        worldMaterial({
          color: spec.color === undefined ? 0xef4444 : spec.color,
          emissive: spec.emissive === undefined ? 0x000000 : spec.emissive,
          emissiveIntensity: spec.emissiveIntensity,
          roughness: spec.roughness,
          metalness: spec.metalness,
          shininess: spec.shininess === undefined ? 28 : spec.shininess,
          specular: spec.specular,
          map: spec.map,
          transparent: spec.transparent,
          opacity: spec.opacity,
          depthWrite: spec.depthWrite,
          side: spec.side,
          flatShading: spec.flatShading,
        }),
      );
      mesh.position.set(spec.x || 0, spec.y || 0, spec.z || 0);
      setShadow(mesh);
      root.add(mesh);
      return mesh;
    }

    function addPointLight(spec) {
      spec = spec || {};
      var light = new THREE.PointLight(
        spec.color || 0xffffff,
        legacyLightIntensity(spec.intensity === undefined ? 0.8 : spec.intensity, lightIntensityScale),
        spec.distance || 6
      );
      light.position.set(spec.x || 0, spec.y || 1, spec.z || 0);
      root.add(light);
      return light;
    }

    function addGroundGoalMarker(spec) {
      spec = spec || {};
      var radius = spec.radius === undefined ? 0.95 : spec.radius;
      var color = spec.color === undefined ? 0x00d84a : spec.color;
      var baseY = spec.baseY === undefined ? 0 : spec.baseY;
      var segments = spec.segments || 64;
      var group = new THREE.Group();
      group.position.set(spec.x || 0, baseY, spec.z || 0);

      function glowMaterial(opacity) {
        return new THREE.MeshBasicMaterial({
          color: color,
          transparent: true,
          opacity: opacity,
          depthWrite: false,
          side: THREE.DoubleSide,
          blending: THREE.NormalBlending,
        });
      }

      var fill = new THREE.Mesh(new THREE.CircleGeometry(radius * 0.84, segments), glowMaterial(0.42));
      fill.rotation.x = -Math.PI / 2;
      fill.position.y = 0.012;
      fill.renderOrder = 2;
      group.add(fill);

      var center = new THREE.Mesh(new THREE.CircleGeometry(radius * 0.3, segments), glowMaterial(0.62));
      center.rotation.x = -Math.PI / 2;
      center.position.y = 0.018;
      center.renderOrder = 3;
      group.add(center);

      var ring = new THREE.Mesh(
        new THREE.TorusGeometry(radius * 0.91, radius * 0.09, 10, segments),
        glowMaterial(0.96),
      );
      ring.rotation.x = Math.PI / 2;
      ring.position.y = 0.035;
      ring.renderOrder = 4;
      group.add(ring);

      var beamHeight = spec.beamHeight === undefined ? 1.5 : spec.beamHeight;
      var beam = new THREE.Mesh(
        new THREE.CylinderGeometry(radius * 0.82, radius * 0.82, beamHeight, segments, 1, true),
        glowMaterial(0.28),
      );
      beam.position.y = beamHeight * 0.5;
      beam.renderOrder = 1;
      group.add(beam);

      var upperRing = new THREE.Mesh(
        new THREE.TorusGeometry(radius * 0.82, radius * 0.028, 8, segments),
        glowMaterial(0.88),
      );
      upperRing.rotation.x = Math.PI / 2;
      upperRing.position.y = beamHeight;
      upperRing.renderOrder = 5;
      group.add(upperRing);

      var light = null;
      if (spec.light !== false) {
        light = new THREE.PointLight(
          spec.lightColor === undefined ? color : spec.lightColor,
          legacyLightIntensity(spec.lightIntensity === undefined ? 0.55 : spec.lightIntensity, lightIntensityScale),
          spec.lightDistance === undefined ? 4.2 : spec.lightDistance,
        );
        light.position.set(0, beamHeight * 0.55, 0);
        group.add(light);
      }

      root.add(group);
      return {
        group: group,
        fill: fill,
        center: center,
        ring: ring,
        beam: beam,
        upperRing: upperRing,
        light: light,
        update: function update(elapsedMs) {
          var pulse = 0.5 + 0.5 * Math.sin((Number(elapsedMs) || 0) * 0.0045);
          fill.material.opacity = 0.38 + pulse * 0.1;
          center.material.opacity = 0.55 + pulse * 0.14;
          ring.material.opacity = 0.92 + pulse * 0.07;
          beam.material.opacity = 0.24 + pulse * 0.08;
          upperRing.material.opacity = 0.9 + pulse * 0.08;
          if (light) {
            light.intensity = legacyLightIntensity(
              (spec.lightIntensity === undefined ? 0.55 : spec.lightIntensity) * (0.85 + pulse * 0.25),
              lightIntensityScale
            );
          }
        },
      };
    }

    function addTargetMarker(spec) {
      spec = spec || {};
      var x = spec.x || 0;
      var z = spec.z === undefined ? 0 : spec.z;
      var baseY = spec.baseY === undefined ? 0 : spec.baseY;
      var color = spec.color === undefined ? 0x22c55e : spec.color;
      var radius = spec.radius === undefined ? 0.42 : spec.radius;
      var markerY = spec.markerY === undefined ? 1.0 : spec.markerY;
      var markerRadius = spec.markerRadius === undefined ? radius : spec.markerRadius;
      var result = {};

      if (spec.base !== false) {
        result.base = addCylinder({
          x: x,
          z: z,
          baseY: baseY,
          radius: spec.baseRadius === undefined ? radius : spec.baseRadius,
          height: spec.baseHeight === undefined ? 0.08 : spec.baseHeight,
          color: spec.baseColor === undefined ? color : spec.baseColor,
          shininess: spec.baseShininess || 16,
        });
      }
      if (spec.pole) {
        result.pole = addCylinder({
          x: x,
          z: z,
          baseY: baseY,
          radius: spec.poleRadius === undefined ? 0.04 : spec.poleRadius,
          height: spec.poleHeight === undefined ? Math.max(0.05, markerY - baseY) : spec.poleHeight,
          color: spec.poleColor === undefined ? 0x14532d : spec.poleColor,
          shininess: spec.poleShininess || 18,
        });
      }
      if (spec.shape === "diamond") {
        result.marker = addDiamond({
          x: x,
          y: markerY,
          z: z,
          radius: markerRadius,
          color: color,
          emissive: spec.emissive === undefined ? 0x000000 : spec.emissive,
        });
      } else {
        result.marker = addSphere({
          x: x,
          y: markerY,
          z: z,
          radius: markerRadius,
          color: color,
          emissive: spec.emissive === undefined ? 0x000000 : spec.emissive,
        });
      }
      if (spec.light !== false) {
        result.light = addPointLight({
          x: x,
          y: spec.lightY === undefined ? markerY + 0.12 : spec.lightY,
          z: z,
          color: spec.lightColor === undefined ? color : spec.lightColor,
          intensity: spec.lightIntensity === undefined ? 0.55 : spec.lightIntensity,
          distance: spec.lightDistance === undefined ? 5 : spec.lightDistance,
        });
      }
      return result;
    }

    function addArena(spec) {
      spec = spec || {};
      var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
      var bounds = spec.bounds || {};
      var explicitWidth = Number(spec.width);
      var explicitDepth = Number(spec.depth);
      var minX = Number(bounds.minX);
      var maxX = Number(bounds.maxX);
      var minZ = Number(bounds.minZ);
      var maxZ = Number(bounds.maxZ);
      var hasXBounds = Number.isFinite(minX) && Number.isFinite(maxX);
      var hasZBounds = Number.isFinite(minZ) && Number.isFinite(maxZ);
      var width = Number.isFinite(explicitWidth) && explicitWidth > 0
        ? explicitWidth
        : (hasXBounds ? Math.max(1, maxX - minX) : 16);
      var depth = Number.isFinite(explicitDepth) && explicitDepth > 0
        ? explicitDepth
        : (hasZBounds ? Math.max(1, maxZ - minZ) : 16);
      var centerX = spec.x === undefined
        ? (hasXBounds ? (minX + maxX) / 2 : 0)
        : spec.x;
      var centerZ = spec.z === undefined
        ? (hasZBounds ? (minZ + maxZ) / 2 : -depth / 2)
        : spec.z;
      var floorY = spec.floorY === undefined ? 0 : spec.floorY;
      var wallHeight = spec.wallHeight === undefined ? 2.8 : spec.wallHeight;
      var wallThickness = spec.wallThickness === undefined ? 0.18 : spec.wallThickness;
      var group = new THREE.Group();
      var result = { group: group, floor: null, walls: [], trim: [] };
      root.add(group);

      function collect(object) {
        root.remove(object);
        group.add(object);
        return object;
      }

      var floorColor = spec.floorColor === undefined ? context.color("floor", INDOOR_FLOOR_COLOR) : spec.floorColor;
      result.floor = collect(addSurfaceFloor({
        x: centerX,
        z: centerZ,
        y: floorY,
        width: width,
        depth: depth,
        color: floorColor,
        assetContext: context,
        surfaceRole: spec.surfaceRole || "floor",
        texture: spec.floorTexture !== false,
        repeatX: Math.max(1, width / (spec.textureScale || 2.4)),
        repeatY: Math.max(1, depth / (spec.textureScale || 2.4)),
        shininess: spec.floorShininess === undefined ? 5 : spec.floorShininess,
        specular: spec.floorSpecular === undefined ? 0x4b5563 : spec.floorSpecular,
      }));

      if (spec.grid !== false) {
        result.grid = collect(addGrid({
          x: centerX,
          z: centerZ,
          y: floorY + 0.014,
          size: Math.max(width, depth),
          divisions: spec.gridDivisions || Math.max(8, Math.round(Math.max(width, depth) / 2)),
          color1: spec.gridColor === undefined ? context.color("floorLine", 0xb9c3cc) : spec.gridColor,
          color2: spec.gridSecondaryColor === undefined ? context.color("floorAccent", 0x8793a1) : spec.gridSecondaryColor,
        }));
        result.grid.material.transparent = true;
        result.grid.material.opacity = spec.gridOpacity === undefined ? 0.24 : spec.gridOpacity;
      }

      if (spec.walls !== false) {
        var wallColor = spec.wallColor === undefined ? context.color("wall", 0xa8b2bd) : spec.wallColor;
        var trimColor = spec.trimColor === undefined ? context.color("trim", 0xd8dee6) : spec.trimColor;
        var openings = spec.openSides || [];
        var wallSpecs = [
          { side: "north", x: centerX, z: centerZ - depth / 2 - wallThickness / 2, width: width + wallThickness * 2, depth: wallThickness },
          { side: "south", x: centerX, z: centerZ + depth / 2 + wallThickness / 2, width: width + wallThickness * 2, depth: wallThickness },
          { side: "west", x: centerX - width / 2 - wallThickness / 2, z: centerZ, width: wallThickness, depth: depth },
          { side: "east", x: centerX + width / 2 + wallThickness / 2, z: centerZ, width: wallThickness, depth: depth },
        ];
        wallSpecs.forEach(function addArenaWall(wall) {
          if (openings.indexOf(wall.side) >= 0) return;
          result.walls.push(collect(addBox({
            x: wall.x,
            z: wall.z,
            baseY: floorY,
            width: wall.width,
            depth: wall.depth,
            height: wallHeight,
            color: wallColor,
            shininess: 8,
          })));
          if (spec.trim !== false) {
            result.trim.push(collect(addBox({
              x: wall.x,
              z: wall.z,
              baseY: floorY + wallHeight - 0.12,
              width: wall.width,
              depth: wall.depth + (wall.side === "north" || wall.side === "south" ? 0.035 : 0),
              height: 0.12,
              color: trimColor,
              shininess: 22,
            })));
          }
        });
      }

      if (spec.perimeterLights !== false) {
        var lightColor = spec.lightColor === undefined ? context.color("trim", 0xd8dee6) : spec.lightColor;
        var corners = [
          [centerX - width / 2 + 0.65, centerZ - depth / 2 + 0.65],
          [centerX + width / 2 - 0.65, centerZ - depth / 2 + 0.65],
          [centerX - width / 2 + 0.65, centerZ + depth / 2 - 0.65],
          [centerX + width / 2 - 0.65, centerZ + depth / 2 - 0.65],
        ];
        result.lights = corners.map(function addArenaLight(point) {
          return collect(addPointLight({
            x: point[0], y: floorY + Math.min(2.4, wallHeight - 0.2), z: point[1],
            color: lightColor,
            intensity: spec.lightIntensity === undefined ? 0.2 : spec.lightIntensity,
            distance: spec.lightDistance === undefined ? 7 : spec.lightDistance,
          }));
        });
      }
      return result;
    }

    function project(mesh) {
      var p = mesh.position.clone().project(camera);
      return { x: ((p.x + 1) / 2) * renderWidth, y: ((1 - p.y) / 2) * renderHeight, z: p.z, width: renderWidth, height: renderHeight };
    }

    return {
      renderer: renderer,
      scene: scene,
      camera: camera,
      root: root,
      ambientLight: ambient,
      sunLight: sun,
      lightIntensityScale: lightIntensityScale,
      visualProfile: stylized ? "stylized" : "legacy",
      baseAmbientIntensity: ambient.intensity,
      baseSunIntensity: sun.intensity,
      baseAmbientColor: ambient.color.getHex(),
      baseSunColor: sun.color.getHex(),
      baseSunPosition: sun.position.clone(),
      baseShadowStrength: sun.shadow && Number.isFinite(Number(sun.shadow.intensity))
        ? Number(sun.shadow.intensity)
        : 1,
      clear: clear,
      render: render,
      prepare: prepare,
      resize: resize,
      getSize: getSize,
      setFov: setFov,
      getFov: getFov,
      getBaseFov: function getBaseFov() { return baseFov; },
      setCameraRigDomain: setCameraRigDomain,
      setFirstPersonCamera: setFirstPersonCamera,
      setLookCamera: setLookCamera,
      setChaseCamera: setChaseCamera,
      setOpticalChaseCamera: setOpticalChaseCamera,
      getCameraOpticalPose: getCameraOpticalPose,
      addFloor: addFloor,
      addSurfaceFloor: addSurfaceFloor,
      addBox: addBox,
      addCylinder: addCylinder,
      addSphere: addSphere,
      addDiamond: addDiamond,
      addPointLight: addPointLight,
      addGroundGoalMarker: addGroundGoalMarker,
      addTargetMarker: addTargetMarker,
      addArena: addArena,
      material: worldMaterial,
      project: project,
    };
  }

  function normalizeUrlBool(value, fallback, emptyValue) {
    if (value === null || value === undefined) return fallback;
    if (value === "") return emptyValue;
    if (value === true || value === 1) return true;
    if (value === false || value === 0) return false;
    var text = String(value).trim().toLowerCase();
    if (text === "1" || text === "true" || text === "yes" || text === "on" || text === "fullscreen" || text === "full") return true;
    if (text === "0" || text === "false" || text === "no" || text === "off" || text === "none") return false;
    return fallback;
  }

  function fullscreenRequestedFromUrl() {
    var params;
    try {
      params = new URLSearchParams(window.location.search || "");
    } catch (error) {
      return false;
    }
    return params.get("fullscreen") === "1";
  }

  function createFullscreenViewport(options) {
    options = options || {};
    var game = options.game || null;
    var world = options.world || null;
    var root = options.root || options.app || document.getElementById("app") || document.body;
    var app = options.app || root;
    var shell = options.shell || document.querySelector(".shell");
    var stage = options.stage || document.querySelector(".stage") || root;
    var canvas = options.canvas || document.querySelector("canvas");
    var baseWidth = Math.max(1, Math.round(Number(options.baseWidth) || (canvas && canvas.width) || 640));
    var baseHeight = Math.max(1, Math.round(Number(options.baseHeight) || (canvas && canvas.height) || 640));
    var nativeBaseWidth = baseWidth;
    var nativeBaseHeight = baseHeight;
    var baseFov = Number(options.baseFov);
    var nativeBaseFov = baseFov;
    var fullscreenFov = Number(options.fullscreenFov);
    var cameraFovOffset = 0;
    var key = String(options.key || "f").toLowerCase();
    var className = options.className || "gamelet-3d-fullscreen";
    var render = typeof options.render === "function" ? options.render : function noop() {};
    var onChange = typeof options.onChange === "function" ? options.onChange : function noop() {};
    var onResize = typeof options.onResize === "function" ? options.onResize : function noop() {};
    var fullscreenBackground = options.background || "#020617";
    var startFullscreen = normalizeUrlBool(options.startFullscreen, false, true);
    var hiddenElements = [];
    var styledElements = [];
    var layoutFullscreen = false;
    var lastState = { width: baseWidth, height: baseHeight, active: false };

    if (!Number.isFinite(baseFov) && world && typeof world.getFov === "function") baseFov = world.getFov();
    if (!Number.isFinite(baseFov)) baseFov = 68;
    nativeBaseFov = baseFov;
    if (!Number.isFinite(fullscreenFov)) fullscreenFov = Math.min(100, nativeBaseFov + 12);

    function rememberStyles(element, styles) {
      if (!element) return;
      var entry = { element: element, styles: styles, previous: {} };
      Object.keys(styles).forEach(function rememberStyle(name) {
        entry.previous[name] = element.style[name] || "";
      });
      styledElements.push(entry);
    }

    rememberStyles(document.documentElement, {
      width: "100%",
      height: "100%",
      overflow: "hidden",
      background: fullscreenBackground,
    });
    rememberStyles(document.body, {
      width: "100%",
      height: "100%",
      overflow: "hidden",
      margin: "0",
      display: "block",
      background: fullscreenBackground,
    });
    rememberStyles(app, {
      width: "100vw",
      height: "100vh",
      padding: "0",
      margin: "0",
      display: "block",
      background: fullscreenBackground,
    });
    if (root !== app) {
      rememberStyles(root, {
        width: "100vw",
        height: "100vh",
        padding: "0",
        margin: "0",
        display: "block",
        background: fullscreenBackground,
      });
    }
    rememberStyles(shell, {
      width: "100vw",
      height: "100vh",
      maxWidth: "none",
      display: "block",
      gap: "0",
      gridTemplateColumns: "none",
      gridTemplateRows: "none",
    });
    rememberStyles(stage, {
      width: "100vw",
      height: "100vh",
      aspectRatio: "auto",
      margin: "0",
      outline: "0",
    });
    rememberStyles(canvas, {
      width: "100vw",
      height: "100vh",
      display: "block",
    });

    function addHiddenElement(element) {
      if (element) hiddenElements.push({ element: element, display: element.style.display });
    }

    if (Array.isArray(options.hiddenElements)) {
      for (var h = 0; h < options.hiddenElements.length; h += 1) addHiddenElement(options.hiddenElements[h]);
    }
    if (Array.isArray(options.hideSelectors)) {
      for (var s = 0; s < options.hideSelectors.length; s += 1) {
        var matches = document.querySelectorAll(options.hideSelectors[s]);
        for (var m = 0; m < matches.length; m += 1) addHiddenElement(matches[m]);
      }
    }

    function browserFullscreenElement() {
      return document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement || null;
    }

    function containsFullscreenElement(element) {
      var fullscreenElement = browserFullscreenElement();
      return !!fullscreenElement && (fullscreenElement === element || (element && typeof element.contains === "function" && element.contains(fullscreenElement)));
    }

    function browserFullscreenActive() {
      return containsFullscreenElement(root) || containsFullscreenElement(app) || containsFullscreenElement(stage) || containsFullscreenElement(canvas);
    }

    function active() {
      return layoutFullscreen || browserFullscreenActive();
    }

    function classTargets() {
      return [document.documentElement, document.body, app, root, shell, stage, canvas];
    }

    function applyLayout(isActive) {
      var targets = classTargets();
      for (var i = 0; i < targets.length; i += 1) {
        if (!targets[i] || !targets[i].classList) continue;
        if (isActive) targets[i].classList.add(className);
        else targets[i].classList.remove(className);
      }
      for (var e = 0; e < styledElements.length; e += 1) {
        var styleEntry = styledElements[e];
        Object.keys(styleEntry.styles).forEach(function applyStyle(name) {
          var configured = styleEntry.styles[name];
          if (typeof configured === "function") configured = configured();
          if (configured === null || configured === undefined) {
            configured = styleEntry.previous[name];
          }
          styleEntry.element.style[name] = isActive ? configured : styleEntry.previous[name];
        });
      }
      for (var j = 0; j < hiddenElements.length; j += 1) {
        hiddenElements[j].element.style.display = isActive ? "none" : hiddenElements[j].display;
      }
    }

    function readActiveSize() {
      var widthSource = stage && stage.clientWidth ? stage.clientWidth : window.innerWidth;
      var heightSource = stage && stage.clientHeight ? stage.clientHeight : window.innerHeight;
      return {
        width: Math.max(1, Math.round(widthSource || nativeBaseWidth)),
        height: Math.max(1, Math.round(heightSource || nativeBaseHeight)),
      };
    }

    function updateViewport(updateOptions) {
      updateOptions = updateOptions || {};
      var isActive = active();
      var displaySize = isActive
        ? readActiveSize()
        : { width: nativeBaseWidth, height: nativeBaseHeight };
      var presentationFov = isActive ? fullscreenFov : nativeBaseFov;
      var activeFov = Math.max(20, Math.min(120, presentationFov + cameraFovOffset));
      if (world && typeof world.setFov === "function") {
        world.setFov(activeFov);
      }
      if (world && typeof world.resize === "function") {
        world.resize(displaySize.width, displaySize.height);
      }
      var state = {
        active: isActive,
        browser_fullscreen: browserFullscreenActive(),
        layout_fullscreen: layoutFullscreen,
        width: displaySize.width,
        height: displaySize.height,
        aspect: displaySize.width / displaySize.height,
        base_width: nativeBaseWidth,
        base_height: nativeBaseHeight,
        fov: world && typeof world.getFov === "function"
          ? world.getFov()
          : activeFov,
      };
      lastState = state;
      onResize(lastState);
      if (updateOptions.render !== false) render();
      return lastState;
    }

    function applyActiveState(isActive, updateOptions) {
      layoutFullscreen = !!isActive;
      applyLayout(layoutFullscreen || browserFullscreenActive());
      var state = updateViewport(updateOptions);
      onChange(state);
      return state;
    }

    function requestBrowserFullscreen() {
      var target = root || app || stage || canvas;
      if (!target) return null;
      var request = target.requestFullscreen || target.webkitRequestFullscreen || target.mozRequestFullScreen || target.msRequestFullscreen;
      if (typeof request !== "function") return null;
      try {
        return request.call(target);
      } catch (error) {
        return null;
      }
    }

    function exitBrowserFullscreen() {
      var exit = document.exitFullscreen || document.webkitExitFullscreen || document.mozCancelFullScreen || document.msExitFullscreen;
      if (typeof exit !== "function") return null;
      try {
        return exit.call(document);
      } catch (error) {
        return null;
      }
    }

    function enter() {
      applyActiveState(true);
      var request = requestBrowserFullscreen();
      if (request && typeof request.catch === "function") request.catch(function keepLayoutFullscreen() { applyActiveState(true); });
      return getState();
    }

    function enterLayout(updateOptions) {
      return applyActiveState(true, updateOptions || {});
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
      if (event.defaultPrevented) return;
      var tag = event && event.target && event.target.tagName ? String(event.target.tagName).toLowerCase() : "";
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      if (String(event.key || "").toLowerCase() !== key) return;
      event.preventDefault();
      toggle();
    }

    function onFullscreenChange() {
      layoutFullscreen = browserFullscreenActive();
      applyLayout(layoutFullscreen);
      var state = updateViewport();
      onChange(state);
    }

    function onWindowResize() {
      updateViewport();
    }

    function getState() {
      var state = {
        active: lastState.active,
        browser_fullscreen: lastState.browser_fullscreen,
        layout_fullscreen: lastState.layout_fullscreen,
        width: lastState.width,
        height: lastState.height,
        aspect: lastState.aspect,
        base_width: lastState.base_width,
        base_height: lastState.base_height,
        fov: lastState.fov,
        key: key,
      };
      return state;
    }

    function configureCameraDomain(profile, updateOptions) {
      var next = profile || {};
      var nextOffset = Number(next.fov_offset_degrees);
      cameraFovOffset = Number.isFinite(nextOffset) ? nextOffset : 0;
      return updateViewport(updateOptions || {});
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
    updateViewport({ render: false });
    if (startFullscreen) enterLayout({ render: false });

    return {
      enter: enter,
      enterLayout: enterLayout,
      exit: exit,
      toggle: toggle,
      resize: updateViewport,
      configureCameraDomain: configureCameraDomain,
      isActive: active,
      getState: getState,
      destroy: destroy,
    };
  }

  function viewportPayload(game, fallback) {
    fallback = fallback || {};
    if (game && game.fullscreenViewport && typeof game.fullscreenViewport.getState === "function") return game.fullscreenViewport.getState();
    var world = game && game.world3d;
    if (world && typeof world.getSize === "function") {
      var size = world.getSize();
      var worldPayload = {
        active: false,
        browser_fullscreen: false,
        layout_fullscreen: false,
        width: size.width,
        height: size.height,
        aspect: size.aspect,
        base_width: fallback.baseWidth || size.width,
        base_height: fallback.baseHeight || size.height,
        fov: typeof world.getFov === "function" ? world.getFov() : (fallback.baseFov || 68),
        key: fallback.key || "f",
      };
      return worldPayload;
    }
    var width = fallback.baseWidth || 640;
    var height = fallback.baseHeight || 640;
    var fallbackPayload = {
      active: false,
      browser_fullscreen: false,
      layout_fullscreen: false,
      width: width,
      height: height,
      aspect: width / height,
      base_width: width,
      base_height: height,
      fov: fallback.baseFov || 68,
      key: fallback.key || "f",
    };
    return fallbackPayload;
  }

  function installFullscreenForGame(game, options) {
    options = options || {};
    if (!game) return null;
    var baseWidth = options.baseWidth || options.width || 640;
    var baseHeight = options.baseHeight || options.height || 640;
    var baseFov = options.baseFov || options.fov || (game.world3d && typeof game.world3d.getFov === "function" ? game.world3d.getFov() : 68);
    var startFullscreen = options.startFullscreen;
    if (startFullscreen === undefined && options.urlStart !== false) startFullscreen = fullscreenRequestedFromUrl();
    var controller = createFullscreenViewport({
      game: game,
      world: options.world || game.world3d,
      root: options.root || document.getElementById("app") || document.body,
      app: options.app || document.getElementById("app") || document.body,
      shell: options.shell || document.querySelector(".shell"),
      stage: options.stage || document.querySelector(".stage"),
      canvas: options.canvas || document.querySelector("canvas"),
      baseWidth: baseWidth,
      baseHeight: baseHeight,
      baseFov: baseFov,
      fullscreenFov: options.fullscreenFov,
      startFullscreen: startFullscreen,
      key: options.key || "f",
      hideSelectors: options.hideSelectors || [".hud", ".spacer"],
      hiddenElements: options.hiddenElements,
      background: options.background,
      render: typeof options.render === "function" ? options.render : function renderGame() {
        if (typeof game.render === "function") game.render();
      },
      onChange: options.onChange,
      onResize: options.onResize,
    });
    game.fullscreenViewport = controller;
    game.viewportPayload = function gameViewportPayload() {
      return viewportPayload(game, { baseWidth: baseWidth, baseHeight: baseHeight, baseFov: baseFov, key: options.key || "f" });
    };
    game.toggleFullscreen = function toggleFullscreen() { return controller.toggle(); };
    game.enterFullscreen = function enterFullscreen() { return controller.enter(); };
    game.exitFullscreen = function exitFullscreen() { return controller.exit(); };
    return controller;
  }

  function addFullscreenAPI(api, game) {
    if (!api || !game) return api;
    api.getFullscreenState = function getFullscreenState() {
      return viewportPayload(game);
    };
    api.toggleFullscreen = function toggleFullscreen() {
      return typeof game.toggleFullscreen === "function" ? game.toggleFullscreen() : viewportPayload(game);
    };
    api.enterFullscreen = function enterFullscreen() {
      return typeof game.enterFullscreen === "function" ? game.enterFullscreen() : viewportPayload(game);
    };
    api.exitFullscreen = function exitFullscreen() {
      return typeof game.exitFullscreen === "function" ? game.exitFullscreen() : viewportPayload(game);
    };
    return api;
  }

  function getCaptureCanvas(game) {
    if (game && game.canvas && typeof game.canvas.toDataURL === "function") return game.canvas;
    var renderer = game && game.world3d && game.world3d.renderer;
    var canvas = renderer && renderer.domElement;
    if (!canvas) canvas = document.getElementById("display") || document.querySelector("canvas");
    return canvas && typeof canvas.toDataURL === "function" ? canvas : null;
  }

  function attachRuntime(runtime, game) {
    if (!runtime || !game) return runtime;
    if (!game.fullscreenViewport) {
      installFullscreenForGame(game, {
        canvas: getCaptureCanvas(game),
        world: game.world3d,
      });
    }
    runtime.capabilities.is_3d = true;
    runtime.capabilities.supports_fullscreen = true;
    runtime.gameGymAPI.getCapabilities = function getRuntimeCapabilities() {
      return Object.assign({}, runtime.capabilities);
    };
    runtime.gameGymAPI.getCameraOpticalPose = function getRuntimeCameraOpticalPose() {
      return game.world3d && typeof game.world3d.getCameraOpticalPose === "function"
        ? game.world3d.getCameraOpticalPose()
        : null;
    };
    addFullscreenAPI(runtime.gameGymAPI, game);
    addFullscreenAPI(runtime.gameAPI, game);
    return runtime;
  }

  function firstPersonMoveDelta(yaw, controls, speed, dt) {
    controls = controls || {};
    var forward = (controls.forward ? 1 : 0) - (controls.back ? 1 : 0);
    var strafe = (controls.right ? 1 : 0) - (controls.left ? 1 : 0);
    var moveSpeed = Number(speed) || 0;
    var seconds = Number(dt) || 0;
    var angle = Number(yaw) || 0;
    return {
      x: (Math.cos(angle) * forward + Math.cos(angle + Math.PI / 2) * strafe) * moveSpeed * seconds,
      z: (Math.sin(angle) * forward + Math.sin(angle + Math.PI / 2) * strafe) * moveSpeed * seconds,
      forward: forward,
      strafe: strafe,
    };
  }

  function directionFromYawPitch(yaw, pitch) {
    var horizontal = Math.cos(Number(pitch) || 0);
    var angle = Number(yaw) || 0;
    return {
      x: Math.cos(angle) * horizontal,
      y: Math.sin(Number(pitch) || 0),
      z: Math.sin(angle) * horizontal,
    };
  }

  var RELATIVE_POINTER_LIMIT = 1000;
  var RELATIVE_POINTER_PROTOCOL = "normalized_viewport_delta_v1";
  var CAMERA_SENSITIVITY = 0.00196; // radians per model-observation pixel

  function resolveLookConfig(options) {
    options = options || {};
    var yawSign = Number(options.yawSign);
    if (!Number.isFinite(yawSign) || yawSign === 0) yawSign = 1;
    var pitchSign = Number(options.pitchSign);
    if (!Number.isFinite(pitchSign) || pitchSign === 0) pitchSign = -1;
    var pitchMin = Number(options.pitchMin);
    var pitchMax = Number(options.pitchMax);
    if (!Number.isFinite(pitchMin)) pitchMin = -1.2;
    if (!Number.isFinite(pitchMax)) pitchMax = 1.2;
    return {
      yawSign: yawSign,
      pitchSign: pitchSign,
      pitchMin: pitchMin,
      pitchMax: pitchMax,
      yawKey: options.yawKey || "yaw",
      pitchKey: options.pitchKey || "pitch",
    };
  }

  function applyLookRadians(state, yawRightRadians, pitchDownRadians, options) {
    state = state || {};
    var config = resolveLookConfig(options);
    var beforeYaw = Number(state[config.yawKey]) || 0;
    var beforePitch = Number(state[config.pitchKey]) || 0;
    var yawStateDelta = (Number(yawRightRadians) || 0) * config.yawSign;
    var pitchStateDelta = (Number(pitchDownRadians) || 0) * config.pitchSign;
    var nextPitch = EngineMath.clamp(beforePitch + pitchStateDelta, config.pitchMin, config.pitchMax);
    state[config.yawKey] = EngineMath.normalizeAngle(beforeYaw + yawStateDelta);
    state[config.pitchKey] = nextPitch;
    return {
      appliedYawRightRadians: yawStateDelta / config.yawSign,
      appliedPitchDownRadians: (nextPitch - beforePitch) / config.pitchSign,
    };
  }

  function applyPointerLook(state, mouseDx, mouseDy, options) {
    options = options || {};
    var sensitivity = Number(options.sensitivity);
    if (!Number.isFinite(sensitivity)) sensitivity = CAMERA_SENSITIVITY;
    applyLookRadians(
      state,
      (Number(mouseDx) || 0) * sensitivity,
      (Number(mouseDy) || 0) * sensitivity,
      options
    );
    return state;
  }

  function normalizedRelativePointerDelta(value) {
    var numeric = Number(value);
    if (!Number.isFinite(numeric)) throw new Error("relative pointer delta must be finite");
    if (numeric < -RELATIVE_POINTER_LIMIT || numeric > RELATIVE_POINTER_LIMIT) {
      throw new Error("relative pointer delta must be in [-1000, 1000]");
    }
    return numeric;
  }

  function createRelativePointerInput(normalizedDx, normalizedDy) {
    return {
      protocol: RELATIVE_POINTER_PROTOCOL,
      dx: normalizedRelativePointerDelta(normalizedDx),
      dy: normalizedRelativePointerDelta(normalizedDy),
    };
  }

  function applyRelativePointerInput(state, pointerInput, options) {
    if (!pointerInput) return null;
    if (pointerInput.protocol !== RELATIVE_POINTER_PROTOCOL) {
      throw new Error("relative pointer input requires normalized_viewport_delta_v1");
    }
    var runtime = state && state.__gameletRuntime;
    if (!runtime || typeof runtime.getObservationSize !== "function") {
      throw new Error("relative pointer input requires model observation dimensions");
    }
    var size = runtime.getObservationSize();
    var width = size && size[0];
    var height = size && size[1];
    if (!Number.isInteger(width) || width <= 0 || !Number.isInteger(height) || height <= 0) {
      throw new Error("relative pointer input requires positive integer observation dimensions");
    }
    var movementX = normalizedRelativePointerDelta(pointerInput.dx) / RELATIVE_POINTER_LIMIT * width;
    var movementY = normalizedRelativePointerDelta(pointerInput.dy) / RELATIVE_POINTER_LIMIT * height;
    pointerInput.observation_width = width;
    pointerInput.observation_height = height;
    pointerInput.movement_units = "observation_pixels";
    pointerInput.movement_x = movementX;
    pointerInput.movement_y = movementY;
    applyPointerLook(state, movementX, movementY, options);
    return pointerInput;
  }

  function readFirstPersonAction(action, options) {
    action = action || {};
    options = options || {};
    var id = Core.actions.readId(action, { lowercase: true }) || "wait";
    var movementAliases = options.includeMovement === false ? {} : {
      forward: ["w", "KeyW", "ArrowUp"],
      back: ["s", "KeyS", "ArrowDown"],
      left: ["a", "KeyA", "ArrowLeft"],
      right: ["d", "KeyD", "ArrowRight"],
    };
    var aliases = Object.assign(movementAliases, options.controlAliases || {});
    var controls = {};
    Object.keys(aliases).forEach(function readControl(name) {
      controls[name] = Core.actions.hasKey(action, aliases[name]);
    });
    var pointerInput = null;
    var controlRelativeMouse = id === "control" && Core.actions.readMouseMode(action) === "relative";
    if (id === "move_pointer" || controlRelativeMouse) {
      var normalizedDx = controlRelativeMouse
        ? Core.actions.readMouseNumber(action, "dx", 0)
        : Core.actions.readNumber(action, "dx", 0);
      var normalizedDy = controlRelativeMouse
        ? Core.actions.readMouseNumber(action, "dy", 0)
        : Core.actions.readNumber(action, "dy", 0);
      pointerInput = createRelativePointerInput(normalizedDx, normalizedDy);
    }
    var button = Core.actions.readButton(action, id === "mouse_right" ? "right" : "left");
    var mouseLeftClick = (id === "mouse_left" && button === "left")
      || (id === "control" && Core.actions.hasMouseClick(action, "left"));
    var mouseLeftHold = id === "control" && Core.actions.hasMouseHold(action, "left");
    var mouseRightClick = (id === "mouse_right" && button === "right")
      || (id === "control" && Core.actions.hasMouseClick(action, "right"));
    var mouseRightHold = id === "control" && Core.actions.hasMouseHold(action, "right");
    return {
      id: id,
      controls: controls,
      pointerInput: pointerInput,
      args: pointerInput ? { relative_pointer: pointerInput } : {},
      mouseLeft: mouseLeftClick || mouseLeftHold,
      mouseRight: mouseRightClick || mouseRightHold,
      mouseLeftClick: mouseLeftClick,
      mouseLeftHold: mouseLeftHold,
      mouseRightClick: mouseRightClick,
      mouseRightHold: mouseRightHold,
    };
  }

  function createFirstPersonInputController(game, options) {
    if (!game) throw new Error("BaseGamelet3D.input.createController requires a game");
    options = options || {};
    var canvas = options.canvas;
    if (!canvas) throw new Error("BaseGamelet3D.input.createController requires a canvas");
    var eventTarget = options.eventTarget || window;
    var movementAliases = options.includeMovement === false ? {} : {
      forward: ["w", "KeyW", "ArrowUp"],
      back: ["s", "KeyS", "ArrowDown"],
      left: ["a", "KeyA", "ArrowLeft"],
      right: ["d", "KeyD", "ArrowRight"],
    };
    var aliases = Object.assign(movementAliases, options.controlAliases || {});
    var lookup = Object.create(null);
    Object.keys(aliases).forEach(function registerControl(name) {
      var values = Array.isArray(aliases[name]) ? aliases[name] : [aliases[name]];
      for (var i = 0; i < values.length; i += 1) lookup[String(values[i]).toLowerCase()] = name;
    });

    function controlForEvent(event) {
      var key = String(event && event.key || "").toLowerCase();
      var code = String(event && event.code || "").toLowerCase();
      return lookup[key] || lookup[code] || null;
    }

    function reset() {
      if (!game.controls || typeof game.controls !== "object") game.controls = {};
      Object.keys(aliases).forEach(function clearControl(name) { game.controls[name] = false; });
      game.lastMouse = null;
      if (typeof options.onReset === "function") options.onReset.call(game);
    }

    function onKey(event, value) {
      var control = controlForEvent(event);
      if (!control) return;
      if (!game.controls || typeof game.controls !== "object") game.controls = {};
      var wasPressed = !!game.controls[control];
      game.controls[control] = value;
      if (event.preventDefault) event.preventDefault();
      if (value && !wasPressed && !event.repeat && typeof options.onPress === "function") {
        options.onPress.call(game, control, event);
      }
      if (!value && wasPressed && typeof options.onRelease === "function") {
        options.onRelease.call(game, control, event);
      }
      if (value && game.mode === "paused" && options.resumeOnInput !== false) game.mode = "playing";
    }

    function onMouseMove(event) {
      if (!game.lastMouse) {
        game.lastMouse = { x: event.clientX, y: event.clientY };
        return;
      }
      var dx = event.movementX;
      var dy = event.movementY;
      if (!Number.isFinite(dx) || !Number.isFinite(dy) || (dx === 0 && dy === 0)) {
        dx = event.clientX - game.lastMouse.x;
        dy = event.clientY - game.lastMouse.y;
      }
      game.lastMouse = { x: event.clientX, y: event.clientY };
      if (typeof options.onLook === "function") options.onLook.call(game, dx || 0, dy || 0, event);
      else if (typeof game.applyMouse === "function") game.applyMouse(dx || 0, dy || 0);
    }

    function onMouseDown(event) {
      if (typeof canvas.focus === "function") canvas.focus();
      if (event.preventDefault) event.preventDefault();
      if (typeof options.onMouseDown === "function") options.onMouseDown.call(game, event);
    }

    function onMouseUp(event) {
      if (typeof options.onMouseUp === "function") options.onMouseUp.call(game, event);
    }

    function onBlur() {
      reset();
      if (typeof options.onBlur === "function") options.onBlur.call(game);
    }

    function onMouseEnter() {
      game.lastMouse = null;
    }

    function onContextMenu(event) {
      if (options.preventContextMenu !== false && event.preventDefault) event.preventDefault();
    }

    function destroy() {
      eventTarget.removeEventListener("keydown", onKeyDown);
      eventTarget.removeEventListener("keyup", onKeyUp);
      eventTarget.removeEventListener("blur", onBlur);
      eventTarget.removeEventListener("mouseup", onMouseUp);
      canvas.removeEventListener("mousemove", onMouseMove);
      canvas.removeEventListener("mousedown", onMouseDown);
      canvas.removeEventListener("mouseenter", onMouseEnter);
      canvas.removeEventListener("contextmenu", onContextMenu);
    }

    function onKeyDown(event) { onKey(event, true); }
    function onKeyUp(event) { onKey(event, false); }
    eventTarget.addEventListener("keydown", onKeyDown);
    eventTarget.addEventListener("keyup", onKeyUp);
    eventTarget.addEventListener("blur", onBlur);
    eventTarget.addEventListener("mouseup", onMouseUp);
    canvas.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("mousedown", onMouseDown);
    canvas.addEventListener("mouseenter", onMouseEnter);
    canvas.addEventListener("contextmenu", onContextMenu);
    reset();
    return { reset: reset, destroy: destroy };
  }

  function createEntityRegistry(world) {
    if (!world || !world.root) throw new Error("BaseGamelet3D.createEntityRegistry requires a world");
    var objects = Object.create(null);

    function get(id) {
      return objects[String(id)] || null;
    }

    function set(id, object) {
      var key = String(id);
      if (objects[key] && objects[key] !== object) remove(key);
      objects[key] = object;
      if (object && !object.parent) world.root.add(object);
      return object;
    }

    function remove(id) {
      var key = String(id);
      var object = objects[key];
      if (!object) return false;
      delete objects[key];
      return removeObject(object, world.root);
    }

    function clear() {
      Object.keys(objects).forEach(remove);
    }

    function sync(items, handlers) {
      handlers = handlers || {};
      var active = Object.create(null);
      var list = Array.isArray(items) ? items : [];
      for (var i = 0; i < list.length; i += 1) {
        var item = list[i];
        var rawId = typeof handlers.id === "function" ? handlers.id(item, i) : item && item.id;
        if (rawId === null || rawId === undefined) continue;
        var id = String(rawId);
        active[id] = true;
        var object = get(id);
        if (!object && typeof handlers.create === "function") object = set(id, handlers.create(item, i));
        if (object && typeof handlers.update === "function") handlers.update(object, item, i);
      }
      Object.keys(objects).forEach(function removeMissing(id) {
        if (!active[id]) remove(id);
      });
      return Object.keys(objects).length;
    }

    return {
      get: get,
      set: set,
      remove: remove,
      clear: clear,
      sync: sync,
      size: function size() { return Object.keys(objects).length; },
    };
  }

  function applyAssetContextToWorld(world, assetContext, options) {
    options = options || {};
    if (!world || !assetContext) return world;
    var sky = options.skyColor === undefined ? assetContext.color("sky", 0xbfd9f2) : options.skyColor;
    if (world.renderer && typeof world.renderer.setClearColor === "function") world.renderer.setClearColor(sky, 1);
    var ambientBase = options.ambient === undefined
      ? world.baseAmbientIntensity
      : legacyLightIntensity(options.ambient, world.lightIntensityScale);
    var sunBase = options.sun === undefined
      ? world.baseSunIntensity
      : legacyLightIntensity(options.sun, world.lightIntensityScale);
    if (assetContext.domainMode !== "isolated") {
      if (world.ambientLight) {
        world.ambientLight.intensity = ambientBase;
        world.ambientLight.color.setHex(world.baseAmbientColor);
      }
      if (world.sunLight) {
        world.sunLight.intensity = sunBase;
        world.sunLight.color.setHex(world.baseSunColor);
        world.sunLight.position.copy(world.baseSunPosition);
        if (world.sunLight.shadow) world.sunLight.shadow.intensity = world.baseShadowStrength;
      }
      return world;
    }
    var samples = assetContext.domainAppearanceSamples || {};
    var lighting = samples.lighting || {};
    var background = samples.background || {};
    if (world.ambientLight) {
      world.ambientLight.intensity = ambientBase * (Number(lighting.ambient_scale) || 1);
    }
    if (world.sunLight) {
      world.sunLight.intensity = sunBase * (Number(lighting.key_scale) || 1);
      var azimuth = Number(lighting.key_azimuth_degrees) || 0;
      var radians = azimuth * Math.PI / 180;
      var cosine = Math.cos(radians);
      var sine = Math.sin(radians);
      var basePosition = world.baseSunPosition;
      world.sunLight.position.set(
        basePosition.x * cosine - basePosition.z * sine,
        basePosition.y,
        basePosition.x * sine + basePosition.z * cosine
      );
      if (world.sunLight.shadow) {
        var shadowStrength = Number(lighting.shadow_strength);
        world.sunLight.shadow.intensity = Number.isFinite(shadowStrength)
          ? world.baseShadowStrength * Math.max(0, Math.min(1, shadowStrength))
          : world.baseShadowStrength;
      }
    }
    var temperature = String(background.environment_temperature || "neutral");
    var temperatureSample = { environment_temperature: temperature };
    if (world.ambientLight) {
      world.ambientLight.color.setHex(Core.perturbations.transformColor(
        world.baseAmbientColor,
        temperatureSample
      ));
    }
    if (world.sunLight) {
      world.sunLight.color.setHex(Core.perturbations.transformColor(
        world.baseSunColor,
        temperatureSample
      ));
    }
    return world;
  }

  function addCompoundPart(world, group, geometry, options) {
    options = options || {};
    var mesh = new THREE.Mesh(
      geometry,
      (world.material || material)({
        color: options.color,
        emissive: options.emissive,
        shininess: options.shininess,
        specular: options.specular,
        map: options.map,
        transparent: options.transparent,
        opacity: options.opacity,
        depthWrite: options.depthWrite,
        side: options.side,
        flatShading: options.flatShading,
      }),
    );
    mesh.position.set(options.x || 0, options.y || 0, options.z || 0);
    mesh.rotation.set(options.rotationX || 0, options.rotationY || 0, options.rotationZ || 0);
    setShadow(mesh);
    group.add(mesh);
    return mesh;
  }

  function addNavigatorHumanoid(world, spec) {
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var isTarget = spec.characterRole === "target";
    var height = Number(spec.height) || 1.2;
    var scale = height / 1.2;
    var bodyColor = spec.bodyColor === undefined
      ? context.color(isTarget ? "target" : "friendly", isTarget ? 0xec5364 : 0x2f80ed)
      : spec.bodyColor;
    var accentColor = spec.accentColor === undefined
      ? context.color(isTarget ? "targetAccent" : "friendlyAccent", isTarget ? 0xffe4e6 : 0xdbeafe)
      : spec.accentColor;
    var gearColor = spec.gearColor === undefined ? context.color("darkMetal", 0x26343a) : spec.gearColor;
    var group = new THREE.Group();
    var parts = {};
    var torsoWidth = (isTarget ? 0.56 : 0.68) * scale;
    var torsoDepth = (isTarget ? 0.34 : 0.42) * scale;
    var torsoHeight = (isTarget ? 0.58 : 0.55) * scale;
    var torsoY = 0.64 * scale;
    var headRadius = Number(spec.headRadius) || 0.2 * scale;
    var headY = spec.headY === undefined ? 0.98 * scale : spec.headY;

    parts.body = addCompoundPart(world, group, new THREE.BoxGeometry(torsoWidth, torsoHeight, torsoDepth), {
      y: torsoY,
      color: bodyColor,
      emissive: mixColor(bodyColor, 0x000000, 0.87),
      shininess: isTarget ? 42 : 30,
      specular: accentColor,
    });
    parts.head = addCompoundPart(world, group, new THREE.SphereGeometry(headRadius, 18, 12), {
      y: headY,
      color: accentColor,
      emissive: mixColor(accentColor, 0x000000, 0.9),
      shininess: 44,
      flatShading: true,
    });
    parts.leftLeg = addCompoundPart(world, group, new THREE.BoxGeometry(0.19 * scale, 0.4 * scale, 0.23 * scale), {
      x: -0.17 * scale,
      y: 0.2 * scale,
      color: gearColor,
      shininess: 16,
    });
    parts.rightLeg = addCompoundPart(world, group, new THREE.BoxGeometry(0.19 * scale, 0.4 * scale, 0.23 * scale), {
      x: 0.17 * scale,
      y: 0.2 * scale,
      color: gearColor,
      shininess: 16,
    });
    parts.leftShoulder = addCompoundPart(world, group, new THREE.BoxGeometry(0.13 * scale, 0.43 * scale, 0.18 * scale), {
      x: -torsoWidth * 0.62,
      y: 0.65 * scale,
      color: isTarget ? bodyColor : gearColor,
      rotationZ: isTarget ? -0.14 : 0.08,
      shininess: 20,
    });
    parts.rightShoulder = addCompoundPart(world, group, new THREE.BoxGeometry(0.13 * scale, 0.43 * scale, 0.18 * scale), {
      x: torsoWidth * 0.62,
      y: 0.65 * scale,
      color: isTarget ? bodyColor : gearColor,
      rotationZ: isTarget ? 0.14 : -0.08,
      shininess: 20,
    });

    if (isTarget) {
      parts.marker = addCompoundPart(world, group, new THREE.TorusGeometry(0.22 * scale, 0.045 * scale, 8, 28), {
        y: torsoY,
        z: torsoDepth * 0.56,
        color: accentColor,
        emissive: mixColor(accentColor, 0x000000, 0.7),
        shininess: 58,
      });
      parts.leftFin = addCompoundPart(world, group, new THREE.ConeGeometry(0.08 * scale, 0.25 * scale, 4), {
        x: -headRadius * 0.85,
        y: headY + headRadius * 0.72,
        rotationZ: -0.32,
        color: bodyColor,
        shininess: 32,
      });
      parts.rightFin = addCompoundPart(world, group, new THREE.ConeGeometry(0.08 * scale, 0.25 * scale, 4), {
        x: headRadius * 0.85,
        y: headY + headRadius * 0.72,
        rotationZ: 0.32,
        color: bodyColor,
        shininess: 32,
      });
    } else {
      parts.backpack = addCompoundPart(world, group, new THREE.BoxGeometry(0.42 * scale, 0.4 * scale, 0.16 * scale), {
        y: 0.65 * scale,
        z: torsoDepth * 0.62,
        color: gearColor,
        shininess: 18,
      });
      parts.navigatorMark = addCompoundPart(world, group, new THREE.BoxGeometry(0.34 * scale, 0.08 * scale, 0.025 * scale), {
        y: 0.7 * scale,
        z: torsoDepth * 0.72,
        color: accentColor,
        emissive: mixColor(accentColor, 0x000000, 0.82),
        shininess: 34,
      });
    }

    group.position.set(spec.x || 0, spec.y || 0, spec.z || 0);
    group.rotation.y = spec.rotationY || 0;
    group.userData.parts = parts;
    group.userData.characterRole = isTarget ? "target" : "player";
    world.root.add(group);
    return group;
  }

  function addHumanoid(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var hostile = spec.hostile !== false;
    var bodyColor = spec.bodyColor === undefined ? context.color(hostile ? "hostile" : "friendly", hostile ? 0xef4444 : 0x2f80ed) : spec.bodyColor;
    var accentColor = spec.accentColor === undefined ? context.color(hostile ? "hostileAccent" : "neutral", 0xfecaca) : spec.accentColor;
    var gearColor = spec.gearColor === undefined ? context.color("darkMetal", 0x1f2937) : spec.gearColor;
    var width = Number(spec.width) || 0.68;
    var height = Number(spec.height) || 1.72;
    var scale = height / 1.72;
    var bodyHeight = Number(spec.bodyHeight) || 0.82 * scale;
    var bodyY = spec.bodyY === undefined ? 0.72 * scale : spec.bodyY;
    var headRadius = Number(spec.headRadius) || 0.29 * scale;
    var headY = spec.headY === undefined ? 1.41 * scale : spec.headY;
    var group = new THREE.Group();
    var parts = {};
    parts.body = addCompoundPart(
      world,
      group,
      new THREE.BoxGeometry(width, bodyHeight, 0.48 * scale),
      { y: bodyY, color: bodyColor, emissive: mixColor(bodyColor, 0x000000, 0.72), shininess: 30 },
    );
    parts.head = addCompoundPart(
      world,
      group,
      new THREE.SphereGeometry(headRadius, 18, 12),
      { y: headY, color: accentColor, emissive: mixColor(accentColor, 0x000000, 0.78), shininess: 36 },
    );
    parts.leftLeg = addCompoundPart(world, group, new THREE.BoxGeometry(0.2 * scale, 0.4 * scale, 0.23 * scale), {
      x: -0.19 * scale, y: 0.2 * scale, color: gearColor, shininess: 14,
    });
    parts.rightLeg = addCompoundPart(world, group, new THREE.BoxGeometry(0.2 * scale, 0.4 * scale, 0.23 * scale), {
      x: 0.19 * scale, y: 0.2 * scale, color: gearColor, shininess: 14,
    });
    parts.leftShoulder = addCompoundPart(world, group, new THREE.BoxGeometry(0.12 * scale, 0.35 * scale, 0.16 * scale), {
      x: -width * 0.57, y: 0.84 * scale, color: gearColor, rotationZ: 0.08, shininess: 16,
    });
    parts.rightShoulder = addCompoundPart(world, group, new THREE.BoxGeometry(0.12 * scale, 0.35 * scale, 0.16 * scale), {
      x: width * 0.57, y: 0.84 * scale, color: gearColor, rotationZ: -0.08, shininess: 16,
    });
    if (spec.weapon !== false) {
      parts.weapon = addCompoundPart(world, group, new THREE.BoxGeometry(0.12 * scale, 0.12 * scale, 0.62 * scale), {
        x: 0.32 * scale, y: 0.8 * scale, z: -0.2 * scale, color: gearColor, shininess: 24,
      });
    }
    if (spec.statusBand !== false) {
      parts.band = addCompoundPart(world, group, new THREE.BoxGeometry(width * 0.78, 0.075 * scale, 0.505 * scale), {
        y: 1.01 * scale, color: accentColor, emissive: mixColor(accentColor, 0x000000, 0.58), shininess: 28,
      });
    }
    group.position.set(spec.x || 0, spec.y || 0, spec.z || 0);
    group.rotation.y = spec.rotationY || 0;
    group.userData.parts = parts;
    world.root.add(group);
    return group;
  }

  function addStraightSword(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var bladeColor = spec.bladeColor === undefined ? context.color("neutral", 0xcbd5e1) : spec.bladeColor;
    var edgeColor = spec.edgeColor === undefined ? context.color("neutral", 0xf8fafc) : spec.edgeColor;
    var guardColor = spec.guardColor === undefined ? context.color("trim", 0xd4a72c) : spec.guardColor;
    var gripColor = spec.gripColor === undefined ? context.color("darkMetal", 0x1f2937) : spec.gripColor;
    var bladeLength = Number(spec.bladeLength) || 1.05;
    var bladeWidth = Number(spec.bladeWidth) || 0.12;
    var bladeThickness = Number(spec.bladeThickness) || 0.035;
    var handleLength = Number(spec.handleLength) || 0.28;
    var group = new THREE.Group();
    var parts = {};
    parts.blade = addCompoundPart(
      world,
      group,
      new THREE.BoxGeometry(bladeWidth, bladeThickness, bladeLength),
      {
        z: bladeLength / 2 + 0.06,
        color: bladeColor,
        emissive: mixColor(bladeColor, 0x000000, 0.84),
        shininess: 72,
      },
    );
    parts.edge = addCompoundPart(
      world,
      group,
      new THREE.BoxGeometry(Math.max(0.018, bladeWidth * 0.22), bladeThickness + 0.012, bladeLength * 0.96),
      {
        x: bladeWidth * 0.46,
        z: bladeLength / 2 + 0.08,
        color: edgeColor,
        emissive: mixColor(edgeColor, 0x000000, 0.9),
        shininess: 88,
      },
    );
    parts.guard = addCompoundPart(
      world,
      group,
      new THREE.BoxGeometry(0.42, 0.065, 0.075),
      { z: 0.015, color: guardColor, shininess: 46 },
    );
    parts.grip = addCompoundPart(
      world,
      group,
      new THREE.CylinderGeometry(0.045, 0.05, handleLength, 10),
      {
        z: -handleLength / 2 - 0.035,
        rotationX: Math.PI / 2,
        color: gripColor,
        shininess: 18,
      },
    );
    parts.pommel = addCompoundPart(
      world,
      group,
      new THREE.SphereGeometry(0.07, 12, 8),
      { z: -handleLength - 0.065, color: guardColor, shininess: 40 },
    );
    group.position.set(spec.x || 0, spec.y || 0, spec.z || 0);
    group.rotation.set(spec.rotationX || 0, spec.rotationY || 0, spec.rotationZ || 0);
    group.scale.setScalar(spec.scale === undefined ? 1 : spec.scale);
    group.userData.parts = parts;
    (spec.parent || world.root).add(group);
    return group;
  }

  function addViewMeleeWeapon(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.camera) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var group = new THREE.Group();
    var sleeveColor = spec.sleeveColor === undefined ? context.color("friendly", 0x2f80ed) : spec.sleeveColor;
    var handColor = spec.handColor === undefined ? context.color("skin", 0xd7a47d) : spec.handColor;
    var parts = {};
    parts.forearm = addCompoundPart(
      world,
      group,
      new THREE.BoxGeometry(0.13, 0.12, 0.28),
      { x: 0.045, y: -0.075, z: 0.18, rotationX: -0.18, color: sleeveColor, shininess: 12 },
    );
    parts.hand = addCompoundPart(
      world,
      group,
      new THREE.BoxGeometry(0.14, 0.12, 0.16),
      { y: -0.012, z: 0.025, rotationX: -0.08, color: handColor, shininess: 10 },
    );
    parts.sword = addStraightSword(world, {
      parent: group,
      assetContext: context,
      rotationX: spec.swordRotationX === undefined ? -0.18 : spec.swordRotationX,
      rotationY: spec.swordRotationY === undefined ? -2.78 : spec.swordRotationY,
      rotationZ: spec.swordRotationZ || 0,
      scale: spec.swordScale === undefined ? 0.68 : spec.swordScale,
      bladeLength: spec.bladeLength === undefined ? 0.98 : spec.bladeLength,
      guardColor: spec.guardColor,
      gripColor: spec.gripColor,
    });
    if (parts.sword && parts.sword.userData.parts) {
      parts.blade = parts.sword.userData.parts.blade;
      parts.edge = parts.sword.userData.parts.edge;
      parts.guard = parts.sword.userData.parts.guard;
      parts.grip = parts.sword.userData.parts.grip;
    }
    group.position.set(
      spec.x === undefined ? 0.4 : spec.x,
      spec.y === undefined ? -0.38 : spec.y,
      spec.z === undefined ? -0.62 : spec.z,
    );
    group.rotation.set(spec.rotationX || 0, spec.rotationY || 0, spec.rotationZ === undefined ? -0.08 : spec.rotationZ);
    group.userData.parts = parts;
    (spec.parent || world.camera).add(group);
    return group;
  }

  function addViewSpear(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.camera) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var sleeveColor = spec.sleeveColor === undefined ? context.color("friendly", 0x2f80ed) : spec.sleeveColor;
    var handColor = spec.handColor === undefined ? context.color("skin", 0xd7a47d) : spec.handColor;
    var shaftColor = spec.shaftColor === undefined ? context.color("crate", 0x79502d) : spec.shaftColor;
    var tipColor = spec.tipColor === undefined ? context.color("neutral", 0xe2e8f0) : spec.tipColor;
    var bindingColor = spec.bindingColor === undefined ? context.color("interactive", 0xfacc15) : spec.bindingColor;
    var shaftLength = Number(spec.shaftLength) || 1.35;
    var tipLength = Number(spec.tipLength) || 0.28;
    var shaftRearZ = 0.2;
    var shaftFrontZ = shaftRearZ - shaftLength;
    var group = new THREE.Group();
    var parts = {};

    parts.forearm = addCompoundPart(
      world,
      group,
      new THREE.BoxGeometry(0.14, 0.13, 0.32),
      { x: 0.075, y: -0.09, z: 0.2, rotationX: -0.18, color: sleeveColor, shininess: 12 },
    );
    parts.hand = addCompoundPart(
      world,
      group,
      new THREE.BoxGeometry(0.15, 0.13, 0.17),
      { x: 0.015, y: -0.02, z: 0.035, rotationX: -0.08, color: handColor, shininess: 10 },
    );
    parts.supportHand = addCompoundPart(
      world,
      group,
      new THREE.BoxGeometry(0.13, 0.115, 0.16),
      { x: -0.025, y: 0.015, z: -0.235, rotationX: 0.08, color: handColor, shininess: 10 },
    );
    parts.shaft = addCompoundPart(
      world,
      group,
      new THREE.CylinderGeometry(0.026, 0.03, shaftLength, 10),
      { z: (shaftRearZ + shaftFrontZ) * 0.5, rotationX: Math.PI / 2, color: shaftColor, shininess: 18 },
    );
    parts.binding = addCompoundPart(
      world,
      group,
      new THREE.CylinderGeometry(0.044, 0.044, 0.12, 10),
      { z: shaftFrontZ + 0.045, rotationX: Math.PI / 2, color: bindingColor, shininess: 36 },
    );
    parts.tip = addCompoundPart(
      world,
      group,
      new THREE.ConeGeometry(0.082, tipLength, 10),
      {
        z: shaftFrontZ - tipLength * 0.5 + 0.02,
        rotationX: -Math.PI / 2,
        color: tipColor,
        emissive: mixColor(tipColor, 0x000000, 0.9),
        shininess: 82,
      },
    );
    group.position.set(
      spec.x === undefined ? 0.39 : spec.x,
      spec.y === undefined ? -0.36 : spec.y,
      spec.z === undefined ? -0.44 : spec.z,
    );
    group.rotation.set(
      spec.rotationX || 0,
      spec.rotationY === undefined ? -0.08 : spec.rotationY,
      spec.rotationZ === undefined ? -0.06 : spec.rotationZ,
    );
    group.userData.parts = parts;
    (spec.parent || world.camera).add(group);
    return group;
  }

  function addViewWeapon(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.camera) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var bodyColor = spec.bodyColor === undefined ? context.color("metal", 0x455466) : spec.bodyColor;
    var accentColor = spec.accentColor === undefined ? context.color("darkMetal", 0x1f2937) : spec.accentColor;
    var highlightColor = spec.highlightColor === undefined ? context.color("friendly", 0x2f80ed) : spec.highlightColor;
    var group = new THREE.Group();
    var parts = {};
    parts.body = addCompoundPart(world, group, new THREE.BoxGeometry(0.22, 0.18, 0.52), { color: bodyColor, shininess: 32 });
    parts.barrel = addCompoundPart(world, group, new THREE.BoxGeometry(0.09, 0.09, 0.42), { y: 0.04, z: -0.36, color: accentColor, shininess: 24 });
    parts.grip = addCompoundPart(world, group, new THREE.BoxGeometry(0.13, 0.28, 0.15), { y: -0.18, z: 0.08, rotationX: -0.25, color: accentColor, shininess: 18 });
    parts.sight = addCompoundPart(world, group, new THREE.BoxGeometry(0.055, 0.075, 0.12), { y: 0.13, z: -0.11, color: highlightColor, emissive: mixColor(highlightColor, 0x000000, 0.65), shininess: 34 });
    group.position.set(
      spec.x === undefined ? 0.34 : spec.x,
      spec.y === undefined ? -0.28 : spec.y,
      spec.z === undefined ? -0.72 : spec.z,
    );
    group.rotation.set(spec.rotationX || 0, spec.rotationY === undefined ? -0.08 : spec.rotationY, spec.rotationZ || 0);
    group.scale.setScalar(spec.scale === undefined ? 0.72 : spec.scale);
    group.userData.parts = parts;
    (spec.parent || world.camera).add(group);
    return group;
  }

  function addProjectileVisual(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var friendly = spec.friendly !== false;
    var color = spec.color === undefined ? context.color(friendly ? "projectileFriendly" : "projectileHostile", friendly ? 0xfacc15 : 0xf97316) : spec.color;
    var radius = Number(spec.radius) || 0.075;
    var group = new THREE.Group();
    var core = addCompoundPart(
      world,
      group,
      new THREE.SphereGeometry(radius, 14, 10),
      { color: color, emissive: mixColor(color, 0x000000, 0.48), shininess: 54 },
    );
    var trail = null;
    if (spec.trail !== false) {
      var trailLength = radius * 3.4;
      trail = addCompoundPart(world, group, new THREE.CylinderGeometry(radius * 0.24, radius * 0.72, trailLength, 8), {
        z: trailLength / 2 + radius * 0.1,
        rotationX: Math.PI / 2,
        color: color,
        emissive: mixColor(color, 0x000000, 0.38),
        transparent: true,
        opacity: 0.54,
        depthWrite: false,
      });
    }
    group.position.set(spec.x || 0, spec.y || 0, spec.z || 0);
    group.userData.parts = { core: core, trail: trail };
    world.root.add(group);
    return group;
  }

  function addCover(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var width = Number(spec.width) || 1.6;
    var height = Number(spec.height) || 1.05;
    var depth = Number(spec.depth) || 0.6;
    var group = new THREE.Group();
    var color = spec.color === undefined ? context.color("cover", 0x3f6475) : spec.color;
    var accent = spec.accentColor === undefined ? context.color("coverAccent", 0x254658) : spec.accentColor;
    var trim = spec.trimColor === undefined ? context.color("trim", 0xd8dee6) : spec.trimColor;
    var trimHeight = Math.min(0.08, height * 0.2);
    var bodyHeight = height - trimHeight;
    addCompoundPart(world, group, new THREE.BoxGeometry(width, bodyHeight, depth), { y: bodyHeight / 2, color: color, shininess: 14 });
    addCompoundPart(world, group, new THREE.BoxGeometry(width + 0.06, trimHeight, depth + 0.06), {
      y: bodyHeight + trimHeight / 2,
      color: trim,
      shininess: 28,
    });
    addCompoundPart(world, group, new THREE.BoxGeometry(width * 0.72, height * 0.38, depth + 0.025), { y: height * 0.5, z: depth * 0.51, color: accent, shininess: 18 });
    group.position.set(spec.x || 0, spec.baseY || 0, spec.z || 0);
    group.rotation.y = spec.rotationY || 0;
    world.root.add(group);
    return group;
  }

  function addCrate(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var size = Number(spec.size) || 0.7;
    var width = Number(spec.width) || size;
    var height = Number(spec.height) || size;
    var depth = Number(spec.depth) || size;
    var color = spec.color === undefined ? context.color("crate", 0x9a6a3a) : spec.color;
    var trim = spec.trimColor === undefined ? mixColor(color, context.color("trim", 0xd8dee6), 0.32) : spec.trimColor;
    var group = new THREE.Group();
    addCompoundPart(world, group, new THREE.BoxGeometry(width, height, depth), { y: height / 2, color: color, shininess: 8, flatShading: true });
    var rail = Math.max(0.035, Math.min(width, height, depth) * 0.08);
    [-1, 1].forEach(function addCrateRail(side) {
      addCompoundPart(world, group, new THREE.BoxGeometry(rail, height * 0.92, depth + 0.025), { x: side * (width / 2 - rail), y: height / 2, color: trim, shininess: 10 });
      addCompoundPart(world, group, new THREE.BoxGeometry(width + 0.025, rail, depth + 0.025), { y: height / 2 + side * (height / 2 - rail), color: trim, shininess: 10 });
    });
    group.position.set(spec.x || 0, spec.baseY || 0, spec.z || 0);
    group.rotation.y = spec.rotationY || 0;
    world.root.add(group);
    return group;
  }

  function addInteractionConsole(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var active = spec.active === true;
    var group = new THREE.Group();
    var metalColor = spec.color === undefined ? context.color("metal", 0x455466) : spec.color;
    var screenColor = spec.screenColor === undefined ? context.color(active ? "goal" : "interactive", active ? 0x18c86b : 0xfacc15) : spec.screenColor;
    addCompoundPart(world, group, new THREE.BoxGeometry(0.42, 0.72, 0.34), { y: 0.36, color: metalColor, shininess: 22 });
    var screen = addCompoundPart(world, group, new THREE.BoxGeometry(0.32, 0.24, 0.035), {
      y: 0.55, z: -0.182, rotationX: -0.08, color: screenColor,
      emissive: mixColor(screenColor, 0x000000, active ? 0.38 : 0.56), shininess: 44,
    });
    addCompoundPart(world, group, new THREE.BoxGeometry(0.14, 0.06, 0.06), { y: 0.31, z: -0.19, color: context.color("darkMetal", 0x1f2937), shininess: 18 });
    group.position.set(spec.x || 0, spec.baseY || 0, spec.z || 0);
    group.rotation.y = spec.rotationY || 0;
    group.userData.screen = screen;
    world.root.add(group);
    return group;
  }

  function addPickup(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var kind = spec.kind || "parcel";
    var color = spec.color === undefined ? context.color("interactive", 0xfacc15) : spec.color;
    var darkColor = spec.darkColor === undefined ? mixColor(color, 0x000000, 0.42) : spec.darkColor;
    var trimColor = spec.trimColor === undefined ? context.color("trim", 0xd8dee6) : spec.trimColor;
    var size = Number(spec.size) || 0.64;
    var group = new THREE.Group();
    var parts = {};
    if (kind === "key") {
      var ringRadius = size * 0.28;
      parts.ring = addCompoundPart(world, group, new THREE.TorusGeometry(ringRadius, Math.max(0.025, size * 0.055), 8, 24), {
        x: -size * 0.22, rotationX: Math.PI / 2, color: color, emissive: mixColor(color, 0x000000, 0.62), shininess: 42,
      });
      parts.shaft = addCompoundPart(world, group, new THREE.BoxGeometry(size * 0.62, size * 0.13, size * 0.13), {
        x: size * 0.2, color: color, shininess: 34,
      });
      parts.tooth = addCompoundPart(world, group, new THREE.BoxGeometry(size * 0.14, size * 0.28, size * 0.13), {
        x: size * 0.43, y: -size * 0.09, color: color, shininess: 34,
      });
    } else {
      parts.body = addCompoundPart(world, group, new THREE.BoxGeometry(size, size * 0.76, size * 0.82), {
        color: color, shininess: 12, flatShading: true,
      });
      parts.bandX = addCompoundPart(world, group, new THREE.BoxGeometry(size * 1.025, size * 0.14, size * 0.84), {
        color: darkColor, shininess: 14,
      });
      parts.bandZ = addCompoundPart(world, group, new THREE.BoxGeometry(size * 0.15, size * 0.78, size * 0.845), {
        color: trimColor, shininess: 18,
      });
    }
    group.position.set(spec.x || 0, spec.y === undefined ? (spec.baseY || 0) : spec.y, spec.z || 0);
    group.rotation.y = spec.rotationY || 0;
    group.userData.parts = parts;
    group.userData.kind = kind;
    world.root.add(group);
    return group;
  }

  function addLever(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var active = spec.active === true;
    var group = new THREE.Group();
    var baseColor = spec.baseColor === undefined ? context.color("darkMetal", 0x334155) : spec.baseColor;
    var postColor = spec.postColor === undefined ? context.color("metal", 0x64748b) : spec.postColor;
    var handleColor = spec.handleColor === undefined ? context.color(active ? "goal" : "hazard", active ? 0x22c55e : 0xef4444) : spec.handleColor;
    var parts = {};
    parts.base = addCompoundPart(world, group, new THREE.BoxGeometry(0.62, 0.18, 0.54), { y: 0.09, color: baseColor, shininess: 18 });
    parts.post = addCompoundPart(world, group, new THREE.CylinderGeometry(0.11, 0.11, 0.88, 16), { y: 0.61, color: postColor, shininess: 24 });
    parts.handle = addCompoundPart(world, group, new THREE.BoxGeometry(0.14, 0.72, 0.16), {
      y: 1.32, color: handleColor, emissive: mixColor(handleColor, 0x000000, 0.66), shininess: 28,
    });
    parts.handle.rotation.z = active ? -0.62 : 0.62;
    group.position.set(spec.x || 0, spec.baseY || 0, spec.z || 0);
    group.rotation.y = spec.rotationY || 0;
    group.userData.parts = parts;
    world.root.add(group);
    return group;
  }

  function addPressurePlate(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var width = Number(spec.width) || 1.2;
    var depth = Number(spec.depth) || 1.2;
    var height = Number(spec.height) || 0.08;
    var active = spec.active === true;
    var group = new THREE.Group();
    var baseColor = spec.baseColor === undefined ? context.color("darkMetal", 0x334155) : spec.baseColor;
    var plateColor = spec.plateColor === undefined ? context.color(active ? "goal" : "hazard", active ? 0x22c55e : 0xef4444) : spec.plateColor;
    var parts = {};
    parts.base = addCompoundPart(world, group, new THREE.BoxGeometry(width + 0.16, 0.025, depth + 0.16), { y: 0.0125, color: baseColor, shininess: 18 });
    parts.plate = addCompoundPart(world, group, new THREE.BoxGeometry(width, height, depth), {
      y: 0.025 + height / 2, color: plateColor, emissive: mixColor(plateColor, 0x000000, 0.76), shininess: 22,
    });
    group.position.set(spec.x || 0, spec.baseY || 0, spec.z || 0);
    group.rotation.y = spec.rotationY || 0;
    group.userData.parts = parts;
    world.root.add(group);
    return group;
  }

  function addDoorAssembly(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var width = Number(spec.width) || 1.8;
    var height = Number(spec.height) || 2.35;
    var depth = Number(spec.depth) || 0.18;
    var frameWidth = Math.max(0.1, width * 0.08);
    var group = new THREE.Group();
    var frameColor = spec.frameColor === undefined ? context.color("metal", 0x455466) : spec.frameColor;
    var panelColor = spec.panelColor === undefined ? context.color("wallAccent", 0x566575) : spec.panelColor;
    var indicatorColor = spec.indicatorColor === undefined ? context.color(spec.open ? "goal" : "interactive", 0xfacc15) : spec.indicatorColor;
    addCompoundPart(world, group, new THREE.BoxGeometry(frameWidth, height, depth * 1.35), { x: -width / 2, y: height / 2, color: frameColor, shininess: 24 });
    addCompoundPart(world, group, new THREE.BoxGeometry(frameWidth, height, depth * 1.35), { x: width / 2, y: height / 2, color: frameColor, shininess: 24 });
    addCompoundPart(world, group, new THREE.BoxGeometry(width + frameWidth, frameWidth, depth * 1.35), { y: height - frameWidth / 2, color: frameColor, shininess: 24 });
    var panel = addCompoundPart(world, group, new THREE.BoxGeometry(width - frameWidth * 1.4, height - frameWidth * 1.4, depth), {
      y: (height - frameWidth) / 2,
      color: panelColor,
      shininess: 18,
    });
    panel.visible = spec.open !== true;
    var indicator = addCompoundPart(world, group, new THREE.BoxGeometry(0.14, 0.24, 0.05), {
      x: width / 2 + frameWidth * 0.75,
      y: height * 0.62,
      z: -depth,
      color: indicatorColor,
      emissive: mixColor(indicatorColor, 0x000000, 0.48),
      shininess: 40,
    });
    group.position.set(spec.x || 0, spec.baseY || 0, spec.z || 0);
    group.rotation.y = spec.rotationY || 0;
    group.userData.panel = panel;
    group.userData.closedPanelY = panel.position.y;
    group.userData.indicator = indicator;
    world.root.add(group);
    return group;
  }

  function addCheckpointGate(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack || "gym-light-default", seed: spec.seed });
    var width = Number(spec.width) || 3.4;
    var height = Number(spec.height) || 2.5;
    var postWidth = Number(spec.postWidth) || 0.09;
    var depth = Number(spec.depth) || 0.12;
    var color = spec.color === undefined ? context.color(spec.active === false ? "metal" : "goal", 0x18c86b) : spec.color;
    var showFrame = spec.frame !== false;
    var group = new THREE.Group();
    var colorParts = [];
    if (showFrame) {
      [-1, 1].forEach(function addGatePost(side) {
        colorParts.push(addCompoundPart(world, group, new THREE.BoxGeometry(postWidth, height, depth), {
          x: side * width / 2,
          y: height / 2,
          color: color,
          emissive: mixColor(color, 0x000000, 0.72),
          shininess: 28,
        }));
      });
      colorParts.push(addCompoundPart(world, group, new THREE.BoxGeometry(width + postWidth, postWidth, depth), {
        y: height - postWidth / 2,
        color: color,
        emissive: mixColor(color, 0x000000, 0.72),
        shininess: 28,
      }));
    }
    var line = addCompoundPart(world, group, new THREE.BoxGeometry(width, 0.025, Math.max(depth, 0.16)), {
      y: 0.025,
      color: color,
      emissive: mixColor(color, 0x000000, 0.68),
      shininess: 18,
    });
    colorParts.push(line);

    var sign = null;
    var label = String(spec.label === undefined || spec.label === null ? "" : spec.label).trim();
    if (label) {
      var signWidth = Number(spec.signWidth) || 0.42;
      var signHeight = Number(spec.signHeight) || 0.3;
      var signLabelWidth = Number(spec.signLabelWidth) || signWidth * 0.72;
      var signLabelHeight = Number(spec.signLabelHeight) || signHeight * 0.78;
      var signDepth = Number(spec.signDepth) || Math.max(0.045, depth * 0.72);
      var signY = spec.signY === undefined ? height + signHeight / 2 - 0.015 : Number(spec.signY);
      var signSide = Number(spec.signSide) || 0;
      var signSideOffset = Number(spec.signSideOffset) || 0;
      var signX = spec.signX === undefined
        ? (signSide === 0 ? 0 : (signSide < 0 ? -1 : 1) * (width / 2 + signSideOffset))
        : Number(spec.signX) || 0;
      var support = null;
      if (spec.signPost) {
        var signPostWidth = Number(spec.signPostWidth) || Math.min(0.055, postWidth);
        var signPostHeight = Math.max(0.025, signY - signHeight / 2);
        support = addCompoundPart(
          world,
          group,
          new THREE.BoxGeometry(signPostWidth, signPostHeight, signDepth),
          {
            x: signX,
            y: signPostHeight / 2,
            color: color,
            emissive: mixColor(color, 0x000000, 0.72),
            shininess: 28,
          },
        );
        colorParts.push(support);
      }
      var frame = addCompoundPart(
        world,
        group,
        new THREE.BoxGeometry(signWidth + 0.055, signHeight + 0.055, signDepth),
        {
          x: signX,
          y: signY,
          color: color,
          emissive: mixColor(color, 0x000000, 0.72),
          shininess: 28,
        },
      );
      colorParts.push(frame);
      var face = addCompoundPart(
        world,
        group,
        new THREE.BoxGeometry(signWidth, signHeight, signDepth + 0.008),
        {
          x: signX,
          y: signY,
          color: spec.signFaceColor === undefined ? context.color("neutral", 0xf8fafc) : spec.signFaceColor,
          shininess: 12,
        },
      );

      var labelCanvas = document.createElement("canvas");
      labelCanvas.width = 128;
      labelCanvas.height = 96;
      var labelContext = labelCanvas.getContext("2d");
      labelContext.clearRect(0, 0, labelCanvas.width, labelCanvas.height);
      labelContext.fillStyle = colorCss(spec.signTextColor === undefined ? 0x111827 : spec.signTextColor);
      labelContext.font = "bold 68px Menlo, Consolas, monospace";
      labelContext.textAlign = "center";
      labelContext.textBaseline = "middle";
      labelContext.fillText(label, labelCanvas.width / 2, labelCanvas.height / 2 + 3);
      var labelTexture = new THREE.CanvasTexture(labelCanvas);
      labelTexture.colorSpace = THREE.SRGBColorSpace;
      labelTexture.needsUpdate = true;
      var labelMaterial = new THREE.MeshBasicMaterial({
        map: labelTexture,
        transparent: true,
        depthWrite: false,
        side: THREE.FrontSide,
      });
      var labelGeometry = new THREE.PlaneGeometry(signLabelWidth, signLabelHeight);
      var frontLabel = new THREE.Mesh(labelGeometry, labelMaterial);
      frontLabel.position.set(signX, signY, signDepth / 2 + 0.008);
      frontLabel.renderOrder = 4;
      group.add(frontLabel);
      var backLabel = new THREE.Mesh(labelGeometry.clone(), labelMaterial.clone());
      backLabel.position.set(signX, signY, -signDepth / 2 - 0.008);
      backLabel.rotation.y = Math.PI;
      backLabel.renderOrder = 4;
      group.add(backLabel);
      sign = { frame: frame, face: face, support: support, frontLabel: frontLabel, backLabel: backLabel };
    }
    group.position.set(spec.x || 0, spec.baseY || 0, spec.z || 0);
    group.rotation.y = spec.rotationY || 0;
    group.userData.line = line;
    group.userData.sign = sign;
    group.userData.colorParts = colorParts;
    world.root.add(group);
    return group;
  }

  function addPlatformVisual(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var width = Number(spec.width) || 2;
    var depth = Number(spec.depth) || 2;
    var height = Number(spec.height) || 0.22;
    var group = new THREE.Group();
    var color = spec.color === undefined ? context.color("metal", 0x455466) : spec.color;
    var topColor = spec.topColor === undefined ? context.color("floorAccent", 0x8793a1) : spec.topColor;
    addCompoundPart(world, group, new THREE.BoxGeometry(width, height, depth), { y: height / 2, color: color, shininess: 18 });
    addCompoundPart(world, group, new THREE.BoxGeometry(width * 0.94, 0.035, depth * 0.94), { y: height + 0.017, color: topColor, shininess: 10 });
    group.position.set(spec.x || 0, spec.baseY || 0, spec.z || 0);
    group.rotation.y = spec.rotationY || 0;
    world.root.add(group);
    return group;
  }

  function addAimTarget(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack, seed: spec.seed });
    var radius = Number(spec.radius) || 0.42;
    var color = spec.color === undefined ? context.color("target", 0xff4f64) : spec.color;
    var group = new THREE.Group();
    var core = addCompoundPart(
      world,
      group,
      new THREE.SphereGeometry(radius, 28, 18),
      { color: color, emissive: mixColor(color, 0x000000, 0.62), shininess: 42 },
    );
    var ring = null;
    if (spec.showRing !== false) {
      ring = new THREE.Mesh(
        new THREE.TorusGeometry(radius * 1.18, Math.max(0.018, radius * 0.055), 8, 32),
        new THREE.MeshBasicMaterial({ color: context.color("neutral", 0xe2e8f0), transparent: true, opacity: 0.86, depthWrite: false }),
      );
      group.add(ring);
    }
    group.position.set(spec.x || 0, spec.y || 0, spec.z || 0);
    group.userData.parts = { core: core };
    if (ring) group.userData.parts.ring = ring;
    world.root.add(group);
    return group;
  }

  function createPrimitiveAsset(definition, spec) {
    spec = Object.assign({}, spec || {});
    var world = spec.world;
    var primitive = definition.primitive;
    var instance;
    if (primitive === "humanoid") instance = addHumanoid(world, spec);
    else if (primitive === "navigator_humanoid") instance = addNavigatorHumanoid(world, spec);
    else if (primitive === "melee_weapon") instance = addStraightSword(world, spec);
    else if (primitive === "view_melee_weapon") instance = addViewMeleeWeapon(world, spec);
    else if (primitive === "view_weapon") instance = addViewWeapon(world, spec);
    else if (primitive === "view_spear") instance = addViewSpear(world, spec);
    else if (primitive === "projectile") instance = addProjectileVisual(world, spec);
    else if (primitive === "cover") instance = addCover(world, spec);
    else if (primitive === "crate") instance = addCrate(world, spec);
    else if (primitive === "console") instance = addInteractionConsole(world, spec);
    else if (primitive === "pickup") instance = addPickup(world, spec);
    else if (primitive === "lever") instance = addLever(world, spec);
    else if (primitive === "pressure_plate") instance = addPressurePlate(world, spec);
    else if (primitive === "door") instance = addDoorAssembly(world, spec);
    else if (primitive === "checkpoint_gate") instance = addCheckpointGate(world, spec);
    else if (primitive === "platform") instance = addPlatformVisual(world, spec);
    else if (primitive === "aim_target") instance = addAimTarget(world, spec);
    else if (primitive === "vehicle") instance = addVehicle(world, spec);
    else if (primitive === "coin") instance = addFloatingCoin(world, spec);
    else if (primitive === "ground_goal") instance = world.addGroundGoalMarker(spec);
    else throw new Error("Unknown 3D primitive asset: " + primitive);
    var object = instance && instance.group ? instance.group : instance;
    if (object) {
      object.userData = object.userData || {};
      object.userData.assetId = definition.asset_id;
      object.userData.assetRole = definition.role;
    }
    return instance;
  }

  function addVehicle(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var width = Number(spec.width) || 0.88;
    var depth = Number(spec.depth) || 1.5;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack || "gym-light-default", seed: spec.seed, visualFlags: spec.visualFlags });
    var palette = Object.assign({
      body: context.color("vehicle", 0xffe133),
      front: context.color("vehicleAccent", 0xfff08a),
      glass: context.color("glass", 0x17384a),
      wheel: context.color("darkMetal", 0x0f172a),
      headlight: 0xfff7ed,
      tailLight: context.color("hostile", 0xef4444),
    }, spec.palette || {});
    var group = new THREE.Group();
    var model = new THREE.Group();
    model.rotation.y = spec.forwardAxis === "x" ? Math.PI / 2 : 0;
    group.add(model);
    var depthScale = depth / 1.5;

    function box(options) {
      var mesh = new THREE.Mesh(
        new THREE.BoxGeometry(options.width, options.height, options.depth),
        (world.material || material)({ color: options.color, shininess: options.shininess || 18 }),
      );
      mesh.position.set(options.x || 0, options.y || 0, options.z || 0);
      setShadow(mesh);
      model.add(mesh);
      return mesh;
    }

    [-0.47, 0.47].forEach(function addWheelSide(x) {
      [-0.42, 0.43].forEach(function addWheelEnd(z) {
        box({ x: x * width / 0.88, y: 0.16, z: z * depth / 1.5, width: 0.14, height: 0.18, depth: 0.32, color: palette.wheel, shininess: 8 });
      });
    });
    box({ y: 0.26, width: width, height: 0.28, depth: depth, color: palette.body, shininess: 24 });
    box({ y: 0.34, z: 0.36 * depthScale, width: width * 0.78, height: 0.16, depth: 0.52 * depthScale, color: palette.front, shininess: 24 });
    box({ y: 0.47, z: -0.12 * depthScale, width: width * 0.62, height: 0.22, depth: 0.48 * depthScale, color: palette.glass, shininess: 30 });
    [-0.18, 0.18].forEach(function addHeadlight(x) {
      box({ x: x, y: 0.29, z: depth / 2 + 0.02, width: 0.16, height: 0.07, depth: 0.035, color: palette.headlight, shininess: 18 });
    });
    [-0.24, 0.24].forEach(function addTailLight(x) {
      box({ x: x, y: 0.28, z: -depth / 2 - 0.02, width: 0.14, height: 0.07, depth: 0.035, color: palette.tailLight, shininess: 18 });
    });
    group.position.set(spec.x || 0, spec.y || 0, spec.z || 0);
    group.userData.model = model;
    world.root.add(group);
    return group;
  }

  function addFloatingCoin(world, spec) {
    spec = spec || {};
    if (!hasThree() || !world || !world.root) return null;
    var context = spec.assetContext || createAssetContext({ assetPack: spec.assetPack || "gym-light-default", seed: spec.seed, visualFlags: spec.visualFlags });
    var radius = spec.radius || 0.22;
    var color = spec.color === undefined ? context.color("coin", 0xfacc15) : spec.color;
    var emissive = spec.emissive === undefined ? 0x422006 : spec.emissive;
    var group = new THREE.Group();
    group.position.set(spec.x || 0, spec.y || 0, spec.z || 0);
    var core = new THREE.Mesh(
      new THREE.CylinderGeometry(radius, radius, Math.max(0.045, radius * 0.2), spec.segments || 40),
      new THREE.MeshPhongMaterial({
        color: color,
        emissive: emissive,
        shininess: spec.shininess || 48,
        specular: spec.specular || 0xfef3c7,
        side: THREE.DoubleSide,
      }),
    );
    core.rotation.x = Math.PI / 2;
    setShadow(core);
    group.add(core);

    var rim = new THREE.Mesh(
      new THREE.TorusGeometry(radius * 0.86, Math.max(0.014, radius * 0.07), 8, spec.segments || 40),
      (world.material || material)({ color: spec.rimColor || 0xfef08a, emissive: emissive, shininess: spec.rimShininess || 42, specular: 0xffffff }),
    );
    setShadow(rim);
    group.add(rim);
    addCompoundPart(world, group, new THREE.BoxGeometry(radius * 0.2, radius * 1.2, Math.max(0.02, radius * 0.07)), {
      z: radius * 0.12,
      color: spec.rimColor || 0xfef08a,
      emissive: emissive,
      shininess: 32,
    });

    world.root.add(group);
    return { group: group, core: core, rim: rim };
  }

  function createSelectionOutline(world, options) {
    options = options || {};
    if (!hasThree() || !world || !world.root) return null;
    var boxGeometry = new THREE.BoxGeometry(1, 1, 1);
    var geometry = new THREE.EdgesGeometry(boxGeometry);
    if (boxGeometry && typeof boxGeometry.dispose === "function") boxGeometry.dispose();
    var outline = new THREE.LineSegments(
      geometry,
      new THREE.LineBasicMaterial({
        color: options.color === undefined ? 0xe5e7eb : options.color,
        transparent: options.opacity !== undefined && options.opacity < 1,
        opacity: options.opacity === undefined ? 0.92 : options.opacity,
        depthTest: options.depthTest !== false,
        depthWrite: false,
      }),
    );
    outline.visible = false;
    outline.renderOrder = options.renderOrder === undefined ? 40 : options.renderOrder;
    world.root.add(outline);
    return outline;
  }

  function setSelectionOutline(outline, bounds, options) {
    options = options || {};
    if (!outline || !bounds) return outline;
    var expand = Number(options.expand);
    if (!Number.isFinite(expand)) expand = 0.018;
    outline.position.set(
      (bounds.minX + bounds.maxX) / 2,
      (bounds.minY + bounds.maxY) / 2,
      (bounds.minZ + bounds.maxZ) / 2,
    );
    outline.scale.set(
      Math.max(0.08, bounds.maxX - bounds.minX) + expand,
      Math.max(0.08, bounds.maxY - bounds.minY) + expand,
      Math.max(0.08, bounds.maxZ - bounds.minZ) + expand,
    );
    outline.visible = true;
    return outline;
  }

  function hideSelectionOutline(outline) {
    if (outline) outline.visible = false;
    return outline;
  }

  function bindAssetGame(game) {
    if (!game) throw new Error("3D asset binding requires a game");
    return function createBoundAsset(assetId, options) {
      return AssetEngine.api.create(assetId, Object.assign({
        world: game.world3d,
        assetContext: game.assetContext,
      }, options || {}));
    };
  }

  AssetEngine.bindAdapter({
    createPrimitive: createPrimitiveAsset,
  });

  var assetsApi = Object.freeze(Object.assign({}, AssetEngine.api, {
    bindGame: bindAssetGame,
  }));

  window.BaseGamelet3D = Object.freeze({
    threeRevision: REQUIRED_THREE_REVISION,
    createWorld: createWorld,
    attachRuntime: attachRuntime,
    getCaptureCanvas: getCaptureCanvas,
    assets: assetsApi,
    visuals: Object.freeze({
      configure: configureGameVisuals,
      sync: syncGameVisuals,
      payload: visualPayload,
    }),
    viewport: Object.freeze({
      baseWidth: PRESENTATION_WIDTH,
      baseHeight: PRESENTATION_HEIGHT,
      install: installFullscreenForGame,
    }),
    camera: Object.freeze({
      computeOpticalChasePose: computeOpticalChasePose,
    }),
    input: Object.freeze({
      moveDelta: firstPersonMoveDelta,
      directionFromLook: directionFromYawPitch,
      applyPointerLook: applyPointerLook,
      CAMERA_SENSITIVITY: CAMERA_SENSITIVITY,
      applyRelativePointerInput: applyRelativePointerInput,
      createRelativePointerInput: createRelativePointerInput,
      readAction: readFirstPersonAction,
      createController: createFirstPersonInputController,
    }),
    textures: Object.freeze({
      createSurface: createSurfaceTexture,
    }),
    entities: Object.freeze({
      createRegistry: createEntityRegistry,
      remove: removeObject,
    }),
    selection: Object.freeze({
      create: createSelectionOutline,
      set: setSelectionOutline,
      hide: hideSelectionOutline,
    }),
  });
})();
