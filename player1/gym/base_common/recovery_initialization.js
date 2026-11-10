(function recoveryInitializationModule() {
  "use strict";

  // A separate episode-variant stream: never draw from a game's domain RNGs.
  // The fixed "reco" salt separates this stream from the published Scene stream.
  // Single-domain resets retain these master-seed-dependent initial samples.
  function create(masterSeed, kind) {
    var seed = (window.GameEngineCore.seeds.forDomain({ seed: masterSeed }, "scene") ^ 0x7265636f) >>> 0;
    var rng = new window.BaseGameletCommon.Rng(seed, 42, { allowZeroSeed: true });
    return {
      rng: rng,
      state: {
        kind: kind,
        sampler_seed: seed,
      },
    };
  }

  function centeredNormal(rng, standardDeviation, limit) {
    var value;
    do {
      value = Math.sqrt(-2 * Math.log(1 - rng.next()))
        * Math.cos(2 * Math.PI * rng.next()) * standardDeviation;
    } while (Math.abs(value) > limit);
    return value;
  }

  window.PlayerOneRecoveryInitialization = Object.freeze({ create: create, centeredNormal: centeredNormal });
})();
