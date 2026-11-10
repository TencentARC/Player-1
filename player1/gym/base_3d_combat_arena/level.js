(function combatDepotLevelModule() {
  "use strict";

  var TEMPLATES = Object.freeze(["depot_loop", "service_cross", "offset_halls"]);

  function sample(context) {
    if (context.profile !== "perturbed") return { template: TEMPLATES[0], wing_offset: 0, door_width: 3.8, cover_shift: 0 };
    return { template: context.rng.choice(TEMPLATES.slice(1)), wing_offset: context.rng.range(-1.2, 1.2),
      door_width: context.rng.range(3.4, 4.4), cover_shift: context.rng.range(-0.45, 0.45) };
  }

  function build(layout, noObstacles) {
    layout = layout || { template: TEMPLATES[0], wing_offset: 0, door_width: 3.8, cover_shift: 0 };
    var offset = layout.wing_offset || 0, door = layout.door_width || 3.8;
    var staggered = layout.template === "offset_halls", cross = layout.template === "service_cross";
    var rooms = [
      { id: "loading_yard", x: 0, z: -2, width: 14, depth: 12, style: "yard", roof: false },
      { id: "machine_hall", x: -13 - offset, z: staggered ? -15 : -12, width: staggered ? 11 : 10,
        depth: 14, style: "workshop", roof: true },
      { id: "freight_hall", x: 13 + offset, z: staggered ? -9 : -12, width: 10,
        depth: staggered ? 14 : 10, style: "loading", roof: true },
      { id: "service_court", x: staggered ? 3 : 0, z: -24, width: cross ? 16 : 14,
        depth: 12, style: "service", roof: false },
    ];
    var regions = rooms.map(function copy(room) { return Object.assign({}, room); }), links = [];
    function passage(id, a, b, bendAtDestinationX) {
      var bend = bendAtDestinationX ? { x: b.x, z: a.z } : { x: a.x, z: b.z };
      [[a, bend], [bend, b]].forEach(function leg(points, index) {
        var from = points[0], to = points[1];
        if (Math.hypot(from.x - to.x, from.z - to.z) < 0.01) return;
        regions.push({ id: id + "_" + index, x: (from.x + to.x) / 2, z: (from.z + to.z) / 2,
          width: Math.abs(from.x - to.x) + door, depth: Math.abs(from.z - to.z) + door,
          style: "passage", roof: false });
      });
      links.push({ id: id, from: a.id, to: b.id, width: door });
    }
    passage("west_entry", rooms[0], rooms[1], true);
    passage("east_entry", rooms[0], rooms[2], true);
    passage("west_service", rooms[1], rooms[3], false);
    passage("east_service", rooms[2], rooms[3], false);
    if (cross) passage("cross_aisle", rooms[1], rooms[2], true);
    else passage("central_aisle", rooms[0], rooms[3], true);

    var shift = layout.cover_shift || 0;
    var props = [
      { id: "yard_crate_west", x: -3.8 + shift, z: -4.5, width: 1.7, depth: 1.0, height: 0.85, kind: "cover" },
      { id: "yard_crate_east", x: 3.8 - shift, z: -5.8, width: 1.8, depth: 1.0, height: 1.05, kind: "cover" },
      { id: "west_machine_a", x: rooms[1].x - 2.3, z: rooms[1].z - 2.9, width: 2.0, depth: 1.65,
        height: 2.25, kind: "equipment", asset: "combat_machine" },
      { id: "west_machine_b", x: rooms[1].x + 2.2, z: rooms[1].z + 3.1, width: 1.85, depth: 1.6,
        height: 2.1, kind: "equipment", asset: "combat_machine" },
      { id: "east_freight_a", x: rooms[2].x - 2.4, z: rooms[2].z - 2.2, width: 1.8, depth: 1.6,
        height: 1.6, kind: "equipment", asset: "combat_cargo" },
      { id: "east_freight_b", x: rooms[2].x + 2.5, z: rooms[2].z + 2.2, width: 1.8, depth: 1.6,
        height: 1.4, kind: "equipment", asset: "combat_cargo" },
      { id: "service_cover_west", x: rooms[3].x - 3.4, z: -25.8, width: 2.1, depth: 1.1, height: 1.05, kind: "cover" },
      { id: "service_cover_east", x: rooms[3].x + 3.2, z: -21.2, width: 2.1, depth: 1.1, height: 0.92, kind: "cover" },
    ];
    var map = window.PlayerOneConnectedLayout.build({ id: layout.template, revision: "industrial-depot-20260910-1",
      regions: regions, blockers: noObstacles ? [] : props, wallHeight: 3.8, wallThickness: 0.28,
      navAnchors: rooms.map(function center(room) { return { x: room.x, z: room.z }; }) });
    map.rooms = rooms;
    map.links = links;
    map.spawn = { x: 0, z: 0.9 };
    map.patrolAnchors = [
      { x: 0, z: -5.8 }, { x: -1.4, z: -6.6 }, { x: 1.6, z: -6.9 }, { x: 0.6, z: -4.9 },
    ].concat(rooms.slice(1).flatMap(function anchors(room) {
      return [{ x: room.x, z: room.z - 1.7 }, { x: room.x, z: room.z + 1.7 }];
    }));
    return map;
  }

  window.CombatDepotLevel = Object.freeze({ templates: TEMPLATES, sample: sample, build: build });
})();
