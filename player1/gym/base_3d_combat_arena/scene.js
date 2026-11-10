(function () {
  "use strict";
  var G3D = window.BaseGamelet3D;
  var VERSION = "industrial-depot-20260910-1";
  var HIT_FEEDBACK_MS = 280;
  var REQUIREMENTS = Object.freeze(["combat_enemy", "combat_rifle", "combat_screen", "combat_pipe", "combat_machine", "combat_cargo"]);

  function material(color, roughness, glow) {
    return new THREE.MeshStandardMaterial({ color: color, roughness: roughness || 0.85, metalness: 0.08,
      emissive: glow ? color : 0x000000, emissiveIntensity: glow ? 0.8 : 0 });
  }

  function build(game) {
    var w = game.world3d, palette = game.assetContext, map = game.map;
    var materials = {
      wall: material(palette.color("wall")), steel: material(palette.color("metal"), 0.65),
      dark: material(palette.color("darkMetal")), panel: material(palette.color("wallAccent")),
      safety: material(palette.color("coverAccent")), white: material(palette.color("trim")),
      glass: material(palette.color("glass"), 0.4), floor: material(palette.color("floorAccent")),
      ground: material(palette.color("verge", 0x58716b)),
      light: material(0xe9ffef, 0.6, true), cover: material(palette.color("cover")),
    };
    var batches = {}, coverBounds = [], props = [];
    function box(role, x, y, z, width, height, depth) {
      (batches[role] || (batches[role] = [])).push([x, y, z, width, height, depth]);
    }
    box("ground", 0, -0.28, -14, 82, 0.24, 82);
    var floorRoles = { yard: "road", workshop: "floor", loading: "floorAccent", service: "vergeAccent", passage: "roadEdge" };
    map.floorPatches.forEach(function floor(rect) {
      var role = floorRoles[rect.style] || "floor";
      var mesh = w.addSurfaceFloor({ x: rect.x, y: -0.003, z: rect.z, width: rect.width, depth: rect.depth,
        assetContext: palette, surfaceRole: role, repeatX: rect.width / 2, repeatY: rect.depth / 2, roughness: 0.95 });
      mesh.name = rect.id; mesh.userData.levelRegion = rect.region_id;
      box("dark", rect.x, -0.075, rect.z, rect.width, 0.13, rect.depth);
    });
    map.walls.forEach(function wall(wall, index) {
      var vertical = wall.width < wall.depth;
      // Stack the base, body and cap; overlapping full-height boxes share visible faces.
      box("wall", wall.x, 0.4 + (wall.height - 0.52) / 2, wall.z, wall.width, wall.height - 0.52, wall.depth);
      box("steel", wall.x, 0.2, wall.z, wall.width, 0.4, wall.depth);
      box("white", wall.x, wall.height - 0.06, wall.z, wall.width, 0.12, wall.depth);
      // Relief clears the supporting face by at least 0.01 world units, including its ends.
      var inwardX = wall.x - wall.normal.x * (wall.width / 2 + 0.02);
      var inwardZ = wall.z - wall.normal.z * (wall.depth / 2 + 0.02);
      box("panel", inwardX, 1.28, inwardZ, vertical ? 0.016 : wall.width - 0.02, 1.08, vertical ? wall.depth - 0.02 : 0.016);
      box("safety", inwardX, 1.89, inwardZ,
        vertical ? 0.02 : wall.width - 0.02, 0.055, vertical ? wall.depth - 0.02 : 0.02);
      var length = vertical ? wall.depth : wall.width;
      for (var along = -length / 2 + 1.1; along < length / 2 - 0.6; along += 2.7) {
        var x = inwardX + (vertical ? 0 : along), z = inwardZ + (vertical ? along : 0);
        box("glass", x, 2.71, z, vertical ? 0.018 : 1.4, 0.95, vertical ? 1.4 : 0.018);
        box("light", x, 3.23, z,
          vertical ? 0.02 : 1.46, 0.045, vertical ? 1.46 : 0.02);
      }
      coverBounds.push({ id: wall.id, min: [wall.x - wall.width / 2, 0, wall.z - wall.depth / 2],
        max: [wall.x + wall.width / 2, wall.height, wall.z + wall.depth / 2] });
    });
    map.rooms.forEach(function room(room, index) {
      if (room.roof) {
        for (var z = room.z - room.depth / 2 + 1; z < room.z + room.depth / 2; z += 3.4) {
          box("steel", room.x, 4.15, z, room.width + 0.2, 0.25, 0.22);
          box("light", room.x, 4.0, z, room.width * 0.43, 0.055, 0.5);
        }
        game.createAsset("combat_pipe", { x: room.x, y: 3.52, z: room.z - room.depth / 2 + 0.18,
          target_size: [room.width * 0.86, 0.2, 0.2] });
      } else {
        box("white", room.x, 0.004, room.z - room.depth / 2 + 1, room.width * 0.74, 0.008, 0.07);
        box("white", room.x, 0.004, room.z + room.depth / 2 - 1, room.width * 0.74, 0.008, 0.07);
      }
      // Flush window panels and service equipment give rooms different uses.
      if (room.roof) {
        game.createAsset("combat_screen", { x: room.x - room.width / 2 + 0.09, y: 2.63, z: room.z,
          target_size: [0.08, 0.72, 1.35], rotationY: Math.PI / 2 });
      }
    });
    map.blockers.forEach(function obstacle(cover) {
      var x = cover.x, z = cover.z, width = cover.width, depth = cover.depth, height = cover.height;
      if (cover.asset) {
        var prop = game.createAsset(cover.asset, { x: x, y: 0, z: z, target_size: [width, height, depth] });
        prop.userData.colliderId = cover.id; props.push(prop);
      } else {
        box("cover", x, 0.16 + (height - 0.25) * 0.5, z, width, height - 0.25, depth);
        box("steel", x, 0.08, z, width, 0.16, depth);
        box("safety", x, height - 0.045, z, width, 0.09, depth);
        for (var face = -1; face <= 1; face += 2) {
          box("panel", x, height * 0.5, z + face * (depth * 0.5 + 0.014), width * 0.82, height * 0.55, 0.008);
        }
      }
      coverBounds.push({ id: cover.id, min: [x - width / 2, 0, z - depth / 2], max: [x + width / 2, height, z + depth / 2] });
    });
    Object.keys(batches).forEach(function finish(role) {
      var entries = batches[role], instance = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), materials[role], entries.length);
      var transform = new THREE.Object3D();
      entries.forEach(function matrix(entry, index) {
        transform.position.set(entry[0], entry[1], entry[2]); transform.scale.set(entry[3], entry[4], entry[5]);
        transform.updateMatrix(); instance.setMatrixAt(index, transform.matrix);
      });
      instance.name = "depot-" + role; instance.instanceMatrix.needsUpdate = true;
      instance.castShadow = role !== "floor" && role !== "white" && role !== "light" && role !== "ground";
      instance.receiveShadow = true; w.root.add(instance);
    });
    var trail = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, 1, 6), new THREE.MeshBasicMaterial({
      color: palette.color("projectileFriendly"), transparent: true, opacity: 0.55, depthWrite: false, toneMapped: false,
    }));
    trail.name = "combat-shot-trail"; trail.visible = false; w.root.add(trail);
    return { trail: trail, coverBounds: coverBounds, props: props, defeatedEnemies: [] };
  }

  function createWeapon(game) {
    var root = new THREE.Group(); root.name = "first-person-rig";
    game.world3d.camera.add(root);
    var weapon = game.createAsset("combat_rifle", { parent: root, target_height: 0.23, x: 0.2, y: -0.3, z: -0.58,
      rotationY: Math.PI, cast_shadow: false, receive_shadow: false });
    var sleeve = material(0x435d61), cuff = material(0xe0b66d), glove = material(0x263c43);
    function arm(name, x, y, z, angle) {
      var group = new THREE.Group(); group.name = name; group.position.set(x, y, z); group.rotation.z = angle;
      var forearm = new THREE.Mesh(new THREE.BoxGeometry(0.115, 0.13, 0.54), sleeve);
      var wrist = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.13, 0.055), cuff);
      var hand = new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.135, 0.13), glove);
      forearm.position.z = 0.22; wrist.position.z = -0.045; hand.position.z = -0.1;
      group.rotation.x = 0.5;
      group.add(forearm, wrist, hand); root.add(group); return group;
    }
    var right = arm("trigger-hand", 0.245, -0.32, -0.38, -0.15);
    var left = arm("support-hand", 0.115, -0.325, -0.7, 0.42); left.rotation.y = -0.47;
    var flash = new THREE.Mesh(new THREE.OctahedronGeometry(0.045, 0), new THREE.MeshBasicMaterial({
      color: 0xc9ffdc, toneMapped: false, transparent: true, opacity: 0.95, depthWrite: false,
    }));
    flash.name = "player-muzzle-flash"; flash.position.set(0.2, -0.186, -1.03); flash.scale.z = 2.8; root.add(flash);
    root.traverse(function foreground(mesh) { if (mesh.isMesh) { mesh.frustumCulled = false; mesh.renderOrder = 20;
      mesh.material.depthTest = false; mesh.material.depthWrite = false; } });
    // These are instance-owned materials; the model's shared template remains untouched.
    weapon.traverse(function sharedDepth(mesh) {
      if (mesh.isMesh) { mesh.renderOrder = 20; }
    });
    return { root: root, weapon: weapon, weaponVisual: G3D.assets.getVisual(weapon), right: right, left: left, flash: flash };
  }

  function enemy(game, state) {
    var root = game.createAsset("combat_enemy", { x: state.x, y: 0, z: state.z, target_height: 1.5 });
    var visual = G3D.assets.getVisual(root), hand = new THREE.Group();
    hand.position.set(-0.17, -0.84, -0.03); hand.rotation.x = Math.PI / 2;
    visual.attach("right_hand", hand);
    var rifle = game.createAsset("combat_rifle", { parent: hand, target_height: 0.43, x: 0, y: -0.12, z: 0.1,
      cast_shadow: true });
    var flash = new THREE.Mesh(new THREE.OctahedronGeometry(0.105), new THREE.MeshBasicMaterial({
      color: game.assetContext.color("projectileHostile"), toneMapped: false,
    }));
    flash.position.set(0, 0.1, 0.92); flash.scale.z = 2; hand.add(flash);
    root.userData.combatVisual = { visual: visual, flash: flash, rifle: rifle };
    return root;
  }

  function projectile(game, state) {
    var mesh = new THREE.Mesh(new THREE.SphereGeometry(state.radius, 8, 6), new THREE.MeshBasicMaterial({
      color: game.assetContext.color(state.owner === "player" ? "projectileFriendly" : "projectileHostile"), toneMapped: false,
    }));
    mesh.position.set(state.x, state.y, state.z); return mesh;
  }

  function showDefeat(game, state) {
    // The enemy has already left combat. Keep its existing model briefly for the impact frame.
    game.sceneMeshes.defeatedEnemies.push({
      id: state.id, x: state.x, z: state.z, alive: false,
      distanceTravelled: state.distanceTravelled, visualShotTimeMs: state.visualShotTimeMs,
      visualDefeatTimeMs: game.gameTimeMs,
      visualHeading: Math.atan2(game.x - state.x, game.z - state.z),
    });
  }

  function sync(game) {
    var scene = game.sceneMeshes, rig = game.weaponRig, now = game.gameTimeMs;
    scene.defeatedEnemies = scene.defeatedEnemies.filter(function visible(state) {
      return now - state.visualDefeatTimeMs < HIT_FEEDBACK_MS;
    });
    game.enemyRegistry.sync(game.enemies.filter(function alive(enemy) { return enemy.alive; }).concat(scene.defeatedEnemies), {
      create: function create(state) { return enemy(game, state); },
      update: function update(mesh, state) {
        mesh.position.set(state.x, 0, state.z);
        var defeated = !state.alive;
        mesh.rotation.y = defeated ? state.visualHeading : Math.atan2(game.x - state.x, game.z - state.z);
        var poseTime = defeated ? state.visualDefeatTimeMs : now;
        var shotAge = poseTime - (state.visualShotTimeMs === undefined ? -1000 : state.visualShotTimeMs);
        var shooting = shotAge >= 0 && shotAge < 230;
        var visual = mesh.userData.combatVisual;
        var pose = { timeMs: now, clip: shooting ? "shoot" : "move",
          clipTimeMs: shooting ? Math.min(199, shotAge) : state.distanceTravelled / 1.55 * 1000, loop: !shooting };
        if (defeated) {
          var age = Math.max(0, now - state.visualDefeatTimeMs);
          var strength = Math.max(0, 1 - age / HIT_FEEDBACK_MS);
          var opacity = Math.min(1, strength * 2);
          pose.materialRoles = { suit: {
            color: 0xf3cf96,
            emissive: new THREE.Color(0x755124).multiplyScalar(strength * 0.65).getHex(),
            opacity: opacity,
          } };
          G3D.assets.getVisual(visual.rifle).applyPose({ timeMs: now, materialRoles: { finish: { opacity: opacity } } });
        }
        visual.visual.applyPose(pose);
        visual.flash.visible = shooting && !defeated;
      },
    });
    game.projectileRegistry.sync(game.projectiles, {
      create: function create(state) { return projectile(game, state); },
      update: function update(mesh, state) { mesh.position.set(state.x, state.y, state.z); },
    });
    if (rig) {
      var recoilAge = game.lastShot ? now - game.lastShot.timeMs : Infinity;
      var recoil = recoilAge < 260 ? Math.pow(1 - Math.max(0, recoilAge) / 260, 2) : 0;
      var reloadProgress = game.reloading ? 1 - game.reloadRemaining / 0.75 : 0;
      var reload = Math.sin(reloadProgress * Math.PI);
      var strideBob = game.grounded ? Math.sin(game.visualStride * 8) * 0.006 : 0;
      rig.root.position.set(0, -0.035 - reload * 0.045 + strideBob, -0.14 + recoil * 0.045);
      rig.root.rotation.set(recoil * 0.07, 0, reload * 0.3);
      rig.left.position.set(0.115 - reload * 0.12, -0.325 - reload * 0.15, -0.7 + reload * 0.28);
      rig.weaponVisual.applyPose({ timeMs: now, clip: "reload", clipTimeMs: game.reloading ? reloadProgress * 750 : 0, loop: false });
      rig.flash.visible = recoilAge >= 0 && recoilAge < 230;
      rig.flash.scale.setScalar(0.7 + recoil * 0.3); rig.flash.scale.z *= 2.8;
    }
    var shotAge = game.lastShot ? now - game.lastShot.timeMs : Infinity;
    scene.trail.visible = !!(shotAge >= 0 && shotAge < 250 && game.lastShot.end);
    if (scene.trail.visible) {
      var start = new THREE.Vector3(game.lastShot.x, game.lastShot.y, game.lastShot.z);
      var end = new THREE.Vector3(game.lastShot.end.x, game.lastShot.end.y, game.lastShot.end.z);
      var direction = end.clone().sub(start), length = direction.length();
      scene.trail.position.copy(start.add(end).multiplyScalar(0.5));
      scene.trail.scale.set(1, length, 1); scene.trail.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize());
      scene.trail.material.opacity = (1 - shotAge / 250) * 0.6;
    }
  }

  window.CombatArenaScene = Object.freeze({ version: VERSION, requirements: REQUIREMENTS, build: build,
    createWeapon: createWeapon, enemy: enemy, projectile: projectile, showDefeat: showDefeat, sync: sync });
})();
