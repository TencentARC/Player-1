(function () {
  "use strict";

  function readMetric(metrics, name) {
    var value = Number(metrics && metrics[name]);
    return Number.isFinite(value) ? value : 0;
  }

  function penaltyMagnitude(value) {
    var numeric = Number(value);
    return Number.isFinite(numeric) ? Math.max(0, numeric) : 0;
  }

  function computePrimaryPositiveScore(metrics) {
    return readMetric(metrics, "checkpoints_passed");
  }

  function computePrimaryPenaltyScore(metrics) {
    var constants = ((window.Base3DDriveRewardConfig || {}).constants || {});
    return Math.max(
      readMetric(metrics, "collisions"),
      readMetric(metrics, "off_road_hits"),
      readMetric(metrics, "out_of_bounds"),
    ) * penaltyMagnitude(constants.roadCollisionPenalty);
  }

  window.Base3DDriveRewardConfig = {
    version: 1,
    gameId: "base_3d_drive",
    constants: {
      checkpointReward: 1,
      roadCollisionPenalty: 0,
    },
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: function computePrimaryScore(metrics) {
      return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
    },
  };
})();
