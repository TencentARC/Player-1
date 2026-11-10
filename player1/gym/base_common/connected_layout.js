(function connectedLayoutModule() {
  "use strict";

  var geometry = window.BaseGameletCommon.geometry3d;
  var EPSILON = 1e-7;

  function rectangle(spec, index, prefix) {
    var result = Object.assign({}, spec);
    ["x", "z", "width", "depth"].forEach(function requireNumber(key) {
      if (!Number.isFinite(result[key])) throw new Error("Layout " + prefix + " requires finite " + key);
    });
    if (result.width <= 0 || result.depth <= 0) throw new Error("Layout rectangles require positive dimensions");
    result.id = result.id || prefix + "_" + index;
    return result;
  }

  function pointInRectangle(x, z, rect) {
    return x >= rect.x - rect.width / 2 - EPSILON && x <= rect.x + rect.width / 2 + EPSILON
      && z >= rect.z - rect.depth / 2 - EPSILON && z <= rect.z + rect.depth / 2 + EPSILON;
  }

  function uniqueSorted(values) {
    return values.sort(function ascending(a, b) { return a - b; }).filter(function unique(value, index, array) {
      return index === 0 || value - array[index - 1] > EPSILON;
    });
  }

  function segmentEntersBoxXZ(from, to, box) {
    var enter = 0, exit = 1;
    for (var axis of ["x", "z"]) {
      var minimum = box[axis === "x" ? "minX" : "minZ"], maximum = box[axis === "x" ? "maxX" : "maxZ"];
      var delta = to[axis] - from[axis];
      if (delta === 0) {
        if (from[axis] <= minimum || from[axis] >= maximum) return false;
        continue;
      }
      var first = (minimum - from[axis]) / delta, last = (maximum - from[axis]) / delta;
      enter = Math.max(enter, Math.min(first, last));
      exit = Math.min(exit, Math.max(first, last));
      if (enter >= exit) return false;
    }
    return true;
  }

  function segmentEntersCircleXZ(from, to, x, z, radius) {
    var dx = to.x - from.x, dz = to.z - from.z;
    var t = Math.max(0, Math.min(1, ((x - from.x) * dx + (z - from.z) * dz) / (dx * dx + dz * dz)));
    var closestX = from.x + t * dx - x, closestZ = from.z + t * dz - z;
    return closestX * closestX + closestZ * closestZ < radius * radius;
  }

  function unionGeometry(regions, wallHeight, wallThickness) {
    var xs = uniqueSorted(regions.flatMap(function edges(rect) { return [rect.x - rect.width / 2, rect.x + rect.width / 2]; }));
    var zs = uniqueSorted(regions.flatMap(function edges(rect) { return [rect.z - rect.depth / 2, rect.z + rect.depth / 2]; }));
    var cells = [], floors = [], edges = [], activeRows = {};
    for (var iz = 0; iz < zs.length - 1; iz += 1) {
      cells[iz] = [];
      for (var ix = 0; ix < xs.length - 1; ix += 1) {
        var owner = null, x = (xs[ix] + xs[ix + 1]) / 2, z = (zs[iz] + zs[iz + 1]) / 2;
        // Later regions may give a connecting passage its own floor treatment.
        regions.forEach(function findOwner(region) { if (pointInRectangle(x, z, region)) owner = region; });
        cells[iz][ix] = owner;
      }
    }
    function occupied(x, z) { return !!(cells[z] && cells[z][x]); }
    for (var row = 0; row < cells.length; row += 1) {
      var nextRows = {};
      for (var column = 0; column < cells[row].length; column += 1) {
        var region = cells[row][column];
        if (!region) continue;
        var start = column;
        while (column + 1 < cells[row].length && cells[row][column + 1] === region) column += 1;
        var key = region.id + ":" + start + ":" + column;
        var previous = activeRows[key], bottom = zs[row], top = zs[row + 1];
        if (previous) {
          previous.depth = top - (previous.z - previous.depth / 2);
          previous.z = top - previous.depth / 2;
          nextRows[key] = previous;
        } else {
          var patch = { id: "floor_" + floors.length, region_id: region.id, style: region.style || "floor",
            x: (xs[start] + xs[column + 1]) / 2, z: (bottom + top) / 2,
            width: xs[column + 1] - xs[start], depth: top - bottom };
          floors.push(patch); nextRows[key] = patch;
        }
      }
      activeRows = nextRows;
      for (var cell = 0; cell < cells[row].length; cell += 1) {
        if (!cells[row][cell]) continue;
        if (!occupied(cell - 1, row)) edges.push({ axis: "x", at: xs[cell], from: zs[row], to: zs[row + 1], sign: -1 });
        if (!occupied(cell + 1, row)) edges.push({ axis: "x", at: xs[cell + 1], from: zs[row], to: zs[row + 1], sign: 1 });
        if (!occupied(cell, row - 1)) edges.push({ axis: "z", at: zs[row], from: xs[cell], to: xs[cell + 1], sign: -1 });
        if (!occupied(cell, row + 1)) edges.push({ axis: "z", at: zs[row + 1], from: xs[cell], to: xs[cell + 1], sign: 1 });
      }
    }
    edges.sort(function edgeOrder(a, b) {
      return a.axis.localeCompare(b.axis) || a.at - b.at || a.sign - b.sign || a.from - b.from;
    });
    var merged = [];
    edges.forEach(function join(edge) {
      var previous = merged[merged.length - 1];
      if (previous && previous.axis === edge.axis && previous.sign === edge.sign
        && Math.abs(previous.at - edge.at) < EPSILON && Math.abs(previous.to - edge.from) < EPSILON) {
        previous.to = edge.to;
      } else merged.push(Object.assign({}, edge));
    });
    var walls = merged.map(function wall(edge, index) {
      var normal = edge.axis === "x" ? { x: edge.sign, z: 0 } : { x: 0, z: edge.sign };
      return { id: "boundary_" + index, kind: "boundary", normal: normal,
        x: edge.axis === "x" ? edge.at + edge.sign * wallThickness / 2 : (edge.from + edge.to) / 2,
        z: edge.axis === "z" ? edge.at + edge.sign * wallThickness / 2 : (edge.from + edge.to) / 2,
        width: edge.axis === "x" ? wallThickness : edge.to - edge.from,
        depth: edge.axis === "z" ? wallThickness : edge.to - edge.from,
        height: wallHeight, baseY: 0 };
    });
    return { floorPatches: floors, walls: walls,
      bounds: { minX: xs[0], maxX: xs[xs.length - 1], minZ: zs[0], maxZ: zs[zs.length - 1] } };
  }

  function build(options) {
    options = options || {};
    if (!Array.isArray(options.regions) || !options.regions.length) throw new Error("Layout requires floor regions");
    var regions = options.regions.map(function normalize(spec, index) { return rectangle(spec, index, "region"); });
    var blockers = (options.blockers || []).map(function normalize(spec, index) {
      var blocker = rectangle(spec, index, "blocker");
      blocker.kind = blocker.kind || "obstacle";
      blocker.height = blocker.height === undefined ? 1 : blocker.height;
      blocker.baseY = blocker.baseY === undefined ? 0 : blocker.baseY;
      if (!Number.isFinite(blocker.height) || blocker.height <= 0 || !Number.isFinite(blocker.baseY)) {
        throw new Error("Layout blocker requires positive height and finite baseY");
      }
      return blocker;
    });
    var wallHeight = options.wallHeight === undefined ? 3 : options.wallHeight;
    var wallThickness = options.wallThickness === undefined ? 0.24 : options.wallThickness;
    if (!Number.isFinite(wallHeight) || wallHeight <= 0 || !Number.isFinite(wallThickness) || wallThickness <= 0) {
      throw new Error("Layout walls require positive finite dimensions");
    }
    var union = unionGeometry(regions, wallHeight, wallThickness);
    var colliders = union.walls.concat(blockers);
    var boxes = colliders.map(function bounds(collider) {
      var box = geometry.aabbFromBox(collider);
      // Navigation uses the complete ground footprint, independently of visual height.
      box.minY = -1; box.maxY = 1;
      return box;
    });
    var graphCache = new Map();

    function contains(x, z, radius) {
      if (!Number.isFinite(x) || !Number.isFinite(z)) return false;
      var clearance = Math.max(1e-6, Number(radius) || 0);
      return regions.some(function inside(region) { return pointInRectangle(x, z, region); })
        && !boxes.some(function blocked(box) { return geometry.circleOverlapsAabbXZ(x, z, clearance, box); });
    }

    function segmentClear(from, to, radius) {
      var clearance = Math.max(0, Number(radius) || 0);
      if (!contains(from.x, from.z, clearance) || !contains(to.x, to.z, clearance)) return false;
      var start = { x: from.x, y: 0, z: from.z }, end = { x: to.x, y: 0, z: to.z };
      if (Math.hypot(end.x - start.x, end.z - start.z) < EPSILON) return true;
      for (var i = 0; i < boxes.length; i += 1) {
        var box = boxes[i];
        if (geometry.segmentAabbHitDistance(start, end, box, clearance) === null) continue;
        if (clearance <= EPSILON) return false;
        // A swept circle has rounded corners. Match movement's strict overlap:
        // touching a slab or corner is legal unless the segment enters its interior.
        var horizontal = { minX: box.minX - clearance, maxX: box.maxX + clearance,
          minZ: box.minZ, maxZ: box.maxZ, minY: -1, maxY: 1 };
        var vertical = { minX: box.minX, maxX: box.maxX,
          minZ: box.minZ - clearance, maxZ: box.maxZ + clearance, minY: -1, maxY: 1 };
        if (segmentEntersBoxXZ(start, end, horizontal) || segmentEntersBoxXZ(start, end, vertical)) return false;
        for (var sideX = 0; sideX < 2; sideX += 1) {
          for (var sideZ = 0; sideZ < 2; sideZ += 1) {
            if (segmentEntersCircleXZ(start, end,
              sideX ? box.maxX : box.minX, sideZ ? box.maxZ : box.minZ, clearance)) return false;
          }
        }
      }
      return true;
    }

    function navigationSegmentClear(from, to, radius) {
      if (!segmentClear(from, to, radius)) return false;
      // The physical mover resolves X before Z. Certify both directional stair-step
      // envelopes as well as the straight swept circle used by the public query.
      var count = Math.max(1, Math.ceil(Math.hypot(to.x - from.x, to.z - from.z) / 0.1));
      var start = { x: from.x, y: 0, z: from.z }, end = { x: to.x, y: 0, z: to.z };
      for (var index = 0; index < boxes.length; index += 1) {
        var box = boxes[index];
        if (geometry.segmentAabbHitDistance(start, end, box, radius + 0.1) === null) continue;
        var previous = from;
        for (var step = 1; step <= count; step += 1) {
          var next = { x: from.x + (to.x - from.x) * step / count, z: from.z + (to.z - from.z) * step / count };
          if (geometry.circleOverlapsAabbXZ(next.x, previous.z, radius, box)
            || geometry.circleOverlapsAabbXZ(previous.x, next.z, radius, box)) return false;
          previous = next;
        }
      }
      return true;
    }

    function navigationGraph(radius) {
      var key = String(radius);
      if (graphCache.has(key)) return graphCache.get(key);
      // Corner waypoints leave room for the mover's separate X/Z sweeps at a 0.1 m step.
      var points = [], seen = new Set(), offset = radius + 0.1;
      function add(x, z) {
        var pointKey = x.toFixed(6) + ":" + z.toFixed(6);
        if (seen.has(pointKey) || !contains(x, z, radius)) return;
        seen.add(pointKey); points.push({ x: x, z: z });
      }
      boxes.forEach(function corners(box) {
        [box.minX - offset, box.maxX + offset].forEach(function xEdge(x) {
          [box.minZ - offset, box.maxZ + offset].forEach(function zEdge(z) { add(x, z); });
        });
      });
      union.floorPatches.forEach(function center(rect) { add(rect.x, rect.z); });
      (options.navAnchors || []).forEach(function anchor(point) { add(point.x, point.z); });
      points.sort(function coordinateOrder(a, b) { return a.x - b.x || a.z - b.z; });
      var edges = points.map(function row() { return []; });
      for (var from = 0; from < points.length; from += 1) {
        for (var to = from + 1; to < points.length; to += 1) {
          if (!navigationSegmentClear(points[from], points[to], radius)) continue;
          var distance = Math.hypot(points[from].x - points[to].x, points[from].z - points[to].z);
          edges[from].push({ index: to, distance: distance });
          edges[to].push({ index: from, distance: distance });
        }
      }
      var graph = { points: points, edges: edges };
      graphCache.set(key, graph);
      return graph;
    }

    function findPath(from, to, radius) {
      var clearance = Math.max(0, Number(radius) || 0);
      if (!contains(from.x, from.z, clearance) || !contains(to.x, to.z, clearance)) return [];
      var start = { x: from.x, z: from.z }, goal = { x: to.x, z: to.z };
      if (navigationSegmentClear(start, goal, clearance)) return [start, goal];
      var graph = navigationGraph(clearance), points = graph.points.concat([start, goal]);
      var startIndex = points.length - 2, goalIndex = points.length - 1;
      var edges = graph.edges.map(function copy(row) { return row.slice(); });
      edges.push([], []);
      for (var index = 0; index < graph.points.length; index += 1) {
        [startIndex, goalIndex].forEach(function connect(endpoint) {
          if (!navigationSegmentClear(points[index], points[endpoint], clearance)) return;
          var distance = Math.hypot(points[index].x - points[endpoint].x, points[index].z - points[endpoint].z);
          edges[index].push({ index: endpoint, distance: distance });
          edges[endpoint].push({ index: index, distance: distance });
        });
      }
      var distances = points.map(function infinity() { return Infinity; });
      var previous = points.map(function empty() { return -1; }), visited = new Set();
      distances[startIndex] = 0;
      for (var step = 0; step < points.length; step += 1) {
        var current = -1, best = Infinity;
        for (var candidate = 0; candidate < points.length; candidate += 1) {
          if (!visited.has(candidate) && distances[candidate] < best) {
            best = distances[candidate]; current = candidate;
          }
        }
        if (current < 0) return [];
        if (current === goalIndex) {
          var route = [];
          while (current >= 0) { route.push(points[current]); current = previous[current]; }
          return route.reverse();
        }
        visited.add(current);
        edges[current].forEach(function relax(edge) {
          var cost = best + edge.distance;
          if (cost < distances[edge.index] - EPSILON) {
            distances[edge.index] = cost; previous[edge.index] = current;
          }
        });
      }
      return [];
    }

    return { id: options.id || "connected_layout", revision: options.revision || null,
      regions: regions, floorPatches: union.floorPatches, walls: union.walls, blockers: blockers,
      colliders: colliders, bounds: union.bounds,
      area: union.floorPatches.reduce(function area(total, rect) { return total + rect.width * rect.depth; }, 0),
      contains: contains, segmentClear: segmentClear, findPath: findPath };
  }

  function pathLength(path) {
    var result = 0;
    for (var i = 1; i < path.length; i += 1) result += Math.hypot(path[i].x - path[i - 1].x, path[i].z - path[i - 1].z);
    return result;
  }

  window.PlayerOneConnectedLayout = Object.freeze({ build: build, pathLength: pathLength });
})();
