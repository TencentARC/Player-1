(function neighborhoodChaseLayout() {
  "use strict";
  window.NeighborhoodChaseLayout = function buildNeighborhood(game) {
    var Core = window.GameEngineCore;
    var rng = Core.domains.gameplayRng(game, "scene", "layout");
    var varied = Core.domains.profile(game, "scene") === "perturbed";
    var blocks = [];
    [[8, 8], [20, 8], [8, 20], [20, 20]].forEach(function block(center, index) {
      var x = center[0] + (varied ? rng.range(-0.7, 0.7) : 0);
      var z = center[1] + (varied ? rng.range(-0.7, 0.7) : 0);
      blocks.push({ id: "house_" + index, x: x, z: z, width: varied ? rng.range(4.8, 6) : 5.4,
        depth: varied ? rng.range(4.8, 6) : 5.4, height: 3.8, style: "house", houseIndex: index });
      // Each private garden is a solid raised planter, with two public routes around it.
      blocks.push({ id: "garden_" + index, x: x, z: z + (index < 2 ? 4.25 : -4.25),
        width: 3.1, depth: 1.25, height: 1.35, style: "garden" });
    });
    return window.PlayerOneConnectedLayout.build({ id: "neighborhood-chase", revision: 2,
      regions: [
        { id: "east_west_street", x: 14, z: 14, width: 28, depth: 18, style: "street" },
        { id: "north_south_street", x: 14, z: 14, width: 18, depth: 28, style: "street" },
      ], blockers: blocks, wallHeight: 1.55, wallThickness: 0.3 });
  };
})();
