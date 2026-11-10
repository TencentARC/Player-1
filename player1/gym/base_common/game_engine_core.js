(function gameEngineCoreModule() {
  "use strict";

  var PLAYER1_RUNTIME_API_VERSION = "1.0";
  var VISIBLE_GAME_GEOMETRY_PROTOCOL = "visible_game_geometry_v1";
  var Engine = window.BaseGameletCommon;
  var hasOwn = Engine.object.hasOwn;
  var parseUnsignedInt = Engine.math.unsignedInt;
  var SEED_DOMAIN_NAMES = Object.freeze(["appearance", "camera", "scene"]);
  var DOMAIN_MODE_LEGACY = "legacy";
  var DOMAIN_MODE_ISOLATED = "isolated";
  var DOMAIN_CONFIG_KINDS = Object.freeze(["Seed", "Profile"]);
  var LEGACY_PLAYER_SPAWN_SEED_OFFSET = 0x9e3779b9;
  var LEGACY_RNG_BY_TARGET = typeof WeakMap === "function" ? new WeakMap() : null;
  var LEGACY_PLAYER_SPAWN_RNG_BY_TARGET = typeof WeakMap === "function" ? new WeakMap() : null;
  var RNG_DOMAIN_MODE = typeof WeakMap === "function" ? new WeakMap() : null;
  var PERTURBATION_PROFILE_NAMES = Object.freeze(["default", "perturbed"]);
  var ENVIRONMENT_TEMPERATURE_NAMES = Object.freeze(["warm", "neutral", "cool"]);
  var CAMERA_ORIENTATION_PITCH_RANGE = Object.freeze([-0.05, 0.05]);
  var CONTROL_RESPONSE_RANGES = Object.freeze({
    look_gain_scale: Object.freeze([0.80, 1.20]),
    move_scale: Object.freeze([0.80, 1.20]),
    chase_move_scale: Object.freeze([0.90, 1.10]),
    platform_move_scale: Object.freeze([0.95, 1.05]),
    drive_scale: Object.freeze([0.80, 1.20]),
    turn_scale: Object.freeze([0.80, 1.20]),
    jump_scale: Object.freeze([0.975, 1.025]),
  });
  var CONTROL_RESPONSE_PARAMETERS = Object.freeze([
    "look_gain_scale", "move_scale", "drive_scale", "turn_scale", "jump_scale",
  ]);

  function readControlResponseConfig(options) {
    var source = options || {};
    if (source.controlResponse) {
      var saved = source.controlResponse;
      source = Object.assign({
        control_response_profile: saved.profile,
        control_response_seed: saved.seed,
      }, source);
      Object.keys(saved.overrides || {}).forEach(function restoreOverride(parameter) {
        if (!hasOwn(source, "control_" + parameter)) source["control_" + parameter] = saved.overrides[parameter];
      });
    }
    var result = { profile: null, seed: null, overrides: {} };
    Object.keys(source).forEach(function readControlOption(key) {
      if (key.indexOf("control_") !== 0 || source[key] === undefined || source[key] === null) return;
      var value = source[key];
      if (key === "control_response_profile") {
        if (value !== "default" && value !== "perturbed") throw new Error("invalid control_response_profile");
        result.profile = value;
      } else if (key === "control_response_seed") {
        var seed = Number(value);
        if (value === "" || ["number", "string"].indexOf(typeof value) < 0
            || !Number.isInteger(seed) || seed < 0 || seed > 4294967295) {
          throw new Error("control_response_seed must be an unsigned 32-bit integer");
        }
        result.seed = seed;
      } else {
        var parameter = key.slice("control_".length);
        if (CONTROL_RESPONSE_PARAMETERS.indexOf(parameter) < 0) throw new Error("unknown control response option: " + key);
        var scale = Number(value);
        if (value === "" || ["number", "string"].indexOf(typeof value) < 0 || !Number.isFinite(scale) || scale <= 0) {
          throw new Error(key + " must be a positive finite multiplier");
        }
        result.overrides[parameter] = scale;
      }
    });
    return result;
  }

  function mergeControlResponseConfig(base, override) {
    base = base || { profile: null, seed: null, overrides: {} };
    override = override || { profile: null, seed: null, overrides: {} };
    return {
      profile: override.profile === null ? base.profile : override.profile,
      seed: override.seed === null ? base.seed : override.seed,
      overrides: Object.assign({}, base.overrides, override.overrides),
    };
  }

  function defineControlResponseRanges(source) {
    var ranges = {};
    Object.keys(source || {}).forEach(function defineRange(parameter) {
      var bounds = source[parameter];
      if (CONTROL_RESPONSE_PARAMETERS.indexOf(parameter) < 0 || !Array.isArray(bounds) || bounds.length !== 2
          || !Number.isFinite(bounds[0]) || !Number.isFinite(bounds[1]) || bounds[0] <= 0
          || bounds[0] >= 1 || bounds[1] <= 1) throw new Error("invalid control response range: " + parameter);
      ranges[parameter] = Object.freeze(bounds.slice());
    });
    return Object.freeze(ranges);
  }

  function beginControlResponseEpisode(target, config, contract, fallbackSeed) {
    var requested = readControlResponseConfig(config);
    var ranges = contract.controlResponse || {};
    var profile = requested.profile || "default";
    // A separate hash/RNG leaves all existing gameplay and visual random streams untouched.
    var seed = requested.seed === null
      ? stableSeedHash(String(parseUnsignedInt(config.seed, fallbackSeed)) + "__control_response") : requested.seed;
    Object.keys(requested.overrides).forEach(function validateOverride(parameter) {
      var bounds = ranges[parameter];
      var value = requested.overrides[parameter];
      if (!bounds) throw new Error(contract.gameId + " does not support control_" + parameter);
      if (value < bounds[0] || value > bounds[1]) throw new Error("control_" + parameter + " outside supported range");
    });
    var applied = {};
    Object.keys(ranges).forEach(function sampleResponse(parameter) {
      var value = 1;
      if (hasOwn(requested.overrides, parameter)) value = requested.overrides[parameter];
      else if (profile === "perturbed") {
        var rng = new Engine.Rng((seed ^ stableSeedHash(parameter)) >>> 0);
        var u = rng.next();
        var a = ranges[parameter][0], b = ranges[parameter][1];
        value = u < (1 - a) / (b - a)
          ? a + Math.sqrt(u * (b - a) * (1 - a))
          : b - Math.sqrt((1 - u) * (b - a) * (b - 1));
      }
      applied[parameter] = value;
    });
    target.controlResponse = Object.freeze({
      profile: profile, seed: seed, distribution: "triangular_native_mode",
      ranges: ranges, overrides: Object.freeze(Object.assign({}, requested.overrides)),
      applied: Object.freeze(applied),
    });
  }
  var PERTURBATION_STREAMS = Object.freeze({
    appearance: Object.freeze(["palette", "lighting", "background", "assets"]),
    camera: Object.freeze(["orientation", "projection", "rig"]),
    scene: Object.freeze(["layout", "player_spawn", "entity_spawn"]),
  });
  var PERTURBATION_PROFILE_RANGES = Object.freeze({
    default: Object.freeze({
      appearance: Object.freeze({
        assets: Object.freeze({ enabled: false }),
        palette: Object.freeze({
          theme: "native",
          hue_shift_degrees: 0,
          saturation_scale: 1,
          brightness_scale: 1,
        }),
        lighting: Object.freeze({
          theme: "native",
          illumination: 1,
          ambient_scale: 1,
          key_scale: 1,
          key_azimuth_degrees: 0,
          shadow_strength: 1,
        }),
        background: Object.freeze({
          theme: "native",
          illumination: 1,
          environment_temperature: "neutral",
          hue_shift_degrees: 0,
          saturation_scale: 1,
          brightness_scale: 1,
        }),
      }),
      camera: Object.freeze({
        orientation: Object.freeze({ yaw_offset_radians: 0, pitch_offset_radians: 0 }),
        projection: Object.freeze({ fov_offset_degrees: 0, orthographic_zoom: 1 }),
        rig: Object.freeze({ height_scale: 1, distance_scale: 1, pitch_offset_radians: 0 }),
      }),
      scene: Object.freeze({
        layout: Object.freeze({ mode: "game_defined" }),
        player_spawn: Object.freeze({ mode: "game_defined" }),
        entity_spawn: Object.freeze({ mode: "game_defined" }),
      }),
    }),
    perturbed: Object.freeze({
      appearance: Object.freeze({
        assets: Object.freeze({ enabled: true }),
        palette: Object.freeze({
          theme: Object.freeze(["dark", "neutral", "light"]),
          illumination: Object.freeze([0, 1]),
          hue_shift_degrees: Object.freeze([0, 60, 120, 180, 240, 300]),
          saturation_scale: Object.freeze([0.95, 1.25]),
          brightness_scale: Object.freeze([0.96, 1.15]),
        }),
        lighting: Object.freeze({
          theme: Object.freeze(["dark", "neutral", "light"]),
          illumination: Object.freeze([0, 1]),
          ambient_scale: Object.freeze([0.35, 1.15]),
          key_scale: Object.freeze([0.45, 1.2]),
          key_azimuth_degrees: Object.freeze([-120, 0, 120]),
          shadow_strength: Object.freeze([0.78, 1]),
        }),
        background: Object.freeze({
          theme: Object.freeze(["dark", "neutral", "light"]),
          illumination: Object.freeze([0, 1]),
          environment_temperature: ENVIRONMENT_TEMPERATURE_NAMES,
          hue_shift_degrees: Object.freeze([-10, 10]),
          saturation_scale: Object.freeze([0.55, 1.05]),
          brightness_scale: Object.freeze([0.32, 1.04]),
        }),
      }),
      camera: Object.freeze({
        orientation: Object.freeze({
          aiming: Object.freeze({
            yaw_offset_radians: Object.freeze([-0.10, 0.10]),
            pitch_offset_radians: CAMERA_ORIENTATION_PITCH_RANGE,
          }),
          combat: Object.freeze({
            yaw_offset_radians: Object.freeze([-0.05, 0.05]),
            pitch_offset_radians: CAMERA_ORIENTATION_PITCH_RANGE,
          }),
          navigation: Object.freeze({
            yaw_offset_radians: Object.freeze([-0.20, 0.20]),
            pitch_offset_radians: CAMERA_ORIENTATION_PITCH_RANGE,
          }),
        }),
        projection: Object.freeze({
          fov_offset_degrees: Object.freeze([-8, 8]),
          orthographic_zoom: Object.freeze([0.8, 1]),
        }),
        rig: Object.freeze({
          height_scale: Object.freeze([0.9, 1.1]),
          distance_scale: Object.freeze([0.85, 1.15]),
          pitch_offset_radians: Object.freeze([-0.05, 0.05]),
        }),
      }),
      scene: Object.freeze({
        layout: Object.freeze({ mode: "game_defined" }),
        player_spawn: Object.freeze({ mode: "game_defined" }),
        entity_spawn: Object.freeze({ mode: "game_defined" }),
      }),
    }),
  });

  function normalizeDifficulty(value, fallback, maxDifficulty) {
    if (value === null || value === undefined || value === "") return fallback;
    var numeric = Number(value);
    if (!Number.isFinite(numeric)) return fallback;
    return Math.max(1, Math.min(maxDifficulty, numeric));
  }

  function difficultyLevel(value) {
    var numeric = Number(value);
    return Number.isFinite(numeric) ? Math.max(0, numeric - 1) : 0;
  }

  function normalizeBoolean(value, fallback) {
    if (value === null || value === undefined || value === "") return fallback;
    if (value === true || value === 1) return true;
    if (value === false || value === 0) return false;
    var text = String(value).trim().toLowerCase();
    if (text === "1" || text === "true" || text === "yes" || text === "on") return true;
    if (text === "0" || text === "false" || text === "no" || text === "off") return false;
    return fallback;
  }

  function normalizePerturb(value) {
    if (value === undefined) return undefined;
    if (value === null || value === "") return null;
    var text = String(value).trim().toLowerCase();
    if (!text || text === "none" || text === "off") return null;
    if (text === "color" || text === "all") return text;
    return null;
  }

  function normalizeDifficultyChoices(value, maxDifficulty) {
    if (value === null || value === undefined || value === "") return null;
    var choices = String(value).split(",").map(function normalizeChoice(part) {
      return normalizeDifficulty(part.trim(), null, maxDifficulty);
    }).filter(function validChoice(choice) {
      return choice !== null;
    });
    return choices.length ? choices : null;
  }

  function chooseDifficulty(seed, difficulty, choices, seedOffset) {
    if (!choices || !choices.length) return difficulty;
    var rng = new Engine.Rng(((Number(seed) >>> 0) + (Number(seedOffset) >>> 0)) >>> 0, 42);
    return choices[rng.randint(0, choices.length)];
  }

  function stableSeedHash(value) {
    var text = String(value === undefined || value === null ? "" : value);
    var hash = 2166136261;
    for (var i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function normalizeSeedDomainName(value) {
    var name = String(value || "").trim().toLowerCase();
    if (SEED_DOMAIN_NAMES.indexOf(name) < 0) {
      throw new Error("unknown seed domain: " + value);
    }
    return name;
  }

  function normalizePerturbationProfile(value, fallback) {
    if (value === null || value === undefined || value === "") return fallback || "default";
    var name = String(value).trim().toLowerCase();
    return PERTURBATION_PROFILE_NAMES.indexOf(name) >= 0 ? name : (fallback || "default");
  }

  function normalizeSeedStreamName(domain, value) {
    var name = String(value || "").trim();
    if (!/^[a-z][a-z0-9_]*$/.test(name)) {
      throw new Error("invalid seed stream name: " + value);
    }
    var domainName = normalizeSeedDomainName(domain);
    if (PERTURBATION_STREAMS[domainName].indexOf(name) < 0) {
      throw new Error("unknown " + domainName + " seed stream: " + name);
    }
    return name;
  }

  function seedDomainCamelName(domain) {
    var name = normalizeSeedDomainName(domain);
    return "domain" + name.charAt(0).toUpperCase() + name.slice(1) + "Seed";
  }

  function seedDomainSnakeName(domain) {
    return "domain_" + normalizeSeedDomainName(domain) + "_seed";
  }

  function domainConfigNames(domain, kind) {
    var name = normalizeSeedDomainName(domain);
    var normalizedKind = String(kind || "");
    if (DOMAIN_CONFIG_KINDS.indexOf(normalizedKind) < 0) {
      throw new Error("unknown Domain config kind: " + kind);
    }
    var lowerKind = normalizedKind.toLowerCase();
    return {
      camel: "domain" + name.charAt(0).toUpperCase() + name.slice(1) + normalizedKind,
      snake: "domain_" + name + "_" + lowerKind,
      provided: "domain" + name.charAt(0).toUpperCase() + name.slice(1) + normalizedKind + "Provided",
    };
  }

  function hasDomainProvidedMarkers(source) {
    if (!source || typeof source !== "object") return false;
    return SEED_DOMAIN_NAMES.some(function hasDomainMarker(domain) {
      return DOMAIN_CONFIG_KINDS.some(function hasKindMarker(kind) {
        return hasOwn(source, domainConfigNames(domain, kind).provided);
      });
    });
  }

  function hasExplicitDomainConfig(config) {
    var source = config || {};
    return SEED_DOMAIN_NAMES.some(function hasConfiguredDomain(domain) {
      return domainConfigIsExplicit(source, domain);
    });
  }

  function domainConfigIsExplicit(config, domain) {
    var source = config || {};
    var domainName = normalizeSeedDomainName(domain);
    if (hasDomainProvidedMarkers(source)) {
      return DOMAIN_CONFIG_KINDS.some(function kindMarkerEnabled(kind) {
        return source[domainConfigNames(domainName, kind).provided] === true;
      });
    }
    return DOMAIN_CONFIG_KINDS.some(function hasDirectKindConfig(kind) {
      var names = domainConfigNames(domainName, kind);
      return hasOwn(source, names.camel) || hasOwn(source, names.snake);
    });
  }

  function activeDomainsForConfig(config) {
    var active = {};
    SEED_DOMAIN_NAMES.forEach(function resolveActiveDomain(domain) {
      active[domain] = domainConfigIsExplicit(config, domain);
    });
    return Object.freeze(active);
  }

  function domainModeForConfig(config) {
    return hasExplicitDomainConfig(config) ? DOMAIN_MODE_ISOLATED : DOMAIN_MODE_LEGACY;
  }

  function domainModeForTarget(target) {
    return target && target.domainEpisode && target.domainEpisode.mode === DOMAIN_MODE_ISOLATED
      ? DOMAIN_MODE_ISOLATED
      : DOMAIN_MODE_LEGACY;
  }

  function isLegacyDomainEpisode(target) {
    return domainModeForTarget(target) === DOMAIN_MODE_LEGACY;
  }

  function isIsolatedDomainEpisode(target) {
    return domainModeForTarget(target) === DOMAIN_MODE_ISOLATED;
  }

  function isDomainActive(target, domain) {
    var name = normalizeSeedDomainName(domain);
    return isIsolatedDomainEpisode(target)
      && !!(target.domainEpisode.activeDomains && target.domainEpisode.activeDomains[name]);
  }

  function domainProfileForTarget(target, domain) {
    var name = normalizeSeedDomainName(domain);
    if (!isDomainActive(target, name)) return "default";
    var profiles = target.domainState && target.domainState.profiles;
    return normalizePerturbationProfile(profiles && profiles[name], "default");
  }

  function deriveSeed(masterSeed, domain, namespace) {
    var name = normalizeSeedDomainName(domain);
    // Preserve the published seed namespace for deterministic episode replay.
    var salt = "game_gym__" + name;
    if (namespace !== undefined && namespace !== null && namespace !== "") {
      salt += "__" + String(namespace);
    }
    var state = (parseUnsignedInt(masterSeed, 42) ^ stableSeedHash(salt)) >>> 0;
    state = Math.imul(state ^ (state >>> 16), 0x21f0aaad);
    state = Math.imul(state ^ (state >>> 15), 0x735a2d97);
    return (state ^ (state >>> 15)) >>> 0;
  }

  function readSeedConfigValue(source, domain) {
    var config = source || {};
    var camelName = seedDomainCamelName(domain);
    var snakeName = seedDomainSnakeName(domain);
    if (hasOwn(config, camelName)) return parseUnsignedInt(config[camelName], null);
    if (hasOwn(config, snakeName)) return parseUnsignedInt(config[snakeName], null);
    return null;
  }

  function resolveSeedDomains(config, fallbackSeed) {
    var source = config && typeof config === "object" ? config : { seed: config };
    var defaultSeed = parseUnsignedInt(fallbackSeed, 42);
    var seed = parseUnsignedInt(source.seed, defaultSeed);
    var resolved = { seed: seed };
    SEED_DOMAIN_NAMES.forEach(function resolveDomain(domain) {
      var override = readSeedConfigValue(source, domain);
      resolved[seedDomainCamelName(domain)] = override === null ? deriveSeed(seed, domain) : override;
    });
    return resolved;
  }

  function legacyRngForTarget(target, seed, fallbackSeed) {
    var rng = LEGACY_RNG_BY_TARGET && LEGACY_RNG_BY_TARGET.get(target);
    if (!rng && target && target.rng && typeof target.rng.setSeed === "function") {
      rng = target.rng;
    }
    if (!rng) rng = new Engine.Rng(seed, fallbackSeed === undefined ? 42 : fallbackSeed);
    else rng.setSeed(seed);
    if (LEGACY_RNG_BY_TARGET) LEGACY_RNG_BY_TARGET.set(target, rng);
    if (RNG_DOMAIN_MODE) RNG_DOMAIN_MODE.set(rng, DOMAIN_MODE_LEGACY);
    return rng;
  }

  function legacyPlayerSpawnRngForTarget(target, seed, fallbackSeed) {
    var rng = LEGACY_PLAYER_SPAWN_RNG_BY_TARGET
      && LEGACY_PLAYER_SPAWN_RNG_BY_TARGET.get(target);
    var playerSpawnSeed = ((parseUnsignedInt(seed, 42) + LEGACY_PLAYER_SPAWN_SEED_OFFSET) >>> 0);
    if (!rng) {
      rng = new Engine.Rng(
        playerSpawnSeed,
        fallbackSeed === undefined ? 42 : fallbackSeed
      );
    } else {
      rng.setSeed(playerSpawnSeed);
    }
    if (LEGACY_PLAYER_SPAWN_RNG_BY_TARGET) {
      LEGACY_PLAYER_SPAWN_RNG_BY_TARGET.set(target, rng);
    }
    if (RNG_DOMAIN_MODE) RNG_DOMAIN_MODE.set(rng, DOMAIN_MODE_LEGACY);
    return rng;
  }

  function installDomainEpisode(target, values) {
    var episode = Object.freeze(Object.assign({}, values));
    target.domainEpisode = episode;
    return episode;
  }

  function configureGameSeedDomains(game, config, fallbackSeed) {
    var resolved = resolveSeedDomains(config, fallbackSeed);
    var domains = Object.freeze({
      seed: resolved.seed,
      domainAppearanceSeed: resolved.domainAppearanceSeed,
      domainCameraSeed: resolved.domainCameraSeed,
      domainSceneSeed: resolved.domainSceneSeed,
    });
    game.seed = domains.seed;
    game.seedDomains = domains;
    var mode = domainModeForConfig(config);
    var activeDomains = activeDomainsForConfig(config);
    var masterRng = legacyRngForTarget(game, domains.seed, fallbackSeed);
    var legacyPlayerSpawnRng = legacyPlayerSpawnRngForTarget(game, domains.seed, fallbackSeed);
    installDomainEpisode(game, {
      mode: mode,
      activeDomains: activeDomains,
      seedDomains: domains,
      masterRng: masterRng,
      legacyPlayerSpawnRng: legacyPlayerSpawnRng,
      streams: null,
      contract: null,
      state: null,
    });
    return domains;
  }

  function seedDomainFor(target, domain, fallbackSeed) {
    var name = normalizeSeedDomainName(domain);
    var source = target && target.seedDomains ? target.seedDomains : target;
    var direct = readSeedConfigValue(source, name);
    if (direct !== null) return direct;
    var seed = source && hasOwn(source, "seed") ? source.seed : fallbackSeed;
    return deriveSeed(seed, name);
  }

  function forkSeedDomain(target, domain, namespace, fallbackSeed) {
    var name = normalizeSeedDomainName(domain);
    var streamName = normalizeSeedStreamName(name, namespace);
    var domainSeed = seedDomainFor(target, name, fallbackSeed);
    return new Engine.Rng(deriveSeed(domainSeed, name, streamName), fallbackSeed);
  }

  function isolatedGameplayRng(target, domain, streamName, fallbackSeed, legacyRng) {
    var isolatedRng = forkSeedDomain(target, domain, streamName, fallbackSeed);
    var isolatedNext = isolatedRng.next.bind(isolatedRng);
    isolatedRng.next = function nextIsolatedGameplayValue() {
      legacyRng.next();
      return isolatedNext();
    };
    return isolatedRng;
  }

  function normalizeStreamSpecification(specification) {
    var usesDefaultSpecification = specification === undefined || specification === null;
    var source = specification && specification.domains
      ? specification.domains
      : (usesDefaultSpecification ? PERTURBATION_STREAMS : specification);
    Object.keys(source).forEach(function rejectUnknownStreamDomain(domain) {
      if (SEED_DOMAIN_NAMES.indexOf(domain) < 0) {
        throw new Error("unknown seed stream domain: " + domain);
      }
    });
    var normalized = {};
    SEED_DOMAIN_NAMES.forEach(function normalizeDomainStreams(domain) {
      var requested = source[domain];
      if (requested === true || (usesDefaultSpecification && requested === undefined)) {
        requested = PERTURBATION_STREAMS[domain];
      }
      if (requested === undefined) requested = [];
      if (requested === false || requested === null) requested = [];
      if (!Array.isArray(requested)) {
        throw new Error("seed stream specification for " + domain + " must be an array");
      }
      var seen = {};
      normalized[domain] = requested.map(function normalizeRequestedStream(streamName) {
        var name = normalizeSeedStreamName(domain, streamName);
        if (seen[name]) throw new Error("duplicate " + domain + " seed stream: " + name);
        seen[name] = true;
        return name;
      });
    });
    return normalized;
  }

  function createSeedStreams(target, specification, fallbackSeed) {
    if (!target) throw new Error("Core.seeds.createStreams requires a target");
    var normalized = normalizeStreamSpecification(specification);
    var streams = {};
    var mode = domainModeForTarget(target);
    var activeDomains = target.domainEpisode && target.domainEpisode.activeDomains
      || activeDomainsForConfig(null);
    var masterRng = target.domainEpisode && target.domainEpisode.masterRng
      || legacyRngForTarget(target, target.seed, fallbackSeed);
    var playerSpawnRng = target.domainEpisode && target.domainEpisode.legacyPlayerSpawnRng
      || legacyPlayerSpawnRngForTarget(target, target.seed, fallbackSeed);
    SEED_DOMAIN_NAMES.forEach(function createDomainStreams(domain) {
      var group = {};
      normalized[domain].forEach(function createStream(streamName) {
        var isolatedStream = mode === DOMAIN_MODE_ISOLATED && activeDomains[domain];
        var legacyRng = domain === "scene" && streamName === "player_spawn"
          ? playerSpawnRng
          : masterRng;
        var rng = isolatedStream
          ? isolatedGameplayRng(target, domain, streamName, fallbackSeed, legacyRng)
          : legacyRng;
        if (RNG_DOMAIN_MODE) {
          RNG_DOMAIN_MODE.set(rng, isolatedStream ? DOMAIN_MODE_ISOLATED : DOMAIN_MODE_LEGACY);
        }
        group[streamName] = rng;
      });
      streams[domain] = Object.freeze(group);
    });
    target.rng = Object.freeze(streams);
    var previous = target.domainEpisode || {};
    installDomainEpisode(target, {
      mode: mode,
      activeDomains: activeDomains,
      seedDomains: previous.seedDomains || target.seedDomains,
      masterRng: masterRng,
      legacyPlayerSpawnRng: playerSpawnRng,
      streams: target.rng,
      contract: previous.contract || null,
      state: previous.state || null,
    });
    return target.rng;
  }

  function createEntityRng(entitySpawnRng, fallbackSeed) {
    if (!entitySpawnRng || typeof entitySpawnRng.randint !== "function") {
      throw new Error("Core.domains.createEntityRng requires the scene entity_spawn stream");
    }
    if (RNG_DOMAIN_MODE && RNG_DOMAIN_MODE.get(entitySpawnRng) === DOMAIN_MODE_LEGACY) {
      return entitySpawnRng;
    }
    return new Engine.Rng(
      entitySpawnRng.randint(0, 4294967296),
      fallbackSeed === undefined ? 42 : fallbackSeed,
      { allowZeroSeed: true }
    );
  }

  function domainGameplayRng(target, domain, stream) {
    if (!target) throw new Error("Core.domains.gameplayRng requires a target");
    var domainName = normalizeSeedDomainName(domain);
    var streamName = normalizeSeedStreamName(domainName, stream);
    var rng = target.rng && target.rng[domainName] && target.rng[domainName][streamName];
    if (!rng) {
      throw new Error("Domain gameplay stream is not enabled: " + domainName + "." + streamName);
    }
    return rng;
  }

  function baselineGameplayRng(target) {
    if (!target || !target.domainEpisode || !target.domainEpisode.masterRng) {
      throw new Error("Core.domains.baselineRng requires an initialized domain episode");
    }
    return target.domainEpisode.masterRng;
  }

  function domainEntityRng(target, entitySpawnRng, fallbackSeed) {
    var rng = entitySpawnRng || domainGameplayRng(target, "scene", "entity_spawn");
    return createEntityRng(rng, fallbackSeed);
  }

  function normalizeCapabilities(source) {
    var capabilities = {};
    var requestedDomains = source || {};
    Object.keys(requestedDomains).forEach(function rejectUnknownCapabilityDomain(domain) {
      if (SEED_DOMAIN_NAMES.indexOf(domain) < 0) {
        throw new Error("unknown perturbation capability domain: " + domain);
      }
    });
    SEED_DOMAIN_NAMES.forEach(function normalizeDomainCapabilities(domain) {
      var requested = requestedDomains[domain];
      var enabled = {};
      if (requested === true) {
        PERTURBATION_STREAMS[domain].forEach(function enableStandardStream(streamName) {
          enabled[streamName] = true;
        });
      } else if (Array.isArray(requested)) {
        requested.forEach(function enableListedStream(streamName) {
          enabled[normalizeSeedStreamName(domain, streamName)] = true;
        });
      } else if (requested && typeof requested === "object") {
        Object.keys(requested).forEach(function enableMappedStream(streamName) {
          var name = normalizeSeedStreamName(domain, streamName);
          enabled[name] = !!requested[streamName];
        });
      } else if (requested !== false && requested !== null && requested !== undefined) {
        throw new Error("invalid perturbation capabilities for " + domain);
      }
      var normalizedDomain = {};
      PERTURBATION_STREAMS[domain].forEach(function setCapability(streamName) {
        normalizedDomain[streamName] = !!enabled[streamName];
      });
      capabilities[domain] = Object.freeze(normalizedDomain);
    });
    return Object.freeze(capabilities);
  }

  function enabledStreamsFromCapabilities(capabilities) {
    var streams = {};
    SEED_DOMAIN_NAMES.forEach(function collectEnabledStreams(domain) {
      streams[domain] = PERTURBATION_STREAMS[domain].filter(function isEnabled(streamName) {
        return !!capabilities[domain][streamName];
      });
    });
    return streams;
  }

  function copyPlainValue(value) {
    if (value === undefined) return undefined;
    return JSON.parse(JSON.stringify(value));
  }

  function perturbationSample(target, domain, stream, fallback) {
    var domainName = normalizeSeedDomainName(domain);
    var streamName = normalizeSeedStreamName(domainName, stream);
    if (!isDomainActive(target, domainName)) return fallback;
    var applied = target && target.domainState && target.domainState.applied;
    if (!applied || !applied[domainName] || applied[domainName][streamName] === undefined) {
      return fallback;
    }
    return applied[domainName][streamName];
  }

  function mixTemperatureTint(color, temperature) {
    var value = Number(color) >>> 0;
    var mode = String(temperature || "neutral");
    if (mode === "neutral") return value;
    var tint = mode === "warm" ? 0xf0aa64 : (mode === "cool" ? 0x72a7e1 : null);
    if (tint === null) return value;
    var amount = mode === "warm" ? 0.36 : 0.28;
    var source = [
      (value >>> 16) & 255,
      (value >>> 8) & 255,
      value & 255,
    ];
    var target = [
      (tint >>> 16) & 255,
      (tint >>> 8) & 255,
      tint & 255,
    ];
    var mixed = source.map(function mixChannel(channel, index) {
      return channel + (target[index] - channel) * amount;
    });
    function luminance(channels) {
      return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
    }
    var mixedLuminance = luminance(mixed);
    var scale = mixedLuminance > 0 ? luminance(source) / mixedLuminance : 1;
    function packedChannel(channel) {
      return Math.max(0, Math.min(255, Math.round(channel * scale)));
    }
    return (
      (packedChannel(mixed[0]) << 16)
      | (packedChannel(mixed[1]) << 8)
      | packedChannel(mixed[2])
    ) >>> 0;
  }

  function transformColor(color, sample) {
    var value = Number(color) >>> 0;
    if (!sample) return value;
    var red = ((value >>> 16) & 255) / 255;
    var green = ((value >>> 8) & 255) / 255;
    var blue = (value & 255) / 255;
    var maxValue = Math.max(red, green, blue);
    var minValue = Math.min(red, green, blue);
    var lightness = (maxValue + minValue) / 2;
    var saturation = 0;
    var hue = 0;
    if (maxValue !== minValue) {
      var delta = maxValue - minValue;
      saturation = lightness > 0.5
        ? delta / (2 - maxValue - minValue)
        : delta / (maxValue + minValue);
      if (maxValue === red) hue = (green - blue) / delta + (green < blue ? 6 : 0);
      else if (maxValue === green) hue = (blue - red) / delta + 2;
      else hue = (red - green) / delta + 4;
      hue /= 6;
    }
    hue = (hue + (Number(sample.hue_shift_degrees) || 0) / 360) % 1;
    if (hue < 0) hue += 1;
    saturation = Math.max(0, Math.min(1, saturation * (Number(sample.saturation_scale) || 1)));
    lightness = Math.max(0, Math.min(1, lightness * (Number(sample.brightness_scale) || 1)));

    function hueChannel(p, q, channel) {
      var t = channel;
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    }

    if (saturation === 0) {
      red = lightness;
      green = lightness;
      blue = lightness;
    } else {
      var q = lightness < 0.5
        ? lightness * (1 + saturation)
        : lightness + saturation - lightness * saturation;
      var p = 2 * lightness - q;
      red = hueChannel(p, q, hue + 1 / 3);
      green = hueChannel(p, q, hue);
      blue = hueChannel(p, q, hue - 1 / 3);
    }
    var transformed = (
      (Math.round(red * 255) << 16)
      | (Math.round(green * 255) << 8)
      | Math.round(blue * 255)
    ) >>> 0;
    return mixTemperatureTint(transformed, sample.environment_temperature);
  }

  function appearanceTone(target) {
    var seed = seedDomainFor(target, "appearance", 42);
    var illumination = (deriveSeed(seed, "appearance", "illumination") >>> 0) / 4294967295;
    return {
      illumination: illumination,
      theme: illumination < 1 / 3 ? "dark" : (illumination > 2 / 3 ? "light" : "neutral"),
    };
  }

  function sampleDefaultPeakedAppearance(stream, parameter, quantile) {
    var bounds = PERTURBATION_PROFILE_RANGES.perturbed.appearance[stream][parameter];
    var mode = PERTURBATION_PROFILE_RANGES.default.appearance[stream][parameter];
    var minimum = bounds[0];
    var maximum = bounds[1];
    var width = maximum - minimum;
    // Inverse triangular CDF: the native value is the density peak, including at an endpoint.
    if (quantile < (mode - minimum) / width) {
      return minimum + Math.sqrt(quantile * width * (mode - minimum));
    }
    return maximum - Math.sqrt((1 - quantile) * width * (maximum - mode));
  }

  function sampleCenteredCategory(values, quantile) {
    return values[quantile < 0.2 ? 0 : (quantile < 0.8 ? 1 : 2)];
  }

  function standardPerturbationSampler(domain, stream) {
    if (domain === "scene" || (domain === "camera" && stream === "orientation")) return null;
    return function sampleStandardPerturbation(context) {
      var profile = normalizePerturbationProfile(context.profile, "default");
      if (profile === "default") {
        return copyPlainValue(PERTURBATION_PROFILE_RANGES.default[domain][stream]);
      }
      var rng = context.rng;
      if (domain === "appearance" && stream === "assets") return { enabled: true };
      if (domain === "appearance" && stream === "palette") {
        var paletteTone = appearanceTone(context.game);
        return {
          theme: paletteTone.theme,
          illumination: paletteTone.illumination,
          hue_shift_degrees: rng.choice([0, 60, 120, 180, 240, 300]),
          saturation_scale: rng.range(0.95, 1.25),
          brightness_scale: rng.range(0.96, 1.15),
        };
      }
      if (domain === "appearance" && stream === "lighting") {
        var lightingTone = appearanceTone(context.game);
        return {
          theme: lightingTone.theme,
          illumination: lightingTone.illumination,
          ambient_scale: sampleDefaultPeakedAppearance("lighting", "ambient_scale", lightingTone.illumination),
          key_scale: sampleDefaultPeakedAppearance("lighting", "key_scale", lightingTone.illumination),
          key_azimuth_degrees: sampleCenteredCategory(
            PERTURBATION_PROFILE_RANGES.perturbed.appearance.lighting.key_azimuth_degrees, rng.next()
          ),
          shadow_strength: sampleDefaultPeakedAppearance("lighting", "shadow_strength", rng.next()),
        };
      }
      if (domain === "appearance" && stream === "background") {
        var backgroundTone = appearanceTone(context.game);
        return {
          theme: backgroundTone.theme,
          illumination: backgroundTone.illumination,
          environment_temperature: sampleCenteredCategory(
            ENVIRONMENT_TEMPERATURE_NAMES,
            (deriveSeed(seedDomainFor(context.game, "appearance", 42), "appearance", "temperature") >>> 0)
              / 4294967295
          ),
          hue_shift_degrees: sampleDefaultPeakedAppearance("background", "hue_shift_degrees", rng.next()),
          saturation_scale: sampleDefaultPeakedAppearance("background", "saturation_scale", backgroundTone.illumination),
          brightness_scale: sampleDefaultPeakedAppearance("background", "brightness_scale", backgroundTone.illumination),
        };
      }
      if (domain === "camera" && stream === "projection") {
        return { fov_offset_degrees: rng.range(-8, 8) };
      }
      if (domain === "camera" && stream === "rig") {
        var rigRanges = PERTURBATION_PROFILE_RANGES.perturbed.camera.rig;
        return {
          height_scale: rng.range(rigRanges.height_scale[0], rigRanges.height_scale[1]),
          distance_scale: rng.range(rigRanges.distance_scale[0], rigRanges.distance_scale[1]),
          pitch_offset_radians: rng.range(rigRanges.pitch_offset_radians[0], rigRanges.pitch_offset_radians[1]),
        };
      }
      return null;
    };
  }

  function cameraOrientationSampler(group) {
    var groups = PERTURBATION_PROFILE_RANGES.perturbed.camera.orientation;
    if (!hasOwn(groups, group)) throw new Error("Unknown camera orientation group: " + group);
    var ranges = groups[group];
    return function sampleCameraOrientation(context) {
      var sample = Object.assign({ group: group }, PERTURBATION_PROFILE_RANGES.default.camera.orientation);
      if (context.profile === "perturbed") {
        sample.yaw_offset_radians = context.rng.range(ranges.yaw_offset_radians[0], ranges.yaw_offset_radians[1]);
        sample.pitch_offset_radians = context.rng.range(ranges.pitch_offset_radians[0], ranges.pitch_offset_radians[1]);
      }
      return sample;
    };
  }

  function templatePerturbationSampler(defaultTemplate, perturbedTemplates) {
    var fallback = String(defaultTemplate || "default");
    var templates = Array.isArray(perturbedTemplates)
      ? perturbedTemplates.map(function normalizeTemplateName(name) { return String(name); })
      : [];
    if (!templates.length) throw new Error("template perturbation sampler requires at least one perturbed template");
    return function sampleTemplatePerturbation(context) {
      var seed = Number(context.rng && context.rng.seed);
      var index = Number.isFinite(seed)
        ? (seed >>> 0) % templates.length
        : context.rng.randint(0, templates.length);
      return {
        template: context.profile === "perturbed" ? templates[index] : fallback,
      };
    };
  }

  function templatePerturbationValidator(templateNames) {
    var allowed = Object.create(null);
    (Array.isArray(templateNames) ? templateNames : []).forEach(function registerTemplate(name) {
      allowed[String(name)] = true;
    });
    return function validateTemplatePerturbation(context) {
      return !!context.value && allowed[String(context.value.template)] === true;
    };
  }

  function normalizeAssetVariations(raw, assets, parsePalette) {
    var variants = {};
    var groups = {};
    var groupSizes = {};
    function identifier(value, label) {
      if (typeof value !== "string" || !/^[a-z0-9][a-z0-9_-]{0,63}$/.test(value)) {
        throw new Error("Invalid asset " + label + ": " + value);
      }
      return value;
    }
    function registerGroup(group, count) {
      if (groupSizes[group] !== undefined && groupSizes[group] !== count) {
        throw new Error("Asset variant group requires equal variant counts: " + group);
      }
      groupSizes[group] = count;
    }
    if (raw.variants !== undefined && (!raw.variants || Array.isArray(raw.variants)
      || typeof raw.variants !== "object")) throw new Error("Asset variants must be an object");
    Object.keys(raw.variants || {}).forEach(function normalizeVariant(baseId) {
      identifier(baseId, "variant id");
      var base = assets[baseId];
      var values = raw.variants[baseId];
      if (!base) throw new Error("Missing base asset for variants: " + baseId);
      if (!Array.isArray(values) || values.length < 2 || values[0] !== baseId
        || new Set(values).size !== values.length) {
        throw new Error("Asset variants require the base id first and distinct alternatives: " + baseId);
      }
      values.forEach(function validateAlternative(id) {
        identifier(id, "variant id");
        var alternative = assets[id];
        if (!alternative) throw new Error("Missing asset variant: " + id);
        if (alternative.role !== base.role || alternative.type !== base.type) {
          throw new Error("Asset variant must preserve role and type: " + baseId + " -> " + id);
        }
        if (base.type === "atlas" && alternative.frames.length !== base.frames.length) {
          throw new Error("Asset variant must preserve animation frame count: " + id);
        }
        if (base.type === "model") {
          ["clips", "sockets", "material_roles"].forEach(function validateRoles(kind) {
            if (JSON.stringify(Object.keys(base.visual[kind]).sort())
              !== JSON.stringify(Object.keys(alternative.visual[kind]).sort())) {
              throw new Error("Asset variant must preserve visual " + kind + " roles: " + id);
            }
          });
        }
      });
      var group = base.variant_group === undefined ? "asset:" + baseId : identifier(base.variant_group, "variant group");
      registerGroup(group, values.length);
      variants[baseId] = values.slice();
      groups[baseId] = group;
    });
    var themes = [];
    if (raw.themes !== undefined && (!Array.isArray(raw.themes) || raw.themes.length < 2)) {
      throw new Error("Asset themes require a native theme and alternatives");
    }
    (raw.themes || []).forEach(function normalizeTheme(source) {
      var id = identifier(source && source.id, "theme id");
      if (themes.some(function duplicate(theme) { return theme.id === id; })) throw new Error("Duplicate asset theme: " + id);
      var surfaces = Object.assign({}, source.surfaces || {});
      Object.keys(surfaces).forEach(function validateSurface(role) {
        if (typeof surfaces[role] !== "string" || !surfaces[role].trim()) throw new Error("Invalid theme surface: " + id + "." + role);
      });
      themes.push({ id: id, palette: parsePalette(source.palette), surfaces: surfaces });
    });
    var themeGroup = raw.theme_group === undefined ? "theme" : identifier(raw.theme_group, "theme group");
    if (themes.length) registerGroup(themeGroup, themes.length);
    return { variants: variants, groups: groups, themes: themes, themeGroup: themeGroup };
  }

  function resolveAssetVariations(manifest, seed, enabled) {
    var variations = manifest.variations;
    var selected = {};
    function index(group, count) {
      return enabled ? deriveSeed(seed, "appearance", "assets:" + manifest.id + ":" + group) % count : 0;
    }
    if (!variations) return { assets: selected, theme: { id: "native", palette: {}, surfaces: {} } };
    Object.keys(variations.variants).forEach(function selectVariant(baseId) {
      var values = variations.variants[baseId];
      selected[baseId] = values[index(variations.groups[baseId], values.length)];
    });
    var theme = variations.themes.length
      ? variations.themes[index(variations.themeGroup, variations.themes.length)]
      : { id: "native", palette: {}, surfaces: {} };
    return { assets: selected, theme: theme };
  }

  function expandAssetRequirements(manifest, required) {
    var expanded = new Set(required);
    var variants = manifest.variations ? manifest.variations.variants : {};
    required.forEach(function includeVariants(assetId) {
      (variants[assetId] || []).forEach(function include(id) { expanded.add(id); });
    });
    return Array.from(expanded);
  }

  function freezeHandlerMap(source, capabilities, label) {
    var handlers = {};
    var requestedDomains = source || {};
    Object.keys(requestedDomains).forEach(function rejectUnknownHandlerDomain(domain) {
      if (SEED_DOMAIN_NAMES.indexOf(domain) < 0) {
        throw new Error("unknown perturbation " + label + " domain: " + domain);
      }
    });
    SEED_DOMAIN_NAMES.forEach(function normalizeDomainHandlers(domain) {
      var domainHandlers = {};
      var requested = requestedDomains[domain] || {};
      Object.keys(requested).forEach(function validateHandler(streamName) {
        var name = normalizeSeedStreamName(domain, streamName);
        if (!capabilities[domain][name]) {
          throw new Error(label + " declared for unsupported " + domain + " stream: " + name);
        }
        if (typeof requested[streamName] !== "function") {
          throw new Error(label + " for " + domain + "." + name + " must be a function");
        }
        domainHandlers[name] = requested[streamName];
      });
      if (label === "sampler") {
        PERTURBATION_STREAMS[domain].forEach(function installStandardSampler(streamName) {
          if (!capabilities[domain][streamName] || domainHandlers[streamName]) return;
          var sampler = standardPerturbationSampler(domain, streamName);
          if (sampler) domainHandlers[streamName] = sampler;
        });
      }
      handlers[domain] = Object.freeze(domainHandlers);
    });
    return Object.freeze(handlers);
  }

  function definePerturbationContract(specification) {
    var spec = specification || {};
    var gameId = String(spec.game_id || spec.gameId || "").trim();
    if (!/^[a-z0-9][a-z0-9_]*$/.test(gameId)) {
      throw new Error("perturbation contract requires a snake_case game_id");
    }
    var capabilities = normalizeCapabilities(spec.capabilities);
    var defaults = spec.defaults || {};
    var contract = {
      gameId: gameId,
      controlResponse: defineControlResponseRanges(spec.control_response),
      capabilities: capabilities,
      defaults: Object.freeze({
        appearance: normalizePerturbationProfile(
          defaults.appearance_profile === undefined ? defaults.appearance : defaults.appearance_profile,
          "default"
        ),
        camera: normalizePerturbationProfile(
          defaults.camera_profile === undefined ? defaults.camera : defaults.camera_profile,
          "default"
        ),
        scene: normalizePerturbationProfile(
          defaults.scene_profile === undefined ? defaults.scene : defaults.scene_profile,
          "default"
        ),
      }),
    };
    contract.samplers = freezeHandlerMap(spec.samplers, capabilities, "sampler");
    contract.validators = freezeHandlerMap(spec.validators, capabilities, "validator");
    return Object.freeze(contract);
  }

  function readPerturbationProfile(config, domain, fallback) {
    var source = config || {};
    var camelName = "domain" + domain.charAt(0).toUpperCase() + domain.slice(1) + "Profile";
    var snakeName = "domain_" + domain + "_profile";
    var value = hasOwn(source, camelName) ? source[camelName] : source[snakeName];
    return normalizePerturbationProfile(value, fallback || "default");
  }

  function perturbationContractPayload(target) {
    if (!target || !target.perturbationContract || isLegacyDomainEpisode(target)) return null;
    var contract = target.perturbationContract;
    var state = target.domainState || {};
    var capabilities = {};
    var streamSeeds = {};
    SEED_DOMAIN_NAMES.forEach(function copyCapabilities(domain) {
      capabilities[domain] = Object.assign({}, contract.capabilities[domain]);
      streamSeeds[domain] = {};
      PERTURBATION_STREAMS[domain].forEach(function copyStreamSeed(streamName) {
        var rng = target.rng && target.rng[domain] && target.rng[domain][streamName];
        if (rng && Number.isFinite(Number(rng.seed))) {
          streamSeeds[domain][streamName] = Number(rng.seed) >>> 0;
        }
      });
    });
    return {
      game_id: contract.gameId,
      mode: DOMAIN_MODE_ISOLATED,
      active_domains: Object.assign({}, target.domainEpisode.activeDomains),
      profiles: Object.assign({}, state.profiles || contract.defaults),
      capabilities: capabilities,
      stream_seeds: streamSeeds,
      ranges: copyPlainValue(PERTURBATION_PROFILE_RANGES),
      applied: state.applied ? JSON.parse(JSON.stringify(state.applied)) : {},
    };
  }

  function beginDomainEpisode(target, config, contract, fallbackSeed) {
    if (!target) throw new Error("Core.domains.beginEpisode requires a target");
    var normalizedContract = contract && contract.gameId
      ? contract
      : definePerturbationContract(contract);
    beginControlResponseEpisode(target, config || {}, normalizedContract, fallbackSeed);
    configureGameSeedDomains(target, config, fallbackSeed);
    target.perturbationContract = normalizedContract;
    createSeedStreams(
      target,
      enabledStreamsFromCapabilities(normalizedContract.capabilities),
      fallbackSeed
    );
    var mode = domainModeForTarget(target);
    var activeDomains = target.domainEpisode.activeDomains;
    var profiles = {};
    var applied = {};
    SEED_DOMAIN_NAMES.forEach(function resolveDomainPerturbations(domain) {
      profiles[domain] = !activeDomains[domain]
        ? "default"
        : readPerturbationProfile(config, domain, normalizedContract.defaults[domain]);
      applied[domain] = {};
      if (!activeDomains[domain]) {
        applied[domain] = Object.freeze(applied[domain]);
        return;
      }
      Object.keys(normalizedContract.samplers[domain]).forEach(function runSampler(streamName) {
        var samplerRng = forkSeedDomain(target, domain, streamName, fallbackSeed);
        var sampled = normalizedContract.samplers[domain][streamName]({
          game: target,
          config: config || {},
          contract: normalizedContract,
          domain: domain,
          stream: streamName,
          profile: profiles[domain],
          rng: samplerRng,
        });
        var validator = normalizedContract.validators[domain][streamName];
        if (validator && validator({
          game: target,
          config: config || {},
          contract: normalizedContract,
          domain: domain,
          stream: streamName,
          profile: profiles[domain],
          value: sampled,
        }) === false) {
          throw new Error("invalid sampled perturbation for " + domain + "." + streamName);
        }
        applied[domain][streamName] = sampled;
      });
      applied[domain] = Object.freeze(applied[domain]);
    });
    target.domainState = Object.freeze({
      mode: mode,
      activeDomains: activeDomains,
      profiles: Object.freeze(profiles),
      applied: Object.freeze(applied),
    });
    var previous = target.domainEpisode || {};
    return installDomainEpisode(target, {
      mode: mode,
      activeDomains: activeDomains,
      seedDomains: previous.seedDomains || target.seedDomains,
      masterRng: previous.masterRng || null,
      legacyPlayerSpawnRng: previous.legacyPlayerSpawnRng || null,
      streams: target.rng,
      contract: normalizedContract,
      state: target.domainState,
    });
  }

  function resolvePerturbationEpisode(target, config, contract, fallbackSeed) {
    beginDomainEpisode(target, config, contract, fallbackSeed);
    return target.domainState;
  }

  function validatePerturbationStream(target, domain, stream, value) {
    if (!target || !target.perturbationContract) return true;
    var domainName = normalizeSeedDomainName(domain);
    var streamName = normalizeSeedStreamName(domainName, stream);
    var validator = target.perturbationContract.validators[domainName][streamName];
    if (!validator) return true;
    return validator({
      game: target,
      contract: target.perturbationContract,
      domain: domainName,
      stream: streamName,
      value: value,
    }) !== false;
  }

  function perturbationStreamSupported(target, domain, stream) {
    if (!target || !target.perturbationContract) return false;
    var domainName = normalizeSeedDomainName(domain);
    var streamName = normalizeSeedStreamName(domainName, stream);
    return !!target.perturbationContract.capabilities[domainName][streamName];
  }

  function seedDomainPayload(target) {
    if (!target || isLegacyDomainEpisode(target)) return null;
    var source = target.seedDomains || target;
    if (!source || !hasOwn(source, "seed")) return null;
    return {
      seed: parseUnsignedInt(source.seed, 42),
      domain_appearance_seed: seedDomainFor(source, "appearance", 42),
      domain_camera_seed: seedDomainFor(source, "camera", 42),
      domain_scene_seed: seedDomainFor(source, "scene", 42),
    };
  }

  function buildVisualFlags(perturbMode, explicit) {
    explicit = explicit || {};
    return {
      bgColor: explicit.bgColor === null || explicit.bgColor === undefined
        ? perturbMode === "color" || perturbMode === "all"
        : !!explicit.bgColor,
      entityColor: explicit.entityColor === null || explicit.entityColor === undefined
        ? perturbMode === "color" || perturbMode === "all"
        : !!explicit.entityColor,
    };
  }

  function cloneVisualFlags(flags) {
    return {
      bgColor: !!(flags && flags.bgColor),
      entityColor: !!(flags && flags.entityColor),
    };
  }

  function immediateColorSample(seed, environment) {
    var value = deriveSeed(seed, "appearance", environment ? "background-flag" : "entity-flag");
    return {
      hue_shift_degrees: environment ? 20 + value % 31 : 38 + value % 43,
      saturation_scale: environment ? 0.9 : 1,
      brightness_scale: environment ? 0.91 : 0.88,
      environment_temperature: environment ? (value % 2 ? "warm" : "cool") : "neutral",
    };
  }

  function visualLabel(flags) {
    var parts = [];
    if (flags && flags.bgColor) parts.push("bg_color");
    if (flags && flags.entityColor) parts.push("entity_color");
    return parts.length ? parts.join("+") : "none";
  }

  function buildVisualPayload(options) {
    var opts = options || {};
    var active = cloneVisualFlags(opts.active);
    var payload = {
      active: active,
      active_any: visualLabel(active) !== "none",
      label: visualLabel(active),
      asset: opts.asset || null,
    };
    if (opts.extra && typeof opts.extra === "object") Object.assign(payload, opts.extra);
    return payload;
  }

  function activePerturbationDomains(target) {
    var active = {};
    SEED_DOMAIN_NAMES.forEach(function resolveActivePerturbationDomain(domain) {
      var capabilities = target && target.perturbationContract
        && target.perturbationContract.capabilities
        && target.perturbationContract.capabilities[domain];
      var supported = capabilities && Object.keys(capabilities).some(function supportsDomainStream(stream) {
        return capabilities[stream];
      });
      active[domain] = isDomainActive(target, domain)
        && domainProfileForTarget(target, domain) === "perturbed"
        && !!supported;
    });
    return active;
  }

  function perturbationIsActive(target, visualFlags) {
    var flags = visualFlags;
    if (flags === undefined && target && target.visualPerturbations) {
      flags = target.visualPerturbations.active;
    }
    if (visualLabel(flags) !== "none") return true;
    var domains = activePerturbationDomains(target);
    return SEED_DOMAIN_NAMES.some(function hasActivePerturbationDomain(domain) {
      return domains[domain];
    });
  }

  function perturbationLabel(target, visualFlags) {
    var flags = visualFlags;
    if (flags === undefined && target && target.visualPerturbations) {
      flags = target.visualPerturbations.active;
    }
    var parts = [];
    var legacyLabel = visualLabel(flags);
    if (legacyLabel !== "none") parts = legacyLabel.split("+");
    var domains = activePerturbationDomains(target);
    SEED_DOMAIN_NAMES.forEach(function appendActivePerturbationDomain(domain) {
      if (domains[domain]) parts.push(domain);
    });
    return parts.length ? parts.join("+") : "none";
  }

  function perturbationVisualPayload(target, payload) {
    var source = payload || buildVisualPayload({});
    var next = Object.assign({}, source);
    next.active = cloneVisualFlags(source.active);
    next.active_any = perturbationIsActive(target, next.active);
    next.label = perturbationLabel(target, next.active);
    return next;
  }

  function visualState(config, options) {
    var source = config || {};
    return buildVisualPayload({
      active: source.visualFlags,
      asset: options && options.asset,
      extra: options && options.extra,
    });
  }

  function optionBool(opts, snakeName, camelName, flagName) {
    if (hasOwn(opts, snakeName)) return normalizeBoolean(opts[snakeName], null);
    if (hasOwn(opts, camelName)) return normalizeBoolean(opts[camelName], null);
    if (opts.visualFlags && hasOwn(opts.visualFlags, flagName)) {
      return normalizeBoolean(opts.visualFlags[flagName], null);
    }
    return null;
  }

  function optionProvided(opts, snakeName, camelName, flagName) {
    if (hasOwn(opts, snakeName) || hasOwn(opts, camelName)) return true;
    if (opts.visualFlagsProvided && hasOwn(opts.visualFlagsProvided, flagName)) {
      return opts.visualFlagsProvided[flagName] === true;
    }
    return !!(opts.visualFlags && hasOwn(opts.visualFlags, flagName));
  }

  function domainOptionProvided(opts, domain, kind) {
    var names = domainConfigNames(domain, kind);
    if (hasOwn(opts, names.provided)) return opts[names.provided] === true;
    return hasOwn(opts, names.snake) || hasOwn(opts, names.camel);
  }

  function firstFiniteNumber() {
    for (var i = 0; i < arguments.length; i += 1) {
      var numeric = Number(arguments[i]);
      if (Number.isFinite(numeric)) return numeric;
    }
    return null;
  }

  function normalizeDurationMs(value, fallback) {
    var numeric = Number(value);
    return Number.isFinite(numeric) && numeric > 0 ? numeric : fallback;
  }

  function readStepActionId(action, options) {
    var id = "";
    if (typeof action === "string") id = action;
    else if (action && typeof action === "object" && action.id !== undefined && action.id !== null) id = action.id;
    id = String(id || "").trim();
    return options && options.lowercase ? id.toLowerCase() : id;
  }

  function readStepActionValue(action, key) {
    if (action && typeof action === "object" && hasOwn(action, key)) return action[key];
    return undefined;
  }

  function readStepActionNumber(action, key, fallback) {
    var numeric = Number(readStepActionValue(action, key));
    return Number.isFinite(numeric) ? numeric : fallback;
  }

  function readStepActionButton(action, fallback) {
    var value = readStepActionValue(action, "button");
    var text = String(value === undefined || value === null ? (fallback || "") : value).trim().toLowerCase();
    return text || String(fallback || "").trim().toLowerCase();
  }

  function readStepActionMouse(action) {
    var mouse = readStepActionValue(action, "mouse");
    return mouse && typeof mouse === "object" && !Array.isArray(mouse) ? mouse : null;
  }

  function readStepActionMouseMode(action) {
    var mouse = readStepActionMouse(action);
    return mouse ? String(mouse.mode || "").trim().toLowerCase() : "";
  }

  function readStepActionMouseNumber(action, key, fallback) {
    var mouse = readStepActionMouse(action);
    var numeric = Number(mouse ? mouse[key] : undefined);
    return Number.isFinite(numeric) ? numeric : fallback;
  }

  function readStepActionMouseButton(action, fieldName) {
    var value = readStepActionValue(action, fieldName);
    if (typeof value === "string") return String(value).trim().toLowerCase();
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return String(value.button || "").trim().toLowerCase();
    }
    return "";
  }

  function readStepActionMouseButtons(action) {
    var buttons = {};
    function addButton(value) {
      var button = String(value || "").trim().toLowerCase();
      if (button) buttons[button] = true;
    }
    ["mouse_click", "mouse_hold"].forEach(function addStructuredButton(key) {
      addButton(readStepActionMouseButton(action, key));
    });
    return buttons;
  }

  function stepActionHasMouseButton(action, button) {
    var normalized = String(button || "").trim().toLowerCase();
    return !!(normalized && readStepActionMouseButtons(action)[normalized]);
  }

  function stepActionHasMouseButtonInField(action, fieldName, button) {
    var normalized = String(button || "").trim().toLowerCase();
    return !!normalized && readStepActionMouseButton(action, fieldName) === normalized;
  }

  function createButtonLifecycle() {
    var lifecycle = {
      down: false,
      pressed_this_step: false,
      released_this_step: false,
      held_ms: 0,
    };

    lifecycle.setDown = function setDown(value) {
      var next = !!value;
      if (next === lifecycle.down) return false;
      lifecycle.down = next;
      if (next) {
        lifecycle.pressed_this_step = true;
        lifecycle.held_ms = 0;
      } else {
        lifecycle.released_this_step = true;
        lifecycle.held_ms = 0;
      }
      return true;
    };
    lifecycle.advance = function advance(durationMs) {
      var elapsed = Number(durationMs);
      if (lifecycle.down && Number.isFinite(elapsed) && elapsed > 0) lifecycle.held_ms += elapsed;
      return lifecycle.held_ms;
    };
    lifecycle.endStep = function endStep() {
      lifecycle.pressed_this_step = false;
      lifecycle.released_this_step = false;
      return lifecycle;
    };
    lifecycle.reset = function reset() {
      lifecycle.down = false;
      lifecycle.pressed_this_step = false;
      lifecycle.released_this_step = false;
      lifecycle.held_ms = 0;
      return lifecycle;
    };
    lifecycle.payload = function payload() {
      return {
        down: lifecycle.down,
        pressed_this_step: lifecycle.pressed_this_step,
        released_this_step: lifecycle.released_this_step,
        held_ms: lifecycle.held_ms,
      };
    };
    return lifecycle;
  }

  function readStepActionKeyFields(action, fieldNames) {
    var keys = {};
    function add(value) {
      var rawText = String(value === undefined || value === null ? "" : value);
      var rawLower = rawText.toLowerCase();
      if (rawText === " " || rawLower === "space" || rawLower === "spacebar") {
        keys[" "] = true;
        keys.Space = true;
        keys.space = true;
        keys.Spacebar = true;
        keys.spacebar = true;
      }
      var text = rawText.trim();
      if (!text) return;
      keys[text] = true;
      keys[text.toLowerCase()] = true;
    }
    fieldNames.forEach(function readKeyField(fieldName) {
      var rawKeys = readStepActionValue(action, fieldName);
      if (typeof rawKeys === "string") {
        rawKeys.replace(/\+/g, ",").split(",").forEach(add);
      } else if (Array.isArray(rawKeys)) {
        rawKeys.forEach(add);
      } else if (rawKeys && typeof rawKeys === "object") {
        Object.keys(rawKeys).forEach(function (key) {
          if (rawKeys[key]) add(key);
        });
      }
    });
    return keys;
  }

  function mergeStepActionKeys(target, source) {
    Object.keys(source).forEach(function mergeKey(key) {
      if (source[key]) target[key] = true;
    });
    return target;
  }

  function readStepActionKeys(action) {
    var keys = readStepActionKeyFields(action, ["keys", "key_hold", "key_tap"]);
    ["key", "code"].forEach(function readSingleKey(fieldName) {
      mergeStepActionKeys(keys, readStepActionKeyFields(action, [fieldName]));
    });
    return keys;
  }

  function stepActionHasKey(action, names) {
    var keys = readStepActionKeys(action);
    for (var i = 0; i < names.length; i += 1) {
      var name = String(names[i] || "").trim();
      if (name && (keys[name] || keys[name.toLowerCase()])) return true;
    }
    return false;
  }

  function normalizeApiOptions(opts, maxDifficulty) {
    opts = opts || {};
    var difficultyChoicesProvided = hasOwn(opts, "difficulty_choices") || hasOwn(opts, "difficultyChoices");
    var domainAppearanceSeedProvided = domainOptionProvided(opts, "appearance", "Seed");
    var domainCameraSeedProvided = domainOptionProvided(opts, "camera", "Seed");
    var domainSceneSeedProvided = domainOptionProvided(opts, "scene", "Seed");
    var domainAppearanceProfileProvided = domainOptionProvided(opts, "appearance", "Profile");
    var domainCameraProfileProvided = domainOptionProvided(opts, "camera", "Profile");
    var domainSceneProfileProvided = domainOptionProvided(opts, "scene", "Profile");
    return {
      seed: hasOwn(opts, "seed") ? parseUnsignedInt(opts.seed, null) : null,
      controlResponse: readControlResponseConfig(opts),
      domainAppearanceSeed: domainAppearanceSeedProvided
        ? parseUnsignedInt(hasOwn(opts, "domain_appearance_seed") ? opts.domain_appearance_seed : opts.domainAppearanceSeed, null)
        : null,
      domainAppearanceSeedProvided: domainAppearanceSeedProvided,
      domainCameraSeed: domainCameraSeedProvided
        ? parseUnsignedInt(hasOwn(opts, "domain_camera_seed") ? opts.domain_camera_seed : opts.domainCameraSeed, null)
        : null,
      domainCameraSeedProvided: domainCameraSeedProvided,
      domainSceneSeed: domainSceneSeedProvided
        ? parseUnsignedInt(hasOwn(opts, "domain_scene_seed") ? opts.domain_scene_seed : opts.domainSceneSeed, null)
        : null,
      domainSceneSeedProvided: domainSceneSeedProvided,
      domainAppearanceProfile: domainAppearanceProfileProvided
        ? normalizePerturbationProfile(
          hasOwn(opts, "domain_appearance_profile") ? opts.domain_appearance_profile : opts.domainAppearanceProfile,
          "default"
        )
        : null,
      domainAppearanceProfileProvided: domainAppearanceProfileProvided,
      domainCameraProfile: domainCameraProfileProvided
        ? normalizePerturbationProfile(
          hasOwn(opts, "domain_camera_profile") ? opts.domain_camera_profile : opts.domainCameraProfile,
          "default"
        )
        : null,
      domainCameraProfileProvided: domainCameraProfileProvided,
      domainSceneProfile: domainSceneProfileProvided
        ? normalizePerturbationProfile(
          hasOwn(opts, "domain_scene_profile") ? opts.domain_scene_profile : opts.domainSceneProfile,
          "default"
        )
        : null,
      domainSceneProfileProvided: domainSceneProfileProvided,
      level: opts.level === undefined || opts.level === null ? null : String(opts.level),
      difficulty: hasOwn(opts, "difficulty") ? normalizeDifficulty(opts.difficulty, null, maxDifficulty) : null,
      difficultyProvided: hasOwn(opts, "difficulty"),
      difficultyChoices: difficultyChoicesProvided
        ? normalizeDifficultyChoices(
          hasOwn(opts, "difficulty_choices") ? opts.difficulty_choices : opts.difficultyChoices,
          maxDifficulty
        )
        : null,
      difficultyChoicesProvided: difficultyChoicesProvided,
      autostart: hasOwn(opts, "autostart") ? normalizeBoolean(opts.autostart, null) : null,
      randInitPos: hasOwn(opts, "rand_init_pos")
        ? normalizeBoolean(opts.rand_init_pos, null)
        : (hasOwn(opts, "randInitPos") ? normalizeBoolean(opts.randInitPos, null) : null),
      perturb: hasOwn(opts, "perturb") ? normalizePerturb(opts.perturb) : undefined,
      visualFlags: {
        bgColor: optionBool(opts, "perturb_bg_color", "perturbBgColor", "bgColor"),
        entityColor: optionBool(opts, "perturb_entity_color", "perturbEntityColor", "entityColor"),
      },
      visualFlagsProvided: {
        bgColor: optionProvided(opts, "perturb_bg_color", "perturbBgColor", "bgColor"),
        entityColor: optionProvided(opts, "perturb_entity_color", "perturbEntityColor", "entityColor"),
      },
    };
  }

  function defaultDomainConfigProvided(defaults, domain, kind) {
    var source = defaults || {};
    var names = domainConfigNames(domain, kind);
    if (hasOwn(source, names.provided)) return source[names.provided] === true;
    return hasOwn(source, names.camel) || hasOwn(source, names.snake);
  }

  function readUrlConfig(defaults) {
    var params = new URLSearchParams(window.location.search || "");
    var perturb = normalizePerturb(params.get("perturb"));
    var defaultVisualFlags = buildVisualFlags(perturb, defaults.visualFlags || {});
    return {
      seed: parseUnsignedInt(params.get("seed"), defaults.seed),
      controlResponse: mergeControlResponseConfig(
        readControlResponseConfig(defaults), readControlResponseConfig(Object.fromEntries(params))
      ),
      domainAppearanceSeed: parseUnsignedInt(
        params.get("domain_appearance_seed"),
        readSeedConfigValue(defaults, "appearance")
      ),
      domainAppearanceSeedProvided: params.has("domain_appearance_seed")
        || defaultDomainConfigProvided(defaults, "appearance", "Seed"),
      domainCameraSeed: parseUnsignedInt(
        params.get("domain_camera_seed"),
        readSeedConfigValue(defaults, "camera")
      ),
      domainCameraSeedProvided: params.has("domain_camera_seed")
        || defaultDomainConfigProvided(defaults, "camera", "Seed"),
      domainSceneSeed: parseUnsignedInt(
        params.get("domain_scene_seed"),
        readSeedConfigValue(defaults, "scene")
      ),
      domainSceneSeedProvided: params.has("domain_scene_seed")
        || defaultDomainConfigProvided(defaults, "scene", "Seed"),
      domainAppearanceProfile: normalizePerturbationProfile(
        params.get("domain_appearance_profile"),
        readPerturbationProfile(defaults, "appearance", "default")
      ),
      domainAppearanceProfileProvided: params.has("domain_appearance_profile")
        || defaultDomainConfigProvided(defaults, "appearance", "Profile"),
      domainCameraProfile: normalizePerturbationProfile(
        params.get("domain_camera_profile"),
        readPerturbationProfile(defaults, "camera", "default")
      ),
      domainCameraProfileProvided: params.has("domain_camera_profile")
        || defaultDomainConfigProvided(defaults, "camera", "Profile"),
      domainSceneProfile: normalizePerturbationProfile(
        params.get("domain_scene_profile"),
        readPerturbationProfile(defaults, "scene", "default")
      ),
      domainSceneProfileProvided: params.has("domain_scene_profile")
        || defaultDomainConfigProvided(defaults, "scene", "Profile"),
      difficulty: normalizeDifficulty(params.get("difficulty"), defaults.difficulty, defaults.maxDifficulty),
      difficultyChoices: normalizeDifficultyChoices(params.get("difficulty_choices"), defaults.maxDifficulty),
      difficultyChoiceSeedOffset: parseUnsignedInt(defaults.difficultyChoiceSeedOffset, 0),
      autostart: normalizeBoolean(params.get("autostart"), defaults.autostart === undefined ? true : !!defaults.autostart),
      randInitPos: normalizeBoolean(params.get("rand_init_pos"), !!defaults.randInitPos),
      perturb: perturb,
      visualFlags: buildVisualFlags(perturb, {
        bgColor: normalizeBoolean(params.get("perturb_bg_color"), defaultVisualFlags.bgColor),
        entityColor: normalizeBoolean(params.get("perturb_entity_color"), defaultVisualFlags.entityColor),
      }),
      visualFlagsProvided: {
        bgColor: params.has("perturb_bg_color"),
        entityColor: params.has("perturb_entity_color"),
      },
    };
  }

  function mergeEpisodeConfig(urlConfig, normalized) {
    var perturb = normalized.perturb === undefined ? urlConfig.perturb : normalized.perturb;
    var normalizedProvided = normalized.visualFlagsProvided || {};
    var urlProvided = urlConfig.visualFlagsProvided || {};
    var explicitFlags = {};
    Object.keys(normalized.visualFlags).forEach(function mergeVisualFlag(key) {
      if (normalizedProvided[key]) explicitFlags[key] = normalized.visualFlags[key];
      else if (urlProvided[key]) explicitFlags[key] = urlConfig.visualFlags[key];
      else explicitFlags[key] = null;
    });
    var visualFlagsProvided = {};
    Object.keys(explicitFlags).forEach(function mergeVisualPresence(key) {
      visualFlagsProvided[key] = !!(normalizedProvided[key] || urlProvided[key]);
    });
    var difficultyChoices = normalized.difficultyChoicesProvided
      ? normalized.difficultyChoices
      : (normalized.difficultyProvided ? null : urlConfig.difficultyChoices);
    var seed = normalized.seed === null ? urlConfig.seed : normalized.seed;
    var domainAppearanceSeed = normalized.domainAppearanceSeedProvided
      ? normalized.domainAppearanceSeed
      : urlConfig.domainAppearanceSeed;
    var domainCameraSeed = normalized.domainCameraSeedProvided
      ? normalized.domainCameraSeed
      : urlConfig.domainCameraSeed;
    var domainSceneSeed = normalized.domainSceneSeedProvided
      ? normalized.domainSceneSeed
      : urlConfig.domainSceneSeed;
    var domainAppearanceProfile = normalized.domainAppearanceProfileProvided
      ? normalized.domainAppearanceProfile
      : urlConfig.domainAppearanceProfile;
    var domainCameraProfile = normalized.domainCameraProfileProvided
      ? normalized.domainCameraProfile
      : urlConfig.domainCameraProfile;
    var domainSceneProfile = normalized.domainSceneProfileProvided
      ? normalized.domainSceneProfile
      : urlConfig.domainSceneProfile;
    var difficulty = normalized.difficulty === null ? urlConfig.difficulty : normalized.difficulty;
    difficulty = chooseDifficulty(seed, difficulty, difficultyChoices, urlConfig.difficultyChoiceSeedOffset);
    return {
      seed: seed,
      controlResponse: mergeControlResponseConfig(urlConfig.controlResponse, normalized.controlResponse),
      domainAppearanceSeed: domainAppearanceSeed,
      domainAppearanceSeedProvided: normalized.domainAppearanceSeedProvided || urlConfig.domainAppearanceSeedProvided,
      domainCameraSeed: domainCameraSeed,
      domainCameraSeedProvided: normalized.domainCameraSeedProvided || urlConfig.domainCameraSeedProvided,
      domainSceneSeed: domainSceneSeed,
      domainSceneSeedProvided: normalized.domainSceneSeedProvided || urlConfig.domainSceneSeedProvided,
      domainAppearanceProfile: domainAppearanceProfile,
      domainAppearanceProfileProvided: normalized.domainAppearanceProfileProvided || urlConfig.domainAppearanceProfileProvided,
      domainCameraProfile: domainCameraProfile,
      domainCameraProfileProvided: normalized.domainCameraProfileProvided || urlConfig.domainCameraProfileProvided,
      domainSceneProfile: domainSceneProfile,
      domainSceneProfileProvided: normalized.domainSceneProfileProvided || urlConfig.domainSceneProfileProvided,
      difficulty: difficulty,
      difficultyChoices: difficultyChoices,
      difficultyChoiceSeedOffset: urlConfig.difficultyChoiceSeedOffset,
      autostart: normalized.autostart === null ? urlConfig.autostart : normalized.autostart,
      randInitPos: normalized.randInitPos === null ? urlConfig.randInitPos : normalized.randInitPos,
      perturb: perturb,
      visualFlags: buildVisualFlags(perturb, explicitFlags),
      visualFlagsProvided: visualFlagsProvided,
    };
  }

  function applyStandardVisuals(flags, displayWidth, displayHeight) {
    var root = document.documentElement;
    root.style.setProperty("--stage-width", displayWidth + "px");
    root.style.setProperty("--stage-height", displayHeight + "px");
    root.style.setProperty("--stage-aspect", displayWidth + " / " + displayHeight);
  }

  function cloneEpisodeConfig(config) {
    config = config || {};
    var cloned = {};
    Object.keys(config).forEach(function (key) {
      if (key === "visualFlags") cloned.visualFlags = cloneVisualFlags(config.visualFlags);
      else if (key === "controlResponse") cloned.controlResponse = copyPlainValue(config.controlResponse);
      else if (key === "visualFlagsProvided") cloned.visualFlagsProvided = Object.assign({}, config.visualFlagsProvided || {});
      else cloned[key] = config[key];
    });
    return cloned;
  }

  function getTerminalGeneration(game) {
    var generation = Number(game && game.terminalLatchId);
    return Number.isFinite(generation) ? generation : 0;
  }

  function didGenerateTerminal(game, generationBefore) {
    return getTerminalGeneration(game) !== generationBefore;
  }

  function initTerminalLatch(game) {
    game.terminalLatch = null;
    game.terminalLatchId = 0;
  }

  function clearTerminalLatch(game, flags) {
    var episodeFlags = flags || {};
    if (!episodeFlags.preserveTerminalLatch) game.terminalLatch = null;
  }

  function captureTerminalLatch(game, buildPayload) {
    var nextGeneration = getTerminalGeneration(game) + 1;
    var previousLatch = game.terminalLatch;
    game.terminalLatch = null;
    try {
      game.terminalLatch = buildPayload();
    } catch (error) {
      game.terminalLatch = previousLatch;
      throw error;
    }
    game.terminalLatchId = nextGeneration;
    if (game.runtime) game.runtime.lastResetMethod = "terminal_auto_reset";
    if (game.terminalLatch && game.terminalLatch.debug) {
      game.terminalLatch.debug.terminal_latch_id = game.terminalLatchId;
      game.terminalLatch.debug.terminal_latch_consumed = false;
      game.terminalLatch.debug.visible_status = game.mode === undefined ? game.phase : game.mode;
      game.terminalLatch.debug.last_reset_method = "terminal_auto_reset";
    }
    return game.terminalLatch;
  }

  function consumeTerminalLatch(game) {
    if (!game.terminalLatch) return null;
    var latched = game.terminalLatch;
    game.terminalLatch = null;
    if (latched.debug) {
      latched.debug.terminal_latch_consumed = true;
      latched.debug.visible_status = game.mode === undefined ? game.phase : game.mode;
    }
    return latched;
  }

  function autoResetAfterTerminal(game, beginEpisode) {
    var resetConfig = cloneEpisodeConfig(game.currentConfig || {});
    beginEpisode.call(game, resetConfig, true, { preserveTerminalLatch: true });
    if (game.runtime) game.runtime.lastResetMethod = "terminal_auto_reset";
  }

  function terminalAwareInfo(game, state, info) {
    var result = info || {};
    if (!state || !state.terminal || !state.terminal.isTerminal) return result;
    result.outcome = state.terminal.outcome;
    result.reason = state.terminal.reason;
    result.terminal = {
      isTerminal: true,
      outcome: state.terminal.outcome,
      reason: state.terminal.reason,
    };
    if (state.metrics) {
      Object.keys(state.metrics).forEach(function (key) {
        result[key] = state.metrics[key];
      });
    }
    return result;
  }

  function resetRewardLedger(game) {
    if (!game) return;
    game.envRewardStep = 0;
    game.envRewardEpisode = 0;
    game.__rewardWindow = null;
  }

  function resetStepReward(game) {
    if (!game) return;
    game.envRewardStep = 0;
  }

  function rewardEpisodeValue(game) {
    var value = Number(game && game.envRewardEpisode);
    return Number.isFinite(value) ? value : 0;
  }

  function beginRewardWindow(game, baseline) {
    if (!game) return { owned: false, baseline: 0 };
    if (game.__rewardWindow && game.__rewardWindow.open) {
      return { owned: false, baseline: game.__rewardWindow.baseline };
    }
    var normalizedBaseline = Number(baseline);
    if (!Number.isFinite(normalizedBaseline)) normalizedBaseline = rewardEpisodeValue(game);
    game.__rewardWindow = { open: true, baseline: normalizedBaseline };
    game.envRewardStep = rewardEpisodeValue(game) - normalizedBaseline;
    return { owned: true, baseline: normalizedBaseline };
  }

  function addEnvReward(game, value) {
    if (!game) return 0;
    var reward = Number(value);
    if (!Number.isFinite(reward) || reward === 0) return 0;
    game.envRewardEpisode = rewardEpisodeValue(game) + reward;
    if (game.__rewardWindow && game.__rewardWindow.open) {
      game.envRewardStep = game.envRewardEpisode - game.__rewardWindow.baseline;
    } else {
      game.envRewardStep = reward;
    }
    return reward;
  }

  function endRewardWindow(game, ticket) {
    if (!game) return 0;
    var windowState = game.__rewardWindow;
    if (!windowState || !windowState.open) return Number(game.envRewardStep) || 0;
    var reward = rewardEpisodeValue(game) - windowState.baseline;
    game.envRewardStep = reward;
    if (!ticket || ticket.owned !== false) {
      windowState.open = false;
      game.__rewardWindow = null;
    }
    return reward;
  }

  function resetEpisodeRuntime(game, options) {
    if (!game) return;
    options = options || {};
    game.paused = false;
    game.lastMouse = null;
    if (game.simulationRunner && typeof game.simulationRunner.reset === "function") {
      game.simulationRunner.reset();
    }
    if (options.controls) {
      game.controls = Object.assign({}, options.controls);
    } else if (game.controls && typeof game.controls === "object") {
      Object.keys(game.controls).forEach(function clearControl(name) {
        if (typeof game.controls[name] === "boolean") game.controls[name] = false;
      });
    }
    if (typeof options.clearTransient === "function") options.clearTransient.call(game);
  }

  function pauseEpisodeRuntime(game) {
    if (!game) {
      return { ok: false, source: "game", paused: false, runtime_paused: false };
    }
    game.paused = true;
    if (game.simulationRunner && typeof game.simulationRunner.resetClock === "function") {
      game.simulationRunner.resetClock();
    }
    return { ok: true, source: "game", paused: true, runtime_paused: true };
  }

  function resumeEpisodeRuntime(game) {
    if (!game) {
      return { ok: false, source: "game", paused: false, runtime_paused: false };
    }
    game.paused = false;
    if (game.simulationRunner && typeof game.simulationRunner.resetClock === "function") {
      game.simulationRunner.resetClock();
    }
    return { ok: true, source: "game", paused: false, runtime_paused: false };
  }

  function createFixedStepRunner(settings) {
    settings = settings || {};
    var game = settings.game;
    if (!game) throw new Error("GameEngineCore.createFixedStepRunner requires a game");
    var stepMs = normalizeDurationMs(settings.stepMs, 1000 / 60);
    var maxFrameDeltaMs = normalizeDurationMs(settings.maxFrameDeltaMs, 100);
    var update = settings.update;
    var render = settings.render;
    var isActive = typeof settings.isActive === "function"
      ? settings.isActive
      : function defaultIsActive() { return game.mode === "playing" && !game.paused; };
    var customShouldStop = typeof settings.shouldStop === "function" ? settings.shouldStop : null;
    var requestHandle = 0;

    function resetClock() {
      runner.lastFrameMs = 0;
      runner.accumulatorMs = 0;
    }

    function runOneStep() {
      var terminalBefore = getTerminalGeneration(game);
      // Actions are applied before advance(); update receives fixed-step time only.
      var updateResult = typeof update === "function" ? update(stepMs) : undefined;
      var generatedTerminal = didGenerateTerminal(game, terminalBefore);
      return {
        advanced: updateResult !== false,
        shouldStop: generatedTerminal || (customShouldStop ? !!customShouldStop() : false),
      };
    }

    function advance(durationMs, options) {
      options = options || {};
      var duration = normalizeDurationMs(durationMs, stepMs);
      var steps = Math.max(1, Math.round(duration / stepMs));
      var rewardTicket = beginRewardWindow(game, options.rewardBaseline);
      var executed = 0;
      for (var i = 0; i < steps; i += 1) {
        var stepResult = runOneStep();
        if (stepResult.advanced) executed += 1;
        if (stepResult.shouldStop) break;
      }
      var reward = endRewardWindow(game, rewardTicket);
      if (options.render !== false && typeof render === "function") render();
      return { steps: executed, reward: reward };
    }

    function frame(timestamp) {
      if (!runner.lastFrameMs) runner.lastFrameMs = timestamp;
      var delta = Math.min(maxFrameDeltaMs, Math.max(0, timestamp - runner.lastFrameMs));
      runner.lastFrameMs = timestamp;
      if (isActive()) {
        var rewardTicket = beginRewardWindow(game);
        runner.accumulatorMs += delta;
        while (runner.accumulatorMs >= stepMs) {
          runner.accumulatorMs -= stepMs;
          if (runOneStep().shouldStop) {
            runner.accumulatorMs = 0;
            runner.lastFrameMs = timestamp;
            break;
          }
        }
        endRewardWindow(game, rewardTicket);
      }
      if (typeof render === "function") render();
      requestHandle = window.requestAnimationFrame(frame);
    }

    function start() {
      if (requestHandle || (shouldUseManualRender && shouldUseManualRender())) return requestHandle;
      requestHandle = window.requestAnimationFrame(frame);
      return requestHandle;
    }

    function stop() {
      if (requestHandle) window.cancelAnimationFrame(requestHandle);
      requestHandle = 0;
    }

    var runner = {
      stepMs: stepMs,
      lastFrameMs: 0,
      accumulatorMs: 0,
      start: start,
      stop: stop,
      reset: resetClock,
      resetClock: resetClock,
      advance: advance,
    };
    return runner;
  }

  function metricNumber(value, fallback) {
    if (value === null || value === undefined || value === "") return fallback;
    var numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : fallback;
  }

  function normalizeStatePayload(state, fallbackState, game) {
    var fallback = fallbackState && typeof fallbackState === "object" ? fallbackState : {};
    var source = state && typeof state === "object" ? state : fallback;
    var normalized = Object.assign({}, source);
    var sourceMetrics = source.metrics && typeof source.metrics === "object" ? source.metrics : {};
    var fallbackMetrics = fallback.metrics && typeof fallback.metrics === "object" ? fallback.metrics : {};
    var metrics = Object.assign({}, fallbackMetrics, sourceMetrics);
    var rawPrimaryScore = hasOwn(sourceMetrics, "primary_score") ? sourceMetrics.primary_score : undefined;

    metrics.env_reward_step = metricNumber(metrics.env_reward_step, 0);
    metrics.env_reward_episode = metricNumber(metrics.env_reward_episode, 0);
    metrics.primary_positive_score = metricNumber(metrics.primary_positive_score, 0);
    metrics.primary_penalty_score = metricNumber(metrics.primary_penalty_score, 0);
    metrics.primary_score = metricNumber(
      rawPrimaryScore,
      metrics.primary_positive_score - metrics.primary_penalty_score
    );

    if (metrics.best_primary_score !== undefined || metrics.best_score !== undefined) {
      metrics.best_primary_score = metricNumber(
        metrics.best_primary_score,
        metricNumber(metrics.best_score, metrics.primary_score)
      );
    }
    if (metrics.best_score !== undefined) {
      var bestScoreFallback =
        metrics.best_primary_score === undefined ? metrics.primary_score : metrics.best_primary_score;
      metrics.best_score = metricNumber(metrics.best_score, bestScoreFallback);
    }

    normalized.metrics = metrics;
    if (!normalized.terminal || typeof normalized.terminal !== "object") {
      normalized.terminal = { isTerminal: false, outcome: null, reason: null };
    }
    if (!normalized.game_state || typeof normalized.game_state !== "object") {
      normalized.game_state = {
        score: metrics.primary_score,
        player: null,
        environment: null,
      };
    } else if (normalized.game_state.score === undefined || normalized.game_state.score === null) {
      normalized.game_state = Object.assign({}, normalized.game_state, { score: metrics.primary_score });
    }
    var seedDomains = seedDomainPayload(game);
    var perturbationContract = perturbationContractPayload(game);
    var assetState = game && game.assetEngine && typeof game.assetEngine.getState === "function"
      ? game.assetEngine.getState()
      : null;
    if (seedDomains || perturbationContract || assetState || (game && game.controlResponse)) {
      var gameState = Object.assign({}, normalized.game_state);
      var environment = gameState.environment && typeof gameState.environment === "object"
        ? Object.assign({}, gameState.environment)
        : {};
      if (seedDomains) environment.seed_domains = seedDomains;
      if (perturbationContract) environment.perturbation_contract = perturbationContract;
      if (game && game.controlResponse) environment.control_response = copyPlainValue(game.controlResponse);
      if (assetState) {
        environment.asset_type = assetState.asset_type;
        environment.asset_pack = assetState.asset_pack;
        environment.asset_manifest_version = assetState.asset_manifest_version;
        environment.selected_assets = Object.assign({}, assetState.selected_assets || {});
        if (assetState.error) environment.asset_error = assetState.error;
      }
      gameState.environment = environment;
      normalized.game_state = gameState;
    }
    return normalized;
  }

  function readRenderModeConfig() {
    var params = new URLSearchParams(window.location.search || "");
    var renderMode = String(params.get("render_mode") || params.get("renderMode") || "").trim().toLowerCase();
    var manualRender = params.get("manual_render");
    if (manualRender === null) manualRender = params.get("manualRender");
    return {
      renderMode: renderMode,
      manualRender: manualRender,
    };
  }

  function shouldUseManualRender() {
    var config = readRenderModeConfig();
    if (config.renderMode) {
      if (config.renderMode === "manual" || config.renderMode === "step" || config.renderMode === "training") {
        return true;
      }
      if (config.renderMode === "raf" || config.renderMode === "loop" || config.renderMode === "continuous") {
        return false;
      }
    }
    if (config.manualRender !== null) {
      var manual = normalizeBoolean(config.manualRender, null);
      if (manual !== null) return manual;
    }
    return !!window.__speedControlInstalled;
  }

  function callRuntimeHook(fn, owner) {
    if (typeof fn !== "function") return undefined;
    return fn.call(owner || window);
  }

  function mergeHookResult(inheritedResult, gameResult, fallbackPaused) {
    var result = {};
    if (inheritedResult && typeof inheritedResult === "object") Object.assign(result, inheritedResult);
    if (gameResult && typeof gameResult === "object") Object.assign(result, gameResult);
    if (!hasOwn(result, "ok")) result.ok = true;
    if (!hasOwn(result, "source")) result.source = "game";
    if (!hasOwn(result, "paused")) result.paused = fallbackPaused;
    if (!hasOwn(result, "runtime_paused")) result.runtime_paused = fallbackPaused;
    return result;
  }

  function createRuntime(settings) {
    settings = settings || {};
    var game = settings.game;
    if (!game) throw new Error("GameEngineCore.createRuntime requires a game");

    var gameId = settings.gameId || game.gameId || "gamelet";
    var assetSettings = settings.assets || null;
    var assetEngine = assetSettings && assetSettings.engine;
    var assetRequirements = assetSettings && Array.isArray(assetSettings.requiredAssetIds)
      ? assetSettings.requiredAssetIds.slice()
      : [];
    var fixedAssetPack = assetSettings && assetSettings.packId
      ? String(assetSettings.packId)
      : null;
    if (assetEngine) {
      game.assetEngine = assetEngine;
      game.assetRequirements = assetRequirements.slice();
    }
    var bridgeName = settings.bridgeName || null;
    var inheritedPauseHook = typeof window.__pauseGame === "function" ? window.__pauseGame : null;
    var inheritedResumeHook = typeof window.__resumeGame === "function" ? window.__resumeGame : null;
    var inheritedPauseStateHook = typeof window.__getGamePauseState === "function" ? window.__getGamePauseState : null;
    var inheritedSpeedStateHook = typeof window.__getGameSpeedState === "function" ? window.__getGameSpeedState : null;
    var runtimePausedFallback = false;
    var defaultSeed = settings.defaultSeed || 42;
    var maxDifficulty = settings.maxDifficulty || 5;
    var defaultStepMs = settings.defaultStepMs === undefined ? 200 : Number(settings.defaultStepMs);
    if (!Number.isFinite(defaultStepMs) || defaultStepMs <= 0) defaultStepMs = 200;
    var currentObservationSize = null;
    var capabilities = Object.assign({
      supports_seed: true,
      supports_level_select: false,
      supports_difficulty: true,
      supports_autostart: true,
      supports_rand_init_pos: false,
      supports_visual_perturbations: true,
      supports_inplace_reset: true,
      supports_reload_reset: false,
      supports_pause_detection: true,
      supports_menu_detection: false,
      supports_fullscreen: typeof game.enterFullscreen === "function" && typeof game.exitFullscreen === "function",
      provides_actionable_flag: true,
      provides_gamelet_step_api: true,
    }, settings.capabilities || {});

    function callHook(name, args) {
      if (typeof settings[name] === "function") return settings[name].apply(null, args || []);
      if (game && typeof game[name] === "function") return game[name].apply(game, args || []);
      return undefined;
    }

    function boundAssetPack() {
      if (fixedAssetPack) return fixedAssetPack;
      var current = assetEngine && assetEngine.getState ? assetEngine.getState() : null;
      return current && current.asset_pack ? current.asset_pack : "gym-light-default";
    }

    function assetsReadyFor(packId) {
      if (!assetEngine || typeof assetEngine.getState !== "function") return true;
      var current = assetEngine.getState();
      if (!current || current.status !== "ready" || current.asset_pack !== packId) return false;
      var selected = Object.keys(current.selected_assets || {}).map(function selectedId(role) {
        return current.selected_assets[role];
      });
      return assetRequirements.every(function requiredLoaded(assetId) { return selected.indexOf(assetId) >= 0; });
    }

    function setAssetError(error) {
      var message = error && error.message ? error.message : String(error);
      game.assetError = message;
      game.mode = "error";
      game.paused = true;
      window.__gameGymLoadError = message;
    }

    function clearAssetError() {
      if (!game.assetError) return;
      game.assetError = null;
      window.__gameGymLoadError = null;
    }

    function prepareEpisode() {
      abortNativeInputRuntime();
      if (!assetEngine) return Promise.resolve(null);
      var packId = boundAssetPack();
      if (assetsReadyFor(packId)) {
        clearAssetError();
        return Promise.resolve(assetEngine.getState());
      }
      return assetEngine.preload(packId, assetRequirements).then(function assetPreloadReady(result) {
        clearAssetError();
        return result;
      }).catch(function assetPreloadFailed(error) {
        setAssetError(error);
        throw error;
      });
    }

    function requireAssetsReady() {
      if (!assetEngine) return;
      var current = assetEngine.getState();
      if (!current || current.status !== "ready") {
        throw new Error("Game assets are not ready" + (current && current.error ? ": " + current.error : ""));
      }
    }

    function readState() {
      var state = callHook("getState", []);
      if (state !== undefined) return state;
      if (typeof game.consumeStatePayload === "function") return game.consumeStatePayload();
      if (typeof game.getStatePayload === "function") return game.getStatePayload();
      if (typeof game.getState === "function") return game.getState();
      return null;
    }

    function readObservation() {
      var observation = callHook("getObservation", []);
      if (observation !== undefined) return observation;
      if (typeof game.getObservation === "function") return game.getObservation();
      return null;
    }

    function readInfo(state, normalizedAction, stepOptions, beforeState) {
      var info = callHook("buildStepInfo", [state, stepOptions, normalizedAction, beforeState]);
      if (info === undefined && typeof settings.info === "function") {
        info = settings.info(state, stepOptions, normalizedAction, beforeState);
      }
      if (info === undefined && typeof game.infoPayload === "function") {
        info = terminalAwareInfo(game, state, game.infoPayload());
      }
      if (!info || typeof info !== "object") info = {};
      if (info.durationMs === undefined) info.durationMs = stepOptions.durationMs;
      if (info.source === undefined) info.source = stepOptions.source;
      if (normalizedAction && info.action === undefined) {
        info.action = {
          type: "game_step_action",
          id: normalizedAction.id || "anonymous",
          args: normalizedAction.args || {},
        };
      }
      return info;
    }

    function rewardFromState(state) {
      if (state && state.metrics && Number.isFinite(Number(state.metrics.env_reward_episode))) {
        return Number(state.metrics.env_reward_episode);
      }
      if (Number.isFinite(Number(game.envRewardEpisode))) return Number(game.envRewardEpisode);
      if (Number.isFinite(Number(game.env_reward_episode))) return Number(game.env_reward_episode);
      return 0;
    }

    function normalizeStepOptions(action, options) {
      var opts = typeof options === "number" ? { durationMs: options } : (options || {});
      var duration = firstFiniteNumber(
        opts.durationMs,
        opts.duration_ms
      );
      if (duration === null || duration <= 0) duration = defaultStepMs;
      var observationSize = opts.observationSize;
      if (observationSize != null && (!Array.isArray(observationSize) || observationSize.length !== 2
          || !observationSize.every(function validSize(value) { return Number.isInteger(value) && value > 0; }))) {
        throw new Error("observationSize must contain positive integer width and height");
      }
      return {
        durationMs: duration,
        source: opts.source || "agent",
        render: opts.render !== false,
        persistent: !!opts.persistent,
        observationSize: observationSize == null ? null : observationSize.slice(),
      };
    }

    function normalizeAction(action, stepOptions) {
      var normalized = callHook("normalizeAction", [action || {}, stepOptions]);
      if (normalized !== undefined) return normalized;
      var id = "";
      if (action && typeof action === "object" && action.id !== undefined && action.id !== null) {
        id = String(action.id).trim();
      } else if (typeof action === "string") {
        id = action.trim();
      }
      return { id: id || "anonymous", rawAction: action || {} };
    }

    function applyAction(normalizedAction, context) {
      var result = callHook("applyAction", [normalizedAction, context]);
      return result === undefined ? null : result;
    }

    function advanceSimulation(durationMs, context) {
      var state = callHook("advanceSimulation", [durationMs, context]);
      if (state !== undefined) return state;
      if (typeof game.advanceTime === "function") return game.advanceTime(durationMs, false);
      return readState();
    }

    function render() {
      if (typeof settings.render === "function") return settings.render();
      if (typeof game.render === "function") return game.render();
      return undefined;
    }

    function startEpisode(options, methodName, fallbackMethod) {
      var result;
      if (typeof settings[methodName] === "function") {
        result = settings[methodName](options || {});
      } else if (typeof game[methodName + "FromAPI"] === "function") {
        result = game[methodName + "FromAPI"](options || {});
      } else if (typeof game[fallbackMethod] === "function") {
        result = game[fallbackMethod](options || {});
      } else if (typeof game.beginEpisode === "function") {
        result = game.beginEpisode(options || {}, methodName === "reset");
      } else {
        result = { accepted: options || {}, applied: {}, notes: [methodName + "_unavailable"] };
      }
      result = result || { accepted: options || {}, applied: {}, notes: [] };
      var seedDomains = seedDomainPayload(game);
      if (seedDomains) result.applied = Object.assign({}, result.applied || {}, seedDomains);
      var perturbationContract = perturbationContractPayload(game);
      if (perturbationContract) {
        result.applied = Object.assign({}, result.applied || {}, {
          perturbation_contract: perturbationContract,
        });
      }
      if (assetEngine) {
        result.applied = Object.assign({}, result.applied || {}, {
          assets: assetEngine.getState(),
        });
      }
      return result;
    }

    function normalizeCaptureFormat(value) {
      var format = String(value || "png").trim().toLowerCase();
      if (format === "jpg") format = "jpeg";
      if (format !== "png" && format !== "jpeg" && format !== "webp") format = "png";
      return format;
    }

    function captureMimeType(format) {
      return format === "jpeg" ? "image/jpeg" : "image/" + format;
    }

    function normalizeCaptureQuality(value) {
      var quality = Number(value);
      if (!Number.isFinite(quality) || quality <= 0) quality = 85;
      if (quality > 1) quality /= 100;
      if (quality < 0.01) quality = 0.01;
      if (quality > 1) quality = 1;
      return quality;
    }

    function normalizeCaptureMaxHeight(options) {
      var raw = options && (options.maxHeight || options.max_height || options.captureMaxHeight || options.capture_max_height);
      var maxHeight = Number(raw);
      if (!Number.isFinite(maxHeight) || maxHeight <= 0) return null;
      return Math.max(1, Math.round(maxHeight));
    }

    function findCaptureCanvas() {
      if (typeof settings.getCaptureCanvas === "function") {
        var settingsCanvas = settings.getCaptureCanvas(game);
        if (settingsCanvas && typeof settingsCanvas.toDataURL === "function") return settingsCanvas;
      }
      if (settings.renderer && typeof settings.renderer.getCaptureCanvas === "function") {
        var rendererCanvas = settings.renderer.getCaptureCanvas(game);
        if (rendererCanvas && typeof rendererCanvas.toDataURL === "function") return rendererCanvas;
      }
      if (typeof game.getCaptureCanvas === "function") {
        var gameCanvas = game.getCaptureCanvas();
        if (gameCanvas && typeof gameCanvas.toDataURL === "function") return gameCanvas;
      }
      if (game.canvas && typeof game.canvas.toDataURL === "function") return game.canvas;
      var displayCanvas = document.getElementById("display");
      if (displayCanvas && typeof displayCanvas.toDataURL === "function") return displayCanvas;
      return document.querySelector && document.querySelector("canvas");
    }

    function getVisibleGameGeometry() {
      var canvas = findCaptureCanvas();
      if (!canvas || typeof canvas.getBoundingClientRect !== "function") {
        throw new Error("visible game geometry requires the observation capture canvas");
      }
      var rect = canvas.getBoundingClientRect();
      var left = Number(rect.left);
      var top = Number(rect.top);
      var width = Number(rect.width);
      var height = Number(rect.height);
      if (![left, top, width, height].every(Number.isFinite) || width <= 0 || height <= 0) {
        throw new Error("observation capture canvas has invalid visible game geometry");
      }
      return {
        protocol: VISIBLE_GAME_GEOMETRY_PROTOCOL,
        units: "css_pixels",
        left: left,
        top: top,
        width: width,
        height: height,
        backing_width: Math.max(1, Math.round(Number(canvas.width) || width)),
        backing_height: Math.max(1, Math.round(Number(canvas.height) || height)),
      };
    }

    function scaledCaptureCanvas(sourceCanvas, maxHeight) {
      var sourceWidth = Math.max(1, Math.round(Number(sourceCanvas.width) || sourceCanvas.clientWidth || 1));
      var sourceHeight = Math.max(1, Math.round(Number(sourceCanvas.height) || sourceCanvas.clientHeight || 1));
      if (!maxHeight || sourceHeight <= maxHeight) {
        return { canvas: sourceCanvas, width: sourceWidth, height: sourceHeight, scaled: false };
      }
      var scale = maxHeight / sourceHeight;
      var width = Math.min(sourceWidth, Math.max(2, 2 * Math.round((sourceWidth * scale) / 2)));
      var height = maxHeight;
      var output = document.createElement("canvas");
      output.width = width;
      output.height = height;
      var ctx = output.getContext("2d");
      ctx.drawImage(sourceCanvas, 0, 0, sourceWidth, sourceHeight, 0, 0, width, height);
      return { canvas: output, width: width, height: height, scaled: true };
    }

    function dataUrlPayload(dataUrl) {
      var comma = String(dataUrl || "").indexOf(",");
      return comma >= 0 ? String(dataUrl).slice(comma + 1) : "";
    }

    function encodeCaptureCanvas(canvas, mimeType, quality) {
      return new Promise(function encodeCapturePromise(resolve, reject) {
        function resolveDataUrl(dataUrl, method) {
          if (!dataUrl) {
            reject(new Error("canvas capture returned empty data"));
            return;
          }
          resolve({ data: dataUrlPayload(dataUrl), method: method });
        }
        function fallbackDataUrl() {
          try {
            resolveDataUrl(canvas.toDataURL(mimeType, quality), "toDataURL");
          } catch (error) {
            reject(error);
          }
        }
        if (typeof canvas.toBlob !== "function") {
          fallbackDataUrl();
          return;
        }
        try {
          canvas.toBlob(function onCaptureBlob(blob) {
            if (!blob) {
              fallbackDataUrl();
              return;
            }
            var reader = new FileReader();
            reader.onloadend = function onCaptureLoad() { resolveDataUrl(String(reader.result || ""), "toBlob"); };
            reader.onerror = function onCaptureError() { reject(reader.error || new Error("canvas capture reader failed")); };
            reader.readAsDataURL(blob);
          }, mimeType, quality);
        } catch (error) {
          reject(error);
        }
      });
    }

    function captureFrame(options) {
      options = options || {};
      var canvas = findCaptureCanvas();
      if (!canvas || typeof canvas.toDataURL !== "function") {
        return Promise.resolve({ ok: false, error: "capture canvas unavailable" });
      }
      render();
      var format = normalizeCaptureFormat(options.format || options.imageFormat || options.image_format);
      var mimeType = captureMimeType(format);
      var quality = normalizeCaptureQuality(options.quality);
      var maxHeight = normalizeCaptureMaxHeight(options);
      var output = scaledCaptureCanvas(canvas, maxHeight);
      return encodeCaptureCanvas(output.canvas, mimeType, quality).then(function onEncoded(encoded) {
        return {
          ok: true,
          data: encoded.data,
          mimeType: mimeType,
          format: format,
          width: output.width,
          height: output.height,
          scaled: output.scaled,
          method: encoded.method,
          source: "canvas",
        };
      }, function onEncodeError(error) {
        return {
          ok: false,
          error: error && error.message ? error.message : String(error),
          errorType: error && error.name ? error.name : "Error",
          source: "canvas",
        };
      });
    }

    function pauseRuntime() {
      var inheritedResult = callRuntimeHook(inheritedPauseHook, window);
      var gamePause = typeof game.pause === "function" ? game.pause : null;
      var gameResult = gamePause && gamePause !== inheritedPauseHook ? callRuntimeHook(gamePause, game) : undefined;
      runtimePausedFallback = true;
      if (game.infoPanel) game.infoPanel.update();
      return mergeHookResult(inheritedResult, gameResult, true);
    }

    function resumeRuntime() {
      var inheritedResult = callRuntimeHook(inheritedResumeHook, window);
      var gameResume = typeof game.resume === "function" ? game.resume : null;
      var gameResult = gameResume && gameResume !== inheritedResumeHook ? callRuntimeHook(gameResume, game) : undefined;
      runtimePausedFallback = false;
      if (game.infoPanel) game.infoPanel.update();
      return mergeHookResult(inheritedResult, gameResult, false);
    }

    function readPausedFallback() {
      if (typeof game.paused === "boolean") return game.paused;
      if (typeof game.runtimePaused === "boolean") return game.runtimePaused;
      return runtimePausedFallback;
    }

    function getPauseStateRuntime() {
      var inheritedState = callRuntimeHook(inheritedPauseStateHook, window);
      var gameState = typeof game.getPauseState === "function" ? game.getPauseState() : undefined;
      return mergeHookResult(inheritedState, gameState, readPausedFallback());
    }

    function getGameSpeedStateRuntime() {
      var inheritedState = callRuntimeHook(inheritedSpeedStateHook, window);
      var gameState = typeof game.getGameSpeedState === "function" ? game.getGameSpeedState() : undefined;
      var inheritedPaused = Boolean(inheritedState && inheritedState.isPaused);
      var gamePaused = Boolean(gameState && gameState.isPaused);
      var result = {};
      if (inheritedState && typeof inheritedState === "object") Object.assign(result, inheritedState);
      if (gameState && typeof gameState === "object") Object.assign(result, gameState);
      result.isPaused = inheritedPaused || gamePaused || readPausedFallback();
      return result;
    }

    function beginNativeInputRuntime() {
      requireAssetsReady();
      if (game.__rewardWindow && game.__rewardWindow.open) {
        throw new Error("A native input reward window is already open");
      }
      var beforeState = readState();
      var ticket = beginRewardWindow(game, rewardFromState(beforeState));
      // Keep the pending input with the ledger so any episode reset discards it.
      game.__rewardWindow.nativeInput = { beforeState: beforeState, ticket: ticket };
      return { ok: true };
    }

    function abortNativeInputRuntime() {
      var pending = game.__rewardWindow && game.__rewardWindow.nativeInput;
      if (pending) {
        endRewardWindow(game, pending.ticket);
        resetStepReward(game);
      }
      return { ok: true };
    }

    var runtime = {
      capabilities: capabilities,
      normalizeStepOptions: normalizeStepOptions,
      normalizeAction: normalizeAction,
      applyAction: applyAction,
      advanceSimulation: advanceSimulation,
      render: render,
      getState: function getState() {
        return normalizeStatePayload(readState(), null, game);
      },
      getObservation: readObservation,
      beginNativeInput: beginNativeInputRuntime,
      abortNativeInput: abortNativeInputRuntime,
      step: function step(action, options) {
        var pending = game.__rewardWindow && game.__rewardWindow.nativeInput;
        if (pending) delete game.__rewardWindow.nativeInput;
        var rewardTicket = pending && pending.ticket;
        var beforeState, beforeReward, stepOptions, normalizedAction, state;
        try {
          requireAssetsReady();
          beforeState = pending ? pending.beforeState : readState();
          beforeReward = pending ? pending.ticket.baseline : rewardFromState(beforeState);
          stepOptions = normalizeStepOptions(action || {}, options || {});
          currentObservationSize = stepOptions.observationSize;
          normalizedAction = normalizeAction(action || {}, stepOptions);
          var context = {
            game: game,
            action: action || {},
            normalizedAction: normalizedAction,
            stepOptions: stepOptions,
            beforeState: beforeState,
          };
          if (!rewardTicket) rewardTicket = beginRewardWindow(game, beforeReward);
          applyAction(normalizedAction, context);
          state = advanceSimulation(stepOptions.durationMs, context);
        } finally {
          currentObservationSize = null;
          if (rewardTicket) endRewardWindow(game, rewardTicket);
        }
        if (stepOptions.render) render();
        if (!state) state = readState();
        state = normalizeStatePayload(state, null, game);
        var reward = rewardFromState(state) - beforeReward;
        if (state && state.metrics) state.metrics.env_reward_step = reward;
        var done = Boolean(state && state.terminal && state.terminal.isTerminal);
        return {
          state: state,
          observation: readObservation(),
          reward: reward,
          done: done,
          info: readInfo(state, normalizedAction, stepOptions, beforeState),
        };
      },
      reset: async function reset(options) {
        await prepareEpisode();
        if (typeof game.resetGym === "function") return game.resetGym(options || {});
        startEpisode(options || {}, "reset", "reset");
        return { observation: readObservation(), reward: 0, done: false, info: readInfo(readState(), null, { durationMs: 0, source: "reset" }, null) };
      },
      init: async function init(options) {
        await prepareEpisode();
        return startEpisode(options || {}, "init", "init");
      },
      advanceTime: function runtimeAdvanceTime(ms) {
        requireAssetsReady();
        var duration = Number(ms);
        if (!Number.isFinite(duration) || duration <= 0) duration = defaultStepMs;
        var context = { game: game, action: null, normalizedAction: null, stepOptions: { durationMs: duration, source: "advanceTime", render: true } };
        var state = advanceSimulation(duration, context);
        render();
        return normalizeStatePayload(state || readState(), null, game);
      },
      renderGameToText: function runtimeRenderGameToText() {
        if (typeof settings.renderGameToText === "function") return settings.renderGameToText();
        if (typeof game.renderGameToText === "function") return game.renderGameToText();
        return JSON.stringify(readState());
      },
      getVisibleGameGeometry: getVisibleGameGeometry,
      getObservationSize: function getObservationSize() {
        if (!currentObservationSize) throw new Error("camera relative input requires this step's observationSize");
        return currentObservationSize.slice();
      },
      captureFrame: captureFrame,
    };

    runtime.gameGymAPI = {
      version: PLAYER1_RUNTIME_API_VERSION,
      reset: function reset(options) { return runtime.reset(options || {}); },
      beginNativeInput: runtime.beginNativeInput,
      abortNativeInput: runtime.abortNativeInput,
      step: function step(action, options) { return runtime.step(action || {}, options || {}); },
      getState: runtime.getState,
      getObservation: runtime.getObservation,
      advanceTime: runtime.advanceTime,
      getVisibleGameGeometry: runtime.getVisibleGameGeometry,
      captureFrame: runtime.captureFrame,
    };

    runtime.gameAPI = {
      version: PLAYER1_RUNTIME_API_VERSION,
      capabilities: capabilities,
      init: async function init(config) {
        var result = await runtime.init(config || {});
        return {
          ok: true,
          accepted: result && result.accepted ? result.accepted : (config || {}),
          applied: result && result.applied ? result.applied : {},
          notes: result && Array.isArray(result.notes) ? result.notes : [],
        };
      },
      reset: async function reset(options) {
        await prepareEpisode();
        var result = startEpisode(options || {}, "reset", "reset");
        return {
          ok: true,
          method: "inplace_reset",
          accepted: result && result.accepted ? result.accepted : (options || {}),
          applied: result && result.applied ? result.applied : {},
          notes: result && Array.isArray(result.notes) ? result.notes : [],
        };
      },
      getState: runtime.getState,
      getVisibleGameGeometry: runtime.getVisibleGameGeometry,
      pause: async function pause() {
        if (!inheritedPauseHook && typeof game.pause !== "function") {
          return { ok: false, source: "game", paused: false, runtime_paused: false };
        }
        return pauseRuntime();
      },
      resume: async function resume() {
        if (!inheritedResumeHook && typeof game.resume !== "function") {
          return { ok: false, source: "game", paused: false, runtime_paused: false };
        }
        return resumeRuntime();
      },
    };

    if (settings.presentation) {
      game.infoPanel = window.GameShell.create(game, settings.presentation);
    }
    if (settings.renderer && typeof settings.renderer.attachRuntime === "function") {
      settings.renderer.attachRuntime(runtime, game);
    }
    if (game.infoPanel) game.infoPanel.update();
    window.gameGymAPI = runtime.gameGymAPI;
    window.gameAPI = runtime.gameAPI;
    window.advanceTime = runtime.advanceTime;
    window.__advanceGameTime = runtime.advanceTime;
    window.render_game_to_text = runtime.renderGameToText;
    if (bridgeName) {
      window[bridgeName] = {
        init: runtime.init,
        reset: async function reset(options) {
          await prepareEpisode();
          return startEpisode(options || {}, "reset", "reset");
        },
        getState: runtime.getState,
        pause: runtime.gameAPI.pause,
        resume: runtime.gameAPI.resume,
      };
    }
    var hasGamePauseControl = typeof game.pause === "function" || typeof game.resume === "function";
    var hasPauseStateHook =
      inheritedPauseStateHook ||
      inheritedPauseHook ||
      inheritedResumeHook ||
      typeof game.getPauseState === "function" ||
      hasGamePauseControl;
    var hasSpeedStateHook =
      inheritedSpeedStateHook ||
      typeof game.getGameSpeedState === "function" ||
      hasGamePauseControl;
    if (inheritedPauseHook || typeof game.pause === "function") window.__pauseGame = pauseRuntime;
    if (inheritedResumeHook || typeof game.resume === "function") window.__resumeGame = resumeRuntime;
    if (hasPauseStateHook) window.__getGamePauseState = getPauseStateRuntime;
    if (hasSpeedStateHook) window.__getGameSpeedState = getGameSpeedStateRuntime;

    game.__gameletRuntime = runtime;
    return runtime;
  }

  var randomSeedFallbackCounter = 0;

  function createRandomSeed(previousSeed) {
    var seed;
    var cryptoObject = window.crypto || window.msCrypto;
    if (cryptoObject && typeof cryptoObject.getRandomValues === "function" && typeof Uint32Array !== "undefined") {
      try {
        var values = new Uint32Array(1);
        cryptoObject.getRandomValues(values);
        seed = values[0] >>> 0;
      } catch (_error) {
        seed = undefined;
      }
    }
    if (seed === undefined) {
      randomSeedFallbackCounter = (randomSeedFallbackCounter + 1) >>> 0;
      seed = ((Date.now() >>> 0) + randomSeedFallbackCounter) >>> 0;
    }
    var previous = Number(previousSeed);
    if (Number.isFinite(previous) && seed === (previous >>> 0)) {
      seed = (seed + 1) >>> 0;
    }
    return seed;
  }

  function randomizePerturbedEpisode(options, game, selectedDomain) {
    var domains = resolveSeedDomains(options, game.seed);
    if (selectedDomain === "all") options.seed = createRandomSeed(domains.seed);
    SEED_DOMAIN_NAMES.forEach(function enablePerturbedDomain(domain) {
      if (selectedDomain !== "all" && selectedDomain !== domain) return;
      var seedNames = domainConfigNames(domain, "Seed");
      var profileNames = domainConfigNames(domain, "Profile");
      options[seedNames.camel] = createRandomSeed(domains[seedNames.camel]);
      options[seedNames.provided] = true;
      options[profileNames.camel] = "perturbed";
      options[profileNames.provided] = true;
    });
    if (selectedDomain === "all" || selectedDomain === "control") {
      options.control_response_seed = createRandomSeed(game.controlResponse && game.controlResponse.seed);
      options.control_response_profile = "perturbed";
    }
  }

  function resetKeyAction(event) {
    if (!event || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.isComposing) return null;
    var target = event.target;
    if (target && (target.isContentEditable
        || (typeof target.closest === "function" && target.closest("input, textarea, select")))) return null;
    var key = event && event.key;
    var code = event && event.code;
    if (key === "-" || code === "Minus") return "appearance";
    if (key === "=" || code === "Equal") return "camera";
    if (key === "[" || code === "BracketLeft") return "scene";
    if (key === "]" || code === "BracketRight") return "control";
    if (key === "\\" || code === "Backslash") return "all";
    if (key === "," || code === "Comma") return "current";
    return null;
  }

  function isResetKey(event) {
    return resetKeyAction(event) !== null;
  }

  function bindHiddenResetKeys(game, target) {
    if (!game || game.__hiddenResetKeysBound) return;
    var eventTarget = target || document;
    if (!eventTarget || typeof eventTarget.addEventListener !== "function") return;
    game.__hiddenResetKeysBound = true;
    eventTarget.addEventListener("keydown", function onHiddenResetKey(event) {
      var action = resetKeyAction(event);
      if (!action) return;
      if (event.preventDefault) event.preventDefault();
      if (event.stopPropagation) event.stopPropagation();
      if (event.repeat) return;
      var options = cloneEpisodeConfig(game.currentConfig || game.urlConfig || {});
      if (action !== "current") {
        randomizePerturbedEpisode(options, game, action);
      }
      if (typeof game.resetFromAPI === "function") {
        game.resetFromAPI(options);
      } else if (typeof game.resetGym === "function") {
        game.resetGym(options);
      } else if (typeof game.beginEpisode === "function") {
        game.beginEpisode(options, true);
      }
    }, true);
  }

  function bootGame(start) {
    if (typeof start !== "function") throw new Error("Core.lifecycle.boot requires a start function");
    function reportStartError(error) {
      window.__gameGymLoadError = error && (error.stack || error.message) || String(error);
      throw error;
    }
    try {
      return Promise.resolve(start()).catch(reportStartError);
    } catch (error) {
      return reportStartError(error);
    }
  }

  window.GameEngineCore = Object.freeze({
    version: PLAYER1_RUNTIME_API_VERSION,
    controlResponse: Object.freeze({ ranges: CONTROL_RESPONSE_RANGES }),
    config: Object.freeze({
      difficultyLevel: difficultyLevel,
      normalizeBoolean: normalizeBoolean,
      normalizeOptions: normalizeApiOptions,
      readUrl: readUrlConfig,
      mergeEpisode: mergeEpisodeConfig,
      cloneEpisode: cloneEpisodeConfig,
    }),
    seeds: Object.freeze({
      names: SEED_DOMAIN_NAMES,
      STREAMS: PERTURBATION_STREAMS,
      resolve: resolveSeedDomains,
      configure: configureGameSeedDomains,
      createStreams: createSeedStreams,
      forDomain: seedDomainFor,
      payload: seedDomainPayload,
    }),
    domains: Object.freeze({
      modes: Object.freeze({
        legacy: DOMAIN_MODE_LEGACY,
        isolated: DOMAIN_MODE_ISOLATED,
      }),
      beginEpisode: beginDomainEpisode,
      mode: domainModeForTarget,
      isLegacy: isLegacyDomainEpisode,
      isIsolated: isIsolatedDomainEpisode,
      isActive: isDomainActive,
      profile: domainProfileForTarget,
      baselineRng: baselineGameplayRng,
      gameplayRng: domainGameplayRng,
      createEntityRng: domainEntityRng,
      sample: perturbationSample,
    }),
    perturbations: Object.freeze({
      profileNames: PERTURBATION_PROFILE_NAMES,
      profiles: PERTURBATION_PROFILE_RANGES,
      streams: PERTURBATION_STREAMS,
      defineContract: definePerturbationContract,
      cameraOrientationSampler: cameraOrientationSampler,
      templateSampler: templatePerturbationSampler,
      templateValidator: templatePerturbationValidator,
      normalizeAssetVariations: normalizeAssetVariations,
      resolveAssetVariations: resolveAssetVariations,
      expandAssetRequirements: expandAssetRequirements,
      resolveEpisode: resolvePerturbationEpisode,
      payload: perturbationContractPayload,
      supports: perturbationStreamSupported,
      validate: validatePerturbationStream,
      transformColor: transformColor,
      activeDomains: activePerturbationDomains,
      isActive: perturbationIsActive,
      label: perturbationLabel,
      visualPayload: perturbationVisualPayload,
    }),
    visuals: Object.freeze({
      cloneFlags: cloneVisualFlags,
      colorSample: immediateColorSample,
      label: visualLabel,
      buildPayload: buildVisualPayload,
      state: visualState,
      applyLayout: applyStandardVisuals,
    }),
    actions: Object.freeze({
      readId: readStepActionId,
      readNumber: readStepActionNumber,
      readButton: readStepActionButton,
      readMouseMode: readStepActionMouseMode,
      readMouseNumber: readStepActionMouseNumber,
      hasMouseButton: stepActionHasMouseButton,
      hasMouseClick: function hasMouseClick(action, button) {
        return stepActionHasMouseButtonInField(action, "mouse_click", button);
      },
      hasMouseHold: function hasMouseHold(action, button) {
        return stepActionHasMouseButtonInField(action, "mouse_hold", button);
      },
      hasKey: stepActionHasKey,
      createButtonLifecycle: createButtonLifecycle,
    }),
    reward: Object.freeze({
      resetEpisode: resetRewardLedger,
      resetStep: resetStepReward,
      add: addEnvReward,
    }),
    terminal: Object.freeze({
      generation: getTerminalGeneration,
      generatedSince: didGenerateTerminal,
      initialize: initTerminalLatch,
      clear: clearTerminalLatch,
      capture: captureTerminalLatch,
      consume: consumeTerminalLatch,
      autoReset: autoResetAfterTerminal,
      withInfo: terminalAwareInfo,
    }),
    lifecycle: Object.freeze({
      resetEpisode: resetEpisodeRuntime,
      pause: pauseEpisodeRuntime,
      resume: resumeEpisodeRuntime,
      bindResetKeys: bindHiddenResetKeys,
      isResetKey: isResetKey,
      boot: bootGame,
    }),
    rendering: Object.freeze({
      shouldUseManual: shouldUseManualRender,
    }),
    createFixedStepRunner: createFixedStepRunner,
    createRuntime: createRuntime,
  });
})();
