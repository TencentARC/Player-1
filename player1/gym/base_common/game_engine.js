(function gameEngineModule() {
  "use strict";

  function parseUnsignedInt(value, fallback) {
    if (value === null || value === undefined || value === "") return fallback;
    var numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric < 0) return fallback;
    return Math.trunc(numeric) >>> 0;
  }

  function hasOwn(object, key) {
    return Object.prototype.hasOwnProperty.call(object, key);
  }

  function clamp(value, minValue, maxValue) {
    return Math.max(minValue, Math.min(maxValue, value));
  }

  function finiteNumber(value, fallback) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    return fallback === undefined ? null : fallback;
  }

  function finiteRoundedInt(value, fallback) {
    var numeric = finiteNumber(value, fallback);
    return numeric === null ? null : Math.round(numeric);
  }

  function readMetricNumber(metrics, names, fallback) {
    var keys = Array.isArray(names) ? names : [names];
    for (var i = 0; i < keys.length; i += 1) {
      if (!metrics || metrics[keys[i]] === undefined) continue;
      var numeric = Number(metrics[keys[i]]);
      if (Number.isFinite(numeric)) return numeric;
    }
    return fallback === undefined ? 0 : fallback;
  }

  function normalizeAngle(angle) {
    var normalized = Number(angle);
    if (!Number.isFinite(normalized)) return 0;
    while (normalized > Math.PI) normalized -= Math.PI * 2;
    while (normalized < -Math.PI) normalized += Math.PI * 2;
    return normalized;
  }

  function distanceSq2D(a, b) {
    var dx = a.x - b.x;
    var dy = a.y - b.y;
    return dx * dx + dy * dy;
  }

  function distance2D(a, b) {
    return Math.sqrt(distanceSq2D(a, b));
  }

  function clonePoint(point) {
    var cloned = { x: point.x, y: point.y };
    if (point.z !== undefined) cloned.z = point.z;
    return cloned;
  }

  function rectsOverlap(a, b) {
    return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
  }

  function circleRectOverlap(cx, cy, radius, rect) {
    var closestX = clamp(cx, rect.x, rect.x + rect.w);
    var closestY = clamp(cy, rect.y, rect.y + rect.h);
    var dx = cx - closestX;
    var dy = cy - closestY;
    return dx * dx + dy * dy <= radius * radius;
  }

  function segmentRectIntersection(start, end, rect, padding) {
    var inset = Math.max(0, Number(padding) || 0);
    var minX = rect.x - inset;
    var maxX = rect.x + rect.w + inset;
    var minY = rect.y - inset;
    var maxY = rect.y + rect.h + inset;
    var dx = end.x - start.x;
    var dy = end.y - start.y;
    var tMin = 0;
    var tMax = 1;

    function clip(origin, delta, lower, upper) {
      if (Math.abs(delta) < 1e-9) return origin >= lower && origin <= upper;
      var t1 = (lower - origin) / delta;
      var t2 = (upper - origin) / delta;
      if (t1 > t2) {
        var swap = t1;
        t1 = t2;
        t2 = swap;
      }
      tMin = Math.max(tMin, t1);
      tMax = Math.min(tMax, t2);
      return tMin <= tMax;
    }

    if (!clip(start.x, dx, minX, maxX) || !clip(start.y, dy, minY, maxY)) return null;
    return { t: tMin, x: start.x + dx * tMin, y: start.y + dy * tMin };
  }

  function segmentCircleIntersection(start, end, circle, padding) {
    var radius = Math.max(0, Number(circle.r === undefined ? circle.radius : circle.r) || 0)
      + Math.max(0, Number(padding) || 0);
    var dx = end.x - start.x;
    var dy = end.y - start.y;
    var offsetX = start.x - circle.x;
    var offsetY = start.y - circle.y;
    var lengthSq = dx * dx + dy * dy;
    var startDistanceSq = offsetX * offsetX + offsetY * offsetY;
    if (startDistanceSq <= radius * radius) return { t: 0, x: start.x, y: start.y };
    if (lengthSq <= 1e-12) return null;
    var projection = -(offsetX * dx + offsetY * dy) / lengthSq;
    var closestDistanceSq = startDistanceSq - projection * projection * lengthSq;
    var radiusSq = radius * radius;
    if (closestDistanceSq > radiusSq) return null;
    var offsetT = Math.sqrt(Math.max(0, radiusSq - closestDistanceSq) / lengthSq);
    var t = projection - offsetT;
    if (t < 0 || t > 1) return null;
    return { t: t, x: start.x + dx * t, y: start.y + dy * t };
  }

  function rayRectangleBoundaryIntersection(origin, through, rect) {
    var dx = through.x - origin.x;
    var dy = through.y - origin.y;
    if (dx * dx + dy * dy <= 1e-12) return null;
    var minX = rect.x;
    var maxX = rect.x + rect.w;
    var minY = rect.y;
    var maxY = rect.y + rect.h;
    var tMin = -Infinity;
    var tMax = Infinity;

    function clip(axisOrigin, axisDelta, lower, upper) {
      if (Math.abs(axisDelta) < 1e-9) return axisOrigin >= lower && axisOrigin <= upper;
      var t1 = (lower - axisOrigin) / axisDelta;
      var t2 = (upper - axisOrigin) / axisDelta;
      if (t1 > t2) {
        var swap = t1;
        t1 = t2;
        t2 = swap;
      }
      tMin = Math.max(tMin, t1);
      tMax = Math.min(tMax, t2);
      return tMin <= tMax;
    }

    if (!clip(origin.x, dx, minX, maxX) || !clip(origin.y, dy, minY, maxY) || tMax < 0) return null;
    var t = tMin >= 0 ? tMin : tMax;
    return { t: t, x: origin.x + dx * t, y: origin.y + dy * t };
  }

  function projectPointToSegment(point, a, b) {
    var abx = b.x - a.x;
    var aby = b.y - a.y;
    var lengthSq = abx * abx + aby * aby;
    if (lengthSq <= 0) {
      return { x: a.x, y: a.y, t: 0, distance: distance2D(point, a) };
    }
    var t = ((point.x - a.x) * abx + (point.y - a.y) * aby) / lengthSq;
    t = clamp(t, 0, 1);
    var projected = { x: a.x + abx * t, y: a.y + aby * t };
    return { x: projected.x, y: projected.y, t: t, distance: distance2D(point, projected) };
  }

  function distanceToSegment(point, a, b) {
    return projectPointToSegment(point, a, b).distance;
  }

  function segmentsIntersect(a, b, c, d) {
    var epsilon = 1e-9;
    var rx = b.x - a.x;
    var ry = b.y - a.y;
    var sx = d.x - c.x;
    var sy = d.y - c.y;
    var rLengthSq = rx * rx + ry * ry;
    var sLengthSq = sx * sx + sy * sy;
    if (rLengthSq <= epsilon) return distanceToSegment(a, c, d) <= epsilon;
    if (sLengthSq <= epsilon) return distanceToSegment(c, a, b) <= epsilon;
    var qpx = c.x - a.x;
    var qpy = c.y - a.y;
    var crossRS = rx * sy - ry * sx;
    var crossQR = qpx * ry - qpy * rx;
    if (Math.abs(crossRS) <= epsilon) {
      if (Math.abs(crossQR) > epsilon) return false;
      var t0 = (qpx * rx + qpy * ry) / rLengthSq;
      var t1 = ((d.x - a.x) * rx + (d.y - a.y) * ry) / rLengthSq;
      return Math.max(Math.min(t0, t1), 0) <= Math.min(Math.max(t0, t1), 1) + epsilon;
    }
    var t = (qpx * sy - qpy * sx) / crossRS;
    var u = crossQR / crossRS;
    return t >= -epsilon && t <= 1 + epsilon && u >= -epsilon && u <= 1 + epsilon;
  }

  function distanceBetweenSegments(a, b, c, d) {
    if (segmentsIntersect(a, b, c, d)) return 0;
    return Math.min(
      distanceToSegment(a, c, d),
      distanceToSegment(b, c, d),
      distanceToSegment(c, a, b),
      distanceToSegment(d, a, b)
    );
  }

  function sweptCircleIntersectsSegment(from, to, radius, a, b) {
    var safeRadius = Math.max(0, finiteNumber(radius, 0));
    return distanceBetweenSegments(from, to, a, b) <= safeRadius + 1e-9;
  }

  function crossSectionSegment(center, tangentAngle, halfWidth) {
    var angle = finiteNumber(tangentAngle, 0);
    var extent = Math.max(0, finiteNumber(halfWidth, 0));
    var tangentX = Math.cos(angle);
    var tangentY = Math.sin(angle);
    var normalX = -tangentY;
    var normalY = tangentX;
    return {
      a: { x: center.x + normalX * extent, y: center.y + normalY * extent },
      b: { x: center.x - normalX * extent, y: center.y - normalY * extent },
      tangentX: tangentX,
      tangentY: tangentY,
      normalX: normalX,
      normalY: normalY,
      halfWidth: extent,
    };
  }

  function distanceToPolyline(point, points) {
    if (!points || !points.length) {
      return { distance: Infinity, x: point.x, y: point.y, segmentIndex: -1, t: 0 };
    }
    if (points.length === 1) {
      return { distance: distance2D(point, points[0]), x: points[0].x, y: points[0].y, segmentIndex: 0, t: 0 };
    }
    var best = { distance: Infinity, x: point.x, y: point.y, segmentIndex: 0, t: 0 };
    for (var i = 0; i < points.length - 1; i += 1) {
      var projected = projectPointToSegment(point, points[i], points[i + 1]);
      if (projected.distance < best.distance) {
        best = {
          distance: projected.distance,
          x: projected.x,
          y: projected.y,
          segmentIndex: i,
          t: projected.t,
        };
      }
    }
    return best;
  }

  function polylineLength(points) {
    var total = 0;
    if (!points) return total;
    for (var i = 0; i < points.length - 1; i += 1) total += distance2D(points[i], points[i + 1]);
    return total;
  }

  function samplePolylineAtDistance(points, targetDistance) {
    if (!points || points.length === 0) return { x: 0, y: 0, angle: 0, segmentIndex: -1, t: 0 };
    if (points.length === 1) return { x: points[0].x, y: points[0].y, angle: 0, segmentIndex: 0, t: 0 };
    var target = Math.max(0, finiteNumber(targetDistance, 0));
    var traveled = 0;
    var lastAngle = 0;
    var lastSegmentIndex = 0;
    for (var i = 0; i < points.length - 1; i += 1) {
      var a = points[i];
      var b = points[i + 1];
      var dx = b.x - a.x;
      var dy = b.y - a.y;
      var length = Math.sqrt(dx * dx + dy * dy);
      if (length <= 1e-9) continue;
      lastAngle = Math.atan2(dy, dx);
      lastSegmentIndex = i;
      if (traveled + length >= target) {
        var t = clamp((target - traveled) / length, 0, 1);
        return {
          x: a.x + dx * t,
          y: a.y + dy * t,
          angle: lastAngle,
          segmentIndex: i,
          t: t,
        };
      }
      traveled += length;
    }
    var last = points[points.length - 1];
    return { x: last.x, y: last.y, angle: lastAngle, segmentIndex: lastSegmentIndex, t: 1 };
  }

  function samplePolylineAtLowCurvatureDistance(points, targetDistance, options) {
    options = options || {};
    var routeLength = Number(options.routeLength);
    if (!Number.isFinite(routeLength)) routeLength = polylineLength(points);
    routeLength = Math.max(0, routeLength);
    if (routeLength <= 1e-9) return samplePolylineAtDistance(points, targetDistance);
    var searchRadius = Math.max(0, finiteNumber(options.searchRadius, 40));
    var searchStep = Math.max(1, finiteNumber(options.searchStep, 4));
    var tangentSpan = Math.max(1, finiteNumber(options.tangentSpan, 18));
    var offsetPenalty = Math.max(0, finiteNumber(options.offsetPenalty, 0.03));
    var closed = options.closed !== false;

    function normalizedDistance(distance) {
      if (!closed) return clamp(distance, 0, routeLength);
      return ((distance % routeLength) + routeLength) % routeLength;
    }

    function candidateAt(distance) {
      var routeDistance = normalizedDistance(distance);
      var center = samplePolylineAtDistance(points, routeDistance);
      var before = samplePolylineAtDistance(points, normalizedDistance(distance - tangentSpan));
      var after = samplePolylineAtDistance(points, normalizedDistance(distance + tangentSpan));
      var incomingAngle = Math.atan2(center.y - before.y, center.x - before.x);
      var outgoingAngle = Math.atan2(after.y - center.y, after.x - center.x);
      center.angle = Math.atan2(after.y - before.y, after.x - before.x);
      center.curvature = Math.abs(normalizeAngle(outgoingAngle - incomingAngle));
      center.routeDistance = routeDistance;
      return center;
    }

    var best = null;
    for (var offset = -searchRadius; offset <= searchRadius + 1e-9; offset += searchStep) {
      var candidate = candidateAt(targetDistance + offset);
      var distancePenalty = searchRadius > 0 ? Math.abs(offset) / searchRadius * offsetPenalty : 0;
      var score = candidate.curvature + distancePenalty;
      if (!best || score < best.score - 1e-9 || (
        Math.abs(score - best.score) <= 1e-9
        && Math.abs(offset) < Math.abs(best.offset)
      )) {
        best = { sample: candidate, score: score, offset: offset };
      }
    }
    return best.sample;
  }

  function rotateClosedPolylineToDistance(points, targetDistance) {
    if (!points || !points.length) return [];
    if (points.length === 1) return [clonePoint(points[0])];
    var closed = points.map(clonePoint);
    if (distance2D(closed[0], closed[closed.length - 1]) > 1e-9) {
      closed.push(clonePoint(closed[0]));
    }
    var routeLength = polylineLength(closed);
    if (routeLength <= 1e-9) return closed;
    var target = ((finiteNumber(targetDistance, 0) % routeLength) + routeLength) % routeLength;
    var traveled = 0;

    for (var i = 0; i < closed.length - 1; i += 1) {
      var a = closed[i];
      var b = closed[i + 1];
      var segmentLength = distance2D(a, b);
      if (segmentLength <= 1e-9) continue;
      if (traveled + segmentLength + 1e-9 < target) {
        traveled += segmentLength;
        continue;
      }
      var t = clamp((target - traveled) / segmentLength, 0, 1);
      var start = {
        x: a.x + (b.x - a.x) * t,
        y: a.y + (b.y - a.y) * t,
      };
      var rotated = [start];
      var j;
      for (j = i + 1; j < closed.length - 1; j += 1) {
        if (distance2D(rotated[rotated.length - 1], closed[j]) > 1e-9) {
          rotated.push(clonePoint(closed[j]));
        }
      }
      for (j = 0; j <= i; j += 1) {
        if (distance2D(rotated[rotated.length - 1], closed[j]) > 1e-9) {
          rotated.push(clonePoint(closed[j]));
        }
      }
      if (distance2D(rotated[rotated.length - 1], start) > 1e-9) {
        rotated.push(clonePoint(start));
      } else {
        rotated[rotated.length - 1] = clonePoint(start);
      }
      return rotated;
    }
    return closed;
  }

  function randomizeClosedPolylineStart(rng, points, options) {
    options = options || {};
    if (!rng || typeof rng.range !== "function") {
      throw new Error("randomizeClosedPolylineStart requires BaseGameletCommon.Rng");
    }
    var routeLength = polylineLength(points);
    if (routeLength <= 1e-9) return (points || []).map(clonePoint);
    var straightDistanceMin = Math.max(0, finiteNumber(options.forwardStraightDistanceMin, 0));
    var straightDistanceMax = Math.max(
      straightDistanceMin,
      finiteNumber(options.forwardStraightDistanceMax, straightDistanceMin)
    );
    if (straightDistanceMax > 0) {
      var straightDistance = rng.range(straightDistanceMin, straightDistanceMax);
      var scanStep = Math.max(1, finiteNumber(options.forwardStraightSearchStep, 4));
      var sampleCount = Math.max(2, finiteRoundedInt(options.forwardStraightSamples, 4));
      var maxTurn = Math.max(0, finiteNumber(options.forwardStraightMaxTurn, 0.08));
      var candidates = [];
      var bestCandidate = null;

      function wrappedSample(distance) {
        var wrappedDistance = ((distance % routeLength) + routeLength) % routeLength;
        return samplePolylineAtDistance(points, wrappedDistance);
      }

      for (var distance = 0; distance < routeLength; distance += scanStep) {
        var firstAngle = null;
        var turn = 0;
        var previous = wrappedSample(distance);
        for (var sampleIndex = 1; sampleIndex <= sampleCount; sampleIndex += 1) {
          var current = wrappedSample(distance + straightDistance * sampleIndex / sampleCount);
          var segmentAngle = Math.atan2(current.y - previous.y, current.x - previous.x);
          if (firstAngle === null) firstAngle = segmentAngle;
          else turn = Math.max(turn, Math.abs(normalizeAngle(segmentAngle - firstAngle)));
          previous = current;
        }
        var candidate = { distance: distance, turn: turn };
        if (!bestCandidate || turn < bestCandidate.turn) bestCandidate = candidate;
        if (turn <= maxTurn) candidates.push(candidate);
      }
      var selected = candidates.length ? rng.choice(candidates) : bestCandidate;
      var straightRoute = rotateClosedPolylineToDistance(points, selected.distance);
      straightRoute.startStraightLength = straightDistance;
      straightRoute.startStraightTurn = selected.turn;
      return straightRoute;
    }
    var targetDistance = rng.range(0, routeLength);
    var startSample = samplePolylineAtLowCurvatureDistance(points, targetDistance, {
      routeLength: routeLength,
      searchRadius: Math.max(0, finiteNumber(options.searchRadius, 32)),
      searchStep: Math.max(1, finiteNumber(options.searchStep, 4)),
      tangentSpan: Math.max(1, finiteNumber(options.tangentSpan, 18)),
      offsetPenalty: Math.max(0, finiteNumber(options.offsetPenalty, 0.03)),
    });
    return rotateClosedPolylineToDistance(points, startSample.routeDistance);
  }

  function buildRoundedClosedPolyline(vertices, options) {
    options = options || {};
    if (!vertices || vertices.length < 3) return (vertices || []).map(clonePoint);
    var cornerCut = clamp(finiteNumber(options.cornerCut, 0.2), 0.05, 0.4);
    var cornerSamples = Math.max(2, finiteRoundedInt(options.cornerSamples, 6));
    var maxCornerDistance = Math.max(1, finiteNumber(options.maxCornerDistance, 42));
    var corners = [];

    for (var i = 0; i < vertices.length; i += 1) {
      var previous = vertices[(i + vertices.length - 1) % vertices.length];
      var current = vertices[i];
      var next = vertices[(i + 1) % vertices.length];
      var incomingX = previous.x - current.x;
      var incomingY = previous.y - current.y;
      var outgoingX = next.x - current.x;
      var outgoingY = next.y - current.y;
      var incomingLength = Math.sqrt(incomingX * incomingX + incomingY * incomingY);
      var outgoingLength = Math.sqrt(outgoingX * outgoingX + outgoingY * outgoingY);
      var cornerDistance = Math.min(
        maxCornerDistance,
        incomingLength * cornerCut,
        outgoingLength * cornerCut
      );
      corners.push({
        vertex: clonePoint(current),
        entry: {
          x: current.x + incomingX * cornerDistance / Math.max(1e-9, incomingLength),
          y: current.y + incomingY * cornerDistance / Math.max(1e-9, incomingLength),
        },
        exit: {
          x: current.x + outgoingX * cornerDistance / Math.max(1e-9, outgoingLength),
          y: current.y + outgoingY * cornerDistance / Math.max(1e-9, outgoingLength),
        },
      });
    }

    var route = [clonePoint(corners[0].exit)];
    for (var cornerIndex = 1; cornerIndex <= corners.length; cornerIndex += 1) {
      var corner = corners[cornerIndex % corners.length];
      route.push(clonePoint(corner.entry));
      for (var sampleIndex = 1; sampleIndex <= cornerSamples; sampleIndex += 1) {
        var t = sampleIndex / cornerSamples;
        var inverseT = 1 - t;
        route.push({
          x: inverseT * inverseT * corner.entry.x
            + 2 * inverseT * t * corner.vertex.x
            + t * t * corner.exit.x,
          y: inverseT * inverseT * corner.entry.y
            + 2 * inverseT * t * corner.vertex.y
            + t * t * corner.exit.y,
        });
      }
    }
    return route;
  }

  function catmullRomKnot(previousKnot, a, b, alpha) {
    return previousKnot + Math.pow(Math.max(1e-9, distance2D(a, b)), alpha);
  }

  function interpolateKnotPoint(a, b, knotA, knotB, knot) {
    var span = Math.max(1e-9, knotB - knotA);
    var weightA = (knotB - knot) / span;
    var weightB = (knot - knotA) / span;
    return {
      x: a.x * weightA + b.x * weightB,
      y: a.y * weightA + b.y * weightB,
    };
  }

  function sampleCentripetalCatmullRom(p0, p1, p2, p3, t, alpha) {
    var knot0 = 0;
    var knot1 = catmullRomKnot(knot0, p0, p1, alpha);
    var knot2 = catmullRomKnot(knot1, p1, p2, alpha);
    var knot3 = catmullRomKnot(knot2, p2, p3, alpha);
    var knot = knot1 + (knot2 - knot1) * clamp(t, 0, 1);
    var a1 = interpolateKnotPoint(p0, p1, knot0, knot1, knot);
    var a2 = interpolateKnotPoint(p1, p2, knot1, knot2, knot);
    var a3 = interpolateKnotPoint(p2, p3, knot2, knot3, knot);
    var b1 = interpolateKnotPoint(a1, a2, knot0, knot2, knot);
    var b2 = interpolateKnotPoint(a2, a3, knot1, knot3, knot);
    return interpolateKnotPoint(b1, b2, knot1, knot2, knot);
  }

  function uniqueClosedControlPoints(vertices) {
    var controls = [];
    (vertices || []).forEach(function appendControl(point) {
      var control = clonePoint(point);
      if (!controls.length || distance2D(controls[controls.length - 1], control) > 1e-7) controls.push(control);
    });
    if (controls.length > 1 && distance2D(controls[0], controls[controls.length - 1]) <= 1e-7) controls.pop();
    return controls;
  }

  function controlPointBounds(points) {
    var minX = Infinity;
    var maxX = -Infinity;
    var minY = Infinity;
    var maxY = -Infinity;
    points.forEach(function measureControl(point) {
      minX = Math.min(minX, point.x);
      maxX = Math.max(maxX, point.x);
      minY = Math.min(minY, point.y);
      maxY = Math.max(maxY, point.y);
    });
    return {
      centerX: (minX + maxX) * 0.5,
      centerY: (minY + maxY) * 0.5,
      halfWidth: Math.max(1e-9, (maxX - minX) * 0.5),
      halfHeight: Math.max(1e-9, (maxY - minY) * 0.5),
    };
  }

  function smoothClosedControlPoints(vertices, factor, passes, preserveBounds) {
    var controls = uniqueClosedControlPoints(vertices);
    var blend = clamp(finiteNumber(factor, 0), 0, 0.45);
    var passCount = Math.max(0, finiteRoundedInt(passes, 0));
    var targetBounds = controls.length ? controlPointBounds(controls) : null;
    for (var pass = 0; pass < passCount && blend > 0; pass += 1) {
      controls = controls.map(function smoothControl(point, index) {
        var previous = controls[(index + controls.length - 1) % controls.length];
        var next = controls[(index + 1) % controls.length];
        return {
          x: point.x * (1 - blend) + (previous.x + next.x) * 0.5 * blend,
          y: point.y * (1 - blend) + (previous.y + next.y) * 0.5 * blend,
        };
      });
      if (preserveBounds && controls.length) {
        var smoothedBounds = controlPointBounds(controls);
        controls = controls.map(function restoreControlBounds(point) {
          return {
            x: targetBounds.centerX
              + (point.x - smoothedBounds.centerX) * targetBounds.halfWidth / smoothedBounds.halfWidth,
            y: targetBounds.centerY
              + (point.y - smoothedBounds.centerY) * targetBounds.halfHeight / smoothedBounds.halfHeight,
          };
        });
      }
    }
    return controls;
  }

  function resampleClosedPolyline(points, spacing) {
    var closed = (points || []).map(clonePoint);
    if (closed.length < 2) return closed;
    if (distance2D(closed[0], closed[closed.length - 1]) > 1e-7) closed.push(clonePoint(closed[0]));
    var routeLength = polylineLength(closed);
    if (routeLength <= 1e-9) return [clonePoint(closed[0])];
    var requestedSpacing = Math.max(0.5, finiteNumber(spacing, 4));
    var segmentCount = Math.max(3, Math.ceil(routeLength / requestedSpacing));
    var route = [];
    for (var index = 0; index < segmentCount; index += 1) {
      var sample = samplePolylineAtDistance(closed, routeLength * index / segmentCount);
      route.push({ x: sample.x, y: sample.y });
    }
    route.push(clonePoint(route[0]));
    route.sampleSpacing = routeLength / segmentCount;
    return route;
  }

  function orientation2D(a, b, c) {
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
  }

  function segmentsProperlyIntersect(a, b, c, d) {
    var abC = orientation2D(a, b, c);
    var abD = orientation2D(a, b, d);
    var cdA = orientation2D(c, d, a);
    var cdB = orientation2D(c, d, b);
    return abC * abD < -1e-9 && cdA * cdB < -1e-9;
  }

  function segmentDistance2D(a, b, c, d) {
    if (segmentsProperlyIntersect(a, b, c, d)) return 0;
    return Math.min(
      distanceToSegment(a, c, d),
      distanceToSegment(b, c, d),
      distanceToSegment(c, a, b),
      distanceToSegment(d, a, b)
    );
  }

  function circumradius2D(a, b, c) {
    var sideA = distance2D(b, c);
    var sideB = distance2D(a, c);
    var sideC = distance2D(a, b);
    var doubleArea = Math.abs(orientation2D(a, b, c));
    if (doubleArea <= 1e-7) return Infinity;
    return sideA * sideB * sideC / (2 * doubleArea);
  }

  function validateClosedTrack(route, options) {
    options = options || {};
    var closed = (route || []).map(clonePoint);
    if (closed.length > 1 && distance2D(closed[0], closed[closed.length - 1]) > 1e-7) {
      closed.push(clonePoint(closed[0]));
    }
    var segmentCount = Math.max(0, closed.length - 1);
    var routeLength = polylineLength(closed);
    var averageSpacing = segmentCount > 0 ? routeLength / segmentCount : 0;
    var requiredRadius = Math.max(0, finiteNumber(options.minTurnRadius, 0));
    var requiredSeparation = Math.max(0, finiteNumber(options.minSeparation, 0));
    var curvatureSpan = Math.max(
      averageSpacing,
      finiteNumber(options.curvatureSpan, Math.max(12, averageSpacing * 3))
    );
    var radiusOffset = Math.max(1, Math.round(curvatureSpan / Math.max(1e-9, averageSpacing)));
    var minimumRadius = Infinity;
    var minimumSeparation = Infinity;
    var intersections = 0;
    var uniqueCount = segmentCount;
    var index;

    if (uniqueCount >= radiusOffset * 2 + 1) {
      for (index = 0; index < uniqueCount; index += 1) {
        var previous = closed[(index + uniqueCount - radiusOffset) % uniqueCount];
        var current = closed[index];
        var next = closed[(index + radiusOffset) % uniqueCount];
        minimumRadius = Math.min(minimumRadius, circumradius2D(previous, current, next));
      }
    }

    var neighborDistance = Math.max(
      requiredSeparation * 1.25,
      finiteNumber(options.neighborDistance, requiredSeparation * 1.25)
    );
    var neighborSegments = Math.max(1, Math.ceil(neighborDistance / Math.max(1e-9, averageSpacing)));
    for (index = 0; index < segmentCount; index += 1) {
      var a = closed[index];
      var b = closed[index + 1];
      for (var otherIndex = index + 1; otherIndex < segmentCount; otherIndex += 1) {
        var indexGap = otherIndex - index;
        var circularGap = Math.min(indexGap, segmentCount - indexGap);
        if (circularGap <= neighborSegments) continue;
        var c = closed[otherIndex];
        var d = closed[otherIndex + 1];
        if (
          Math.max(a.x, b.x) + requiredSeparation < Math.min(c.x, d.x)
          || Math.max(c.x, d.x) + requiredSeparation < Math.min(a.x, b.x)
          || Math.max(a.y, b.y) + requiredSeparation < Math.min(c.y, d.y)
          || Math.max(c.y, d.y) + requiredSeparation < Math.min(a.y, b.y)
        ) continue;
        var separation = segmentDistance2D(a, b, c, d);
        minimumSeparation = Math.min(minimumSeparation, separation);
        if (separation <= 1e-7) intersections += 1;
      }
    }

    var issues = [];
    if (segmentCount < 3 || routeLength <= 1e-9) issues.push("degenerate_route");
    if (intersections > 0) issues.push("self_intersection");
    if (requiredRadius > 0 && minimumRadius + 1e-7 < requiredRadius) issues.push("turn_radius");
    if (requiredSeparation > 0 && minimumSeparation + 1e-7 < requiredSeparation) issues.push("separation");
    return {
      valid: issues.length === 0,
      issues: issues,
      routeLength: routeLength,
      sampleSpacing: averageSpacing,
      minTurnRadius: minimumRadius,
      minSeparation: minimumSeparation,
      selfIntersections: intersections,
    };
  }

  function buildClosedSpline(vertices, options) {
    options = options || {};
    var controls = smoothClosedControlPoints(
      vertices,
      finiteNumber(options.controlSmoothing, 0),
      finiteRoundedInt(options.smoothingPasses, 0),
      options.preserveControlBounds === true
    );
    if (controls.length < 3) return controls;
    var alpha = clamp(finiteNumber(options.alpha, 0.5), 0.01, 1);
    var spacing = Math.max(0.5, finiteNumber(options.spacing, 4));
    var denseSpacing = Math.max(0.25, spacing * 0.3);
    var dense = [];

    for (var segment = 0; segment < controls.length; segment += 1) {
      var p0 = controls[(segment + controls.length - 1) % controls.length];
      var p1 = controls[segment];
      var p2 = controls[(segment + 1) % controls.length];
      var p3 = controls[(segment + 2) % controls.length];
      var subdivisions = Math.max(12, Math.ceil(distance2D(p1, p2) / denseSpacing));
      for (var sampleIndex = 0; sampleIndex < subdivisions; sampleIndex += 1) {
        dense.push(sampleCentripetalCatmullRom(p0, p1, p2, p3, sampleIndex / subdivisions, alpha));
      }
    }
    dense.push(clonePoint(dense[0]));
    var route = resampleClosedPolyline(dense, spacing);
    route.validation = validateClosedTrack(route, options);
    route.controlPoints = controls.map(clonePoint);
    return route;
  }

  function distance3(a, b) {
    var dx = (Number(a && a.x) || 0) - (Number(b && b.x) || 0);
    var dy = (Number(a && a.y) || 0) - (Number(b && b.y) || 0);
    var dz = (Number(a && a.z) || 0) - (Number(b && b.z) || 0);
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
  }


  function horizontalDistance(a, b) {
    var dx = (Number(a && a.x) || 0) - (Number(b && b.x) || 0);
    var ay = Number(a && a.y);
    var by = Number(b && b.y);
    var az = Number(a && a.z);
    var bz = Number(b && b.z);
    var za = Number.isFinite(az) ? az : (Number.isFinite(ay) ? ay : 0);
    var zb = Number.isFinite(bz) ? bz : (Number.isFinite(by) ? by : 0);
    var dz = za - zb;
    return Math.sqrt(dx * dx + dz * dz);
  }


  function circleIntersectsSectorXZ(origin, facing, target, options) {
    options = options || {};
    var ox = Number(origin && origin.x) || 0;
    var oz = Number(origin && origin.z) || 0;
    var tx = Number(target && target.x) || 0;
    var tz = Number(target && target.z) || 0;
    var dx = tx - ox;
    var dz = tz - oz;
    var distance = Math.sqrt(dx * dx + dz * dz);
    var radius = Number(options.targetRadius);
    if (!Number.isFinite(radius)) radius = Number(target && (target.radius === undefined ? target.r : target.radius));
    radius = Math.max(0, Number.isFinite(radius) ? radius : 0);
    var range = Math.max(0, Number(options.range) || 0);
    var halfAngle = Math.max(0, Number(options.halfAngle) || 0);
    if (distance - radius > range) return false;
    if (distance <= radius) return true;
    var angularRadius = Math.asin(Math.min(1, radius / distance));
    var angleError = Math.abs(normalizeAngle(Math.atan2(dz, dx) - (Number(facing) || 0)));
    return angleError <= halfAngle + angularRadius;
  }


  function raycastVerticalCapsule(origin, direction, target, options) {
    options = options || {};
    var ox = Number(origin && origin.x) || 0;
    var oy = Number(origin && origin.y) || 0;
    var oz = Number(origin && origin.z) || 0;
    var dx = Number(direction && direction.x) || 0;
    var dy = Number(direction && direction.y) || 0;
    var dz = Number(direction && direction.z) || 0;
    var directionLength = Math.sqrt(dx * dx + dy * dy + dz * dz);
    if (directionLength <= 1e-9) return null;
    dx /= directionLength;
    dy /= directionLength;
    dz /= directionLength;

    var tx = Number(target && target.x) || 0;
    var tz = Number(target && target.z) || 0;
    var bottomY = Number(options.bottomY);
    if (!Number.isFinite(bottomY)) bottomY = Number(target && target.bottomY);
    if (!Number.isFinite(bottomY)) bottomY = Number(target && target.minY);
    if (!Number.isFinite(bottomY)) bottomY = 0;
    var topY = Number(options.topY);
    if (!Number.isFinite(topY)) topY = Number(target && target.topY);
    if (!Number.isFinite(topY)) topY = Number(target && target.maxY);
    if (!Number.isFinite(topY)) topY = bottomY;
    if (topY < bottomY) {
      var swapY = bottomY;
      bottomY = topY;
      topY = swapY;
    }
    var radius = Number(options.targetRadius);
    if (!Number.isFinite(radius)) radius = Number(target && (target.radius === undefined ? target.r : target.radius));
    radius = Math.max(0, Number.isFinite(radius) ? radius : 0);

    var height = topY - bottomY;
    if (height > 1e-9) radius = Math.min(radius, height * 0.5);
    var axisBottomY = height > 1e-9 ? bottomY + radius : bottomY;
    var axisTopY = height > 1e-9 ? topY - radius : topY;
    var range = Number(options.maxDistance);
    if (!Number.isFinite(range)) range = Number(options.range);
    if (!Number.isFinite(range) || range <= 0) range = Infinity;
    var radiusSquared = radius * radius;

    function hitResult(distance) {
      var point = {
        x: ox + dx * distance,
        y: oy + dy * distance,
        z: oz + dz * distance,
      };
      var axisY = clamp(point.y, axisBottomY, axisTopY);
      var nx = point.x - tx;
      var ny = point.y - axisY;
      var nz = point.z - tz;
      var normalLength = Math.sqrt(nx * nx + ny * ny + nz * nz);
      return {
        distance: distance,
        point: point,
        normal: normalLength > 1e-9
          ? { x: nx / normalLength, y: ny / normalLength, z: nz / normalLength }
          : { x: -dx, y: -dy, z: -dz },
      };
    }

    var nearestAxisY = clamp(oy, axisBottomY, axisTopY);
    var insideX = ox - tx;
    var insideY = oy - nearestAxisY;
    var insideZ = oz - tz;
    if (insideX * insideX + insideY * insideY + insideZ * insideZ <= radiusSquared) {
      return hitResult(0);
    }

    var bestDistance = Infinity;
    function consider(distance) {
      if (distance >= 0 && distance <= range && distance < bestDistance) bestDistance = distance;
    }

    if (axisTopY - axisBottomY > 1e-9) {
      var radialX = ox - tx;
      var radialZ = oz - tz;
      var radialA = dx * dx + dz * dz;
      var radialB = 2 * (radialX * dx + radialZ * dz);
      var radialC = radialX * radialX + radialZ * radialZ - radiusSquared;
      var radialDiscriminant = radialB * radialB - 4 * radialA * radialC;
      if (radialA > 1e-12 && radialDiscriminant >= 0) {
        var radialRoot = Math.sqrt(radialDiscriminant);
        var cylinderNear = (-radialB - radialRoot) / (2 * radialA);
        var cylinderFar = (-radialB + radialRoot) / (2 * radialA);
        var nearY = oy + dy * cylinderNear;
        var farY = oy + dy * cylinderFar;
        if (nearY >= axisBottomY && nearY <= axisTopY) consider(cylinderNear);
        if (farY >= axisBottomY && farY <= axisTopY) consider(cylinderFar);
      }
    }

    function testCap(centerY) {
      var mx = ox - tx;
      var my = oy - centerY;
      var mz = oz - tz;
      var projected = mx * dx + my * dy + mz * dz;
      var offsetSquared = mx * mx + my * my + mz * mz - radiusSquared;
      var discriminant = projected * projected - offsetSquared;
      if (discriminant < 0) return;
      consider(-projected - Math.sqrt(discriminant));
    }

    testCap(axisBottomY);
    if (axisTopY - axisBottomY > 1e-9) testCap(axisTopY);
    return Number.isFinite(bestDistance) ? hitResult(bestDistance) : null;
  }


  function verticalCapsuleIntersectsViewCone(origin, direction, target, options) {
    options = options || {};
    var ox = Number(origin && origin.x) || 0;
    var oy = Number(origin && origin.y) || 0;
    var oz = Number(origin && origin.z) || 0;
    var tx = Number(target && target.x) || 0;
    var tz = Number(target && target.z) || 0;
    var bottomY = Number(options.bottomY);
    if (!Number.isFinite(bottomY)) bottomY = Number(target && target.bottomY);
    if (!Number.isFinite(bottomY)) bottomY = Number(target && target.minY);
    if (!Number.isFinite(bottomY)) bottomY = 0;
    var topY = Number(options.topY);
    if (!Number.isFinite(topY)) topY = Number(target && target.topY);
    if (!Number.isFinite(topY)) topY = Number(target && target.maxY);
    if (!Number.isFinite(topY)) topY = bottomY;
    if (topY < bottomY) {
      var swapY = bottomY;
      bottomY = topY;
      topY = swapY;
    }
    var radius = Number(options.targetRadius);
    if (!Number.isFinite(radius)) radius = Number(target && (target.radius === undefined ? target.r : target.radius));
    radius = Math.max(0, Number.isFinite(radius) ? radius : 0);

    var dx = tx - ox;
    var dz = tz - oz;
    var horizontalDistance = Math.sqrt(dx * dx + dz * dz);
    var nearestY = clamp(oy, bottomY, topY);
    var verticalDistance = nearestY - oy;
    var closestDistance = Math.sqrt(
      horizontalDistance * horizontalDistance + verticalDistance * verticalDistance
    );
    var range = Math.max(0, Number(options.range) || 0);
    if (closestDistance - radius > range) return false;

    var directionX = Number(direction && direction.x) || 0;
    var directionY = Number(direction && direction.y) || 0;
    var directionZ = Number(direction && direction.z) || 0;
    var directionLength = Math.sqrt(
      directionX * directionX + directionY * directionY + directionZ * directionZ
    );
    if (directionLength <= 1e-9) return false;
    directionX /= directionLength;
    directionY /= directionLength;
    directionZ /= directionLength;

    var horizontalHalfAngle = Math.max(0, Number(options.horizontalHalfAngle) || 0);
    if (horizontalDistance > radius) {
      var targetYaw = Math.atan2(dz, dx);
      var directionYaw = Math.atan2(directionZ, directionX);
      var horizontalAngularRadius = Math.asin(Math.min(1, radius / horizontalDistance));
      if (Math.abs(normalizeAngle(targetYaw - directionYaw)) > horizontalHalfAngle + horizontalAngularRadius) {
        return false;
      }
    }

    var directionPitch = Math.atan2(
      directionY,
      Math.sqrt(directionX * directionX + directionZ * directionZ)
    );
    var bottomPitch = Math.atan2(bottomY - oy, horizontalDistance);
    var topPitch = Math.atan2(topY - oy, horizontalDistance);
    var minPitch = Math.min(bottomPitch, topPitch);
    var maxPitch = Math.max(bottomPitch, topPitch);
    var verticalAngularRadius = closestDistance <= radius
      ? Math.PI / 2
      : Math.asin(Math.min(1, radius / closestDistance));
    var verticalHalfAngle = Math.max(0, Number(options.verticalHalfAngle) || 0);
    return directionPitch >= minPitch - verticalHalfAngle - verticalAngularRadius
      && directionPitch <= maxPitch + verticalHalfAngle + verticalAngularRadius;
  }


  function circleOverlapsAabbXZ(x, z, radius, bounds) {
    if (!bounds) return false;
    var px = Number(x) || 0;
    var pz = Number(z) || 0;
    var r = Math.max(0, Number(radius) || 0);
    var closestX = clamp(px, Number(bounds.minX) || 0, Number(bounds.maxX) || 0);
    var closestZ = clamp(pz, Number(bounds.minZ) || 0, Number(bounds.maxZ) || 0);
    var dx = px - closestX;
    var dz = pz - closestZ;
    return dx * dx + dz * dz < r * r;
  }


  function sampleOpenPointXZ(rng, options) {
    options = options || {};
    if (!rng || typeof rng.range !== "function") return null;
    var bounds = options.bounds || {};
    var minX = Number(bounds.minX);
    var maxX = Number(bounds.maxX);
    var minZ = Number(bounds.minZ);
    var maxZ = Number(bounds.maxZ);
    if (![minX, maxX, minZ, maxZ].every(Number.isFinite)) return null;
    var radius = Math.max(0, Number(options.radius) || 0);
    minX += radius;
    maxX -= radius;
    minZ += radius;
    maxZ -= radius;
    if (maxX < minX || maxZ < minZ) return null;

    var colliders = Array.isArray(options.colliders) ? options.colliders : [];
    var getBounds = typeof options.getBounds === "function" ? options.getBounds : aabbFromBox;
    var reference = options.reference || null;
    var minDistance = Math.max(0, Number(options.minDistance) || 0);
    var minDistanceSquared = minDistance * minDistance;
    var rawMaxDistance = Number(options.maxDistance);
    var hasMaxDistance = Number.isFinite(rawMaxDistance) && rawMaxDistance >= 0;
    var maxDistance = hasMaxDistance ? rawMaxDistance : Infinity;
    if (hasMaxDistance && maxDistance < minDistance) return null;
    var maxDistanceSquared = maxDistance * maxDistance;
    var radialSampling = !!reference && hasMaxDistance;
    var heading = Number(options.heading) || 0;
    var rawMinAngleOffset = Number(options.minAngleOffset);
    var rawMaxAngleOffset = Number(options.maxAngleOffset);
    var hasAngleOffsets = Number.isFinite(rawMinAngleOffset) && Number.isFinite(rawMaxAngleOffset);
    var minAngleOffset = hasAngleOffsets ? Math.min(rawMinAngleOffset, rawMaxAngleOffset) : -Math.PI;
    var maxAngleOffset = hasAngleOffsets ? Math.max(rawMinAngleOffset, rawMaxAngleOffset) : Math.PI;
    var mirrorAngle = !!options.mirrorAngle;
    var accept = typeof options.accept === "function" ? options.accept : null;
    var maxAttempts = Math.max(1, Math.floor(Number(options.maxAttempts) || 96));

    for (var attempt = 0; attempt < maxAttempts; attempt += 1) {
      var point;
      if (radialSampling) {
        var distance = Math.sqrt(rng.range(minDistanceSquared, maxDistanceSquared));
        var angleOffset = rng.range(minAngleOffset, maxAngleOffset);
        if (mirrorAngle && rng.range(0, 1) < 0.5) angleOffset *= -1;
        var angle = heading + angleOffset;
        point = {
          x: (Number(reference.x) || 0) + Math.cos(angle) * distance,
          z: (Number(reference.z) || 0) + Math.sin(angle) * distance,
        };
      } else {
        point = { x: rng.range(minX, maxX), z: rng.range(minZ, maxZ) };
      }
      if (point.x < minX || point.x > maxX || point.z < minZ || point.z > maxZ) continue;
      if (reference && (minDistance > 0 || hasMaxDistance)) {
        var dx = point.x - (Number(reference.x) || 0);
        var dz = point.z - (Number(reference.z) || 0);
        var distanceSquared = dx * dx + dz * dz;
        if (distanceSquared < minDistanceSquared || distanceSquared > maxDistanceSquared) continue;
      }
      var blocked = false;
      for (var i = 0; i < colliders.length; i += 1) {
        if (circleOverlapsAabbXZ(point.x, point.z, radius, getBounds(colliders[i]))) {
          blocked = true;
          break;
        }
      }
      if (blocked || (accept && !accept(point))) continue;
      point.attempt = attempt + 1;
      return point;
    }
    return null;
  }


  function moveCircleWithAabbs(position, delta, options) {
    position = position || {};
    delta = delta || {};
    options = options || {};
    var x = Number(position.x) || 0;
    var z = Number(position.z) || 0;
    var dx = Number(delta.x) || 0;
    var dz = Number(delta.z) || 0;
    var radius = Math.max(0, Number(options.radius) || 0);
    var bounds = options.bounds || null;
    var colliders = Array.isArray(options.colliders) ? options.colliders : [];
    var getBounds = typeof options.getBounds === "function" ? options.getBounds : aabbFromBox;
    var filter = typeof options.filter === "function" ? options.filter : null;
    var circles = Array.isArray(options.circles) ? options.circles : [];
    var getCircle = typeof options.getCircle === "function"
      ? options.getCircle
      : function defaultCircle(candidate) { return candidate; };
    var circleFilter = typeof options.circleFilter === "function" ? options.circleFilter : null;
    var circlePadding = Math.max(0, Number(options.circlePadding) || 0);

    function blocked(nextX, nextZ, currentX, currentZ) {
      if (bounds && (
        nextX - radius < bounds.minX || nextX + radius > bounds.maxX ||
        nextZ - radius < bounds.minZ || nextZ + radius > bounds.maxZ
      )) return true;
      for (var i = 0; i < colliders.length; i += 1) {
        if (filter && !filter(colliders[i])) continue;
        if (circleOverlapsAabbXZ(nextX, nextZ, radius, getBounds(colliders[i]))) return true;
      }
      for (var circleIndex = 0; circleIndex < circles.length; circleIndex += 1) {
        if (circleFilter && !circleFilter(circles[circleIndex])) continue;
        var circle = getCircle(circles[circleIndex], circleIndex);
        if (!circle) continue;
        var circleRadius = Math.max(0, Number(circle.radius === undefined ? circle.r : circle.radius) || 0);
        var minDistance = radius + circleRadius + circlePadding;
        var nextDx = nextX - (Number(circle.x) || 0);
        var nextDz = nextZ - (Number(circle.z) || 0);
        var nextDistanceSquared = nextDx * nextDx + nextDz * nextDz;
        if (nextDistanceSquared >= minDistance * minDistance) continue;
        var currentDx = currentX - (Number(circle.x) || 0);
        var currentDz = currentZ - (Number(circle.z) || 0);
        var currentDistanceSquared = currentDx * currentDx + currentDz * currentDz;
        if (currentDistanceSquared < minDistance * minDistance
          && nextDistanceSquared > currentDistanceSquared + 1e-12) continue;
        return true;
      }
      return false;
    }

    var blockedX = blocked(x + dx, z, x, z);
    if (!blockedX) x += dx;
    var blockedZ = blocked(x, z + dz, x, z);
    if (!blockedZ) z += dz;
    return {
      x: x,
      z: z,
      movedX: !blockedX && dx !== 0,
      movedZ: !blockedZ && dz !== 0,
      blockedX: blockedX,
      blockedZ: blockedZ,
    };
  }


  function aabbFromBox(spec) {
    spec = spec || {};
    var x = Number(spec.x);
    if (!Number.isFinite(x)) x = 0;
    var z = Number(spec.z);
    if (!Number.isFinite(z)) z = Number(spec.y);
    if (!Number.isFinite(z)) z = 0;
    var width = Number(spec.width);
    var depth = Number(spec.depth);
    var height = Number(spec.height);
    var baseY = Number(spec.baseY);
    if (!Number.isFinite(width) || width <= 0) width = Number(spec.r) > 0 ? Number(spec.r) * 2 : 1;
    if (!Number.isFinite(depth) || depth <= 0) depth = width;
    if (!Number.isFinite(baseY)) baseY = Number(spec.minY);
    if (!Number.isFinite(baseY)) baseY = 0;
    if (!Number.isFinite(height) || height <= 0) {
      var topY = Number(spec.top_y);
      height = Number.isFinite(topY) && topY > baseY ? topY - baseY : 1;
    }
    return {
      minX: x - width / 2,
      maxX: x + width / 2,
      minY: baseY,
      maxY: baseY + height,
      minZ: z - depth / 2,
      maxZ: z + depth / 2,
    };
  }


  function aabbOverlap(a, b) {
    return !!(
      a && b &&
      a.minX < b.maxX && a.maxX > b.minX &&
      a.minY < b.maxY && a.maxY > b.minY &&
      a.minZ < b.maxZ && a.maxZ > b.minZ
    );
  }


  function horizontalOverlap(a, b) {
    return !!(
      a && b &&
      a.minX < b.maxX && a.maxX > b.minX &&
      a.minZ < b.maxZ && a.maxZ > b.minZ
    );
  }


  function raycastAabb(origin, direction, bounds, maxDistance) {
    origin = origin || {};
    direction = direction || {};
    bounds = bounds || {};
    var range = Number(maxDistance);
    if (!Number.isFinite(range) || range <= 0) range = Infinity;
    var tMin = 0;
    var tMax = range;
    var enterNormal = { x: 0, y: 0, z: 0 };

    function testAxis(start, dir, min, max, normalNegative, normalPositive) {
      if (Math.abs(dir) < 0.000001) return start >= min && start <= max;
      var t1 = (min - start) / dir;
      var t2 = (max - start) / dir;
      var normal = normalNegative;
      if (t1 > t2) {
        var tmp = t1;
        t1 = t2;
        t2 = tmp;
        normal = normalPositive;
      }
      if (t1 > tMin) {
        tMin = t1;
        enterNormal = normal;
      }
      tMax = Math.min(tMax, t2);
      return tMin <= tMax;
    }

    var ox = Number(origin.x) || 0;
    var oy = Number(origin.y) || 0;
    var oz = Number(origin.z) || 0;
    var dx = Number(direction.x) || 0;
    var dy = Number(direction.y) || 0;
    var dz = Number(direction.z) || 0;
    if (!testAxis(ox, dx, bounds.minX, bounds.maxX, { x: -1, y: 0, z: 0 }, { x: 1, y: 0, z: 0 })) return null;
    if (!testAxis(oy, dy, bounds.minY, bounds.maxY, { x: 0, y: -1, z: 0 }, { x: 0, y: 1, z: 0 })) return null;
    if (!testAxis(oz, dz, bounds.minZ, bounds.maxZ, { x: 0, y: 0, z: -1 }, { x: 0, y: 0, z: 1 })) return null;
    if (tMax < 0 || tMin > range) return null;
    var distance = Math.max(0, tMin);
    return {
      distance: distance,
      normal: enterNormal,
      point: {
        x: ox + dx * distance,
        y: oy + dy * distance,
        z: oz + dz * distance,
      },
    };
  }


  function raycastAabbs(origin, direction, candidates, options) {
    options = options || {};
    var range = Number(options.maxDistance);
    if (!Number.isFinite(range) || range <= 0) range = Infinity;
    var getBounds = typeof options.bounds === "function" ? options.bounds : aabbFromBox;
    var best = null;
    for (var i = 0; Array.isArray(candidates) && i < candidates.length; i += 1) {
      var candidate = candidates[i];
      var block = candidate && candidate.block ? candidate.block : candidate;
      var hit = raycastAabb(origin, direction, getBounds(block, candidate), range);
      if (!hit || (best && hit.distance >= best.distance)) continue;
      best = {
        kind: candidate && candidate.kind,
        block: block,
        candidate: candidate,
        distance: hit.distance,
        normal: hit.normal,
        point: hit.point,
      };
    }
    return best;
  }


  function hasLineOfSight(origin, target, blockers, options) {
    options = options || {};
    var dx = (Number(target && target.x) || 0) - (Number(origin && origin.x) || 0);
    var dy = (Number(target && target.y) || 0) - (Number(origin && origin.y) || 0);
    var dz = (Number(target && target.z) || 0) - (Number(origin && origin.z) || 0);
    var distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
    if (distance <= 0.000001) return true;
    var hit = raycastAabbs(
      origin,
      { x: dx / distance, y: dy / distance, z: dz / distance },
      blockers || [],
      {
        maxDistance: distance,
        bounds: options.bounds,
      }
    );
    var epsilon = Number(options.epsilon);
    if (!Number.isFinite(epsilon)) epsilon = 0.02;
    return !hit || hit.distance >= distance - epsilon;
  }


  function segmentSphereHitDistance(start, end, center, radius) {
    var dx = (Number(end && end.x) || 0) - (Number(start && start.x) || 0);
    var dy = (Number(end && end.y) || 0) - (Number(start && start.y) || 0);
    var dz = (Number(end && end.z) || 0) - (Number(start && start.z) || 0);
    var ox = (Number(start && start.x) || 0) - (Number(center && center.x) || 0);
    var oy = (Number(start && start.y) || 0) - (Number(center && center.y) || 0);
    var oz = (Number(start && start.z) || 0) - (Number(center && center.z) || 0);
    var a = dx * dx + dy * dy + dz * dz;
    var hitRadius = Math.max(0, Number(radius) || 0);
    if (a <= 0.0000001) return Math.sqrt(ox * ox + oy * oy + oz * oz) <= hitRadius ? 0 : null;
    var b = 2 * (ox * dx + oy * dy + oz * dz);
    var c = ox * ox + oy * oy + oz * oz - hitRadius * hitRadius;
    var discriminant = b * b - 4 * a * c;
    if (discriminant < 0) return null;
    var root = Math.sqrt(discriminant);
    var t1 = (-b - root) / (2 * a);
    var t2 = (-b + root) / (2 * a);
    var t = t1 >= 0 && t1 <= 1 ? t1 : (t2 >= 0 && t2 <= 1 ? t2 : null);
    return t === null ? null : Math.sqrt(a) * t;
  }


  function segmentAabbHitDistance(start, end, bounds, padding) {
    if (!bounds) return null;
    var dx = (Number(end && end.x) || 0) - (Number(start && start.x) || 0);
    var dy = (Number(end && end.y) || 0) - (Number(start && start.y) || 0);
    var dz = (Number(end && end.z) || 0) - (Number(start && start.z) || 0);
    var distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
    if (distance <= 0.000001) return null;
    var amount = Math.max(0, Number(padding) || 0);
    var expanded = {
      minX: bounds.minX - amount,
      maxX: bounds.maxX + amount,
      minY: bounds.minY - amount,
      maxY: bounds.maxY + amount,
      minZ: bounds.minZ - amount,
      maxZ: bounds.maxZ + amount,
    };
    var hit = raycastAabb(start, { x: dx / distance, y: dy / distance, z: dz / distance }, expanded, distance);
    return hit ? hit.distance : null;
  }


  function surfaceFromAabbHit(hit, bounds, scale) {
    if (!hit || !bounds || !hit.normal) return null;
    var shrink = Number(scale);
    if (!Number.isFinite(shrink) || shrink <= 0) shrink = 0.96;
    var centerX = (bounds.minX + bounds.maxX) / 2;
    var centerY = (bounds.minY + bounds.maxY) / 2;
    var centerZ = (bounds.minZ + bounds.maxZ) / 2;
    var nx = hit.normal.x > 0.5 ? 1 : (hit.normal.x < -0.5 ? -1 : 0);
    var ny = hit.normal.y > 0.5 ? 1 : (hit.normal.y < -0.5 ? -1 : 0);
    var nz = hit.normal.z > 0.5 ? 1 : (hit.normal.z < -0.5 ? -1 : 0);
    var surface = {
      normal: { x: nx, y: ny, z: nz },
      position: { x: centerX, y: centerY, z: centerZ },
      width: Math.max(0.08, bounds.maxX - bounds.minX),
      height: Math.max(0.08, bounds.maxY - bounds.minY),
    };
    if (nx) {
      surface.position.x = nx > 0 ? bounds.maxX : bounds.minX;
      surface.width = Math.max(0.08, bounds.maxZ - bounds.minZ);
      surface.height = Math.max(0.08, bounds.maxY - bounds.minY);
    } else if (ny) {
      surface.position.y = ny > 0 ? bounds.maxY : bounds.minY;
      surface.width = Math.max(0.08, bounds.maxX - bounds.minX);
      surface.height = Math.max(0.08, bounds.maxZ - bounds.minZ);
    } else if (nz) {
      surface.position.z = nz > 0 ? bounds.maxZ : bounds.minZ;
      surface.width = Math.max(0.08, bounds.maxX - bounds.minX);
      surface.height = Math.max(0.08, bounds.maxY - bounds.minY);
    } else {
      return null;
    }
    surface.width *= shrink;
    surface.height *= shrink;
    return surface;
  }


  function Rng(seed, defaultSeed, options) {
    this.defaultSeed = defaultSeed === undefined ? 42 : defaultSeed;
    this.allowZeroSeed = !!(options && options.allowZeroSeed);
    this.setSeed(seed);
  }

  Rng.prototype.setSeed = function setSeed(seed) {
    var normalized = parseUnsignedInt(seed, this.defaultSeed);
    this.seed = normalized;
    this.state = normalized >>> 0;
    if (this.state === 0 && !this.allowZeroSeed) this.state = 0x6d2b79f5;
    return this.seed;
  };

  Rng.prototype.next = function next() {
    var state = this.state >>> 0;
    state += 0x6d2b79f5;
    var t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    this.state = state >>> 0;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };

  Rng.prototype.randint = function randint(minInclusive, maxExclusive) {
    if (maxExclusive <= minInclusive) return minInclusive;
    return minInclusive + Math.floor(this.next() * (maxExclusive - minInclusive));
  };

  Rng.prototype.range = function range(minInclusive, maxExclusive) {
    if (maxExclusive <= minInclusive) return minInclusive;
    return minInclusive + this.next() * (maxExclusive - minInclusive);
  };

  Rng.prototype.choice = function choice(items) {
    return items[this.randint(0, items.length)];
  };

  Rng.prototype.choiceExcept = function choiceExcept(items, excluded) {
    if (!items || !items.length) return undefined;
    if (items.length === 1) return items[0];
    var excludedIndex = items.indexOf(excluded);
    if (excludedIndex < 0) return this.choice(items);
    var index = this.randint(0, items.length - 1);
    return items[index >= excludedIndex ? index + 1 : index];
  };

  window.BaseGameletCommon = Object.freeze({
    Rng: Rng,
    object: Object.freeze({
      hasOwn: hasOwn,
    }),
    math: Object.freeze({
      clamp: clamp,
      finiteNumber: finiteNumber,
      normalizeAngle: normalizeAngle,
      unsignedInt: parseUnsignedInt,
    }),
    metrics: Object.freeze({
      readNumber: readMetricNumber,
    }),
    geometry2d: Object.freeze({
      clonePoint: clonePoint,
      distance: distance2D,
      rectanglesOverlap: rectsOverlap,
      circleOverlapsRectangle: circleRectOverlap,
      segmentRectangleIntersection: segmentRectIntersection,
      segmentCircleIntersection: segmentCircleIntersection,
      rayRectangleBoundaryIntersection: rayRectangleBoundaryIntersection,
      projectPointToSegment: projectPointToSegment,
      distanceToSegment: distanceToSegment,
    }),
    geometry3d: Object.freeze({
      distance: distance3,
      horizontalDistance: horizontalDistance,
      circleIntersectsSectorXZ: circleIntersectsSectorXZ,
      raycastVerticalCapsule: raycastVerticalCapsule,
      verticalCapsuleIntersectsViewCone: verticalCapsuleIntersectsViewCone,
      circleOverlapsAabbXZ: circleOverlapsAabbXZ,
      sampleOpenPointXZ: sampleOpenPointXZ,
      moveCircleWithAabbs: moveCircleWithAabbs,
      aabbFromBox: aabbFromBox,
      aabbOverlap: aabbOverlap,
      horizontalOverlap: horizontalOverlap,
      raycastAabb: raycastAabb,
      raycastAabbs: raycastAabbs,
      hasLineOfSight: hasLineOfSight,
      segmentSphereHitDistance: segmentSphereHitDistance,
      segmentAabbHitDistance: segmentAabbHitDistance,
      surfaceFromAabbHit: surfaceFromAabbHit,
    }),
    track: Object.freeze({
      sweptCircleIntersectsSegment: sweptCircleIntersectsSegment,
      crossSection: crossSectionSegment,
      distanceToPolyline: distanceToPolyline,
      polylineLength: polylineLength,
      sampleAtDistance: samplePolylineAtDistance,
      sampleAtLowCurvatureDistance: samplePolylineAtLowCurvatureDistance,
      buildRoundedClosed: buildRoundedClosedPolyline,
      buildClosedSpline: buildClosedSpline,
      validateClosed: validateClosedTrack,
      randomizeClosedStart: randomizeClosedPolylineStart,
    }),
  });
})();
