(function spearCloisterLayout() {
  "use strict";
  window.SpearCloisterLayout = function buildSpearCloister(game) {
    var Core = window.GameEngineCore;
    var rng = Core.domains.gameplayRng(game, "scene", "layout");
    var varied = Core.domains.profile(game, "scene") === "perturbed";
    var westOffset = varied ? rng.range(-1.4, 1.4) : 0;
    var eastOffset = varied ? rng.range(-1.4, 1.4) : 0;
    var blockers = game.noObstacles ? [] : [
      { id: "west_colonnade", x: -4.8, z: westOffset, width: 1.25, depth: 5.4, height: 2.4, style: "arcade" },
      { id: "east_colonnade", x: 4.8, z: eastOffset, width: 1.25, depth: 5.4, height: 2.4, style: "arcade" },
      { id: "north_west_pedestal", x: -3.5, z: -7.7, width: 1.9, depth: 1.1, height: 0.68, style: "pedestal" },
      { id: "south_east_pedestal", x: 3.5, z: 7.7, width: 1.9, depth: 1.1, height: 0.68, style: "pedestal" },
    ];
    if (varied && !game.noObstacles) {
      blockers[2].z += rng.range(-0.6, 0.6);
      blockers[3].z += rng.range(-0.6, 0.6);
      blockers[0].depth = rng.range(4.5, 6.2);
      blockers[1].depth = rng.range(4.5, 6.2);
    }
    return window.PlayerOneConnectedLayout.build({ id: "spear-cloister", revision: 2,
      regions: [
        { id: "court", x: 0, z: 0, width: 14, depth: 22, style: "court" },
        { id: "west_gallery", x: -9, z: westOffset, width: 6, depth: 12, style: "gallery" },
        { id: "east_gallery", x: 9, z: eastOffset, width: 6, depth: 12, style: "gallery" },
      ], blockers: blockers, wallHeight: 3.2, wallThickness: 0.32 });
  };
})();
