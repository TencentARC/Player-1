(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var constants = Object.freeze({ coinReward: 1, coinMissPenalty: 0 });

  function computePrimaryPositiveScore(metrics) {
    return U.metrics.readNumber(metrics, ["coinsCollected", "coins_collected"], 0);
  }

  function computePrimaryPenaltyScore(metrics) {
    return U.metrics.readNumber(metrics, ["coinsMissed", "coins_missed"], 0) * constants.coinMissPenalty;
  }

  function computePrimaryScore(metrics) {
    return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
  }

  window.Base2DDriveLaneCollectRewardConfig = Object.freeze({
    version: 2,
    gameId: "base_2d_drive_lane_collect",
    constants: constants,
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: computePrimaryScore,
  });
})();
