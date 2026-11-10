(function () {
  "use strict";

  function toNumber(value, fallback) {
    var numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : fallback;
  }

  function computePrimaryPositiveScore(metrics) {
    return toNumber(metrics && metrics.coins_collected, 0);
  }

  function computePrimaryPenaltyScore(metrics) {
    return toNumber(metrics && metrics.coins_missed, 0)
      * window.Base3DDriveLaneRewardConfig.constants.missedCoinPenalty;
  }

  function computePrimaryScore(metrics) {
    return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
  }

  window.Base3DDriveLaneRewardConfig = Object.freeze({
    version: 1,
    gameId: "base_3d_drive_lane",
    constants: Object.freeze({ coinReward: 1, missedCoinPenalty: 0 }),
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: computePrimaryScore,
  });
})();
