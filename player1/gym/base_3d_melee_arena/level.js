(function monasteryLevelModule() {
  "use strict";
  var TEMPLATES = Object.freeze(["cloister_loop", "garden_cross", "staggered_sanctuary"]);
  function sample(context) {
    return context.profile !== "perturbed" ? { template: TEMPLATES[0], offset: 0, gate_width: 4.2 }
      : { template: context.rng.choice(TEMPLATES.slice(1)), offset: context.rng.range(-1.2, 1.2), gate_width: context.rng.range(3.8, 4.8) };
  }
  function build(layout, noObstacles) {
    var offset = layout.offset || 0, gate = layout.gate_width || 4.2;
    var staggered = layout.template === "staggered_sanctuary", cross = layout.template === "garden_cross";
    var rooms = [
      { id: "main_court", x: 0, z: 0, width: 18, depth: 18, style: "court" },
      { id: "timber_dojo", x: -16 - offset, z: staggered ? -6 : -2, width: 11, depth: 12, style: "wood", roof: true },
      { id: "garden_court", x: 15 + offset, z: cross ? -4 : 2, width: 10, depth: 13, style: "garden" },
      { id: "sanctuary", x: staggered ? 3 : 0, z: -17, width: 16, depth: 10, style: "sanctuary", roof: true },
    ];
    var regions = rooms.map(function copy(room) { return Object.assign({}, room); }), links = [];
    function link(id, a, b, horizontalFirst) {
      var bend = horizontalFirst ? { x: b.x, z: a.z } : { x: a.x, z: b.z };
      [[a, bend], [bend, b]].forEach(function leg(pair, index) {
        if (Math.hypot(pair[0].x - pair[1].x, pair[0].z - pair[1].z) < 0.01) return;
        regions.push({ id: id + "_" + index, x: (pair[0].x + pair[1].x) / 2, z: (pair[0].z + pair[1].z) / 2,
          width: Math.abs(pair[0].x - pair[1].x) + gate, depth: Math.abs(pair[0].z - pair[1].z) + gate, style: "passage" });
      });
      links.push({ id: id, from: a.id, to: b.id, width: gate });
    }
    link("west_gate", rooms[0], rooms[1], true);
    link("east_gate", rooms[0], rooms[2], true);
    link("north_gate", rooms[0], rooms[3], false);
    link("west_cloister", rooms[1], rooms[3], false);
    if (!cross) link("east_cloister", rooms[2], rooms[3], false);
    var blockers = [
      { id: "court_plinth_west", x: -5.3, z: -4.8, width: 2.1, depth: 1.2, height: 0.88 },
      { id: "court_plinth_east", x: 4.8, z: -3.7, width: 1.7, depth: 1.1, height: 0.82 },
      { id: "dojo_bench_a", x: rooms[1].x - 3.2, z: rooms[1].z - 3.5, width: 1.5, depth: 1.2, height: 0.75 },
      { id: "dojo_bench_b", x: rooms[1].x + 3.2, z: rooms[1].z + 3.5, width: 1.5, depth: 1.2, height: 0.75 },
      { id: "garden_planter_a", x: rooms[2].x - 2.5, z: rooms[2].z - 3.8, width: 1.8, depth: 1.8, height: 0.78, tree: true },
      { id: "garden_planter_b", x: rooms[2].x + 2.5, z: rooms[2].z + 3.8, width: 1.8, depth: 1.8, height: 0.78, tree: true },
      { id: "sanctuary_dais", x: rooms[3].x, z: rooms[3].z - 3, width: 4.4, depth: 1.6, height: 0.9 },
    ];
    // Reflect source geometry before building collision and navigation closures.
    if (layout.mirror_sign === -1) {
      [rooms, regions, blockers].forEach(function mirror(items) {
        items.forEach(function point(item) { item.x = -item.x; });
      });
    }
    var map = window.PlayerOneConnectedLayout.build({ id: layout.template, revision: "monastery-20260910-1", regions: regions,
      blockers: noObstacles ? [] : blockers, wallHeight: 2.8, wallThickness: 0.36,
      navAnchors: rooms.map(function center(room) { return { x: room.x, z: room.z }; }) });
    map.rooms = rooms; map.links = links; map.spawn = { x: 0, z: 5.95 };
    var anchorOffset = layout.mirror_sign === -1 ? -1.8 : 1.8;
    map.spawnAnchors = rooms.flatMap(function anchors(room) {
      return [{ x: room.x, z: room.z }, { x: room.x - anchorOffset, z: room.z + 1.8 }, { x: room.x + anchorOffset, z: room.z - 1.8 }];
    });
    return map;
  }
  window.MeleeMonasteryLevel = Object.freeze({ templates: TEMPLATES, sample: sample, build: build });
})();
