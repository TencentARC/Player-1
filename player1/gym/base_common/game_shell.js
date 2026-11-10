(function gameShellModule() {
  "use strict";

  function formatValue(value, precision) {
    if (value === undefined || value === null || (typeof value === "string" && !value.trim())) return "—";
    if (precision !== undefined) {
      if (typeof value !== "number" && typeof value !== "string") return "—";
      var number = Number(value);
      if (!Number.isFinite(number)) return "—";
      var fixed = number.toFixed(precision);
      return Number(fixed) === 0 ? (0).toFixed(precision) : fixed;
    }
    if (typeof value === "number") {
      if (!Number.isFinite(value)) return "—";
      return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)));
    }
    if (typeof value === "boolean") return value ? "Yes" : "No";
    return String(value);
  }

  function element(tag, className, parent) {
    var node = document.createElement(tag);
    node.className = className;
    if (parent) parent.appendChild(node);
    return node;
  }

  function writeText(node, value) {
    if (node.textContent !== value) node.textContent = value;
  }

  function metric(parent, label) {
    var root = element("div", "metric", parent);
    var name = element("span", "label", root);
    var value = element("span", "value", root);
    writeText(name, label);
    writeText(value, "—");
    return { root: root, label: name, value: value };
  }

  function create(game, config) {
    if (!config || typeof config.read !== "function") throw new Error("GameShell requires a presentation reader");
    var shell = document.querySelector(".shell");
    if (!shell) throw new Error("GameShell requires a .shell container");
    var panel = element("aside", "hud game-info", shell);
    panel.setAttribute("aria-label", "Game information");
    var header = element("div", "game-info-header", panel);
    writeText(element("h2", "game-info-title", header), formatValue(config.title));
    var status = element("span", "game-info-state", header);
    status.id = "metric-status";
    writeText(status, "—");
    var metrics = element("div", "game-info-metrics", panel);
    var fields = [
      ["primaryScore", "Primary score", 2, "metric-primary-score"],
      ["stepReward", "Step reward", 2, "metric-step-reward"],
      ["episodeReward", "Episode reward", 2, "metric-episode-reward"],
      ["difficulty", "Difficulty", undefined, "metric-difficulty"],
      ["perturbation", "Variation", undefined, "metric-perturb"],
    ];
    var commonRows = fields.map(function commonRow(field) {
      var row = metric(metrics, field[1]);
      row.value.id = field[3];
      return row;
    });
    var seeds = element("div", "game-info-seeds", panel);
    var seedFields = [
      ["seed", "Master seed", "metric-seed"],
      ["domainAppearanceSeed", "Appearance seed", "metric-appearance-seed"],
      ["domainCameraSeed", "Camera seed", "metric-camera-seed"],
      ["domainSceneSeed", "Scene seed", "metric-scene-seed"],
      ["control", "Control seed", "metric-control-seed"],
    ];
    var seedRows = seedFields.map(function seedRow(field) {
      var row = metric(seeds, field[1]);
      row.value.id = field[2];
      return row;
    });
    var details = element("div", "game-info-details", panel);
    var detailRows = [];
    var controls = Array.isArray(config.controls) ? config.controls.join(" · ") : config.controls;
    var shortcuts = "F: Fullscreen · -: Appearance · =: Camera · [: Scene · ]: Control"
      + " · \\: All seeds · ,: Replay same seeds";
    writeText(element("p", "hint", panel), controls ? String(controls) + " · " + shortcuts : shortcuts);

    function isFullscreen() {
      var classes = document.documentElement.classList;
      return classes.contains("gamelet-3d-fullscreen") || classes.contains("gamelet-three2d-fullscreen");
    }

    function update() {
      if (isFullscreen()) return;
      // The presentation reader samples game fields; state APIs may consume terminal receipts.
      var data = config.read.call(game) || {};
      var control = game.controlResponse;
      if (control && (control.profile === "perturbed" || Object.keys(control.overrides).length)) {
        data.perturbation = data.perturbation && data.perturbation !== "none"
          ? data.perturbation + "+control" : "control";
      }
      writeText(status, formatValue(data.status));
      fields.forEach(function updateCommon(field, index) {
        writeText(commonRows[index].value, formatValue(data[field[0]], field[2]));
      });
      // Read resolved episode seeds, including derived defaults, without consuming RNG or state receipts.
      var seedValues = game.seedDomains || {};
      seedFields.forEach(function updateSeed(field, index) {
        var value = field[0] === "control" ? control && control.seed : seedValues[field[0]];
        writeText(seedRows[index].value, formatValue(value));
      });
      var values = Array.isArray(data.details) ? data.details : [];
      while (detailRows.length > values.length) details.removeChild(detailRows.pop().root);
      values.forEach(function updateDetail(entry, index) {
        entry = entry || [];
        var row = detailRows[index];
        if (!row) row = detailRows[index] = metric(details, "—");
        writeText(row.label, formatValue(entry[0]));
        writeText(row.value, formatValue(entry[1]));
      });
    }

    var observer = new window.MutationObserver(function updateLayout() { update(); });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });

    return { update: update };
  }

  window.GameShell = Object.freeze({ create: create });
})();
