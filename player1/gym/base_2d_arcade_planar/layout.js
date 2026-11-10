(function dispatchLayoutModule() {
  "use strict";
  var FAMILIES = ["cross_dock", "double_loop", "offset_workshops", "long_gallery"];
  function sample(context) {
    var seed = Number(context.rng.seed) >>> 0;
    return { template: FAMILIES[(seed + (context.profile === "perturbed" ? 1 : 0)) % FAMILIES.length],
      width_scale: [0.84, 0.92, 1][(seed >>> 8) % 3], depth_scale: [0.88, 1][(seed >>> 13) % 2] };
  }
  function build(layout, width, height) {
    var cx = width / 2, cy = height / 2, sx = layout.width_scale, sy = layout.depth_scale;
    var definitions = {
      cross_dock: [[0, 0, 1040, 210], [-350, -15, 250, 550], [0, 0, 260, 570], [350, 15, 250, 550]],
      double_loop: [[-375, 0, 250, 580], [375, 0, 250, 580], [0, -180, 920, 220], [0, 180, 920, 220], [0, 0, 220, 450]],
      offset_workshops: [[0, 0, 1040, 200], [-350, -120, 290, 350], [310, 120, 340, 350], [25, -155, 240, 270], [-40, 185, 250, 220]],
      long_gallery: [[0, 0, 1030, 240], [-345, -190, 300, 200], [280, 190, 380, 200], [-360, -95, 190, 210], [340, 105, 190, 200]],
    };
    if (!definitions[layout.template]) throw new Error("Unknown dispatch workzone");
    var map = window.PlayerOneConnectedLayout.build({ id: layout.template, revision: 2, wallThickness: 12, wallHeight: 12,
      regions: definitions[layout.template].map(function region(value, index) {
        return { id: "workzone_" + index, x: cx + value[0] * sx, z: cy + value[1] * sy,
          width: value[2] * sx, depth: value[3] * sy, style: index ? "bay" : "hall" };
      }) });
    map.rectFits = function rectFits(x, y, w, h) {
      var right = x + w, bottom = y + h;
      return map.contains(x, y, 0) && map.contains(right, y, 0) && map.contains(x, bottom, 0)
        && map.contains(right, bottom, 0) && !map.walls.some(function intersects(wall) {
          return x < wall.x + wall.width / 2 && right > wall.x - wall.width / 2
            && y < wall.z + wall.depth / 2 && bottom > wall.z - wall.depth / 2;
        });
    };
    map.laneSegments = function laneSegments(y, size) {
      var intervals = [];
      var start = null;
      for (var x = 0; x <= width - size; x += 2) {
        if (map.rectFits(x, y, size, size)) { if (start === null) start = x; }
        else if (start !== null) { intervals.push({ start: start, end: x - 2 }); start = null; }
      }
      if (start !== null) intervals.push({ start: start, end: width - size });
      return intervals.filter(function usable(value) { return value.end - value.start > size * 2; });
    };
    return map;
  }
  window.DispatchWorkzoneLayout = Object.freeze({ sample: sample, build: build });
})();
