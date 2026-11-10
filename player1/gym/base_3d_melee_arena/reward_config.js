(function () {
  "use strict";

  function finiteCount(value) {
    var number = Number(value);
    return Number.isFinite(number) ? Math.max(0, number) : 0;
  }

  function computePrimaryPositiveScore(metrics) {
    var constants = window.Base3DMeleeArenaRewardConfig.constants;
    return finiteCount(metrics && metrics.attack_hits) * constants.hitReward
      + finiteCount(metrics && metrics.kills) * constants.killReward;
  }

  function computePrimaryPenaltyScore(metrics) {
    var constants = window.Base3DMeleeArenaRewardConfig.constants;
    return finiteCount(metrics && metrics.damage_taken) * constants.hitPenalty;
  }

  function computePrimaryScore(metrics) {
    return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
  }

  window.Base3DMeleeArenaRewardConfig = Object.freeze({
    version: 1,
    gameId: "base_3d_melee_arena",
    constants: Object.freeze({
      hitReward: 1,
      killReward: 1,
      hitPenalty: 0.5,
    }),
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: computePrimaryScore,
  });
})();
