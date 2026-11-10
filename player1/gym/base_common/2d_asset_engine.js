(function gameAssetEngine2DModule() {
  "use strict";

  var MANIFEST_VERSION = 1;
  var Core = window.GameEngineCore;
  var manifestCache = Object.create(null);
  var manifestPromises = Object.create(null);
  var images = Object.create(null);
  var imagePromises = Object.create(null);
  var resources = Object.create(null);
  var resourcePromises = Object.create(null);
  var fonts = Object.create(null);
  var fontPromises = Object.create(null);
  var ownedTextures = new WeakSet();
  var readyAssets = Object.create(null);
  var adapter = null;
  var state = emptyState();
  var preloadSerial = 0;
  var lifecycle = 0;

  function emptyState() {
    return {
      status: "idle", asset_type: "2d", asset_pack: null, asset_manifest_version: null,
      content_revision: null, visual_profile: null, selected_assets: {}, error: null,
    };
  }

  function normalizeId(value, label) {
    var id = String(value || "").trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(id)) throw new Error("Invalid 2D " + label + ": " + value);
    return id;
  }

  function manifestUrl(packId) {
    return new URL("../base_assets/2d/manifests/" + encodeURIComponent(packId) + ".json", document.baseURI).href;
  }

  function parseColor(value) {
    if (typeof value === "number" && Number.isFinite(value)) return value >>> 0;
    var text = String(value || "").trim();
    if (/^#[0-9a-f]{6}$/i.test(text)) return parseInt(text.slice(1), 16) >>> 0;
    throw new Error("Invalid 2D manifest color: " + value);
  }

  function normalizePalette(source) {
    var palette = {};
    Object.keys(source || {}).forEach(function normalizeColor(role) { palette[role] = parseColor(source[role]); });
    return palette;
  }

  function normalizeFrame(frame, assetId) {
    if (!Array.isArray(frame) || frame.length !== 4 || frame.some(function invalidCoordinate(value, index) {
      return !Number.isInteger(value) || (index < 2 ? value < 0 : value <= 0);
    })) throw new Error("2D atlas frame requires pixel [x,y,w,h]: " + assetId);
    return frame.slice();
  }

  function normalizeManifest(raw, sourceUrl, expectedPackId) {
    if (!raw || Number(raw.version) !== MANIFEST_VERSION) throw new Error("Unsupported 2D asset manifest version for " + expectedPackId);
    var packId = normalizeId(raw.pack_id, "asset pack id");
    if (packId !== expectedPackId) throw new Error("2D asset pack id does not match manifest filename: " + packId);
    var assets = {};
    Object.keys(raw.assets || {}).forEach(function normalizeAsset(rawAssetId) {
      var assetId = normalizeId(rawAssetId, "asset id");
      var source = raw.assets[rawAssetId] || {};
      var type = String(source.type || "").trim().toLowerCase();
      if (type !== "primitive" && type !== "image" && type !== "atlas") throw new Error("Unsupported 2D asset type for " + assetId + ": " + type);
      var definition = Object.assign({}, source, {
        asset_id: assetId, role: normalizeId(source.role || assetId, "asset role"), type: type,
      });
      if (type === "primitive") definition.primitive = normalizeId(source.primitive || source.shape, "primitive name");
      else {
        if (!source.url) throw new Error("2D " + type + " asset requires a url: " + assetId);
        definition.url = new URL(String(source.url), sourceUrl).href;
        definition.filter = source.filter === undefined ? "linear" : source.filter;
        if (definition.filter !== "linear" && definition.filter !== "nearest") throw new Error("Unsupported 2D texture filter: " + definition.filter);
        if (type === "atlas") {
          if (source.frame !== undefined && source.frames !== undefined) throw new Error("2D atlas frame and frames are mutually exclusive: " + assetId);
          var frames = source.frames === undefined ? [source.frame] : source.frames;
          if (!Array.isArray(frames) || !frames.length) throw new Error("2D atlas requires frame or frames: " + assetId);
          definition.frames = frames.map(function normalize(frame) { return normalizeFrame(frame, assetId); });
          if (definition.frames.length > 1 && (!Number.isFinite(source.frame_duration_ms) || source.frame_duration_ms <= 0)) {
            throw new Error("2D animated atlas requires positive frame_duration_ms: " + assetId);
          }
        }
      }
      assets[assetId] = definition;
    });
    var externalFonts = (raw.fonts || []).filter(function externalFont(source) { return source && source.url; }).map(function normalizeFont(source) {
      if (typeof source.family !== "string" || !source.family.trim()) throw new Error("2D external font requires family");
      return {
        family: source.family,
        url: new URL(String(source.url), sourceUrl).href,
        descriptors: Object.assign({}, source.descriptors || {}),
      };
    });
    return {
      version: MANIFEST_VERSION, id: packId, pack_id: packId,
      content_revision: raw.content_revision === undefined ? null : String(raw.content_revision),
      visual_profile: raw.visual_profile === undefined ? null : String(raw.visual_profile),
      palette: normalizePalette(raw.palette), alternatePalette: normalizePalette(raw.alternate_palette),
      variations: Core.perturbations.normalizeAssetVariations(raw, assets, normalizePalette),
      surfaces: Object.assign({}, raw.surfaces || {}), assets: assets, fonts: externalFonts, source_url: sourceUrl,
    };
  }

  function loadManifest(packId) {
    if (manifestCache[packId]) return Promise.resolve(manifestCache[packId]);
    if (manifestPromises[packId]) return manifestPromises[packId];
    var url = manifestUrl(packId);
    var generation = lifecycle;
    var promise = fetch(url, { credentials: "same-origin" }).then(function onResponse(response) {
      if (!response.ok) throw new Error("Failed to load 2D asset manifest " + packId + ": HTTP " + response.status);
      return response.json();
    }).then(function onManifest(raw) {
      if (generation !== lifecycle) throw new Error("2D assets disposed during preload");
      return (manifestCache[packId] = normalizeManifest(raw, url, packId));
    }).finally(function clearPromise() { if (manifestPromises[packId] === promise) delete manifestPromises[packId]; });
    manifestPromises[packId] = promise;
    return promise;
  }

  function resourceKey(definition) { return JSON.stringify([definition.url, definition.filter]); }

  function loadImage(url) {
    if (images[url]) return Promise.resolve(images[url]);
    if (imagePromises[url]) return imagePromises[url];
    var generation = lifecycle;
    var promise = new Promise(function load(resolve, reject) {
      var image = new Image();
      image.onload = function onImageLoad() {
        if (generation !== lifecycle) { reject(new Error("2D assets disposed during preload")); return; }
        images[url] = image;
        resolve(image);
      };
      image.onerror = function onImageError() { reject(new Error("Failed to load 2D asset image: " + url)); };
      image.src = url;
    }).finally(function clearPromise() { if (imagePromises[url] === promise) delete imagePromises[url]; });
    imagePromises[url] = promise;
    return promise;
  }

  function loadTexture(definition) {
    var key = resourceKey(definition);
    if (resources[key]) return Promise.resolve(resources[key]);
    if (resourcePromises[key]) return resourcePromises[key];
    var generation = lifecycle;
    var promise = loadImage(definition.url).then(function createTexture(image) {
      if (generation !== lifecycle) throw new Error("2D assets disposed during preload");
      var texture = new THREE.Texture(image);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.minFilter = definition.filter === "nearest" ? THREE.NearestFilter : THREE.LinearFilter;
      texture.magFilter = texture.minFilter;
      texture.generateMipmaps = false;
      texture.needsUpdate = true;
      ownedTextures.add(texture);
      return (resources[key] = { image: image, texture: texture });
    }).finally(function clearPromise() { if (resourcePromises[key] === promise) delete resourcePromises[key]; });
    resourcePromises[key] = promise;
    return promise;
  }

  function loadFont(definition) {
    var key = JSON.stringify([definition.family, definition.url, definition.descriptors]);
    if (fonts[key]) return Promise.resolve(fonts[key]);
    if (fontPromises[key]) return fontPromises[key];
    var generation = lifecycle;
    var face = new FontFace(definition.family, "url(" + JSON.stringify(definition.url) + ")", definition.descriptors);
    var promise = face.load().then(function fontReady(loaded) {
      if (generation !== lifecycle) throw new Error("2D assets disposed during preload");
      document.fonts.add(loaded);
      fonts[key] = loaded;
      return loaded;
    }).catch(function fontFailed(error) {
      throw new Error("Failed to load 2D font " + definition.family + ": " + error.message);
    }).finally(function clearPromise() { if (fontPromises[key] === promise) delete fontPromises[key]; });
    fontPromises[key] = promise;
    return promise;
  }

  function requiredIds(values) {
    return Array.from(new Set((Array.isArray(values) ? values : []).map(function normalizeRequired(value) {
      return normalizeId(value, "required asset id");
    })));
  }

  function validateImageFrames(definition, resource) {
    (definition.frames || []).forEach(function validateFrame(frame) {
      if (frame[0] + frame[2] > resource.image.naturalWidth || frame[1] + frame[3] > resource.image.naturalHeight) {
        throw new Error("2D atlas frame exceeds image bounds: " + definition.asset_id);
      }
    });
  }

  function preload(packValue, requiredAssetIds) {
    var packId = normalizeId(packValue, "asset pack id");
    var required = requiredIds(requiredAssetIds);
    var serial = ++preloadSerial;
    var generation = lifecycle;
    var selectedAssets = {};
    state = Object.assign(emptyState(), { status: "loading", asset_pack: packId });
    return loadManifest(packId).then(function prepareAssets(manifest) {
      if (generation !== lifecycle) throw new Error("2D assets disposed during preload");
      var packReadyAssets = readyAssets[packId] || (readyAssets[packId] = Object.create(null));
      var expanded = Core.perturbations.expandAssetRequirements(manifest, required);
      var definitions = expanded.map(function requiredDefinition(assetId) {
        var definition = manifest.assets[assetId];
        if (!definition) throw new Error("Missing required 2D asset " + assetId + " in pack " + packId);
        return definition;
      });
      required.forEach(function selectRequired(assetId) { selectedAssets[manifest.assets[assetId].role] = assetId; });
      var loads = definitions.map(function prepareAsset(definition) {
        if (definition.type === "primitive") return null;
        return loadTexture(definition).then(function validate(resource) { validateImageFrames(definition, resource); });
      });
      manifest.fonts.forEach(function prepareFont(font) { loads.push(loadFont(font)); });
      return Promise.all(loads).then(function assetsReady() {
        if (generation !== lifecycle) throw new Error("2D assets disposed during preload");
        expanded.forEach(function markReady(assetId) { packReadyAssets[assetId] = true; });
        var readyState = {
          status: "ready", asset_type: "2d", asset_pack: packId, asset_manifest_version: manifest.version,
          content_revision: manifest.content_revision, visual_profile: manifest.visual_profile,
          selected_assets: selectedAssets, error: null,
        };
        if (serial === preloadSerial) state = readyState;
        return copyState(readyState);
      });
    }).catch(function preloadFailed(error) {
      if (serial === preloadSerial) {
        state.status = "error";
        state.error = error && error.message ? error.message : String(error);
      }
      throw error;
    });
  }

  function mergedOptions(definition, options) {
    var merged = Object.assign({}, definition.style || {}, definition.defaults || {}, options || {});
    if (Array.isArray(definition.size)) {
      if (merged.w === undefined && merged.width === undefined) merged.w = Number(definition.size[0]);
      if (merged.h === undefined && merged.height === undefined) merged.h = Number(definition.size[1]);
    }
    if (merged.anchor === undefined && Array.isArray(definition.anchor)) merged.anchor = definition.anchor.slice(0, 2);
    if (merged.layer === undefined && definition.layer !== undefined) merged.layer = definition.layer;
    merged.assetDefinition = definition;
    return merged;
  }

  function selectFrame(definition, resource, options) {
    var frames = definition.frames || [[0, 0, resource.image.naturalWidth, resource.image.naturalHeight]];
    var index = options.frameIndex;
    if (index !== undefined) {
      if (!Number.isInteger(index) || index < 0 || index >= frames.length) throw new Error("2D frameIndex is out of range: " + definition.asset_id);
    } else if (frames.length > 1) {
      if (!Number.isFinite(options.timeMs) || options.timeMs < 0) throw new Error("2D animated atlas requires nonnegative timeMs or frameIndex: " + definition.asset_id);
      var elapsedFrames = Math.floor(options.timeMs / definition.frame_duration_ms);
      var loop = options.loop === undefined ? definition.loop !== false : options.loop !== false;
      index = loop ? elapsedFrames % frames.length : Math.min(frames.length - 1, elapsedFrames);
    } else index = 0;
    return { image: resource.image, texture: resource.texture, frame: frames[index], frameIndex: index };
  }

  function create(assetValue, options) {
    if (!adapter) throw new Error("2D asset renderer adapter is not installed");
    var assetId = normalizeId(assetValue, "asset id");
    if (options && options.assetContext && options.assetContext.assetId) assetId = options.assetContext.assetId(assetId);
    var packId = options && options.assetContext && options.assetContext.id ? options.assetContext.id : state.asset_pack;
    var manifest = manifestCache[packId];
    if (!manifest || !readyAssets[packId] || !readyAssets[packId][assetId]) throw new Error("2D asset was not preloaded: " + assetId + " in pack " + packId);
    var definition = manifest.assets[assetId];
    if (state.status === "ready" && state.asset_pack === packId) state.selected_assets[definition.role] = assetId;
    var resolved = mergedOptions(definition, options);
    if (definition.type === "primitive") return adapter.createPrimitive(definition, resolved);
    if (resolved.filter !== undefined && resolved.filter !== definition.filter) throw new Error("2D texture filter must match the preloaded asset definition: " + assetId);
    return adapter.createImage(definition, selectFrame(definition, resources[resourceKey(definition)], resolved), resolved);
  }

  function disposeAll() {
    lifecycle += 1;
    preloadSerial += 1;
    Object.keys(resources).forEach(function disposeResource(key) { resources[key].texture.dispose(); });
    Object.keys(fonts).forEach(function removeFont(key) { document.fonts.delete(fonts[key]); });
    resources = Object.create(null);
    resourcePromises = Object.create(null);
    images = Object.create(null);
    imagePromises = Object.create(null);
    fonts = Object.create(null);
    fontPromises = Object.create(null);
    manifestCache = Object.create(null);
    manifestPromises = Object.create(null);
    readyAssets = Object.create(null);
    state = emptyState();
  }

  function copyState(source) { return Object.assign({}, source, { selected_assets: Object.assign({}, source.selected_assets) }); }
  function getState() { return copyState(state); }

  function getManifest(packValue) {
    var packId = normalizeId(packValue || state.asset_pack, "asset pack id");
    if (!manifestCache[packId]) throw new Error("2D asset manifest is not loaded: " + packId);
    return manifestCache[packId];
  }

  function bindAdapter(nextAdapter) {
    if (!nextAdapter || typeof nextAdapter.createPrimitive !== "function" || typeof nextAdapter.createImage !== "function") {
      throw new Error("Invalid 2D asset renderer adapter");
    }
    adapter = nextAdapter;
  }

  var api = Object.freeze({ preload: preload, create: create, getState: getState });
  window.addEventListener("pagehide", disposeAll);
  window.GameAssetEngine2D = Object.freeze({
    api: api, getManifest: getManifest, bindAdapter: bindAdapter,
    ownsTexture: function ownsTexture(texture) { return !!texture && ownedTextures.has(texture); },
  });
})();
