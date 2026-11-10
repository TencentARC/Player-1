(function () {
  "use strict";

  function finiteCount(value) {
    var number = Number(value);
    return Number.isFinite(number) ? Math.max(0, number) : 0;
  }

  function computePrimaryPositiveScore(metrics) {
    return finiteCount(metrics && metrics.kills) * window.Base3DCombatArenaRewardConfig.constants.killReward;
  }

  function computePrimaryPenaltyScore(metrics) {
    var constants = window.Base3DCombatArenaRewardConfig.constants;
    return finiteCount(metrics && metrics.damage_taken) * constants.hitPenalty
      + finiteCount(metrics && metrics.deaths) * constants.deathPenalty;
  }

  function computePrimaryScore(metrics) {
    return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
  }

  window.Base3DCombatArenaRewardConfig = Object.freeze({
    version: 1,
    gameId: "base_3d_combat_arena",
    constants: Object.freeze({
      killReward: 1,
      hitPenalty: 0,
      deathPenalty: 0,
    }),
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: computePrimaryScore,
  });
})();
