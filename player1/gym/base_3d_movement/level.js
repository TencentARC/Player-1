(function movementRoomLevelModule() {
  "use strict";
  var TEMPLATES = Object.freeze(["central_barriers", "offset_barriers", "side_barriers"]);

  function sample(context) {
    return context.profile !== "perturbed" ? { template: TEMPLATES[0], offset: 0 }
      : { template: context.rng.choice(TEMPLATES.slice(1)), offset: context.rng.range(-0.35, 0.35) };
  }

  function build(layout) {
    var offset = layout.offset || 0;
    var specs = layout.template === "offset_barriers"
      ? [[-1.5, -6.3, 2.6, 1.3, 0.85], [2.9, -8.3, 1.8, 1.6, 1.0], [-2.7, -9.8, 1.8, 1.3, 0.9]]
      : layout.template === "side_barriers"
        ? [[-3.0, -6.6, 2.4, 1.3, 0.85], [3.0, -6.6, 2.4, 1.3, 0.85], [0, -9.0, 2.5, 1.3, 1.0]]
        : [[0, -6.5, 3.4, 1.3, 0.85], [-3.6, -9.0, 1.8, 1.4, 1.0], [3.6, -9.0, 1.8, 1.4, 1.0]];
    var blockers = specs.map(function barrier(spec, index) {
      return { id: "barrier_" + index, x: spec[0] + offset, z: spec[1], width: spec[2], depth: spec[3],
        height: spec[4] };
    });
    var room = { id: "movement_room", x: 0, z: -8, width: 16, depth: 16, style: "floor" };
    var map = window.PlayerOneConnectedLayout.build({
      id: layout.template, revision: "movement-cuboids-20261020-1", regions: [room], blockers: blockers,
      wallHeight: 3.6, wallThickness: 0.24,
      navAnchors: [{ x: -5.8, z: -7 }, { x: 5.8, z: -7 }, { x: 0, z: -12 }],
    });
    map.rooms = [room];
    map.links = [];
    map.spawn = { x: 0, z: -1.2 };
    map.targets = [
      { x: 0, z: -3.4 }, { x: -4.7, z: -3.4 }, { x: 4.7, z: -3.4 },
      { x: -5.9, z: -6.5 }, { x: 5.9, z: -6.5 },
      { x: -5.9, z: -11.2 }, { x: 5.9, z: -11.2 }, { x: 0, z: -11.4 },
    ].filter(function clear(point) { return map.contains(point.x, point.z, 1.4); });
    return map;
  }

  window.MovementRoomLevel = Object.freeze({ templates: TEMPLATES, sample: sample, build: build });
})();
