(function () {
  "use strict";

  function computePrimaryPositiveScore(metrics) {
    return Number(metrics && metrics.targets_reached) || 0;
  }

  function computePrimaryPenaltyScore(metrics) {
    return (Number(metrics && metrics.collisions) || 0)
      * window.Base3DNavigateChaseRewardConfig.constants.collisionPenalty;
  }

  window.Base3DNavigateChaseRewardConfig = {
    version: 1,
    gameId: "base_3d_navigate_chase",
    constants: {
      progressRewardScale: 0,
      progressRewardCap: 0,
      targetReward: 1,
      collisionPenalty: 0,
    },
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: function computePrimaryScore(metrics) {
      return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
    },
  };
})();
