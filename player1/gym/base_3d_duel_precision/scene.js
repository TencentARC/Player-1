(function swordTrainingHall() {
  "use strict";

  var G3D = window.BaseGamelet3D;
  var U = window.BaseGameletCommon;
  var ASSETS = Object.freeze(["duelist", "skirmisher", "hopper", "armory_weapon_sword", "armory_column"]);

  function build(game) {
    var w = game.world3d;
    var p = game.assetContext;
    var batches = Object.create(null);
    var materials = {
      plaster: w.material({ color: p.color("wall"), roughness: 0.94 }),
      wood: w.material({ color: p.color("floor"), roughness: 0.83 }),
      lightWood: w.material({ color: p.color("floorAccent"), roughness: 0.84 }),
      frame: w.material({ color: p.color("metal"), roughness: 0.75 }),
      pad: w.material({ color: p.color("cover"), roughness: 0.96 }),
      seam: w.material({ color: p.color("coverAccent"), roughness: 0.95 }),
      window: new THREE.MeshBasicMaterial({ color: 0xd4e7eb, toneMapped: false }),
      light: new THREE.MeshBasicMaterial({ color: 0xffedc1, toneMapped: false }),
    };
    function box(role, x, y, z, width, height, depth) {
      if (!batches[role]) batches[role] = [];
      batches[role].push([x, y, z, width, height, depth]);
    }
    w.addFloor({ width: 70, depth: 70, y: -0.05, color: p.color("verge"), roughness: 0.86 });
    game.map.floorPatches.forEach(function floor(region) {
      w.addSurfaceFloor({ x: region.x, z: region.z, width: region.width, depth: region.depth, y: 0,
        assetContext: p, surfaceRole: "floor", pattern: p.surface("floor"), repeatX: region.width / 2, repeatY: region.depth / 2 });
      for (var z = -region.depth / 2 + 0.3; z < region.depth / 2 - 0.025; z += 0.6) {
        box("lightWood", region.x, 0.008, region.z + z, region.width - 0.02, 0.003, 0.025);
      }
    });
    game.map.regions.forEach(function ceiling(region) {
      for (var beam = -region.depth / 2 + 1; beam < region.depth / 2; beam += 3.6) {
        box("frame", region.x, 5.0, region.z + beam, region.width, 0.25, 0.18);
        box("wood", region.x, 5.2, region.z + beam, region.width, 0.08, 1.4);
        box("light", region.x, 4.82, region.z + beam, Math.min(2.3, region.width / 3), 0.035, 0.2);
      }
    });
    var coversById = {};
    game.covers.forEach(function cover(c) {
      coversById[c.id] = c;
      var low = c.height < 1;
      box(low ? "pad" : "plaster", c.x, 0.24 + (c.height - 0.38) / 2, c.z, c.width, c.height - 0.38, c.depth);
      box(low ? "seam" : "frame", c.x, 0.12, c.z, c.width, 0.24, c.depth);
      box(low ? "seam" : "wood", c.x, c.height - 0.07, c.z, c.width, 0.14, c.depth);
      if (c.height > 4) {
        var horizontal = c.width > c.depth;
        var length = horizontal ? c.width : c.depth;
        var count = Math.max(1, Math.floor(length / 2.8));
        for (var panel = 0; panel < count; panel += 1) {
          var along = -length / 2 + length / count * (panel + 0.5);
          var px = c.x + (horizontal ? along : 0), pz = c.z + (horizontal ? 0 : along);
          var span = Math.min(2.05, length / count - 0.25);
          // Windows are shallow insets on both faces of the physical boundary wall.
          box("frame", px, 3.55, pz, horizontal ? span + 0.12 : c.width + 0.008, 1.5,
            horizontal ? c.depth + 0.008 : span + 0.12);
          box("window", px, 3.55, pz, horizontal ? span : c.width + 0.012, 1.3,
            horizontal ? c.depth + 0.012 : span);
          // Extend the mullion beyond the pane so their top/bottom faces cannot coincide.
          box("frame", px, 3.55, pz, horizontal ? 0.06 : c.width + 0.016, 1.34,
            horizontal ? c.depth + 0.016 : 0.06);
        }
      }
    });
    [-1, 1].forEach(function support(side) {
      [-8.8, 8.8].forEach(function column(z) {
        game.createAsset("armory_column", { x: side * 7.16, z: z, target_size: [0.32, 5.05, 0.5] });
      });
    });
    // Side-room weapon racks face the doorway, with all relief mounted on the room walls.
    [-1, 1].forEach(function rack(side) {
      var region = game.map.regions[side < 0 ? 1 : 2];
      [-2, 0, 2].forEach(function sword(z) {
        var mesh = game.createAsset("armory_weapon_sword", { x: side * 13.08, y: 2.2, z: region.z + z,
          target_size: [0.035, 0.95, 0.28], rotationY: Math.PI / 2 });
        mesh.rotation.z = side * 0.15;
      });
    });
    Object.keys(batches).forEach(function batch(role) {
      var entries = batches[role];
      var mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), materials[role], entries.length);
      var transform = new THREE.Object3D();
      entries.forEach(function instance(v, i) {
        transform.position.set(v[0], v[1], v[2]); transform.scale.set(v[3], v[4], v[5]);
        transform.updateMatrix(); mesh.setMatrixAt(i, transform.matrix);
      });
      mesh.name = "sword-cross-hall-" + role; mesh.castShadow = role !== "window" && role !== "light";
      mesh.receiveShadow = true; w.root.add(mesh);
    });
    return { coversById: coversById };
  }

  function createEnemy(game, enemy, height) {
    var mesh = game.createAsset(enemy.type, { x: enemy.x, y: enemy.y, z: enemy.z, target_height: height });
    var visual = G3D.assets.getVisual(mesh);
    var mount = new THREE.Group(); visual.attach("hand", mount);
    mount.position.set(0, -0.62, 0.1); mount.rotation.x = Math.PI / 2;
    var sword = game.createAsset("armory_weapon_sword", { parent: mount, target_size: [0.23, 0.92, 0.07] });
    mesh.userData.precision = { visual: visual, sword: sword,
      rightArm: mesh.getObjectByName("arm-right"), leftLeg: mesh.getObjectByName("leg-left"), rightLeg: mesh.getObjectByName("leg-right") };
    return mesh;
  }

  function syncEnemy(game, mesh, enemy) {
    var v = mesh.userData.precision;
    var progress = enemy.phaseDuration ? U.math.clamp(1 - enemy.phaseRemaining / enemy.phaseDuration, 0, 1) : 0;
    var clip = enemy.moving ? "walk" : "idle";
    var time = enemy.moving ? game.gameTimeMs * 1.15 : 167;
    var loop = enemy.moving;
    if (enemy.combatState === "windup") { clip = "attack"; time = progress * 105; loop = false; }
    if (enemy.combatState === "active") { clip = "attack"; time = 105 + progress * 175; loop = false; }
    if (enemy.combatState === "recovery") { clip = "attack"; time = 280 + progress * 136; loop = false; }
    if (enemy.combatState === "stagger") { clip = "hurt"; time = 55 * Math.sin(Math.PI * progress); loop = false; }
    var hit = enemy.combatState === "stagger" ? Math.sqrt(1 - progress) : 0;
    var tint = new THREE.Color(game.assetContext.color("characterTint"));
    tint.lerp(new THREE.Color(0xffd591), hit * 0.65);
    var glow = new THREE.Color(0xffd391).multiplyScalar(hit * 0.18);
    v.visual.applyPose({ timeMs: game.gameTimeMs, clip: clip, clipTimeMs: time, loop: loop,
      materialRoles: { body: { color: tint.getHex(), emissive: glow.getHex() } } });
    mesh.position.set(enemy.x, enemy.y, enemy.z); mesh.rotation.set(0, Math.PI / 2 - enemy.heading, 0);
    if (clip === "walk") v.rightArm.rotation.x = -Math.PI / 2;
    if (!enemy.grounded) { v.leftLeg.rotation.x = -0.48; v.rightLeg.rotation.x = 0.4; }
  }

  function createWeapon(game) {
    var root = new THREE.Group(); game.world3d.camera.add(root);
    var sword = game.createAsset("armory_weapon_sword", { parent: root, target_size: [0.19, 0.82, 0.06] });
    sword.position.y = -0.115;
    var cloth = game.world3d.material({ color: 0x3c677e, roughness: 0.88 });
    var leather = game.world3d.material({ color: 0x876446, roughness: 0.89 });
    var band = game.world3d.material({ color: 0xc2ae75, roughness: 0.52, metalness: 0.18 });
    function hand(parent, wrist, elbow) {
      var start = new THREE.Vector3().fromArray(wrist), end = new THREE.Vector3().fromArray(elbow);
      var arm = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.12, start.distanceTo(end), 8), cloth);
      arm.position.copy(start).add(end).multiplyScalar(0.5);
      arm.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), start.clone().sub(end).normalize()); parent.add(arm);
      var glove = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.16, 0.13), leather);
      glove.position.copy(start); parent.add(glove);
      var cuff = new THREE.Mesh(new THREE.BoxGeometry(0.17, 0.055, 0.15), band);
      cuff.position.copy(start).add(new THREE.Vector3(0, -0.085, 0.04)); parent.add(cuff);
      for (var i = 0; i < 3; i += 1) {
        var finger = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.035, 0.05), leather);
        finger.position.copy(start).add(new THREE.Vector3(0, (i - 1) * 0.047, -0.066)); parent.add(finger);
      }
    }
    hand(root, [0, -0.015, 0], [0.24, -0.49, 0.31]);
    var guard = new THREE.Group(); game.world3d.camera.add(guard);
    hand(guard, [0, 0, 0], [-0.13, -0.28, 0.26]);
    root.userData.precision = { sword: sword, guard: guard };
    [root, guard].forEach(function group(parent) {
      parent.traverse(function foreground(mesh) { if (mesh.isMesh) { mesh.castShadow = false; mesh.receiveShadow = false; } });
    });
    return root;
  }

  function syncWeapon(game) {
    var root = game.viewMeleeWeapon; if (!root) return;
    var age = game.gameTimeMs - game.precisionSwingTime;
    var sweep = 0;
    if (age >= 0 && age < 50) sweep = age / 50 * -0.35;
    else if (age < 90) sweep = -0.35 + (age - 50) / 40 * 1.35;
    else if (age < 340) sweep = Math.pow(1 - (age - 90) / 250, 1.5);
    // The 45/30/75ms hit windows stay native; only the follow-through returns slowly.
    var bob = game.playerMoving && !game.dodgeRemaining ? Math.sin(game.gameTimeMs * 0.014) * 0.009 : 0;
    var dodge = game.dodgeRemaining / 0.28;
    root.position.set(0.36 - sweep * 0.49, -0.4 + bob + sweep * 0.13 - dodge * 0.04, -0.58 - sweep * 0.2);
    root.rotation.set(-0.2 + sweep * 0.8, -0.16 - sweep * 0.56, -0.2 + sweep * 1.2 + dodge * 0.18);
    var guard = root.userData.precision.guard;
    guard.position.set(-0.36 + sweep * 0.04, -0.39 + bob - dodge * 0.06, -0.54);
    guard.rotation.set(-0.15, 0.1, -0.18 - sweep * 0.12);
  }

  window.SwordTrainingHall = Object.freeze({ assets: ASSETS, build: build, createEnemy: createEnemy,
    syncEnemy: syncEnemy, createWeapon: createWeapon, syncWeapon: syncWeapon });
})();
