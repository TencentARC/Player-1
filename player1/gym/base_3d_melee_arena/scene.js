(function () {
  "use strict";
  var G3D = window.BaseGamelet3D;
  var U = window.BaseGameletCommon;
  var VERSION = "monastery-20260910-1";
  var HIT_HIGHLIGHT_MS = 280;
  var REQUIREMENTS = Object.freeze(["melee_player", "melee_raider", "melee_skirmisher", "melee_brute", "melee_sword", "melee_oak", "melee_tree"]);

  function build(game) {
    var w = game.world3d, palette = game.assetContext, map = game.map, batches = {};
    var materials = {};
    var roles = { stone: "wall", cap: "trim", jade: "wallAccent", floor: "floor", wood: "metal",
      paving: "floorAccent", joint: "floorLine", cover: "cover", coverCap: "coverAccent", metal: "darkMetal", grass: "verge" };
    Object.keys(roles).forEach(function role(name) {
      materials[name] = new THREE.MeshStandardMaterial({ color: palette.color(roles[name]), roughness: 0.92, metalness: 0.02 });
    });
    function box(role, x, y, z, width, height, depth) {
      (batches[role] || (batches[role] = [])).push([x, y, z, width, height, depth]);
    }
    box("grass", 0, -0.18, -8, 78, 0.2, 78);
    var surfaces = { court: "floor", wood: "road", garden: "verge", sanctuary: "floorAccent", passage: "roadEdge" };
    map.floorPatches.forEach(function floor(rect) {
      var floor = w.addSurfaceFloor({ x: rect.x, y: -0.006, z: rect.z, width: rect.width, depth: rect.depth,
        assetContext: palette, surfaceRole: surfaces[rect.style] || "floor", repeatX: rect.width / 1.5, repeatY: rect.depth / 1.5 });
      floor.userData.levelRegion = rect.region_id;
      box("stone", rect.x, -0.055, rect.z, rect.width, 0.09, rect.depth);
    });
    map.walls.forEach(function wall(wall) {
      var vertical = wall.width < wall.depth, length = vertical ? wall.depth : wall.width;
      // Base, body and cap occupy adjacent height bands with the original wall footprint.
      box("stone", wall.x, 0.36 + (wall.height - 0.5) / 2, wall.z, wall.width, wall.height - 0.5, wall.depth);
      box("jade", wall.x, 0.18, wall.z, wall.width, 0.36, wall.depth);
      box("cap", wall.x, wall.height - 0.07, wall.z, wall.width, 0.14, wall.depth);
      // Columns and their caps sit inside the physical wall's footprint.
      for (var at = -length / 2 + 0.3; at < length / 2; at += 3.8) {
        var x = wall.x + (vertical ? 0 : at), z = wall.z + (vertical ? at : 0);
        box("wood", x, 2.75, z, 0.3, 5.5, 0.3);
        box("cap", x, 4.35, z, 0.48, 0.16, 0.48);
      }
      box("jade", wall.x, 4.56, wall.z, vertical ? 0.65 : wall.width, 0.18, vertical ? wall.depth : 0.65);
      var ix = wall.x - wall.normal.x * (wall.width / 2 - 0.003);
      var iz = wall.z - wall.normal.z * (wall.depth / 2 - 0.003);
      for (var joint = -length / 2 + 0.5; joint < length / 2; joint += 1.25) {
        box("joint", ix + (vertical ? 0 : joint), 1.3, iz + (vertical ? joint : 0), vertical ? 0.004 : 0.012,
          2.05, vertical ? 0.012 : 0.004);
      }
    });
    map.rooms.forEach(function room(room) {
      if (room.roof) {
        for (var z = room.z - room.depth / 2 + 0.6; z < room.z + room.depth / 2; z += 2.4) {
          box("wood", room.x, 4.35, z, room.width + 0.55, 0.25, 0.23);
          box("jade", room.x, 4.59, z, room.width + 0.8, 0.16, 1.9);
        }
      } else {
        for (var edge = -1; edge <= 1; edge += 2) {
          box("jade", room.x + edge * (room.width / 2 - 0.8), 0.005, room.z, 0.05, 0.009, room.depth - 1.6);
          box("jade", room.x, 0.005, room.z + edge * (room.depth / 2 - 0.8), room.width - 1.6, 0.009, 0.05);
        }
      }
    });
    map.blockers.forEach(function plinth(cover, index) {
      box("cover", cover.x, (cover.height - 0.07) / 2, cover.z, cover.width, cover.height - 0.07, cover.depth);
      box("coverCap", cover.x, cover.height - 0.035, cover.z, cover.width, 0.07, cover.depth);
      if (cover.tree) game.createAsset(index % 2 ? "melee_tree" : "melee_oak", {
        x: cover.x, y: cover.height, z: cover.z, target_size: [1.7, 3.5, 1.7] });
    });
    [[-26, -12], [25, -12], [-26, 8], [23, 12], [-8, -27], [10, -27]].forEach(function tree(at, index) {
      game.createAsset(index % 2 ? "melee_tree" : "melee_oak", { x: game.sceneMirrorSign * at[0], z: at[1], target_height: 5.5,
        rotationY: game.sceneMirrorSign * index * 0.83 });
    });
    Object.keys(batches).forEach(function finish(role) {
      var entries = batches[role], mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), materials[role], entries.length);
      var transform = new THREE.Object3D();
      entries.forEach(function matrix(spec, index) {
        transform.position.set(spec[0], spec[1], spec[2]); transform.scale.set(spec[3], spec[4], spec[5]);
        transform.updateMatrix(); mesh.setMatrixAt(index, transform.matrix);
      });
      mesh.instanceMatrix.needsUpdate = true; mesh.name = "monastery-" + role;
      mesh.castShadow = role !== "joint" && role !== "paving" && role !== "grass";
      mesh.receiveShadow = true; w.root.add(mesh);
    });
    return { avatar: character(game, "melee_player", 1.64, true) };
  }

  function character(game, role, height, player) {
    var root = game.createAsset(role, { target_height: height });
    var visual = G3D.assets.getVisual(root), hand = new THREE.Group();
    visual.attach("hand", hand); hand.position.set(0, -0.72, 0.1); hand.rotation.x = Math.PI / 2;
    var sword = game.createAsset("melee_sword", { parent: hand, target_size: [0.31, 1.45, 0.10], y: -0.16 });
    root.userData.meleeVisual = { visual: visual, hand: hand, sword: sword, height: height };
    return root;
  }

  function samplePose(game, mesh, state, player) {
    var visual = mesh.userData.meleeVisual;
    var combatState = player ? game.attackState : state.combatState;
    var duration = player ? game.attackPhaseDuration : state.phaseDuration;
    var remaining = player ? game.attackPhaseRemaining : state.phaseRemaining;
    var progress = duration > 0 ? U.math.clamp(1 - remaining / duration, 0, 1) : 0;
    var moving = player ? game.playerMoving : state.moving;
    var stride = player ? game.visualStride : state.visualStride;
    var clip = moving ? "walk" : "idle", time = moving ? stride / 2.2 * 1000 : 167, loop = moving;
    if (combatState === "windup") { clip = "attack"; time = progress * 105; loop = false; }
    if (combatState === "active") { clip = "attack"; time = 105 + progress * 175; loop = false; }
    if (combatState === "recovery") { clip = "attack"; time = 280 + progress * 136; loop = false; }
    var stagger = player ? game.playerStaggerRemaining : state.staggerRemaining;
    if (stagger > 0) { clip = "hurt"; time = 40 * Math.sin(Math.PI * Math.min(1, stagger / (player ? 0.18 : 0.28))); loop = false; }
    var dodging = player && game.dodgeRemaining > 0;
    if (dodging) { clip = "dodge"; time = stride / 3.1 * 1000; loop = true; }
    var hitTime = player ? game.lastPlayerHitMs : state.lastVisualHitMs;
    var hit = Number.isFinite(hitTime) ? U.math.clamp(1 - (game.gameTimeMs - hitTime) / HIT_HIGHLIGHT_MS, 0, 1) : 0;
    // Keep the atlas and shading visible beneath a short warm, simulation-time highlight.
    var tint = new THREE.Color(game.assetContext.color("characterTint", 0xffffff));
    tint.lerp(new THREE.Color(0xffd99a), 0.42 * hit);
    var glow = new THREE.Color(0xffd395).multiplyScalar(0.11 * hit);
    visual.visual.applyPose({ timeMs: game.gameTimeMs, clip: clip, clipTimeMs: time, loop: loop,
      materialRoles: { body: { color: tint.getHex(), emissive: glow.getHex() } } });
    mesh.position.set(player ? game.x : state.x, 0, player ? game.z : state.z);
    mesh.rotation.set(dodging ? 0.28 : 0, Math.PI / 2 - (player ? game.yaw : state.heading), 0, "YXZ");
  }

  function constrainCamera(game, optical) {
    var camera = game.world3d.camera;
    var start = { x: game.x, y: 1.18, z: game.z };
    var end = { x: camera.position.x, y: camera.position.y, z: camera.position.z };
    var length = Math.hypot(end.x - start.x, end.y - start.y, end.z - start.z), nearest = length;
    game.covers.forEach(function collide(cover) {
      var hit = U.geometry3d.segmentAabbHitDistance(start, end, game.coverBounds(cover, 0.12));
      if (hit !== null) nearest = Math.min(nearest, Math.max(0, hit - 0.04));
    });
    if (nearest < length && length > 0.0001) {
      var amount = nearest / length;
      camera.position.set(start.x + (end.x - start.x) * amount, start.y + (end.y - start.y) * amount, start.z + (end.z - start.z) * amount);
      camera.lookAt(camera.position.x + optical.direction.x, camera.position.y + optical.direction.y, camera.position.z + optical.direction.z);
    }
    game.visualCameraDistance = nearest;
    camera.updateMatrixWorld(true);
  }

  function sync(game) {
    var scene = game.sceneMeshes;
    samplePose(game, scene.avatar, game, true);
    scene.avatar.visible = game.visualCameraDistance > 0.85;
    var visibleEnemies = game.enemies.filter(function alive(state) { return state.alive; });
    // A defeated fighter only survives visually for its final impact; gameplay removes it immediately.
    game.visualHits.forEach(function finalImpact(hit) {
      var elapsed = (game.gameTimeMs - hit.timeMs) / 1000;
      if (hit.killed && elapsed * 1000 < HIT_HIGHLIGHT_MS) visibleEnemies.push(Object.assign({}, hit.enemy, {
        staggerRemaining: Math.max(0, 0.28 - elapsed),
      }));
    });
    game.enemyRegistry.sync(visibleEnemies, {
      create: function create(state) { return character(game, "melee_" + state.type, 1.64 * state.radius / 0.38, false); },
      update: function update(mesh, state) { samplePose(game, mesh, state, false); },
    });
  }

  window.MeleeArenaScene = Object.freeze({ version: VERSION, requirements: REQUIREMENTS, build: build,
    character: character, constrainCamera: constrainCamera, sync: sync });
})();
