(function coastHighwayScene() {
  "use strict";
  var ASSETS = Object.freeze(["car_hatchback", "palm", "tree_pine", "rock", "street_lamp", "road_sign", "house_a", "bush", "grass"]);
  var LOOP = 126, NEAR = -12;
  function modulo(value, period) { return ((value % period) + period) % period; }

  function build(game, dimensions) {
    var w = game.world3d, palette = game.assetContext;
    var layout = game.sceneLayout.template;
    var causeway = layout === "causeway";
    var forest = layout === "forest-cut";
    var village = layout === "village-road";
    var coastal = layout === "coast-highway";
    function color(role, fallback) { return palette.color(role, fallback); }
    var track = new THREE.Group(); w.root.add(track);
    function ground(x, z, width, depth, y, role, baseColor) {
      var object = w.addSurfaceFloor({ x: x, z: z, y: y, width: width, depth: depth,
        assetContext: palette, surfaceRole: role, color: baseColor,
        textureOptions: { repeatX: width * 0.5, repeatY: depth * 0.5 } });
      track.add(object); return object;
    }
    if (!causeway) ground(-38, 47, 68, 150, 0, "verge", color("verge"));
    ground(3.5, 47, forest || village ? 140 : 9, 150, 0.002, "verge", color(coastal ? "sand" : "verge"));
    var water = new THREE.Mesh(new THREE.PlaneGeometry(130, 200), w.material({
      color: color("sea"), roughness: 0.45, metalness: 0.12,
    }));
    water.rotation.x = -Math.PI / 2; water.position.set(72, -0.14, 65); track.add(water);
    water.visible = coastal || causeway;
    if (causeway) { water.position.x = 0; water.scale.x = 2; }
    var asphalt = window.BaseGamelet3D.textures.createSurface(palette, "road", { repeatX: 3.6, repeatY: 63 });
    function trackBox(x, y, z, width, height, depth, material) {
      var mesh = new THREE.Mesh(new THREE.BoxGeometry(width, height, depth), material);
      mesh.position.set(x, y, z); mesh.receiveShadow = true; track.add(mesh); return mesh;
    }
    var steel = w.material({ color: color("metal"), roughness: 0.52, metalness: 0.4 });
    var concrete = w.material({ color: color("neutral"), roughness: 0.87 });
    var edge = w.material({ color: color("roadEdge"), roughness: 0.83 });
    var roadMaterial = w.material({ color: 0xffffff, map: asphalt, roughness: 0.96 });
    // Adjacent vertical bands keep the road and retaining-wall end faces from overlapping.
    trackBox(0, 0.0355, 51, dimensions.roadWidth + 1.5, 0.051, LOOP, w.material({ color: 0x6a6d68, roughness: 1 }));
    trackBox(0, 0.081, 51, dimensions.roadWidth, 0.04, LOOP, roadMaterial);
    [-1, 1].forEach(function edgeStripe(side) {
      trackBox(side * 3.5, 0.11, 51, 0.08, 0.012, LOOP, edge);
      trackBox(side * 4.12, 0.33, 51, 0.07, 0.18, LOOP, steel);
      trackBox(side * 4.12, 0.22, 51, 0.075, 0.028, LOOP, edge);
    });
    if (coastal) {
      trackBox(5.9, 0.19, 51, 0.3, 0.38, LOOP, concrete);
      trackBox(5.9, 0.40, 51, 0.34, 0.04, LOOP, edge);
    }
    if (forest) {
      [-1, 1].forEach(function retainingWall(side) {
        trackBox(side * 7.2, 0.58, 51, 0.45, 1.16, LOOP, concrete);
        trackBox(side * 7.2, 1.22, 51, 0.55, 0.12, LOOP, edge);
      });
    }
    // Every lane marker and rail support shares one draw per material.
    var dashSpecs = [], postSpecs = [], reflectorSpecs = [], waveSpecs = [];
    for (var z = NEAR; z < NEAR + LOOP; z += 2.0) {
      [-1.8, 0, 1.8].forEach(function stripe(x) { dashSpecs.push([x, 0.115, z, 0.075, 0.016, 1.1]); });
    }
    for (var p = NEAR; p < NEAR + LOOP; p += 2.8) {
      [-1, 1].forEach(function post(side) {
        postSpecs.push([side * 4.12, 0.20, p, 0.08, 0.35, 0.075]);
        reflectorSpecs.push([side * 4.065, 0.34, p, 0.024, 0.04, 0.09]);
      });
    }
    for (var wave = 0; wave < (coastal || causeway ? 52 : 0); wave += 1) {
      waveSpecs.push([8 + (wave % 7) * 3.8, -0.126, NEAR + wave * 7.7 % LOOP, 1.2 + wave % 3, 0.005, 0.035]);
    }
    function batch(name, specs, material) {
      var mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), material, specs.length);
      mesh.name = name; mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      mesh.receiveShadow = name !== "coast-waves"; mesh.castShadow = name === "coast-posts"; w.root.add(mesh);
      return { mesh: mesh, specs: specs, matrix: new THREE.Object3D() };
    }
    var batches = [batch("coast-lanes", dashSpecs, edge), batch("coast-posts", postSpecs, steel),
      batch("coast-reflectors", reflectorSpecs, w.material({ color: 0xffe9b6, roughness: 0.8 })),
      batch("coast-waves", waveSpecs, new THREE.MeshBasicMaterial({ color: 0xadd1c9, transparent: true, opacity: 0.25 }))];

    var scenery = [];
    function prop(id, x, z, height, rotationY) {
      var object = game.createAsset(id, { x: x, z: z, target_height: height, forward_axis: "+z", rotationY: rotationY || 0 });
      scenery.push({ object: object, baseZ: z }); return object;
    }
    for (var palm = 0; palm < 12; palm += 1) {
      if (!causeway) {
        prop(coastal ? "palm" : "tree_pine", coastal ? 5.05 + (palm % 2) * 0.17 : 10 + palm % 3 * 2,
          NEAR + palm * 10.5, 2.8 + palm % 3 * 0.24, palm * 1.7);
        prop("tree_pine", -9.0 - palm % 3 * 1.5, NEAR + palm * 10.5 + 3.8, 3.0 + palm % 4 * 0.4, palm * 0.8);
        if (palm % 3 === 0) prop("rock", -6.3, NEAR + palm * 10.5 + 1.8, 0.45);
        prop(palm % 3 ? "grass" : "bush", -5.2 - palm % 2 * 0.6, NEAR + palm * 10.5 + 0.8, palm % 3 ? 0.15 : 0.32);
      }
    }
    for (var lamp = 0; lamp < 5; lamp += 1) prop("street_lamp", -4.8, NEAR + lamp * LOOP / 5, 2.3, Math.PI);
    for (var sign = 0; sign < 3; sign += 1) prop("road_sign", -4.8, 5 + sign * 42, 1.0, Math.PI);
    if (!causeway && !forest) [18, 68, 110].forEach(function houses(z, i) {
      prop("house_a", -15 - i * 1.7, z, 3.0, Math.PI / 2);
      if (village) prop("house_a", 15 + i % 2 * 3, z + 20, 3.7, -Math.PI / 2);
    });
    var hillMaterial = w.material({ color: 0x73896a, roughness: 1, flatShading: true });
    var hillGeometry = new THREE.SphereGeometry(1, 12, 8);
    for (var hill = 0; hill < (causeway ? 0 : 7); hill += 1) {
      var mesh = new THREE.Mesh(hillGeometry, hillMaterial);
      mesh.position.set(-34 - hill % 2 * 9, -2.8, NEAR + hill * 18); mesh.scale.set(16, 7 + hill % 3 * 2, 16);
      w.root.add(mesh); scenery.push({ object: mesh, baseZ: mesh.position.z });
    }

    var car = game.createAsset("car_hatchback", { target_size: [dimensions.carWidth, 0.62, dimensions.carDepth], forward_axis: "+z" });
    var carVisual = window.BaseGamelet3D.assets.getVisual(car);
    var shadow = new THREE.Mesh(new THREE.PlaneGeometry(1.02, 1.58), new THREE.MeshBasicMaterial({
      color: 0x112a30, transparent: true, opacity: 0.19, depthWrite: false,
    }));
    shadow.rotation.x = -Math.PI / 2; w.root.add(shadow);

    var coins = [], radius = dimensions.coinRadius;
    var gold = w.material({ color: color("coin"), roughness: 0.35, metalness: 0.55,
      emissive: color("coin"), emissiveIntensity: 0.12 });
    var rimMaterial = w.material({ color: 0xffeda8, roughness: 0.4, metalness: 0.3 });
    var coinGeometry = new THREE.CylinderGeometry(radius, radius, 0.075, 32);
    var rimGeometry = new THREE.TorusGeometry(radius * 0.81, 0.024, 6, 32);
    var stampGeometry = new THREE.BoxGeometry(0.045, radius * 1.15, 0.009);
    var diskGeometry = new THREE.RingGeometry(radius * 0.8, radius * 1.12, 24);
    var ringMaterial = new THREE.MeshBasicMaterial({ color: color("coin"), transparent: true, opacity: 0.33,
      side: THREE.DoubleSide, depthWrite: false, toneMapped: false });
    for (var coinIndex = 0; coinIndex < dimensions.maxCoins; coinIndex += 1) {
      var group = new THREE.Group(), disk = new THREE.Mesh(coinGeometry, gold); disk.rotation.x = Math.PI / 2; group.add(disk);
      [-1, 1].forEach(function face(side) {
        var rim = new THREE.Mesh(rimGeometry, rimMaterial); rim.position.z = side * 0.04; group.add(rim);
        var stamp = new THREE.Mesh(stampGeometry, rimMaterial); stamp.position.z = side * 0.045; group.add(stamp);
      });
      group.visible = false; w.root.add(group);
      var groundRing = new THREE.Mesh(diskGeometry, ringMaterial); groundRing.rotation.x = -Math.PI / 2; groundRing.visible = false; w.root.add(groundRing);
      coins.push({ group: group, ground: groundRing });

    }
    return { dimensions: dimensions, track: track, batches: batches, scenery: scenery, car: car, carVisual: carVisual,
      shadow: shadow, coins: coins, asphalt: asphalt,
      sunOffset: w.sunLight.position.clone() };
  }

  function sync(game, scene) {
    var scroll = game.distancePx / scene.dimensions.pixelsPerWorld, time = game.gameTimeMs;
    scene.track.position.z = game.playerZ;
    scene.asphalt.offset.y = modulo(scroll / 2, 1);
    scene.batches.forEach(function updateBatch(batch) {
      var transform = batch.matrix;
      batch.specs.forEach(function place(spec, i) {
        transform.position.set(spec[0], spec[1], game.playerZ + NEAR + modulo(spec[2] - NEAR - scroll, LOOP));
        transform.scale.set(spec[3], spec[4], spec[5]); transform.updateMatrix(); batch.mesh.setMatrixAt(i, transform.matrix);
      });
      batch.mesh.instanceMatrix.needsUpdate = true; batch.mesh.computeBoundingSphere();
    });
    scene.scenery.forEach(function place(item) {
      item.object.position.z = game.playerZ + NEAR + modulo(item.baseZ - NEAR - scroll, LOOP);
    });
    scene.car.position.set(-game.playerX, 0.105, game.playerZ);
    scene.car.rotation.y = -game.visualSteer * 0.12;
    scene.car.rotation.z = game.visualSteer * 0.02;
    scene.carVisual.applyPose({ timeMs: time, clip: "roll", clipTimeMs: modulo(scroll / (2 * Math.PI * 0.169), 1) * 1000,
      materialRoles: { paint: { color: game.assetContext.color("vehicle"), roughness: 0.38, metalness: 0.15 } } });
    scene.shadow.position.set(-game.playerX, 0.106, game.playerZ);
    scene.shadow.rotation.z = -game.visualSteer * 0.12;
    scene.coins.forEach(function poseCoin(item, i) {
      var coin = game.coins[i]; item.group.visible = !!coin; item.ground.visible = !!coin;
      if (!coin) return;
      item.group.position.set(-coin.x, 0.72 + Math.sin(time * 0.006 + Number(coin.id.slice(5))) * 0.025, coin.z);
      item.group.rotation.y = coin.spin;
      item.ground.position.set(-coin.x, 0.113, coin.z);
    });
    // Follow the world-space car so the same sunlight and shadow resolution persist along the highway.
    game.world3d.sunLight.position.copy(scene.sunOffset); game.world3d.sunLight.position.z += game.playerZ;
    game.world3d.sunLight.target.position.set(0, 0, game.playerZ); game.world3d.sunLight.target.updateMatrixWorld(true);
  }
  window.CoastHighwayScene = Object.freeze({ assets: ASSETS, build: build, sync: sync });
})();
