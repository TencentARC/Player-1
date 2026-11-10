(function swordHallLayout() {
  "use strict";
  window.SwordHallLayout = function buildSwordHall(game) {
    var Core = window.GameEngineCore;
    var rng = Core.domains.gameplayRng(game, "scene", "layout");
    var varied = Core.domains.profile(game, "scene") === "perturbed";
    var westOffset = varied ? rng.range(-1.2, 1.2) : 0;
    var eastOffset = varied ? rng.range(-1.2, 1.2) : 0;
    var blockers = [];
    if (!game.noObstacles) {
      [-1, 1].forEach(function wing(side) {
        var offset = side < 0 ? westOffset : eastOffset;
        [-1, 1].forEach(function jamb(end) {
          blockers.push({ id: "screen_" + side + "_" + end, x: side * 6.6, z: offset + end * 3.5,
            width: 0.42, depth: 2, height: 3.6, style: "screen" });
        });
      });
      blockers.push({ id: "west_practice_block", x: -3.7, z: varied ? rng.range(-2.6, -1) : -1.8,
        width: 1.35, depth: 1.0, height: 0.7, style: "practice" });
      blockers.push({ id: "east_practice_block", x: 3.7, z: varied ? rng.range(1, 2.6) : 1.8,
        width: 1.35, depth: 1.0, height: 0.7, style: "practice" });
    }
    return window.PlayerOneConnectedLayout.build({ id: "sword-cross-hall", revision: 2,
      regions: [
        { id: "main_hall", x: 0, z: 0, width: 14, depth: 20, style: "hall" },
        { id: "west_room", x: -10, z: westOffset, width: 6.5, depth: 9, style: "room" },
        { id: "east_room", x: 10, z: eastOffset, width: 6.5, depth: 9, style: "room" },
      ], blockers: blockers, wallHeight: 5.3, wallThickness: 0.32 });
  };
})();
