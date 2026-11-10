(function spearCourtyardScene() {
  "use strict";

  var G3D = window.BaseGamelet3D;
  var U = window.BaseGameletCommon;
  var ASSETS = Object.freeze([
    "duelist", "skirmisher", "hopper", "armory_weapon_spear", "armory_weapon_sword", "armory_column",
    "castle_wall", "nature_tree_oak", "nature_tree_detailed",
  ]);

  function build(game) {
    var w = game.world3d;
    var p = game.assetContext;
    var batches = Object.create(null);
    var materials = {
      stone: w.material({ color: p.color("wall"), roughness: 0.9 }),
      trim: w.material({ color: p.color("trim"), roughness: 0.8 }),
      dark: w.material({ color: p.color("wallAccent"), roughness: 0.85 }),
      paving: w.material({ color: p.color("floorAccent"), roughness: 0.96 }),
    };
    function box(role, x, y, z, width, height, depth) {
      if (!batches[role]) batches[role] = [];
      batches[role].push([x, y, z, width, height, depth]);
    }
    w.addFloor({ width: 80, depth: 80, y: -0.035, color: p.color("verge"), roughness: 1 });
    game.map.floorPatches.forEach(function floor(r, i) {
      w.addSurfaceFloor({ x: r.x, z: r.z, width: r.width, depth: r.depth, y: 0,
        assetContext: p, surfaceRole: "floor", pattern: p.surface("floor"), repeatX: r.width / 1.6, repeatY: r.depth / 1.6 });
    });
    // Wide court and covered side galleries are connected at both ends of the colonnades.
    [-9, 9].forEach(function gallery(x, index) {
      var region = game.map.regions[index + 1];
      box("paving", x, 0.005, region.z, 3.8, 0.006, region.depth);
      [-4.6, -1.55, 1.55, 4.6].forEach(function column(z) {
        game.createAsset("armory_column", { x: x < 0 ? -12.3 : 12.3, z: z + region.z,
          target_size: [0.5, 4.1, 0.5] });
      });
      box("dark", x, 4.05, region.z, 6, 0.22, region.depth);
      for (var beam = -5; beam <= 5; beam += 2.5) box("stone", x, 3.88, region.z + beam, 6, 0.12, 0.16);
    });
    var coversById = {};
    game.covers.forEach(function cover(c) {
      coversById[c.id] = c;
      var wall = c.height > 2.8;
      if (wall) {
        var rotated = c.depth > c.width;
        game.createAsset("castle_wall", { x: c.x, z: c.z, target_size: rotated
          ? [c.depth, c.height, c.width] : [c.width, c.height, c.depth], rotationY: rotated ? Math.PI / 2 : 0 });
      } else {
        var foot = Math.min(0.3, c.height / 3);
        box("dark", c.x, foot / 2, c.z, c.width, foot, c.depth);
        box("stone", c.x, foot + (c.height - foot - 0.14) / 2, c.z, c.width, c.height - foot - 0.14, c.depth);
        box("trim", c.x, c.height - 0.07, c.z, c.width, 0.14, c.depth);
      }
      if (c.style === "arcade") {
        for (var side = -1; side <= 1; side += 2) {
          // Shallow masonry panels are inside the obstacle footprint.
          box("dark", c.x + side * (c.width / 2 - 0.025), c.height * 0.55, c.z, 0.052, 1.7, c.depth - 0.45);
        }
      }
    });
    [[-16,-9,7], [16,9,6], [-8,-16,6.5], [8,-16,7.5], [-8,16,7], [8,16,6.5]].forEach(function tree(spec, i) {
      game.createAsset(i % 2 ? "nature_tree_oak" : "nature_tree_detailed", { x: spec[0], z: spec[1],
        target_height: spec[2], rotationY: i * 0.63 });
    });
    Object.keys(batches).forEach(function batch(role) {
      var entries = batches[role];
      var mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), materials[role], entries.length);
      var transform = new THREE.Object3D();
      entries.forEach(function instance(v, index) {
        transform.position.set(v[0], v[1], v[2]); transform.scale.set(v[3], v[4], v[5]);
        transform.updateMatrix(); mesh.setMatrixAt(index, transform.matrix);
      });
      mesh.name = "spear-cloister-" + role; mesh.castShadow = role !== "paving";
      mesh.receiveShadow = true; w.root.add(mesh);
    });
    return { coversById: coversById };
  }

  function createEnemy(game, enemy, height) {
    var mesh = game.createAsset(enemy.type, { x: enemy.x, y: enemy.y, z: enemy.z, target_height: height });
    var visual = G3D.assets.getVisual(mesh);
    var swordMount = new THREE.Group();
    visual.attach("hand", swordMount);
    swordMount.position.set(0, -0.62, 0.1);
    swordMount.rotation.x = Math.PI / 2;
    var sword = game.createAsset("armory_weapon_sword", { parent: swordMount, target_size: [0.27, 1.08, 0.08] });
    mesh.userData.duel = { visual: visual, sword: sword,
      rightArm: mesh.getObjectByName("arm-right"), leftLeg: mesh.getObjectByName("leg-left"),
      rightLeg: mesh.getObjectByName("leg-right") };
    return mesh;
  }

  function syncEnemy(game, mesh, enemy) {
    var visual = mesh.userData.duel;
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
    visual.visual.applyPose({ timeMs: game.gameTimeMs, clip: clip, clipTimeMs: time, loop: loop,
      materialRoles: { body: { color: tint.getHex(), emissive: glow.getHex() } } });
    mesh.position.set(enemy.x, enemy.y, enemy.z);
    mesh.rotation.set(0, Math.PI / 2 - enemy.heading, 0);
    if (clip === "walk") visual.rightArm.rotation.x = -Math.PI / 2;
    if (!enemy.grounded) {
      // The source has no jump clip: fold the legs while the simulation owns height.
      visual.leftLeg.rotation.x = -0.48;
      visual.rightLeg.rotation.x = 0.4;
    }
  }

  function createWeapon(game) {
    var root = new THREE.Group();
    game.world3d.camera.add(root);
    var shaft = game.createAsset("armory_weapon_spear", { parent: root, target_size: [0.16, 2.15, 0.10] });
    shaft.rotation.x = -Math.PI / 2;
    var cloth = game.world3d.material({ color: 0x36565c, roughness: 0.86 });
    var cuff = game.world3d.material({ color: 0xb69358, roughness: 0.52, metalness: 0.25 });
    var leather = game.world3d.material({ color: 0x7b573f, roughness: 0.85 });
    function arm(wrist, elbow) {
      var group = new THREE.Group();
      var start = new THREE.Vector3().fromArray(wrist);
      var end = new THREE.Vector3().fromArray(elbow);
      var sleeve = new THREE.Mesh(new THREE.CylinderGeometry(0.083, 0.12, start.distanceTo(end), 8), cloth);
      sleeve.position.copy(start).add(end).multiplyScalar(0.5);
      sleeve.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), start.clone().sub(end).normalize());
      group.add(sleeve);
      var glove = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.12, 0.16), leather);
      glove.position.copy(start);
      group.add(glove);
      var band = new THREE.Mesh(new THREE.BoxGeometry(0.158, 0.04, 0.17), cuff);
      band.position.copy(start).add(new THREE.Vector3(0, -0.066, 0.028));
      group.add(band);
      for (var finger = 0; finger < 3; finger += 1) {
        var digit = new THREE.Mesh(new THREE.BoxGeometry(0.13, 0.028, 0.038), leather);
        digit.position.copy(start).add(new THREE.Vector3(0, 0.068, (finger - 1) * 0.039));
        group.add(digit);
      }
      root.add(group);
      return group;
    }
    var rear = arm([0, -0.025, -0.18], [0.33, -0.56, 0.2]);
    var support = arm([0, -0.025, -0.69], [-0.53, -0.52, -0.24]);
    root.userData.duel = { shaft: shaft, rear: rear, support: support };
    root.traverse(function foreground(mesh) { if (mesh.isMesh) { mesh.castShadow = false; mesh.receiveShadow = false; } });
    return root;
  }

  function syncWeapon(game) {
    var root = game.viewSpear;
    if (!root) return;
    var charge = game.chargeRatio();
    var progress = game.playerAttackPhaseDuration ? 1 - game.playerAttackPhaseRemaining / game.playerAttackPhaseDuration : 0;
    var thrust = game.playerAttackState === "thrust" ? Math.sin(Math.PI * U.math.clamp(progress, 0, 1) / 2)
      : game.playerAttackState === "recovery" ? Math.pow(1 - U.math.clamp(progress, 0, 1), 2) : 0;
    var bob = game.playerMoving && !game.dodgeRemaining ? Math.sin(game.gameTimeMs * 0.014) * 0.009 : 0;
    var dodge = game.dodgeRemaining / 0.28;
    root.position.set(0.34 + charge * 0.09 - thrust * 0.13, -0.38 + bob - charge * 0.035 + thrust * 0.05,
      -0.38 + charge * 0.18 - thrust * 0.45);
    // The shaft points toward the same view ray as the spear's hit query.
    root.rotation.set(Math.atan2(-root.position.y, 2.15), Math.atan2(root.position.x, 2.15),
      -0.035 - charge * 0.045 + dodge * 0.15);
    root.userData.duel.support.position.z = charge * 0.04 - thrust * 0.035;
  }

  function createChargeIndicator(game) {
    var canvas = document.createElement("canvas");
    canvas.width = 512;
    canvas.height = 100;
    var texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.minFilter = THREE.LinearFilter;
    texture.magFilter = THREE.LinearFilter;
    texture.generateMipmaps = false;
    var material = new THREE.MeshBasicMaterial({ map: texture, transparent: true,
      depthTest: false, depthWrite: false, toneMapped: false, fog: false });
    var mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), material);
    mesh.name = "duel-charge-indicator";
    mesh.renderOrder = 10000;
    mesh.frustumCulled = false;
    mesh.userData = { canvas: canvas, context: canvas.getContext("2d"), texture: texture,
      lastState: null, lastPercent: null };
    game.world3d.camera.add(mesh);
    return mesh;
  }

  function syncChargeIndicator(game) {
    var mesh = game.chargeIndicator;
    if (!mesh) return;
    var camera = game.world3d.camera;
    var viewport = game.world3d.getSize();
    var distance = 0.2;
    var unitsPerPixel = 2 * distance * Math.tan(THREE.MathUtils.degToRad(camera.getEffectiveFOV() / 2)) / viewport.height;
    var width = Math.min(256 * viewport.height / 540, viewport.width * 0.72);
    var height = width * 100 / 512;
    mesh.position.set(0, -(48 * viewport.height / 540 + height / 2) * unitsPerPixel, -distance);
    mesh.scale.set(width * unitsPerPixel, height * unitsPerPixel, 1);

    var state = game.chargeState();
    var percent = Math.round(game.chargeRatio() * 100);
    var data = mesh.userData;
    if (data.lastState === state && data.lastPercent === percent) return;
    var labels = {
      ready: "READY",
      charging: "CHARGING",
      charged: "CHARGED",
      thrust: "THRUST",
      recovery: "RECOVERING",
    };
    var label = labels[state];
    var ctx = data.context;
    ctx.clearRect(0, 0, 512, 100);
    // Cut stone corners, brass trim and cloth-green fill match the courtyard gear.
    ctx.beginPath();
    ctx.moveTo(16, 6); ctx.lineTo(496, 6); ctx.lineTo(506, 16); ctx.lineTo(506, 84);
    ctx.lineTo(496, 94); ctx.lineTo(16, 94); ctx.lineTo(6, 84); ctx.lineTo(6, 16);
    ctx.closePath();
    ctx.fillStyle = "rgba(23, 42, 45, 0.42)";
    ctx.fill();
    ctx.strokeStyle = state === "charged" ? "rgba(231, 199, 128, 0.7)" : "rgba(182, 147, 88, 0.55)";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#f1e6cd";
    ctx.font = "bold 28px Arial, sans-serif";
    ctx.fillText(label, 256, 35);
    ctx.fillStyle = "#101e21";
    ctx.fillRect(38, 60, 436, 20);
    ctx.strokeStyle = "#a58a5b";
    ctx.strokeRect(38, 60, 436, 20);
    ctx.fillStyle = state === "charged" ? "#e7c780" : "#79b5a5";
    ctx.fillRect(42, 64, 428 * percent / 100, 12);
    ctx.fillStyle = "rgba(23, 42, 45, 0.45)";
    for (var tick = 1; tick < 4; tick += 1) ctx.fillRect(42 + 428 * tick / 4 - 1, 64, 2, 12);
    data.texture.needsUpdate = true;
    data.lastState = state;
    data.lastPercent = percent;
  }

  window.SpearCourtyardScene = Object.freeze({ assets: ASSETS, build: build, createEnemy: createEnemy,
    syncEnemy: syncEnemy, createWeapon: createWeapon, syncWeapon: syncWeapon,
    createChargeIndicator: createChargeIndicator, syncChargeIndicator: syncChargeIndicator });
})();
