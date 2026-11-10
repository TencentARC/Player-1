(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var constants = Object.freeze({ checkpointReward: 1, closerRewardScale: 0, roadCollisionPenalty: 0 });

  function collisionEvents(metrics) {
    return Math.max(
      U.metrics.readNumber(metrics, "collisions", 0),
      U.metrics.readNumber(metrics, ["offRoadHits", "off_road_hits"], 0),
      U.metrics.readNumber(metrics, ["outOfBounds", "out_of_bounds"], 0)
    );
  }

  function computePrimaryPositiveScore(metrics) {
    return U.metrics.readNumber(metrics, ["checkpointsPassed", "checkpoints_passed"], 0);
  }

  function computePrimaryPenaltyScore(metrics) {
    return collisionEvents(metrics) * constants.roadCollisionPenalty;
  }

  window.Base2DDrivePlanarWasdRewardConfig = Object.freeze({
    version: 2,
    gameId: "base_2d_drive_planar_wasd",
    constants: constants,
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: function computePrimaryScore(metrics) {
      return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
    },
  });
})();
