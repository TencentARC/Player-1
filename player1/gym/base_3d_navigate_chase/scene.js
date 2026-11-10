(function courtyardChaseScene() {
  "use strict";

  var U = window.BaseGameletCommon;
  var G3D = window.BaseGamelet3D;
  var ASSETS = Object.freeze([
    "chase_player", "chase_target", "suburban_building_type_a", "suburban_building_type_j",
    "suburban_building_type_p", "nature_tree_small", "nature_tree_plateau",
  ]);

  function build(game, roomSize, avatarHeight) {
    var world = game.world3d;
    var p = game.assetContext;
    var batches = Object.create(null);
    var materials = {
      stone: world.material({ color: p.color("wall"), roughness: 0.88 }),
      cap: world.material({ color: p.color("trim"), roughness: 0.83 }),
      accent: world.material({ color: p.color("wallAccent"), roughness: 0.78 }),
      paving: world.material({ color: p.color("floorAccent"), roughness: 0.93 }),
      garden: world.material({ color: p.color("verge"), roughness: 0.96 }),
    };
    function box(role, x, y, z, width, height, depth) {
      if (!batches[role]) batches[role] = [];
      batches[role].push([x, y, z, width, height, depth]);
    }
    world.addFloor({ x: 14, z: 14, y: -0.025, width: 90, depth: 90, color: p.color("verge"), roughness: 1 });
    game.map.floorPatches.forEach(function floor(r, i) {
      world.addSurfaceFloor({ x: r.x, z: r.z, y: 0, width: r.width, depth: r.depth,
        assetContext: p, surfaceRole: "floor", pattern: p.surface("floor"), repeatX: r.width / 2, repeatY: r.depth / 2 });
    });
    box("paving", 14, 0.005, 14, 4.2, 0.004, 28);
    box("paving", 14, 0.006, 14, 28, 0.004, 4.2);
    game.walls.forEach(function structure(c) {
      if (c.style === "house") {
        // The continuous plinth exposes the full occupied footprint even for recessed doorways.
        box("stone", c.x, 0.17, c.z, c.width, 0.34, c.depth);
        game.createAsset(["suburban_building_type_a", "suburban_building_type_j", "suburban_building_type_p"][c.houseIndex % 3],
          { x: c.x, z: c.z, y: 0.33, target_size: [c.width, c.height - 0.33, c.depth],
            rotationY: c.houseIndex >= 2 ? Math.PI : 0 });
      } else if (c.style === "garden") {
        box("stone", c.x, c.height * 0.35, c.z, c.width, c.height * 0.7, c.depth);
        box("garden", c.x, c.height * 0.85, c.z, c.width, c.height * 0.3, c.depth);
      } else {
        box("stone", c.x, 0.32 + (c.height - 0.43) / 2, c.z, c.width, c.height - 0.43, c.depth);
        box("accent", c.x, 0.16, c.z, c.width, 0.32, c.depth);
        box("cap", c.x, c.height - 0.055, c.z, c.width, 0.11, c.depth);
      }
    });
    [[2,2], [26,2], [2,26], [26,26], [-3,10], [31,18], [10,-3], [18,31]].forEach(function tree(v, index) {
      game.createAsset(index % 2 ? "nature_tree_plateau" : "nature_tree_small", {
        x: v[0], z: v[1], target_height: 4.0 + index % 3 * 0.4, rotationY: index * 0.7 });
    });
    Object.keys(batches).forEach(function batch(role) {
      var entries = batches[role];
      var mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), materials[role], entries.length);
      var transform = new THREE.Object3D();
      entries.forEach(function place(v, index) {
        transform.position.set(v[0], v[1], v[2]); transform.scale.set(v[3], v[4], v[5]);
        transform.updateMatrix(); mesh.setMatrixAt(index, transform.matrix);
      });
      mesh.name = "neighborhood-" + role; mesh.castShadow = role !== "paving";
      mesh.receiveShadow = true; world.root.add(mesh);
    });
    var avatar = game.createAsset("chase_player", { x: game.x, z: game.z, target_height: avatarHeight });
    var target = game.createAsset("chase_target", { x: game.beacon.x, z: game.beacon.z, target_height: avatarHeight });
    return { avatar: avatar, target: target,
      avatarVisual: G3D.assets.getVisual(avatar), targetVisual: G3D.assets.getVisual(target) };
  }

  function sync(game) {
    var scene = game.sceneMeshes;
    scene.avatar.position.set(game.x, 0, game.z);
    scene.avatar.rotation.y = Math.PI / 2 - game.playerHeading;
    scene.avatarVisual.applyPose({ timeMs: game.gameTimeMs, clip: game.playerMoving ? "run" : "idle",
      clipTimeMs: game.playerMoving ? game.playerStrideMs : game.gameTimeMs,
      materialRoles: { body: { color: game.assetContext.color("characterTint") } } });
    scene.target.position.set(game.beacon.x, 0, game.beacon.z);
    scene.target.rotation.y = Math.PI / 2 - game.targetVisualHeading;
    scene.targetVisual.applyPose({ timeMs: game.gameTimeMs, clip: game.targetMoving ? "run" : "idle",
      clipTimeMs: game.targetMoving ? game.targetStrideMs : game.gameTimeMs,
      materialRoles: { body: { color: game.assetContext.color("characterTint") } } });

  }

  function avoidCameraObstacles(game) {
    var camera = game.world3d.camera;
    var origin = { x: game.x, y: 1.05, z: game.z };
    var delta = { x: camera.position.x - origin.x, y: camera.position.y - origin.y, z: camera.position.z - origin.z };
    var distance = Math.hypot(delta.x, delta.y, delta.z);
    if (distance < 0.0001) return;
    var direction = { x: delta.x / distance, y: delta.y / distance, z: delta.z / distance };
    var hit = U.geometry3d.raycastAabbs(origin, direction, game.targetColliders(), {
      maxDistance: distance,
      bounds: function cameraBounds(collider) {
        var bounds = U.geometry3d.aabbFromBox(collider);
        return { minX: bounds.minX - 0.13, maxX: bounds.maxX + 0.13, minY: bounds.minY,
          maxY: bounds.maxY + 0.13, minZ: bounds.minZ - 0.13, maxZ: bounds.maxZ + 0.13 };
      },
    });
    if (hit) {
      var safeDistance = Math.max(0.08, hit.distance - 0.03);
      camera.position.set(origin.x + direction.x * safeDistance, origin.y + direction.y * safeDistance,
        origin.z + direction.z * safeDistance);
    }
    game.sceneMeshes.avatar.visible = Math.hypot(camera.position.x - game.x, camera.position.z - game.z) > 0.48;
  }

  window.CourtyardChaseScene = Object.freeze({ assets: ASSETS, build: build, sync: sync, avoidCameraObstacles: avoidCameraObstacles });
})();
