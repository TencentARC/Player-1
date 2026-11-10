(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var constants = Object.freeze({ hitReward: 1, damagePenalty: 0, deathPenalty: 0 });

  function computePrimaryPositiveScore(metrics) {
    return U.metrics.readNumber(metrics, "kills", 0);
  }

  function computePrimaryPenaltyScore(metrics) {
    return U.metrics.readNumber(metrics, ["damageTaken", "damage_taken"], 0) * constants.damagePenalty
      + U.metrics.readNumber(metrics, "deaths", 0) * constants.deathPenalty;
  }

  function computePrimaryScore(metrics) {
    return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
  }

  window.Base2DAimArenaRewardConfig = Object.freeze({
    version: 2,
    gameId: "base_2d_aim_arena",
    constants: constants,
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: computePrimaryScore,
  });
})();
