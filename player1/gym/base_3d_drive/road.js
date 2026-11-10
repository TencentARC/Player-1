(function countryDriveRoad() {
  "use strict";

  var U = window.BaseGameletCommon;
  var CHECKPOINTS_PER_CHUNK = 10;
  var SAMPLES_PER_SEGMENT = 9;
  var START_X = 1.2;
  var FIRST_CHECKPOINT_X = 4;
  var ROAD_WIDTH = 2.3;
  var CHECKPOINT_LINE_HALF_WIDTH = ROAD_WIDTH / 2 + 0.18;
  var SHAPES = Object.freeze({
    "river-bends": { width: 43, depth: 26, waves: 1.35, amplitude: 4.0 },
    "ridge-sweep": { width: 48, depth: 30, waves: 0.62, amplitude: 6.0 },
    "orchard-esses": { width: 40, depth: 24, waves: 1.8, amplitude: 3.0 },
    "valley-road": { width: 46, depth: 28, waves: 1.1, amplitude: 5.3 },
  });

  function spline(p0, p1, p2, p3, t) {
    if (t === 0) return { x: p1.x, y: p1.y, tangentAngle: Math.atan2(p2.y - p0.y, p2.x - p0.x) };
    if (t === 1) return { x: p2.x, y: p2.y, tangentAngle: Math.atan2(p3.y - p1.y, p3.x - p1.x) };
    function axis(key) {
      var a = -p0[key] + p2[key];
      var b = 2 * p0[key] - 5 * p1[key] + 4 * p2[key] - p3[key];
      var c = -p0[key] + 3 * p1[key] - 3 * p2[key] + p3[key];
      return { value: 0.5 * (2 * p1[key] + a * t + b * t * t + c * t * t * t),
        derivative: 0.5 * (a + 2 * b * t + 3 * c * t * t) };
    }
    var x = axis("x"), y = axis("y");
    return { x: x.value, y: y.value, tangentAngle: Math.atan2(y.derivative, x.derivative) };
  }

  function create(layout, rng) {
    var shape = SHAPES[layout.template];
    if (!shape) throw new Error("Unknown country road template: " + layout.template);
    var phase = rng.range(-0.65, 0.65);
    var amplitude = shape.amplitude * rng.range(0.86, 1.12);
    var mirror = rng.next() < 0.5 ? -1 : 1;
    // Preserve the original checkpoint X spacing and bend scale for each template.
    var rightX = shape.width - 1.35;
    var spacing = (rightX - FIRST_CHECKPOINT_X) / (CHECKPOINTS_PER_CHUNK - 1);
    function pointAtX(x) {
      var progress = (x - START_X) / (rightX - START_X);
      return { x: x, y: shape.depth / 2 + mirror * amplitude * Math.sin(progress * Math.PI * 2 * shape.waves + phase) };
    }
    function controlPoint(index) {
      return pointAtX(index < 0 ? START_X : FIRST_CHECKPOINT_X + index * spacing);
    }
    function checkpoint(index) {
      var point = controlPoint(index);
      var before = controlPoint(index - 1), after = controlPoint(index + 1);
      return {
        id: "checkpoint_" + index, index: index, x: point.x, y: point.y,
        tangentAngle: Math.atan2(after.y - before.y, after.x - before.x),
        lineHalfWidth: CHECKPOINT_LINE_HALF_WIDTH, passed: false,
      };
    }
    function buildChunk(index) {
      var first = index * CHECKPOINTS_PER_CHUNK - 1;
      var last = first + CHECKPOINTS_PER_CHUNK;
      var route = [], controlRoute = [], checkpoints = [];
      for (var i = first; i <= last; i += 1) controlRoute.push(controlPoint(i));
      for (var segment = first; segment < last; segment += 1) {
        var p0 = controlPoint(segment - 1), p1 = controlPoint(segment);
        var p2 = controlPoint(segment + 1), p3 = controlPoint(segment + 2);
        // The next control point is fixed before publishing a segment, including at chunk boundaries.
        for (var sample = segment === first ? 0 : 1; sample <= SAMPLES_PER_SEGMENT; sample += 1) {
          route.push(spline(p0, p1, p2, p3, sample / SAMPLES_PER_SEGMENT));
        }
        checkpoints.push(checkpoint(segment + 1));
      }
      return {
        index: index, originX: controlRoute[0].x, startX: controlRoute[0].x,
        endX: controlRoute[controlRoute.length - 1].x,
        route: route, controlRoute: controlRoute, routeLength: U.track.polylineLength(route),
        checkpoints: checkpoints,
      };
    }
    var start = controlPoint(-1), firstCheckpoint = controlPoint(0);
    start.angle = Math.atan2(firstCheckpoint.y - start.y, firstCheckpoint.x - start.x);
    return Object.freeze({
      template: layout.template, shape: shape, start: start, checkpointSpacing: spacing,
      checkpointsPerChunk: CHECKPOINTS_PER_CHUNK,
      chunkAtX: function chunkAtX(x) {
        return Math.max(0, Math.floor(((x - FIRST_CHECKPOINT_X) / spacing + 1) / CHECKPOINTS_PER_CHUNK));
      },
      checkpoint: checkpoint,
      buildChunk: buildChunk,
    });
  }

  window.CountryDriveRoad = Object.freeze({ create: create, roadWidth: ROAD_WIDTH });
})();
