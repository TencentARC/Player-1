(function gameAssetEngine3DModule() {
  "use strict";

  var MANIFEST_VERSION = 1;
  var Core = window.GameEngineCore;
  var manifestCache = Object.create(null);
  var manifestPromises = Object.create(null);
  var resources = Object.create(null);
  var resourcePromises = Object.create(null);
  var textures = Object.create(null);
  var texturePromises = Object.create(null);
  var readyAssets = Object.create(null);
  // Membership survives disposal so the generic scene cleanup can run afterwards.
  var ownedResources = new WeakSet();
  var templateResources = new Set();
  var disposedResources = new WeakSet();
  var closedImages = new WeakSet();
  var instances = new Map();
  var instanceRecords = new WeakMap();
  var adapter = null;
  var state = emptyState();
  var preloadSerial = 0;
  var lifecycle = 0;

  function emptyState() {
    return {
      status: "idle", asset_type: "3d", asset_pack: null, asset_manifest_version: null,
      content_revision: null, visual_profile: null, selected_assets: {}, error: null,
    };
  }

  function normalizeId(value, label) {
    var id = String(value || "").trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(id)) throw new Error("Invalid 3D " + label + ": " + value);
    return id;
  }

  function manifestUrl(packId) {
    return new URL("../base_assets/3d/manifests/" + encodeURIComponent(packId) + ".json", document.baseURI).href;
  }

  function parseColor(value) {
    if (typeof value === "number" && Number.isFinite(value)) return value >>> 0;
    var text = String(value || "").trim();
    if (/^#[0-9a-f]{6}$/i.test(text)) return parseInt(text.slice(1), 16) >>> 0;
    throw new Error("Invalid 3D manifest color: " + value);
  }

  function normalizePalette(source) {
    var palette = {};
    Object.keys(source || {}).forEach(function normalizeColor(role) { palette[role] = parseColor(source[role]); });
    return palette;
  }

  function forwardRotation(axis) {
    if (axis === "+z" || axis === "z") return 0;
    if (axis === "-z") return Math.PI;
    if (axis === "+x" || axis === "x") return -Math.PI / 2;
    if (axis === "-x") return Math.PI / 2;
    throw new Error("Unsupported model forward_axis: " + axis);
  }

  function validateDimensions(options, label) {
    if (options.target_size !== undefined && options.target_height !== undefined) {
      throw new Error("3D target_size and target_height are mutually exclusive: " + label);
    }
    if (options.target_size !== undefined && (!Array.isArray(options.target_size) || options.target_size.length !== 3
      || options.target_size.some(function invalidDimension(value) { return !Number.isFinite(value) || value <= 0; }))) {
      throw new Error("3D target_size requires three positive dimensions: " + label);
    }
    if (options.target_height !== undefined && (!Number.isFinite(options.target_height) || options.target_height <= 0)) {
      throw new Error("3D target_height must be positive: " + label);
    }
    if (options.ground_offset !== undefined && !Number.isFinite(options.ground_offset)) {
      throw new Error("3D ground_offset must be finite: " + label);
    }
  }

  function normalizeVisual(source, assetId) {
    var visual = { clips: {}, sockets: {}, material_roles: {} };
    ["clips", "sockets", "material_roles"].forEach(function normalizeBindings(kind) {
      Object.keys(source && source[kind] || {}).forEach(function normalizeBinding(role) {
        var value = source[kind][role];
        var names = kind === "material_roles" ? value : [value];
        if (!Array.isArray(names) || !names.length || names.some(function invalidName(name) {
          return typeof name !== "string" || !name.trim();
        })) throw new Error("Invalid 3D visual " + kind + " binding: " + assetId + "." + role);
        visual[kind][role] = kind === "material_roles" ? names.slice() : value;
      });
    });
    return visual;
  }

  function normalizeManifest(raw, sourceUrl, expectedPackId) {
    if (!raw || Number(raw.version) !== MANIFEST_VERSION) {
      throw new Error("Unsupported 3D asset manifest version for " + expectedPackId);
    }
    var packId = normalizeId(raw.pack_id, "asset pack id");
    if (packId !== expectedPackId) throw new Error("3D asset pack id does not match manifest filename: " + packId);
    var assets = {};
    Object.keys(raw.assets || {}).forEach(function normalizeAsset(rawAssetId) {
      var assetId = normalizeId(rawAssetId, "asset id");
      var source = raw.assets[rawAssetId] || {};
      var type = String(source.type || "").trim().toLowerCase();
      if (type !== "primitive" && type !== "model") throw new Error("Unsupported 3D asset type for " + assetId + ": " + type);
      var definition = Object.assign({}, source, {
        asset_id: assetId, role: normalizeId(source.role || assetId, "asset role"), type: type,
      });
      if (type === "primitive") definition.primitive = normalizeId(source.primitive, "primitive name");
      else {
        if (!source.url) throw new Error("3D model asset requires a url: " + assetId);
        definition.url = new URL(String(source.url), sourceUrl).href;
        definition.forward_axis = String(source.forward_axis || "-z").trim().toLowerCase();
        forwardRotation(definition.forward_axis);
        validateDimensions(definition, assetId);
        definition.visual = normalizeVisual(source.visual, assetId);
      }
      assets[assetId] = definition;
    });
    var textureUrls = {};
    Object.keys(raw.textures || {}).forEach(function normalizeTexture(role) {
      if (typeof raw.textures[role] !== "string" || !raw.textures[role].trim()) {
        throw new Error("3D surface texture requires a url: " + role);
      }
      textureUrls[role] = new URL(raw.textures[role], sourceUrl).href;
    });
    return {
      version: MANIFEST_VERSION, id: packId, pack_id: packId,
      content_revision: raw.content_revision === undefined ? null : String(raw.content_revision),
      visual_profile: raw.visual_profile === undefined ? null : String(raw.visual_profile),
      palette: normalizePalette(raw.palette), alternatePalette: normalizePalette(raw.alternate_palette),
      variations: Core.perturbations.normalizeAssetVariations(raw, assets, normalizePalette),
      surfaces: Object.assign({}, raw.surfaces || {}), textures: textureUrls, assets: assets, source_url: sourceUrl,
    };
  }

  function loadManifest(packId) {
    if (manifestCache[packId]) return Promise.resolve(manifestCache[packId]);
    if (manifestPromises[packId]) return manifestPromises[packId];
    var url = manifestUrl(packId);
    var generation = lifecycle;
    var promise = fetch(url, { credentials: "same-origin" }).then(function onResponse(response) {
      if (!response.ok) throw new Error("Failed to load 3D asset manifest " + packId + ": HTTP " + response.status);
      return response.json();
    }).then(function onManifest(raw) {
      if (generation !== lifecycle) throw new Error("3D assets disposed during preload");
      return (manifestCache[packId] = normalizeManifest(raw, url, packId));
    }).finally(function clearPromise() { if (manifestPromises[packId] === promise) delete manifestPromises[packId]; });
    manifestPromises[packId] = promise;
    return promise;
  }

  function resourceKey(packId, assetId) { return packId + ":" + assetId; }

  function materialList(value) { return (Array.isArray(value) ? value : [value]).filter(Boolean); }

  function ownTemplate(resource) {
    if (!resource) return;
    ownedResources.add(resource);
    templateResources.add(resource);
  }

  function materialTextures(material, visit) {
    Object.keys(material).forEach(function visitTexture(name) {
      if (material[name] && material[name].isTexture) visit(material[name]);
    });
  }

  function modelResources(resource, visit) {
    var scenes = resource.scenes || [resource.scene];
    scenes.filter(Boolean).forEach(function visitScene(scene) {
      scene.traverse(function visitObject(child) {
        if (child.geometry) visit(child.geometry);
        if (child.skeleton) visit(child.skeleton);
        materialList(child.material).forEach(function visitMaterial(material) {
          visit(material);
          materialTextures(material, visit);
        });
      });
    });
  }

  function disposeResource(resource) {
    if (!resource || disposedResources.has(resource)) return;
    disposedResources.add(resource);
    if (typeof resource.dispose === "function") resource.dispose();
  }

  function disposeTemplateResource(resource) {
    disposeResource(resource);
    var image = resource && resource.isTexture && resource.source && resource.source.data;
    if (image && typeof image.close === "function" && !closedImages.has(image)) {
      image.close();
      closedImages.add(image);
    }
  }

  function validateModel(definition, resource) {
    var scene = resource.scene || (resource.scenes && resource.scenes[0]);
    if (!scene) throw new Error("3D model has no scene: " + definition.asset_id);
    var visual = definition.visual;
    var nodeCounts = Object.create(null);
    var materials = new Set();
    scene.traverse(function inspectNode(child) {
      nodeCounts[child.name] = (nodeCounts[child.name] || 0) + 1;
      materialList(child.material).forEach(function inspectMaterial(material) { materials.add(material.name); });
      if (child.isSkinnedMesh && typeof THREE.cloneSkinned !== "function") {
        throw new Error("Three.js cloneSkinned is required for skinned models");
      }
    });
    Object.keys(visual.sockets).forEach(function validateSocket(role) {
      if (nodeCounts[visual.sockets[role]] !== 1) throw new Error("Missing or ambiguous 3D socket: " + definition.asset_id + "." + role);
    });
    Object.keys(visual.material_roles).forEach(function validateMaterialRole(role) {
      visual.material_roles[role].forEach(function validateName(name) {
        if (!materials.has(name)) throw new Error("Missing 3D material: " + definition.asset_id + "." + role + " -> " + name);
      });
    });
    Object.keys(visual.clips).forEach(function validateClip(role) {
      var matches = (resource.animations || []).filter(function match(clip) { return clip.name === visual.clips[role]; });
      if (matches.length !== 1 || !Number.isFinite(matches[0].duration) || matches[0].duration <= 0) {
        throw new Error("Missing or invalid 3D animation clip: " + definition.asset_id + "." + role);
      }
    });
  }

  function loadModel(packId, definition) {
    var key = resourceKey(packId, definition.asset_id);
    if (resources[key]) return Promise.resolve(resources[key]);
    if (resourcePromises[key]) return resourcePromises[key];
    if (!window.THREE || typeof THREE.GLTFLoader !== "function") return Promise.reject(new Error("Three.js GLTFLoader is unavailable"));
    var generation = lifecycle;
    var promise = new Promise(function loadGltf(resolve, reject) {
      var dependencyErrors = [];
      var manager = new THREE.LoadingManager();
      manager.onError = function dependencyFailed(url) { dependencyErrors.push(url); };
      new THREE.GLTFLoader(manager).load(definition.url, function onLoad(gltf) {
        try {
          if (generation !== lifecycle) throw new Error("3D assets disposed during preload");
          if (dependencyErrors.length) throw new Error("Failed to load 3D model dependencies: " + dependencyErrors.join(", "));
          validateModel(definition, gltf);
          modelResources(gltf, ownTemplate);
          resources[key] = gltf;
          resolve(gltf);
        } catch (error) {
          modelResources(gltf, disposeTemplateResource);
          reject(error);
        }
      }, undefined, function onError(error) {
        reject(new Error("Failed to load 3D asset " + definition.asset_id + ": " + (error && error.message ? error.message : error)));
      });
    }).finally(function clearPromise() { if (resourcePromises[key] === promise) delete resourcePromises[key]; });
    resourcePromises[key] = promise;
    return promise;
  }

  function loadTexture(packId, role, url) {
    var key = resourceKey(packId, role);
    if (textures[key]) return Promise.resolve(textures[key]);
    if (texturePromises[key]) return texturePromises[key];
    var generation = lifecycle;
    var promise = new Promise(function loadImage(resolve, reject) {
      new THREE.TextureLoader().load(url, function onLoad(texture) {
        if (generation !== lifecycle) {
          disposeTemplateResource(texture);
          reject(new Error("3D assets disposed during preload"));
          return;
        }
        texture.colorSpace = THREE.SRGBColorSpace;
        ownTemplate(texture);
        textures[key] = texture;
        resolve(texture);
      }, undefined, function onError() { reject(new Error("Failed to load 3D surface texture: " + role + " in " + packId)); });
    }).finally(function clearPromise() { if (texturePromises[key] === promise) delete texturePromises[key]; });
    texturePromises[key] = promise;
    return promise;
  }

  function requiredIds(values) {
    return Array.from(new Set((Array.isArray(values) ? values : []).map(function normalizeRequired(value) {
      return normalizeId(value, "required asset id");
    })));
  }

  function preload(packValue, requiredAssetIds) {
    var packId = normalizeId(packValue, "asset pack id");
    var required = requiredIds(requiredAssetIds);
    var serial = ++preloadSerial;
    var generation = lifecycle;
    var selectedAssets = {};
    state = Object.assign(emptyState(), { status: "loading", asset_pack: packId });
    return loadManifest(packId).then(function prepareAssets(manifest) {
      if (generation !== lifecycle) throw new Error("3D assets disposed during preload");
      var packReadyAssets = readyAssets[packId] || (readyAssets[packId] = Object.create(null));
      var expanded = Core.perturbations.expandAssetRequirements(manifest, required);
      var definitions = expanded.map(function requiredDefinition(assetId) {
        var definition = manifest.assets[assetId];
        if (!definition) throw new Error("Missing required 3D asset " + assetId + " in pack " + packId);
        return definition;
      });
      required.forEach(function selectRequired(assetId) { selectedAssets[manifest.assets[assetId].role] = assetId; });
      var loads = definitions.map(function prepareAsset(definition) {
        return definition.type === "model" ? loadModel(packId, definition) : null;
      });
      Object.keys(manifest.textures).forEach(function prepareSurface(role) {
        loads.push(loadTexture(packId, role, manifest.textures[role]));
      });
      return Promise.all(loads).then(function assetsReady() {
        if (generation !== lifecycle) throw new Error("3D assets disposed during preload");
        expanded.forEach(function markReady(assetId) { packReadyAssets[assetId] = true; });
        var readyState = {
          status: "ready", asset_type: "3d", asset_pack: packId, asset_manifest_version: manifest.version,
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

  function cloneModelScene(source, definition, resource, record) {
    var model = typeof THREE.cloneSkinned === "function" ? THREE.cloneSkinned(source) : source.clone(true);
    var mutableNames = new Set();
    Object.keys(definition.visual.material_roles).forEach(function mutableRole(role) {
      definition.visual.material_roles[role].forEach(function mutableMaterial(name) { mutableNames.add(name); });
    });
    var animatedMaterials = (resource.animations || []).some(function materialAnimation(clip) {
      return clip.tracks.some(function materialTrack(track) { return /\.materials?(?:\.|\[)/.test(track.name); });
    });
    var materialCopies = new Map();
    model.traverse(function isolateMutableResources(child) {
      if (child.skeleton) {
        ownedResources.add(child.skeleton);
        record.resources.add(child.skeleton);
      }
      if (!child.material) return;
      function cloneMutable(material) {
        if (!animatedMaterials && !mutableNames.has(material.name)) return material;
        if (!materialCopies.has(material)) {
          var copy = material.clone();
          ownedResources.add(copy);
          record.resources.add(copy);
          materialCopies.set(material, copy);
        }
        return materialCopies.get(material);
      }
      child.material = Array.isArray(child.material) ? child.material.map(cloneMutable) : cloneMutable(child.material);
    });
    return model;
  }

  function createVisual(group, model, definition, resource, record) {
    var config = definition.visual;
    var materialRoles = {};
    Object.keys(config.material_roles).forEach(function bindMaterialRole(role) {
      var matches = new Set();
      model.traverse(function matchMaterials(child) {
        materialList(child.material).forEach(function matchMaterial(material) {
          if (config.material_roles[role].indexOf(material.name) >= 0) matches.add(material);
        });
      });
      materialRoles[role] = Array.from(matches);
    });
    var mixer = Object.keys(config.clips).length ? new THREE.AnimationMixer(model) : null;
    record.mixer = mixer;
    var activeClip = null;
    var activeAction = null;
    function ensureLive() { if (record.released) throw new Error("3D visual instance has been released: " + definition.asset_id); }
    function applyPose(pose) {
      ensureLive();
      pose = pose || {};
      if (!Number.isFinite(pose.timeMs) || pose.timeMs < 0) throw new Error("3D visual pose requires nonnegative timeMs");
      var requestedClip = pose.clip === undefined ? activeClip : pose.clip;
      if (requestedClip !== null && !Object.prototype.hasOwnProperty.call(config.clips, requestedClip)) {
        throw new Error("Unknown 3D visual clip: " + definition.asset_id + "." + requestedClip);
      }
      if (requestedClip !== activeClip) {
        if (mixer) mixer.stopAllAction();
        activeClip = requestedClip;
        activeAction = activeClip === null ? null : mixer.clipAction(THREE.AnimationClip.findByName(resource.animations, config.clips[activeClip]));
      }
      if (activeAction) {
        var milliseconds = pose.clipTimeMs === undefined ? pose.timeMs : pose.clipTimeMs;
        if (!Number.isFinite(milliseconds)) throw new Error("3D clipTimeMs must be finite");
        var duration = activeAction.getClip().duration;
        var seconds = milliseconds / 1000;
        seconds = pose.loop === false ? Math.max(0, Math.min(duration, seconds)) : ((seconds % duration) + duration) % duration;
        activeAction.reset().setLoop(THREE.LoopOnce, 1).play();
        activeAction.clampWhenFinished = true;
        mixer.setTime(seconds);
      }
      Object.keys(pose.materialRoles || {}).forEach(function applyRole(role) {
        if (!Object.prototype.hasOwnProperty.call(materialRoles, role)) throw new Error("Unknown 3D material role: " + role);
        var values = pose.materialRoles[role];
        if (typeof values !== "object" || values === null) values = { color: values };
        Object.keys(values).forEach(function applyProperty(property) {
          if (["color", "emissive", "opacity", "roughness", "metalness"].indexOf(property) < 0) {
            throw new Error("Unsupported 3D material pose property: " + property);
          }
          var color = property === "color" || property === "emissive";
          var value = color ? parseColor(values[property]) : values[property];
          if (!color && (!Number.isFinite(value) || value < 0 || value > 1)) throw new Error("3D material value must be in [0,1]: " + property);
          materialRoles[role].forEach(function updateMaterial(material) {
            if (material[property] === undefined) throw new Error("3D material has no property: " + property);
            if (color) material[property].setHex(value);
            else {
              material[property] = value;
              if (property === "opacity" && material.transparent !== (value < 1)) {
                material.transparent = value < 1;
                material.needsUpdate = true;
              }
            }
          });
        });
      });
      model.updateMatrixWorld(true);
      return group;
    }
    return Object.freeze({
      root: group,
      applyPose: applyPose,
      attach: function attach(socketName, child) {
        ensureLive();
        if (!Object.prototype.hasOwnProperty.call(config.sockets, socketName)) throw new Error("Unknown 3D visual socket: " + socketName);
        if (!child || !child.isObject3D) throw new Error("3D visual socket attachment requires Object3D");
        model.getObjectByName(config.sockets[socketName]).add(child);
        return child;
      },
    });
  }

  function createModel(definition, resource, options) {
    var parent = options.parent || (options.world && options.world.root);
    if (!parent || !parent.isObject3D) throw new Error("3D model asset requires options.world or options.parent");
    var dimensions = {
      target_size: options.target_size === undefined ? definition.target_size : options.target_size,
      target_height: options.target_height === undefined ? definition.target_height : options.target_height,
      ground_offset: options.ground_offset === undefined ? definition.ground_offset : options.ground_offset,
    };
    validateDimensions(dimensions, definition.asset_id);
    var rotation = forwardRotation(options.forward_axis || definition.forward_axis);
    var record = { resources: new Set(), mixer: null, model: null, visual: null, released: false };
    var model = cloneModelScene(resource.scene || resource.scenes[0], definition, resource, record);
    var orientation = new THREE.Group();
    orientation.rotation.y = rotation;
    orientation.add(model);
    var fitted = new THREE.Group();
    fitted.add(orientation);
    var group = new THREE.Group();
    group.add(fitted);
    orientation.updateMatrixWorld(true);
    var bounds = new THREE.Box3().setFromObject(orientation);
    var size = bounds.getSize(new THREE.Vector3());
    if (bounds.isEmpty()) {
      record.resources.forEach(disposeResource);
      throw new Error("3D model has no render bounds: " + definition.asset_id);
    }
    if (dimensions.target_size) {
      if (Math.min(size.x, size.y, size.z) < 0.000001) {
        record.resources.forEach(disposeResource);
        throw new Error("3D target_size cannot fit a zero-size model axis: " + definition.asset_id);
      }
      fitted.scale.set(dimensions.target_size[0] / size.x, dimensions.target_size[1] / size.y, dimensions.target_size[2] / size.z);
    } else if (dimensions.target_height !== undefined) {
      if (size.y < 0.000001) {
        record.resources.forEach(disposeResource);
        throw new Error("3D target_height cannot fit a zero-height model: " + definition.asset_id);
      }
      fitted.scale.setScalar(dimensions.target_height / size.y);
    }
    var center = bounds.getCenter(new THREE.Vector3());
    fitted.position.set(-center.x * fitted.scale.x, (dimensions.ground_offset || 0) - bounds.min.y * fitted.scale.y, -center.z * fitted.scale.z);
    model.traverse(function configureMesh(child) {
      if (!child.isMesh) return;
      child.castShadow = options.cast_shadow === undefined ? definition.cast_shadow !== false : options.cast_shadow !== false;
      child.receiveShadow = options.receive_shadow === undefined ? definition.receive_shadow !== false : options.receive_shadow !== false;
    });
    group.position.set(Number(options.x) || 0, Number(options.y === undefined ? options.baseY : options.y) || 0, Number(options.z) || 0);
    group.rotation.y = Number(options.rotationY) || 0;
    group.userData.assetId = definition.asset_id;
    group.userData.assetRole = definition.role;
    group.userData.animations = (resource.animations || []).slice();
    record.model = model;
    record.visual = createVisual(group, model, definition, resource, record);
    instances.set(group, record);
    instanceRecords.set(group, record);
    parent.add(group);
    group.updateMatrixWorld(true);
    return group;
  }

  function mergedOptions(definition, options) {
    var merged = Object.assign({}, definition.defaults || {}, options || {});
    if (Array.isArray(definition.size) && merged.size === undefined) merged.size = definition.size.slice();
    merged.assetDefinition = definition;
    return merged;
  }

  function create(assetValue, options) {
    if (!adapter) throw new Error("3D asset renderer adapter is not installed");
    var assetId = normalizeId(assetValue, "asset id");
    if (options && options.assetContext && options.assetContext.assetId) assetId = options.assetContext.assetId(assetId);
    var packId = options && options.assetContext && options.assetContext.id ? options.assetContext.id : state.asset_pack;
    var manifest = manifestCache[packId];
    if (!manifest || !readyAssets[packId] || !readyAssets[packId][assetId]) throw new Error("3D asset was not preloaded: " + assetId + " in pack " + packId);
    var definition = manifest.assets[assetId];
    if (state.status === "ready" && state.asset_pack === packId) state.selected_assets[definition.role] = assetId;
    var resolved = mergedOptions(definition, options);
    if (definition.type === "primitive") return adapter.createPrimitive(definition, resolved);
    return createModel(definition, resources[resourceKey(packId, assetId)], resolved);
  }

  function getVisual(group) {
    var record = instanceRecords.get(group);
    return record && !record.released ? record.visual : null;
  }

  function releaseInstance(group) {
    var record = instanceRecords.get(group);
    if (!record || record.released) return false;
    record.released = true;
    if (record.mixer) {
      record.mixer.stopAllAction();
      record.mixer.uncacheRoot(record.model);
    }
    record.resources.forEach(disposeResource);
    record.resources.clear();
    instances.delete(group);
    return true;
  }

  function ownsResource(resource) { return !!resource && ownedResources.has(resource); }

  function disposeAll() {
    lifecycle += 1;
    preloadSerial += 1;
    instances.forEach(function release(record, group) { releaseInstance(group); });
    templateResources.forEach(disposeTemplateResource);
    templateResources.clear();
    resources = Object.create(null);
    textures = Object.create(null);
    manifestCache = Object.create(null);
    manifestPromises = Object.create(null);
    resourcePromises = Object.create(null);
    texturePromises = Object.create(null);
    readyAssets = Object.create(null);
    state = emptyState();
  }

  function copyState(source) { return Object.assign({}, source, { selected_assets: Object.assign({}, source.selected_assets) }); }
  function getState() { return copyState(state); }

  function getManifest(packValue) {
    var packId = normalizeId(packValue || state.asset_pack, "asset pack id");
    if (!manifestCache[packId]) throw new Error("3D asset manifest is not loaded: " + packId);
    return manifestCache[packId];
  }

  function getTexture(packValue, role) {
    var manifest = getManifest(packValue);
    if (!manifest.textures[role]) return null;
    var texture = textures[resourceKey(manifest.id, role)];
    if (!texture) throw new Error("3D surface texture was not preloaded: " + role + " in " + manifest.id);
    return texture;
  }

  function bindAdapter(nextAdapter) {
    if (!nextAdapter || typeof nextAdapter.createPrimitive !== "function") throw new Error("Invalid 3D asset renderer adapter");
    adapter = nextAdapter;
  }

  var api = Object.freeze({ preload: preload, create: create, getState: getState, getVisual: getVisual });
  window.addEventListener("pagehide", disposeAll);
  window.GameAssetEngine3D = Object.freeze({
    api: api, getManifest: getManifest, getTexture: getTexture, bindAdapter: bindAdapter,
    releaseInstance: releaseInstance, ownsResource: ownsResource,
  });
})();
