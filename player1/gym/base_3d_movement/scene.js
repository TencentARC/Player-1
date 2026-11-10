(function movementSceneModule() {
  "use strict";
  var ASSETS = Object.freeze([]);

  function build(game, bounds, floorY) {
    var world = game.world3d, palette = game.assetContext, map = game.map;
    var batches = {}, materials = {};
    var roles = { wall: "wall", steel: "metal", trim: "trim", panel: "wallAccent", safety: "coverAccent",
      ground: "verge", dark: "darkMetal", window: "sky", obstacle: "cover" };
    Object.keys(roles).forEach(function material(role) {
      materials[role] = world.material({ color: palette.color(roles[role]), roughness: role === "steel" ? 0.5 : 0.85,
        metalness: role === "steel" ? 0.25 : 0.02 });
    });
    var goalColor = palette.color("goal");
    materials.goal = world.material({ color: goalColor, roughness: 0.45, emissive: goalColor, emissiveIntensity: 0.35 });
    materials.flag = world.material({ color: goalColor, roughness: 0.85, side: THREE.DoubleSide });
    materials.stripe = world.material({ color: 0xfffdf4, roughness: 0.85, side: THREE.DoubleSide });
    function box(role, x, y, z, width, height, depth) {
      (batches[role] || (batches[role] = [])).push([x, y, z, width, height, depth]);
    }
    var roomX = (bounds.minX + bounds.maxX) / 2, roomZ = (bounds.minZ + bounds.maxZ) / 2;
    box("ground", roomX, floorY - 0.24, roomZ, 30, 0.24, 30);
    map.floorPatches.forEach(function floor(rect) {
      var mesh = world.addSurfaceFloor({ x: rect.x, y: floorY - 0.006, z: rect.z, width: rect.width, depth: rect.depth,
        assetContext: palette, surfaceRole: "floor", repeatX: rect.width / 2, repeatY: rect.depth / 2 });
      mesh.userData.levelRegion = rect.region_id;
      box("steel", rect.x, floorY - 0.055, rect.z, rect.width, 0.09, rect.depth);
    });
    map.walls.forEach(function wall(wall) {
      var vertical = wall.width < wall.depth, length = vertical ? wall.depth : wall.width;
      // Stack the base and body; keep relief clear of the wall face and segment ends.
      box("wall", wall.x, floorY + 0.32 + (wall.height - 0.32) / 2, wall.z, wall.width, wall.height - 0.32, wall.depth);
      box("steel", wall.x, floorY + 0.16, wall.z, wall.width, 0.32, wall.depth);
      var ix = wall.x - wall.normal.x * (wall.width / 2 + 0.02);
      var iz = wall.z - wall.normal.z * (wall.depth / 2 + 0.02);
      box("panel", ix, floorY + 1.16, iz, vertical ? 0.014 : wall.width - 0.02, 0.5, vertical ? wall.depth - 0.02 : 0.014);
      box("trim", ix - wall.normal.x * 0.004, floorY + 1.43, iz - wall.normal.z * 0.004,
        vertical ? 0.02 : wall.width - 0.04, 0.055, vertical ? wall.depth - 0.04 : 0.02);
      for (var along = -length / 2 + 1.7; along < length / 2 - 0.6; along += 3.1) {
        var x = ix + (vertical ? 0 : along), z = iz + (vertical ? along : 0);
        box("window", x, floorY + 2.65, z, vertical ? 0.025 : 2.1, 0.9, vertical ? 2.1 : 0.025);
        box("trim", x - wall.normal.x * 0.012, floorY + 2.15, z - wall.normal.z * 0.012,
          vertical ? 0.05 : 2.2, 0.08, vertical ? 2.2 : 0.05);
        box("trim", x - wall.normal.x * 0.012, floorY + 3.15, z - wall.normal.z * 0.012,
          vertical ? 0.05 : 2.2, 0.08, vertical ? 2.2 : 0.05);
      }
    });
    // Axis-aligned cuboids share the exact ground footprint of their colliders.
    map.blockers.forEach(function barrier(obstacle) {
      box("obstacle", obstacle.x, floorY + obstacle.height / 2, obstacle.z,
        obstacle.width, obstacle.height, obstacle.depth);
      box("safety", obstacle.x, floorY + obstacle.height - 0.008, obstacle.z,
        obstacle.width * 0.93, 0.016, 0.11);
    });
    Object.keys(batches).forEach(function finish(role) {
      var list = batches[role], mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), materials[role], list.length);
      var transform = new THREE.Object3D();
      list.forEach(function place(spec, index) {
        transform.position.set(spec[0], spec[1], spec[2]); transform.scale.set(spec[3], spec[4], spec[5]);
        transform.updateMatrix(); mesh.setMatrixAt(index, transform.matrix);
      });
      mesh.name = "movement-room-" + role; mesh.instanceMatrix.needsUpdate = true;
      mesh.castShadow = role !== "window" && role !== "ground";
      mesh.receiveShadow = true; world.root.add(mesh);
    });

    function part(group, geometry, material, x, y, z) {
      var mesh = new THREE.Mesh(geometry, material);
      mesh.position.set(x, y, z); mesh.castShadow = true; mesh.receiveShadow = true; group.add(mesh);
      return mesh;
    }
    var marker = new THREE.Group(); marker.name = "movement-goal-flag";
    part(marker, new THREE.CylinderGeometry(0.46, 0.59, 0.13, 20), materials.dark, 0, 0.065, 0);
    part(marker, new THREE.CylinderGeometry(0.38, 0.44, 0.07, 20), materials.goal, 0, 0.165, 0);
    part(marker, new THREE.CylinderGeometry(0.045, 0.055, 2.0, 12), materials.stripe, 0, 1.16, 0);
    part(marker, new THREE.SphereGeometry(0.085, 12, 8), materials.goal, 0, 2.19, 0);
    function flagCloth(material, y, height, zOffset) {
      var geometry = new THREE.PlaneGeometry(1.12, height, 12, 2);
      var positions = geometry.attributes.position;
      for (var index = 0; index < positions.count; index += 1) {
        var along = positions.getX(index) + 0.56;
        positions.setZ(index, Math.sin(along * 5.4) * along * 0.13 + zOffset);
      }
      geometry.computeVertexNormals();
      return part(marker, geometry, material, 0.59, y, 0);
    }
    flagCloth(materials.flag, 1.80, 0.62, 0);
    // The broad white stripe preserves a readable flag silhouette across appearance palettes.
    flagCloth(materials.stripe, 1.80, 0.13, 0.006);
    flagCloth(materials.stripe, 1.80, 0.13, -0.006);
    // Dark hems separate the colored cloth from both light walls and bright backgrounds.
    flagCloth(materials.dark, 2.095, 0.03, 0.012);
    flagCloth(materials.dark, 1.505, 0.03, 0.012);
    world.root.add(marker);
    return { marker: marker, sync: function sync() {
      marker.position.set(game.goal.x, floorY, game.goal.z);
      // Swivel the cloth around its upright pole so it remains legible from every approach.
      marker.rotation.y = Math.atan2(game.x - game.goal.x, game.z - game.goal.z);
    } };
  }
  window.MovementScene = Object.freeze({ assets: ASSETS, build: build, version: "movement-cuboids-20261020-1" });
})();
