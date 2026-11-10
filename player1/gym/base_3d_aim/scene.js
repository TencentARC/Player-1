(function precisionRangeSceneModule() {
  "use strict";

  var ASSETS = Object.freeze([
    "range_target_board", "range_case", "range_machine_window", "range_screen_wide",
    "range_pipe_large_long", "range_pipe_large_bend", "range_box_small", "range_catwalk_straight",
  ]);
  var FLOOR_Y = -1;
  var EYE_Y = 1.35;
  var REVISION = "precision-range-2";

  function targetPosition(game) {
    var cosPitch = Math.cos(game.targetPitch);
    return new THREE.Vector3(
      Math.sin(game.targetYaw) * cosPitch * game.targetDistance,
      Math.max(FLOOR_Y + 0.3, EYE_Y + Math.sin(game.targetPitch) * game.targetDistance),
      -Math.cos(game.targetYaw) * cosPitch * game.targetDistance
    );
  }

  function build(game) {
    var world = game.world3d;
    var palette = game.assetContext;
    var template = game.sceneLayout.template;
    var widthScale = template === "side_bays" ? 1.35 : template === "overhead_frames" ? 1.18 : 1;
    var depthScale = template === "backstop_panels" ? 1.38 : template === "overhead_frames" ? 1.22 : 1.1;
    var batches = Object.create(null);
    var materials = Object.create(null);
    function material(role, color, roughness, metalness, emissive) {
      materials[role] = world.material({ color: color, roughness: roughness, metalness: metalness,
        emissive: emissive || 0, emissiveIntensity: emissive ? 0.8 : 0 });
    }
    material("wall", palette.color("wall"), 0.89, 0);
    material("inset", palette.color("wallAccent"), 0.84, 0.05);
    material("steel", palette.color("metal"), 0.53, 0.35);
    material("dark", palette.color("darkMetal"), 0.88, 0.05);
    material("trim", palette.color("trim"), 0.72, 0.05);
    material("safety", palette.color("coverAccent"), 0.72, 0.05);
    material("light", 0xe7fff0, 0.55, 0, 0xcdf4dd);
    material("glass", palette.color("glass"), 0.25, 0.18, 0x1c3339);
    function box(role, x, y, z, width, height, depth, rotationZ) {
      if (!batches[role]) batches[role] = [];
      batches[role].push({ x: x * widthScale, y: y, z: z * depthScale, width: width * widthScale,
        height: height, depth: depth * depthScale, rotationZ: rotationZ || 0 });
    }
    function asset(name, options) {
      var placement = Object.assign({}, options);
      if (!placement.parent) {
        if (placement.x !== undefined) placement.x *= widthScale;
        if (placement.z !== undefined) placement.z *= depthScale;
      }
      return game.createAsset(name, placement);
    }

    world.addSurfaceFloor({ x: 0, y: FLOOR_Y, z: -5.25 * depthScale, width: 16 * widthScale, depth: 13.5 * depthScale,
      assetContext: palette, surfaceRole: "floor", pattern: "tiles", repeatX: 7, repeatY: 6, roughness: 0.91 });
    box("wall", -8.15, 1.85, -5.25, 0.3, 5.7, 13.5);
    box("wall", 8.15, 1.85, -5.25, 0.3, 5.7, 13.5);
    box("wall", 0, 1.85, -12.15, 16.6, 5.7, 0.3);
    box("wall", 0, 1.85, 1.65, 16.6, 5.7, 0.3);
    if (template === "overhead_frames") {
      box("wall", -6.2, 4.8, -5.25, 4.2, 0.2, 13.8);
      box("wall", 6.2, 4.8, -5.25, 4.2, 0.2, 13.8);
    } else {
      box("wall", 0, 4.8, -5.25, 16.6, 0.2, 13.8);
    }
    // A dark, continuous backstop keeps every allowed target position readable.
    box("steel", 0, 1.47, -11.93, 12.1, 4.6, 0.16);
    box("dark", 0, 1.5, -11.81, 11.65, 4.22, 0.08);
    for (var rib = -5.65; rib <= 5.7; rib += 0.3) {
      box("inset", rib, 1.52, -11.73, 0.07, 4.15, 0.08);
    }
    box("trim", 0, 3.87, -11.78, 12.15, 0.085, 0.12);
    box("safety", 0, -0.8, -11.74, 12.15, 0.08, 0.1);
    box("dark", 0, 3.39, -11.61, 5.8, 0.61, 0.08);

    for (var side = -1; side <= 1; side += 2) {
      // Leave 0.01 clearance from the side wall, including the band's end faces.
      box("steel", side * 7.95, -0.57, -5.25, 0.08, 0.84, 13.5);
      box("inset", side * 7.96, 0.5, -5.25, 0.06, 1.15, 13.5);
      box("safety", side * 7.9, 1.13, -5.25, 0.08, 0.055, 13.5);
      box("inset", side * 6.8, -0.94, -6.1, 1.7, 0.1, 10.9);
      box("safety", side * 5.86, -0.992, -5.7, 0.045, 0.012, 11.8);
      for (var z = -1.6; z >= -10.7; z -= 3) {
        box("steel", side * 7.86, 2.98, z, 0.22, 3.6, 0.2);
        box("glass", side * 7.96, 2.82, z - 0.06, 0.04, 1.52, 2.54);
        box("trim", side * 7.91, 2.03, z - 0.06, 0.1, 0.075, 2.57);
        box("light", side * 7.8, 3.65, z - 0.06, 0.055, 0.07, 2.45);
      }
      // Machinery sits outside the target envelope in marked maintenance lanes.
      asset("range_machine_window", { x: side * 6.95, y: -0.89, z: -7.75,
        target_size: [1.25, 1.2, 1.55], rotationY: side * Math.PI / 2 });
      asset("range_screen_wide", { x: side * 6.85, y: 0.31, z: -7.7,
        target_height: 0.43, rotationY: side * Math.PI / 2 });
      asset("range_case", { x: side * 6.85, y: -0.89, z: -4.25,
        target_size: [1.15, 0.42, 0.75], rotationY: side * 0.12 });
      asset("range_box_small", { x: side * 7.3, y: -0.89, z: -10.4, target_height: 0.67 });
      asset("range_pipe_large_bend", { x: side * 7.5, y: 3.83, z: -11.3,
        target_size: [0.65, 0.34, 0.65], rotationY: side * Math.PI / 2 });
      for (var stripeZ = -2; stripeZ >= -10; stripeZ -= 0.5) {
        box("safety", side * 6.13, -0.882, stripeZ, 0.24, 0.012, 0.035);
      }
    }
    asset("range_pipe_large_long", { x: 0, y: 4.08, z: -11.45, target_size: [14.7, 0.25, 0.25] });
    // Ceiling baffles and fixed luminous panels make the room complete overhead.
    for (var beamZ = -1.8; beamZ >= -10.9; beamZ -= 3) {
      box("steel", 0, 4.47, beamZ, 15.7, 0.22, 0.3);
      for (var lampX = -3.6; lampX <= 3.7; lampX += 7.2) {
        box("dark", lampX, 4.28, beamZ + 0.06, 3.75, 0.16, 0.78);
        box("light", lampX, 4.187, beamZ + 0.06, 3.45, 0.025, 0.6);
      }
    }
    for (var tickZ = -3; tickZ >= -9; tickZ -= 3) {
      box("trim", 0, -0.989, tickZ, 10.6, 0.014, 0.027);
    }
    box("dark", 0, -0.935, 0.55, 4.4, 0.12, 1.5);
    box("safety", 0, -0.866, -0.12, 4.36, 0.016, 0.055);

    if (template === "side_bays") {
      for (var bayZ = -3.2; bayZ >= -9.3; bayZ -= 3) {
        box("inset", -6.35, -0.05, bayZ, 0.18, 1.75, 0.8);
        box("inset", 6.35, -0.05, bayZ, 0.18, 1.75, 0.8);
      }
    } else if (template === "overhead_frames") {
      for (var frameZ = -5.2; frameZ >= -10.3; frameZ -= 2.5) {
        asset("range_catwalk_straight", { x: -6.7, y: 3.47, z: frameZ, target_size: [1.5, 0.53, 2.3] });
        asset("range_catwalk_straight", { x: 6.7, y: 3.47, z: frameZ, target_size: [1.5, 0.53, 2.3] });
      }
    } else if (template === "backstop_panels") {
      for (var panelX = -4.1; panelX <= 4.2; panelX += 4.1) {
        box("inset", panelX, 1.2, -10.9, 3.4, 3.7, 0.2);
        box("steel", panelX, -0.69, -10.9, 3.55, 0.14, 0.45);
      }
    }

    Object.keys(batches).forEach(function commit(role) {
      var entries = batches[role];
      var mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), materials[role], entries.length);
      var transform = new THREE.Object3D();
      entries.forEach(function place(spec, index) {
        transform.position.set(spec.x, spec.y, spec.z);
        transform.scale.set(spec.width, spec.height, spec.depth);
        transform.rotation.set(0, 0, spec.rotationZ);
        transform.updateMatrix();
        mesh.setMatrixAt(index, transform.matrix);
      });
      mesh.instanceMatrix.needsUpdate = true;
      mesh.castShadow = role !== "light" && role !== "glass";
      mesh.receiveShadow = role !== "light";
      mesh.name = "range-" + role;
      world.root.add(mesh);
    });

    var target = new THREE.Group();
    target.name = "active-target";
    world.root.add(target);
    var board = asset("range_target_board", { parent: target, target_size: [1, 1, 0.12], y: -0.5, z: -0.14 });
    var core = new THREE.Mesh(new THREE.SphereGeometry(1, 32, 24), world.material({
      color: palette.color("target"), roughness: 0.31, metalness: 0.12,
      emissive: palette.color("target"), emissiveIntensity: 0.14,
    }));
    core.name = "active-sphere";
    core.castShadow = true; core.receiveShadow = true;
    target.add(core);
    var ring = new THREE.Mesh(new THREE.TorusGeometry(1, 0.028, 8, 64), new THREE.MeshBasicMaterial({
      color: palette.color("trim"), transparent: true, opacity: 0.9, toneMapped: false,
    }));
    ring.position.z = 0.035;
    target.add(ring);
    var stand = world.addCylinder({ radius: 0.038, height: 1, x: 0, z: -5,
      baseY: FLOOR_Y, color: palette.color("metal"), roughness: 0.43, metalness: 0.55, segments: 12 });
    var sleeve = world.addCylinder({ radius: 0.075, height: 0.43, x: 0, z: -5,
      baseY: FLOOR_Y, color: palette.color("trim"), roughness: 0.66, metalness: 0.2, segments: 12 });
    var foot = world.addCylinder({ radius: 0.23, height: 0.08, x: 0, z: -5,
      baseY: FLOOR_Y, color: palette.color("darkMetal"), roughness: 0.77, metalness: 0.15, segments: 24 });
    var eye = new THREE.Vector3(0, EYE_Y, 0);
    return {
      target: target,
      sync: function sync(timeMs) {
        var position = targetPosition(game);
        target.position.copy(position);
        target.lookAt(eye);
        core.scale.setScalar(game.targetWorldRadius);
        var plateRadius = Math.tan(game.targetRadius) * game.targetDistance;
        board.scale.set(plateRadius * 2, plateRadius * 2, 1);
        board.position.y = -plateRadius;
        ring.scale.setScalar(plateRadius * 1.055);
        ring.material.opacity = 0.83 + 0.1 * Math.sin(timeMs * 0.003);
        var standHeight = Math.max(0.2, position.y - FLOOR_Y - plateRadius * 0.6);
        stand.position.set(position.x, FLOOR_Y + standHeight * 0.5, position.z);
        stand.scale.y = standHeight;
        sleeve.position.set(position.x, FLOOR_Y + 0.215, position.z);
        foot.position.set(position.x, FLOOR_Y + 0.04, position.z);

      },
    };
  }

  window.Base3DAimScene = Object.freeze({ assets: ASSETS, revision: REVISION, build: build });
})();
