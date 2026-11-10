(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var constants = Object.freeze({ coinReward: 1, obstaclePenalty: 0 });

  function computePrimaryPositiveScore(metrics) {
    return U.metrics.readNumber(metrics, ["coinsCollected", "coins_collected"], 0);
  }

  function computePrimaryPenaltyScore(metrics) {
    return U.metrics.readNumber(metrics, "collisions", 0) * constants.obstaclePenalty;
  }

  function computePrimaryScore(metrics) {
    return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
  }

  window.Base2DArcadePlanarRewardConfig = Object.freeze({
    version: 2,
    gameId: "base_2d_arcade_planar",
    constants: constants,
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: computePrimaryScore,
  });
})();
