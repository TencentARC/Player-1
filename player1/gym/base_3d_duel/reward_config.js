(function () {
  "use strict";

  function finiteCount(value) {
    var number = Number(value);
    return Number.isFinite(number) ? Math.max(0, number) : 0;
  }

  function computePrimaryPositiveScore(metrics) {
    var constants = window.Base3DDuelRewardConfig.constants;
    return finiteCount(metrics && metrics.spear_hits) * constants.hitReward;
  }

  function computePrimaryPenaltyScore(metrics) {
    var constants = window.Base3DDuelRewardConfig.constants;
    return finiteCount(metrics && metrics.damage_taken) * constants.hitPenalty;
  }

  function computePrimaryScore(metrics) {
    return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
  }

  window.Base3DDuelRewardConfig = Object.freeze({
    version: 1,
    gameId: "base_3d_duel",
    constants: Object.freeze({
      hitReward: 1,
      hitPenalty: 0.5,
    }),
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: computePrimaryScore,
  });
})();
