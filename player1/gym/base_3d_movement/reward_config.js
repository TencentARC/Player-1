(function () {
  "use strict";

  function finiteNumber(value, fallback) {
    var number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function computePrimaryPositiveScore(metrics) {
    return finiteNumber(metrics && metrics.goals_reached, 0)
      * window.Base3DMovementRewardConfig.constants.goalReward;
  }

  function computePrimaryPenaltyScore(metrics) {
    return finiteNumber(metrics && metrics.collisions, 0)
      * window.Base3DMovementRewardConfig.constants.collisionPenalty;
  }

  function computePrimaryScore(metrics) {
    return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
  }

  window.Base3DMovementRewardConfig = {
    version: 2,
    gameId: "base_3d_movement",
    constants: {
      goalReward: 1,
      collisionPenalty: 0,
    },
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: computePrimaryScore,
  };
})();
