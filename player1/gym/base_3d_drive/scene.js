(function countryDriveScene() {
  "use strict";

  var G3D = window.BaseGamelet3D;
  var U = window.BaseGameletCommon;
  var ASSETS = Object.freeze([
    "car_sport", "cone", "tree_oak", "tree_pine", "rock", "street_lamp", "road_sign", "house_a", "house_f", "grass", "bush",
  ]);

  function routeNormal(route, index) {
    var point = route[index];
    if ((index === 0 || index === route.length - 1) && Number.isFinite(point.tangentAngle)) {
      return { x: -Math.sin(point.tangentAngle), y: Math.cos(point.tangentAngle) };
    }
    var a = route[Math.max(0, index - 1)], b = route[Math.min(route.length - 1, index + 1)];
    var dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1;
    return { x: -dy / length, y: dx / length };
  }

  function offsetRoute(route, offset) {
    return route.map(function offsetPoint(point, index) {
      var normal = routeNormal(route, index);
      return { x: point.x + normal.x * offset, y: point.y + normal.y * offset, tangentAngle: point.tangentAngle };
    });
  }

  function routeSampleAtDistance(route, targetDistance) {
    var traveled = 0;
    for (var i = 0; i < route.length - 1; i += 1) {
      var a = route[i], b = route[i + 1], dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy);
      if (length <= 0.0001) continue;
      if (traveled + length >= targetDistance) {
        var t = U.math.clamp((targetDistance - traveled) / length, 0, 1);
        return { x: a.x + dx * t, y: a.y + dy * t, angle: Math.atan2(dy, dx) };
      }
      traveled += length;
    }
    var last = route[route.length - 1], previous = route[route.length - 2];
    return { x: last.x, y: last.y, angle: Number.isFinite(last.tangentAngle)
      ? last.tangentAngle : Math.atan2(last.y - previous.y, last.x - previous.x) };
  }

  function repeatingPhase(origin, scale) {
    return ((origin * scale) % 1 + 1) % 1;
  }

  function routeRibbon(w, parent, route, halfWidth, y, color, map, originX) {
    var vertices = [], indices = [], uvs = [], phase = repeatingPhase(originX, 0.7);
    for (var i = 0; i < route.length; i += 1) {
      var normal = routeNormal(route, i);
      vertices.push(route[i].x + normal.x * halfWidth, y, route[i].y + normal.y * halfWidth);
      vertices.push(route[i].x - normal.x * halfWidth, y, route[i].y - normal.y * halfWidth);
    }
    for (var s = 0; s < route.length - 1; s += 1) {
      var left = s * 2, right = left + 1, nextLeft = left + 2, nextRight = left + 3;
      indices.push(left, nextLeft, right, right, nextLeft, nextRight);
    }
    for (var u = 0; u < vertices.length; u += 3) uvs.push(vertices[u] * 0.7 + phase, vertices[u + 2] * 0.7);
    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
    geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
    geometry.setIndex(indices); geometry.computeVertexNormals();
    var mesh = new THREE.Mesh(geometry, w.material({ color: color, map: map || null,
      roughness: 0.94, metalness: 0, side: THREE.DoubleSide }));
    mesh.receiveShadow = true; parent.add(mesh); return mesh;
  }

  function routeRail(w, parent, route, offset, color) {
    var vertices = [], indices = [], halfThickness = 0.035, baseY = 0.19, height = 0.1;
    for (var i = 0; i < route.length; i += 1) {
      var normal = routeNormal(route, i), centerX = route[i].x + normal.x * offset, centerZ = route[i].y + normal.y * offset;
      var innerX = centerX - normal.x * halfThickness, innerZ = centerZ - normal.y * halfThickness;
      var outerX = centerX + normal.x * halfThickness, outerZ = centerZ + normal.y * halfThickness;
      vertices.push(innerX, baseY, innerZ, outerX, baseY, outerZ,
        innerX, baseY + height, innerZ, outerX, baseY + height, outerZ);
    }
    for (var s = 0; s < route.length - 1; s += 1) {
      var current = s * 4, next = current + 4;
      indices.push(current, next, current + 2, current + 2, next, next + 2,
        current + 1, current + 3, next + 1, current + 3, next + 3, next + 1,
        current + 2, next + 2, current + 3, current + 3, next + 2, next + 3,
        current, current + 1, next, current + 1, next + 1, next);
    }
    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
    geometry.setIndex(indices); geometry.computeVertexNormals();
    var mesh = new THREE.Mesh(geometry, w.material({ color: color, roughness: 0.45, metalness: 0.45, side: THREE.DoubleSide }));
    mesh.receiveShadow = true; parent.add(mesh); return mesh;
  }

  function chunkGround(game, chunk, group) {
    var w = game.world3d, context = game.assetContext;
    var left = chunk.startX - chunk.originX - (chunk.index === 0 ? 80 : 0), right = chunk.endX - chunk.originX;
    var nearZ = game.level.depth / 2 - 80, farZ = game.level.depth / 2 + 80;
    var vertices = [left, 0, nearZ, left, 0, farZ, right, 0, nearZ, right, 0, farZ];
    var phase = repeatingPhase(chunk.originX, 0.5), uvs = [];
    for (var i = 0; i < vertices.length; i += 3) uvs.push(vertices[i] * 0.5 + phase, vertices[i + 2] * 0.5);
    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
    geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
    geometry.setIndex([0, 1, 2, 2, 1, 3]); geometry.computeVertexNormals();
    var texture = G3D.textures.createSurface(context, "verge", { baseColor: context.color("vergeDark"),
      accentColor: context.color("vergeDarkAccent"), repeatX: 1, repeatY: 1 });
    var ground = new THREE.Mesh(geometry, w.material({ color: 0xffffff, map: texture, roughness: 0.94 }));
    ground.name = "country-ground"; ground.receiveShadow = true; group.add(ground);
  }

  function buildChunk(game, chunk) {
    var w = game.world3d, context = game.assetContext, group = new THREE.Group();
    group.name = "country-chunk-" + chunk.index; group.userData.chunkIndex = chunk.index;
    var route = chunk.route.map(function local(point) {
      return { x: point.x - chunk.originX, y: point.y, tangentAngle: point.tangentAngle };
    });
    var startX = chunk.startX - chunk.originX, endX = chunk.endX - chunk.originX, span = endX - startX;
    var batches = {}, materials = {};
    function color(role, fallback) { return context.color(role, fallback); }
    function box(role, x, y, z, width, height, depth, rotationY) {
      (batches[role] || (batches[role] = [])).push([x, y, z, width, height, depth, rotationY || 0]);
    }
    // Custom geometry, materials and textures belong to this chunk. Imported model
    // resources retain the asset engine's own lifetime and instance ownership.
    materials.steel = w.material({ color: color("metal"), roughness: 0.56, metalness: 0.38 });
    materials.white = w.material({ color: color("roadEdge"), roughness: 0.8 });
    materials.yellow = w.material({ color: color("lane"), roughness: 0.8 });
    materials.dark = w.material({ color: color("darkMetal"), roughness: 0.68 });
    chunkGround(game, chunk, group);
    var asphalt = G3D.textures.createSurface(context, "road", { repeatX: 1, repeatY: 1 });
    routeRibbon(w, group, route, 1.42, 0.058, 0xb4ac94, null, chunk.originX).name = "country-shoulder";
    routeRibbon(w, group, route, 1.29, 0.076, color("darkMetal"), null, chunk.originX).name = "country-road-base";
    routeRibbon(w, group, route, 1.15, 0.098, 0xffffff, asphalt, chunk.originX).name = "country-asphalt";
    routeRibbon(w, group, offsetRoute(route, 1.07), 0.022, 0.101, color("roadEdge"), null, chunk.originX).name = "country-edge-left";
    routeRibbon(w, group, offsetRoute(route, -1.07), 0.022, 0.101, color("roadEdge"), null, chunk.originX).name = "country-edge-right";
    if (chunk.index === 0) {
      [[1.42, 0.057, 0xb4ac94], [1.29, 0.075, color("darkMetal")], [1.15, 0.097, color("road")]].forEach(function startCap(spec) {
        var cap = new THREE.Mesh(new THREE.CircleGeometry(spec[0], 32), w.material({ color: spec[2], roughness: 0.94 }));
        cap.name = "country-road-start"; cap.position.set(route[0].x, spec[1], route[0].y);
        cap.rotation.x = -Math.PI / 2; cap.receiveShadow = true; group.add(cap);
      });
    }
    for (var d = 0.45; d < chunk.routeLength - 0.25; d += 0.9) {
      var sample = routeSampleAtDistance(route, d);
      box("yellow", sample.x, 0.108, sample.y, 0.43, 0.014, 0.033, -sample.angle);
    }
    [-1, 1].forEach(function roadside(side) {
      routeRail(w, group, route, 1.24 * side, color("neutral")).name = "country-rail-" + side;
      for (var distance = 0.12; distance < chunk.routeLength - 0.12; distance += 1.15) {
        var p = routeSampleAtDistance(route, distance), nx = -Math.sin(p.angle), nz = Math.cos(p.angle);
        box("steel", p.x + nx * 1.24 * side, 0.23, p.y + nz * 1.24 * side, 0.052, 0.27, 0.052, -p.angle);
        box(side === 1 ? "white" : "yellow", p.x + nx * 1.205 * side, 0.245, p.y + nz * 1.205 * side,
          0.045, 0.035, 0.012, -p.angle);
      }
      for (var curb = 0.25, n = 0; curb < chunk.routeLength - 0.25; curb += 0.5, n += 1) {
        var q = routeSampleAtDistance(route, curb);
        box(n % 2 === 0 ? "white" : "dark", q.x - Math.sin(q.angle) * side * 1.18, 0.09,
          q.y + Math.cos(q.angle) * side * 1.18, 0.45, 0.025, 0.06, -q.angle);
      }
    });

    var gates = [];
    chunk.checkpoints.forEach(function checkpoint(cp) {
      var gate = new THREE.Group(); gate.name = "country-checkpoint-" + cp.index;
      gate.position.set(cp.x - chunk.originX, 0.105, cp.y); gate.rotation.y = -cp.tangentAngle - Math.PI / 2; group.add(gate);
      var activeMaterial = w.material({ color: color("goal"), roughness: 0.65, emissive: color("goal"), emissiveIntensity: 0.2 });
      var line = new THREE.Mesh(new THREE.BoxGeometry(cp.lineHalfWidth * 2, 0.012, 0.14), activeMaterial);
      line.position.y = 0.012; gate.add(line);
      [-1, 1].forEach(function flag(side) {
        var pole = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.82, 0.045), materials.dark);
        pole.position.set(side * cp.lineHalfWidth, 0.41, 0); gate.add(pole);
        var banner = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.52, 0.025), activeMaterial);
        banner.position.set(side * cp.lineHalfWidth, 0.51, 0); gate.add(banner);
      });
      var halo = new THREE.Mesh(new THREE.PlaneGeometry(cp.lineHalfWidth * 2, 0.43),
        new THREE.MeshBasicMaterial({ color: color("goal"), transparent: true, opacity: 0.12,
          side: THREE.DoubleSide, depthWrite: false, toneMapped: false }));
      halo.rotation.x = -Math.PI / 2; halo.position.set(0, 0.007, 0); gate.add(halo);
      gates.push({ index: cp.index, material: activeMaterial, halo: halo });
    });

    function asset(id, options) { return game.createAsset(id, Object.assign({ parent: group, forward_axis: "+z" }, options)); }
    var seed = window.GameEngineCore.seeds.forDomain(game, "scene", 42);
    var random = new U.Rng(((seed + 7319) ^ Math.imul(chunk.index + 1, 0x9e3779b1)) >>> 0);
    function clearance(x, z) { return U.track.distanceToPolyline({ x: x, y: z }, route).distance; }
    var planted = 0, treeMargin = Math.min(4, span / 4);
    for (var attempt = 0; attempt < 160 && planted < 24; attempt += 1) {
      var tx = random.range(startX + treeMargin, endX - treeMargin), tz = random.range(-8, game.level.depth + 8);
      if (clearance(tx, tz) < 5.8) continue;
      asset(planted % 3 === 0 ? "tree_oak" : "tree_pine", {
        x: tx, z: tz, target_height: random.range(1.9, 3.5), rotationY: random.range(-Math.PI, Math.PI),
      });
      if (planted % 5 === 0) asset("rock", { x: tx + 0.8, z: tz - 0.2, target_height: 0.28 });
      planted += 1;
    }
    for (var verge = 0; verge < 24; verge += 1) {
      var v = routeSampleAtDistance(route, (verge + 0.5) / 24 * chunk.routeLength);
      var side = verge % 2 ? 1 : -1, offset = 1.65 + random.range(0, 1.8);
      var gx = v.x - Math.sin(v.angle) * side * offset, gz = v.y + Math.cos(v.angle) * side * offset;
      if (gx > startX + 0.5 && gx < endX - 0.5 && clearance(gx, gz) > 1.55) asset(verge % 4 ? "grass" : "bush", {
        x: gx, z: gz, target_height: verge % 4 ? 0.11 : 0.27, rotationY: random.range(-Math.PI, Math.PI),
      });
    }
    for (var house = 0; house < 4; house += 1) {
      var hx = startX + span * (house + 0.5) / 4, hz = house % 2 ? game.level.depth + 5 : -6;
      if (hx > startX + 2.5 && hx < endX - 2.5 && clearance(hx, hz) > 6) asset(house % 2 ? "house_f" : "house_a", {
        x: hx, z: hz, target_height: 2.1 + (house % 2) * 0.35, rotationY: Math.PI / 2,
      });
    }
    for (var hill = 0; hill < 4; hill += 1) {
      var mound = new THREE.Mesh(new THREE.SphereGeometry(1, 12, 7), w.material({
        color: color(hill % 2 ? "vergeDark" : "verge"), roughness: 1, flatShading: true,
      }));
      mound.position.set(startX + span * (hill % 2 ? 0.75 : 0.25), -2.8,
        hill < 2 ? -29 : game.level.depth + 29);
      mound.scale.set(Math.min(8, span * 0.22), 6 + hill % 3, 12); mound.receiveShadow = true; group.add(mound);
    }
    [0.15, 0.5, 0.85].forEach(function trackProps(fraction, index) {
      var p = routeSampleAtDistance(route, chunk.routeLength * fraction), nx = -Math.sin(p.angle), nz = Math.cos(p.angle);
      asset("road_sign", { x: p.x + nx * 1.7, z: p.y + nz * 1.7, target_height: 0.65, rotationY: -p.angle - Math.PI / 2 });
      asset("street_lamp", { x: p.x - nx * 2.0, z: p.y - nz * 2.0, target_height: 1.65, rotationY: -p.angle });
      if (index !== 1) asset("cone", { x: p.x + nx * 1.48, z: p.y + nz * 1.48, target_height: 0.18 });
    });
    Object.keys(batches).forEach(function commit(role) {
      var list = batches[role], mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), materials[role], list.length);
      var transform = new THREE.Object3D();
      list.forEach(function place(spec, i) {
        transform.position.set(spec[0], spec[1], spec[2]); transform.scale.set(spec[3], spec[4], spec[5]);
        transform.rotation.set(0, spec[6], 0); transform.updateMatrix(); mesh.setMatrixAt(i, transform.matrix);
      });
      mesh.instanceMatrix.needsUpdate = true; mesh.castShadow = role === "steel"; mesh.receiveShadow = true;
      mesh.name = "country-road-" + role; group.add(mesh);
    });
    w.root.add(group);
    return { group: group, gates: gates };
  }

  function build(game) {
    var car = game.createAsset("car_sport", { target_height: 0.44, forward_axis: "+z" });
    var shadow = new THREE.Mesh(new THREE.CircleGeometry(0.48, 32), new THREE.MeshBasicMaterial({
      color: 0x183023, transparent: true, opacity: 0.17, depthWrite: false,
    }));
    shadow.rotation.x = -Math.PI / 2; shadow.scale.set(1.2, 0.75, 1); game.world3d.root.add(shadow);
    return { car: car, carVisual: G3D.assets.getVisual(car), shadow: shadow, chunks: new Map() };
  }

  function sync(game, scene) {
    var time = game.gameTimeMs, context = game.assetContext, originX = game.renderOriginX;
    var active = new Set(game.level.chunks.map(function chunkIndex(chunk) { return chunk.index; }));
    scene.chunks.forEach(function retire(chunk, index) {
      if (active.has(index)) return;
      G3D.entities.remove(chunk.group); scene.chunks.delete(index);
    });
    game.level.chunks.forEach(function update(chunk) {
      var rendered = scene.chunks.get(chunk.index);
      if (!rendered) { rendered = buildChunk(game, chunk); scene.chunks.set(chunk.index, rendered); }
      rendered.group.position.x = chunk.originX - originX;
      rendered.gates.forEach(function gate(item) {
        var activeGate = item.index === game.routeCheckpointIndex, passed = item.index < game.routeCheckpointIndex;
        var color = activeGate ? context.color("goal") : passed ? 0x557765 : 0xa9b7ad;
        item.material.color.setHex(color); item.material.emissive.setHex(activeGate ? color : 0);
        item.material.emissiveIntensity = activeGate ? 0.18 : 0; item.halo.visible = activeGate;
        item.halo.material.opacity = 0.11 + 0.04 * Math.sin(time * 0.005);
      });
    });
    var localX = game.x - originX;
    scene.car.position.set(localX, 0.101, game.y); scene.car.rotation.y = Math.PI / 2 - game.angle;
    var circumference = Math.PI * 2 * 0.12, phase = ((game.visualDistance / circumference) % 1 + 1) % 1;
    scene.carVisual.applyPose({ timeMs: time, clip: "roll", clipTimeMs: phase * 1000,
      materialRoles: { paint: { color: context.color("vehicle"), roughness: 0.38, metalness: 0.15 } } });
    scene.shadow.position.set(localX, 0.102, game.y); scene.shadow.rotation.z = -game.angle;
    // Follow the rebased car while preserving the appearance domain's light direction.
    var w = game.world3d, light = w.sunLight, base = w.baseSunPosition;
    if (light && base) {
      var lighting = context.domainMode === "isolated" ? (context.domainAppearanceSamples.lighting || {}) : {};
      var azimuth = (Number(lighting.key_azimuth_degrees) || 0) * Math.PI / 180;
      var cosine = Math.cos(azimuth), sine = Math.sin(azimuth);
      light.position.set(localX + base.x * cosine - base.z * sine, base.y, game.y + base.x * sine + base.z * cosine);
      light.target.position.set(localX, 0, game.y);
      if (!light.target.parent) w.scene.add(light.target);
      light.target.updateMatrixWorld(true);
    }
  }

  window.CountryDriveScene = Object.freeze({ assets: ASSETS, build: build, sync: sync });
})();
