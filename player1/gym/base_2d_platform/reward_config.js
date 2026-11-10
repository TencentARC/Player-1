(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var constants = Object.freeze({
    coinReward: 1,
    gapReward: 1,
    spikeReward: 1,
    flagReward: 1,
    progressRewardScale: 0,
    hazardPenalty: 0,
    fallPenalty: 0,
  });

  function computePrimaryPositiveScore(metrics) {
    var eventScore = U.metrics.readNumber(metrics, ["coinsCollected", "coins_collected"], 0) * constants.coinReward
      + U.metrics.readNumber(metrics, ["gapsCleared", "gaps_cleared"], 0) * constants.gapReward
      + U.metrics.readNumber(metrics, ["spikesCleared", "spikes_cleared"], 0) * constants.spikeReward
      + U.metrics.readNumber(metrics, ["flagsReached", "flags_reached"], 0) * constants.flagReward;
    var levelProgress = Math.min(
      U.metrics.readNumber(metrics, ["levelDistanceProgress", "level_distance_progress"], 0) * constants.progressRewardScale,
      0.1
    );
    return eventScore + levelProgress;
  }

  function computePrimaryPenaltyScore(metrics) {
    var hazardHits = U.metrics.readNumber(metrics, ["hazardHits", "hazard_hits"], 0);
    var falls = U.metrics.readNumber(metrics, "falls", 0);
    return hazardHits * constants.hazardPenalty + falls * constants.fallPenalty;
  }

  function computePrimaryScore(metrics) {
    return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
  }

  window.Base2DPlatformRewardConfig = Object.freeze({
    version: 2,
    gameId: "base_2d_platform",
    constants: constants,
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: computePrimaryScore,
  });
})();
