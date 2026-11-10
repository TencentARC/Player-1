(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var constants = Object.freeze({ correctClickReward: 1, centerPrecisionReward: 0.1, misclickPenalty: 0 });

  function computePrimaryPositiveScore(metrics) {
    var targets = U.metrics.readNumber(metrics, ["targetsCollected", "targets_collected"], 0);
    var precision = U.metrics.readNumber(metrics, ["precisionTotal", "precision_total"], 0);
    return targets * constants.correctClickReward + precision * constants.centerPrecisionReward;
  }

  function computePrimaryPenaltyScore(metrics) {
    return U.metrics.readNumber(metrics, "misclicks", 0) * constants.misclickPenalty;
  }

  function computePrimaryScore(metrics) {
    return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
  }

  window.Base2DAimRewardConfig = Object.freeze({
    version: 3,
    gameId: "base_2d_aim",
    constants: constants,
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: computePrimaryScore,
  });
})();
