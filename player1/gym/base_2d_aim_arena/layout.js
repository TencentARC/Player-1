(function roverHangarLayoutModule() {
  "use strict";
  var FAMILIES = ["twin_hangars", "loading_courts", "perimeter_loop", "staggered_halls"];
  function sample(context) {
    var seed = Number(context.rng.seed) >>> 0;
    return { template: FAMILIES[(seed + (context.profile === "perturbed" ? 1 : 0)) % FAMILIES.length],
      width_scale: [0.84, 0.92, 1][(seed >>> 9) % 3], depth_scale: [0.9, 1][(seed >>> 13) % 2] };
  }
  function build(layout, width, height) {
    var definitions = {
      twin_hangars: [[-305, 0, 420, 510], [325, 0, 350, 460], [5, -30, 480, 180]],
      loading_courts: [[0, 20, 1000, 210], [-305, -155, 370, 270], [325, 145, 360, 280], [295, -180, 280, 230]],
      perimeter_loop: [[-415, 0, 230, 550], [415, 0, 230, 550], [0, -190, 950, 170], [0, 190, 950, 170], [0, 0, 190, 510]],
      staggered_halls: [[-350, -65, 340, 450], [0, 100, 320, 360], [355, -75, 320, 430], [-180, 80, 290, 180], [180, -55, 300, 180]],
    };
    if (!definitions[layout.template]) throw new Error("Unknown rover workshop layout");
    return window.PlayerOneConnectedLayout.build({ id: layout.template, revision: 2, wallThickness: 16, wallHeight: 16,
      regions: definitions[layout.template].map(function region(value, index) {
        return { id: "hangar_" + index, x: width / 2 + value[0] * layout.width_scale,
          z: height / 2 + value[1] * layout.depth_scale, width: value[2] * layout.width_scale,
          depth: value[3] * layout.depth_scale, style: index % 2 ? "service" : "hangar" };
      }) });
  }
  window.RoverHangarLayout = Object.freeze({ sample: sample, build: build });
})();
