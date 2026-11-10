(function () {
  "use strict";

  function computePrimaryPositiveScore(metrics) {
    return Number(metrics && metrics.hits) || 0;
  }

  function computePrimaryPenaltyScore(metrics) {
    return (Number(metrics && metrics.misses) || 0) * window.Base3DAimRewardConfig.constants.missPenalty;
  }

  function computePrimaryScore(metrics) {
    return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
  }

  window.Base3DAimRewardConfig = {
    version: 1,
    gameId: "base_3d_aim",
    constants: {
      hitReward: 1,
      missPenalty: 0,
    },
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: computePrimaryScore,
  };
})();
