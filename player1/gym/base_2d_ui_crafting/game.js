(function () {
  "use strict";

  var T2D = window.BaseGameletThree2D;
  var U = window.BaseGameletCommon;
  var Core = window.GameEngineCore;
  var rewardConfig = window.Base2DUICraftingRewardConfig;
  var Workshop = window.WorkshopScene;

  var GAME_ID = "base_2d_ui_crafting";
  var LOGIC_HEIGHT = 720;
  var LOGIC_WIDTH = T2D.viewport.widthForHeight(LOGIC_HEIGHT);
  var DISPLAY_WIDTH = T2D.viewport.baseWidth;
  var DISPLAY_HEIGHT = T2D.viewport.baseHeight;
  var UI_SCALE = 1.4;
  var UI_CONTENT_WIDTH = Math.round(960 * UI_SCALE);
  var UI_OFFSET_X = (LOGIC_WIDTH - UI_CONTENT_WIDTH) / 2;
  var STEP_MS = 1000 / 60;
  var DEFAULT_SEED = 42;
  var DEFAULT_DIFFICULTY = 1;
  var MAX_DIFFICULTY = 5;
  var ASSET_REQUIREMENTS = Workshop.assets;
  var INVENTORY_SLOT_COUNT = 36;
  var INVENTORY_COLUMNS = 9;
  var HOTBAR_START = 27;
  var MAX_STACK = 64;
  var DRAG_THRESHOLD = 7;
  var FURNACE_SMELT_MS = 1200;
  var FURNACE_FUEL_MS = 8000;
  var FURNACE_ROUND_MARKERS = Object.freeze({
    torch: true,
    stone_shovel: true,
    bread: true,
  });

  function uiPx(value) {
    return Math.round(value * UI_SCALE);
  }

  var ITEMS = Object.freeze({
    oak_log: Object.freeze({ id: "oak_log", label: "Oak Log", kind: "material", maxStack: 64 }),
    oak_planks: Object.freeze({ id: "oak_planks", label: "Oak Planks", kind: "material", maxStack: 64 }),
    stick: Object.freeze({ id: "stick", label: "Stick", kind: "material", maxStack: 64 }),
    coal: Object.freeze({ id: "coal", label: "Coal", kind: "material", maxStack: 64 }),
    cobblestone: Object.freeze({ id: "cobblestone", label: "Cobblestone", kind: "material", maxStack: 64 }),
    iron_ingot: Object.freeze({ id: "iron_ingot", label: "Iron Ingot", kind: "material", maxStack: 64 }),
    gold_ingot: Object.freeze({ id: "gold_ingot", label: "Gold Ingot", kind: "material", maxStack: 64 }),
    leather: Object.freeze({ id: "leather", label: "Leather", kind: "material", maxStack: 64 }),
    string: Object.freeze({ id: "string", label: "String", kind: "material", maxStack: 64 }),
    wheat: Object.freeze({ id: "wheat", label: "Wheat", kind: "material", maxStack: 64 }),
    redstone: Object.freeze({ id: "redstone", label: "Redstone", kind: "material", maxStack: 64 }),
    feather: Object.freeze({ id: "feather", label: "Feather", kind: "material", maxStack: 64 }),
    iron_ore: Object.freeze({ id: "iron_ore", label: "Iron Ore", kind: "material", maxStack: 64 }),
    cactus: Object.freeze({ id: "cactus", label: "Cactus", kind: "material", maxStack: 64 }),
    potato: Object.freeze({ id: "potato", label: "Potato", kind: "food", maxStack: 64 }),
    nether_gold_ore: Object.freeze({ id: "nether_gold_ore", label: "Nether Gold Ore", kind: "material", maxStack: 64 }),
    clay_ball: Object.freeze({ id: "clay_ball", label: "Clay Ball", kind: "material", maxStack: 64 }),
    beef: Object.freeze({ id: "beef", label: "Raw Beef", kind: "food", maxStack: 64 }),
    birch_wood: Object.freeze({ id: "birch_wood", label: "Birch Wood", kind: "material", maxStack: 64 }),
    stone: Object.freeze({ id: "stone", label: "Stone", kind: "material", maxStack: 64 }),
    green_dye: Object.freeze({ id: "green_dye", label: "Green Dye", kind: "material", maxStack: 64 }),
    baked_potato: Object.freeze({ id: "baked_potato", label: "Baked Potato", kind: "food", maxStack: 64 }),
    brick: Object.freeze({ id: "brick", label: "Brick", kind: "material", maxStack: 64 }),
    cooked_beef: Object.freeze({ id: "cooked_beef", label: "Steak", kind: "food", maxStack: 64 }),
    charcoal: Object.freeze({ id: "charcoal", label: "Charcoal", kind: "material", maxStack: 64 }),
    smooth_stone: Object.freeze({ id: "smooth_stone", label: "Smooth Stone", kind: "material", maxStack: 64 }),
    wooden_pickaxe: Object.freeze({ id: "wooden_pickaxe", label: "Wooden Pickaxe", kind: "tool", maxStack: 1 }),
    stone_pickaxe: Object.freeze({ id: "stone_pickaxe", label: "Stone Pickaxe", kind: "tool", maxStack: 1 }),
    iron_pickaxe: Object.freeze({ id: "iron_pickaxe", label: "Iron Pickaxe", kind: "tool", maxStack: 1 }),
    wooden_sword: Object.freeze({ id: "wooden_sword", label: "Wooden Sword", kind: "tool", maxStack: 1 }),
    stone_sword: Object.freeze({ id: "stone_sword", label: "Stone Sword", kind: "tool", maxStack: 1 }),
    iron_sword: Object.freeze({ id: "iron_sword", label: "Iron Sword", kind: "tool", maxStack: 1 }),
    wooden_axe: Object.freeze({ id: "wooden_axe", label: "Wooden Axe", kind: "tool", maxStack: 1 }),
    stone_axe: Object.freeze({ id: "stone_axe", label: "Stone Axe", kind: "tool", maxStack: 1 }),
    iron_axe: Object.freeze({ id: "iron_axe", label: "Iron Axe", kind: "tool", maxStack: 1 }),
    wooden_shovel: Object.freeze({ id: "wooden_shovel", label: "Wooden Shovel", kind: "tool", maxStack: 1 }),
    stone_shovel: Object.freeze({ id: "stone_shovel", label: "Stone Shovel", kind: "tool", maxStack: 1 }),
    torch: Object.freeze({ id: "torch", label: "Torch", kind: "utility", maxStack: 64 }),
    crafting_table: Object.freeze({ id: "crafting_table", label: "Crafting Table", kind: "block", maxStack: 64 }),
    furnace: Object.freeze({ id: "furnace", label: "Furnace", kind: "block", maxStack: 64 }),
    chest: Object.freeze({ id: "chest", label: "Chest", kind: "block", maxStack: 64 }),
    shield: Object.freeze({ id: "shield", label: "Shield", kind: "tool", equipmentSlot: "offhand", maxStack: 1 }),
    wooden_helmet: Object.freeze({ id: "wooden_helmet", label: "Wooden Helmet", kind: "armor", equipmentSlot: "head", maxStack: 1 }),
    wooden_chestplate: Object.freeze({ id: "wooden_chestplate", label: "Wooden Chestplate", kind: "armor", equipmentSlot: "chest", maxStack: 1 }),
    wooden_leggings: Object.freeze({ id: "wooden_leggings", label: "Wooden Leggings", kind: "armor", equipmentSlot: "legs", maxStack: 1 }),
    wooden_boots: Object.freeze({ id: "wooden_boots", label: "Wooden Boots", kind: "armor", equipmentSlot: "feet", maxStack: 1 }),
    iron_helmet: Object.freeze({ id: "iron_helmet", label: "Iron Helmet", kind: "armor", equipmentSlot: "head", maxStack: 1 }),
    iron_chestplate: Object.freeze({ id: "iron_chestplate", label: "Iron Chestplate", kind: "armor", equipmentSlot: "chest", maxStack: 1 }),
    iron_leggings: Object.freeze({ id: "iron_leggings", label: "Iron Leggings", kind: "armor", equipmentSlot: "legs", maxStack: 1 }),
    iron_boots: Object.freeze({ id: "iron_boots", label: "Iron Boots", kind: "armor", equipmentSlot: "feet", maxStack: 1 }),
    bread: Object.freeze({ id: "bread", label: "Bread", kind: "food", maxStack: 64 }),
    bucket: Object.freeze({ id: "bucket", label: "Bucket", kind: "utility", maxStack: 16 }),
  });

  function freezePattern(rows) {
    return Object.freeze(rows.map(function freezeRow(row) { return Object.freeze(row.slice()); }));
  }

  function recipe(id, output, outputCount, mode, rows) {
    return Object.freeze({
      id: id,
      output: output,
      outputCount: outputCount,
      mode: mode,
      pattern: freezePattern(rows),
    });
  }

  function smeltRecipe(id, input, output) {
    return Object.freeze({
      id: id,
      input: input,
      fuel: "coal",
      output: output,
      outputCount: 1,
      mode: "furnace",
      smeltMs: FURNACE_SMELT_MS,
      pattern: freezePattern([[input]]),
    });
  }

  function equipmentRequest(item, slot) {
    return Object.freeze({
      id: "equip_" + item,
      output: item,
      outputCount: 1,
      mode: "equipment",
      equipmentSlot: slot,
      pattern: freezePattern([[item]]),
    });
  }

  var RECIPES = Object.freeze([
    recipe("oak_planks", "oak_planks", 4, "inventory", [["oak_log"]]),
    recipe("stick", "stick", 4, "inventory", [["oak_planks"], ["oak_planks"]]),
    recipe("torch", "torch", 4, "inventory", [["coal"], ["stick"]]),
    recipe("crafting_table", "crafting_table", 1, "inventory", [
      ["oak_planks", "oak_planks"],
      ["oak_planks", "oak_planks"],
    ]),
    recipe("wooden_pickaxe", "wooden_pickaxe", 1, "workbench", [
      ["oak_planks", "oak_planks", "oak_planks"],
      [null, "stick", null],
      [null, "stick", null],
    ]),
    recipe("stone_pickaxe", "stone_pickaxe", 1, "workbench", [
      ["cobblestone", "cobblestone", "cobblestone"],
      [null, "stick", null],
      [null, "stick", null],
    ]),
    recipe("wooden_sword", "wooden_sword", 1, "workbench", [
      ["oak_planks"],
      ["oak_planks"],
      ["stick"],
    ]),
    recipe("stone_sword", "stone_sword", 1, "workbench", [
      ["cobblestone"],
      ["cobblestone"],
      ["stick"],
    ]),
    recipe("wooden_axe", "wooden_axe", 1, "workbench", [
      ["oak_planks", "oak_planks"],
      ["oak_planks", "stick"],
      [null, "stick"],
    ]),
    recipe("stone_axe", "stone_axe", 1, "workbench", [
      ["cobblestone", "cobblestone"],
      ["cobblestone", "stick"],
      [null, "stick"],
    ]),
    recipe("wooden_shovel", "wooden_shovel", 1, "workbench", [
      ["oak_planks"],
      ["stick"],
      ["stick"],
    ]),
    recipe("stone_shovel", "stone_shovel", 1, "workbench", [
      ["cobblestone"],
      ["stick"],
      ["stick"],
    ]),
    recipe("iron_pickaxe", "iron_pickaxe", 1, "workbench", [
      ["iron_ingot", "iron_ingot", "iron_ingot"],
      [null, "stick", null],
      [null, "stick", null],
    ]),
    recipe("iron_sword", "iron_sword", 1, "workbench", [
      ["iron_ingot"],
      ["iron_ingot"],
      ["stick"],
    ]),
    recipe("iron_axe", "iron_axe", 1, "workbench", [
      ["iron_ingot", "iron_ingot"],
      ["iron_ingot", "stick"],
      [null, "stick"],
    ]),
    recipe("furnace", "furnace", 1, "workbench", [
      ["cobblestone", "cobblestone", "cobblestone"],
      ["cobblestone", null, "cobblestone"],
      ["cobblestone", "cobblestone", "cobblestone"],
    ]),
    recipe("chest", "chest", 1, "workbench", [
      ["oak_planks", "oak_planks", "oak_planks"],
      ["oak_planks", null, "oak_planks"],
      ["oak_planks", "oak_planks", "oak_planks"],
    ]),
    recipe("shield", "shield", 1, "workbench", [
      ["oak_planks", "iron_ingot", "oak_planks"],
      ["oak_planks", "oak_planks", "oak_planks"],
      [null, "oak_planks", null],
    ]),
    recipe("iron_helmet", "iron_helmet", 1, "workbench", [
      ["iron_ingot", "iron_ingot", "iron_ingot"],
      ["iron_ingot", null, "iron_ingot"],
    ]),
    recipe("bread", "bread", 1, "workbench", [["wheat", "wheat", "wheat"]]),
    recipe("bucket", "bucket", 1, "workbench", [
      ["iron_ingot", null, "iron_ingot"],
      [null, "iron_ingot", null],
    ]),
  ]);

  var FURNACE_RECIPES = Object.freeze([
    smeltRecipe("smelt_iron_ingot", "iron_ore", "iron_ingot"),
    smeltRecipe("smelt_green_dye", "cactus", "green_dye"),
    smeltRecipe("smelt_baked_potato", "potato", "baked_potato"),
    smeltRecipe("smelt_gold_ingot", "nether_gold_ore", "gold_ingot"),
    smeltRecipe("smelt_brick", "clay_ball", "brick"),
    smeltRecipe("smelt_cooked_beef", "beef", "cooked_beef"),
    smeltRecipe("smelt_charcoal", "birch_wood", "charcoal"),
    smeltRecipe("smelt_smooth_stone", "stone", "smooth_stone"),
  ]);

  var EQUIPMENT_REQUESTS = Object.freeze([
    equipmentRequest("wooden_helmet", "head"),
    equipmentRequest("wooden_chestplate", "chest"),
    equipmentRequest("wooden_leggings", "legs"),
    equipmentRequest("wooden_boots", "feet"),
    equipmentRequest("iron_helmet", "head"),
    equipmentRequest("iron_chestplate", "chest"),
    equipmentRequest("iron_leggings", "legs"),
    equipmentRequest("iron_boots", "feet"),
    equipmentRequest("shield", "offhand"),
  ]);

  var RECIPE_BY_ID = Object.create(null);
  RECIPES.forEach(function indexRecipe(definition) { RECIPE_BY_ID[definition.id] = definition; });
  FURNACE_RECIPES.forEach(function indexFurnaceRecipe(definition) {
    RECIPE_BY_ID[definition.id] = definition;
  });
  EQUIPMENT_REQUESTS.forEach(function indexEquipmentRequest(definition) {
    RECIPE_BY_ID[definition.id] = definition;
  });

  var FURNACE_RECIPE_BY_INPUT = Object.create(null);
  var FURNACE_RECIPE_BY_OUTPUT = Object.create(null);
  FURNACE_RECIPES.forEach(function indexFurnaceInput(definition) {
    FURNACE_RECIPE_BY_INPUT[definition.input] = definition;
    FURNACE_RECIPE_BY_OUTPUT[definition.output] = definition;
  });

  var EQUIPMENT_SLOT_ORDER = Object.freeze(["head", "chest", "legs", "feet", "offhand"]);

  var MATERIAL_IDS = Object.freeze([
    "oak_log", "oak_planks", "stick", "coal", "cobblestone", "iron_ingot",
    "gold_ingot", "leather", "string", "wheat", "redstone", "feather",
  ]);

  var PERTURBATION_CONTRACT = Core.perturbations.defineContract({
    game_id: GAME_ID,
    capabilities: {
      appearance: ["palette", "background", "assets"],
      camera: ["projection"],
      scene: ["layout", "entity_spawn"],
    },
    samplers: {
      camera: { projection: T2D.camera.projectionSampler },
      scene: { layout: Core.perturbations.templateSampler("bench_left", ["bench_right", "inventory_upper", "book_right"]) },
    },
    validators: {
      camera: { projection: T2D.camera.projectionValidator },
      scene: { layout: Core.perturbations.templateValidator(["bench_left", "bench_right", "inventory_upper", "book_right"]) },
    },
  });

  var UI = Object.freeze({
    requestBanner: Object.freeze({ x: 24, y: 8, w: 525, h: 70 }),
    panelY: 88,
    panelW: uiPx(456),
    panelH: uiPx(440),
    closedX: UI_OFFSET_X + uiPx(252),
    openMainX: UI_OFFSET_X + uiPx(436),
    mainInset: uiPx(12),
    bookX: UI_OFFSET_X + uiPx(104),
    bookW: uiPx(324),
    bookCategoryOffset: uiPx(36),
    bookCategorySize: uiPx(34),
    bookCategoryIconSize: uiPx(28),
    bookEntrySize: uiPx(53),
    bookEntryGap: uiPx(6),
    bookEntryColumns: 5,
    inventorySlot: uiPx(48),
    craftSlot: uiPx(48),
    craftArrowWidth: uiPx(36),
  });
  var CRAFTING_BOOK_CATEGORIES = Object.freeze([
    Object.freeze({ id: "all", label: "All Recipes", icon: "crafting_table" }),
    Object.freeze({ id: "tools", label: "Tools", icon: "wooden_pickaxe" }),
    Object.freeze({ id: "gear", label: "Equipment", icon: "iron_helmet" }),
  ]);
  var FURNACE_BOOK_CATEGORIES = Object.freeze([
    Object.freeze({ id: "all", label: "All Recipes", icon: "furnace" }),
    Object.freeze({ id: "materials", label: "Materials", icon: "iron_ingot" }),
    Object.freeze({ id: "food", label: "Food", icon: "baked_potato" }),
  ]);

  var BASE_COLORS = Workshop.colors;
  var LEGACY_COLOR_PERTURBATION = Object.freeze({
    palette: Object.freeze({
      hue_shift_degrees: 28,
      saturation_scale: 0.9,
      brightness_scale: 1.04,
    }),
    background: Object.freeze({
      hue_shift_degrees: -14,
      saturation_scale: 1.08,
      brightness_scale: 0.92,
    }),
  });

  var canvas = document.getElementById("display");
  var view = null;
  var presentation = null;

  function cloneStack(value) {
    return value ? { item: value.item, count: value.count } : null;
  }

  function cloneSlots(values) {
    return values.map(cloneStack);
  }

  function makeStack(item, count) {
    return { item: item, count: Math.max(1, Math.floor(count || 1)) };
  }

  function stackPayload(value) {
    return value ? { item: value.item, count: value.count } : null;
  }

  function shuffledCopy(values, rng) {
    var shuffled = values.slice();
    for (var index = shuffled.length - 1; index > 0; index -= 1) {
      var swapIndex = rng.randint(0, index + 1);
      var temporary = shuffled[index];
      shuffled[index] = shuffled[swapIndex];
      shuffled[swapIndex] = temporary;
    }
    return shuffled;
  }

  function pointInRect(point, rect) {
    return point.x >= rect.x && point.x <= rect.x + rect.w
      && point.y >= rect.y && point.y <= rect.y + rect.h;
  }

  function finiteRounded(value) {
    return Number.isFinite(value) ? Math.round(value * 1000) / 1000 : null;
  }

  function patternDimensions(definition) {
    return { rows: definition.pattern.length, columns: definition.pattern[0].length };
  }

  function recipeFitsGrid(definition, gridSize) {
    var dimensions = patternDimensions(definition);
    return dimensions.rows <= gridSize && dimensions.columns <= gridSize;
  }

  function ingredientCounts(definition) {
    var counts = Object.create(null);
    definition.pattern.forEach(function countRow(row) {
      row.forEach(function countItem(item) {
        if (item) counts[item] = (counts[item] || 0) + 1;
      });
    });
    return counts;
  }

  function recipeMaterialCount(definition) {
    if (definition.mode === "equipment") return 0;
    if (definition.mode === "furnace") return 1 + (definition.fuel ? 1 : 0);
    return definition.pattern.reduce(function countRows(total, row) {
      return total + row.reduce(function countItems(rowTotal, item) {
        return rowTotal + (item ? 1 : 0);
      }, 0);
    }, 0);
  }

  function decoyItemCount(level, poolSize) {
    return Math.min(poolSize, 1 + Math.floor((level - 1) * 1.5));
  }

  function mirroredPattern(pattern) {
    return pattern.map(function reverseRow(row) { return row.slice().reverse(); });
  }

  function gridMatchesPattern(grid, gridSize, pattern, offsetRow, offsetColumn) {
    for (var row = 0; row < gridSize; row += 1) {
      for (var column = 0; column < gridSize; column += 1) {
        var patternRow = row - offsetRow;
        var patternColumn = column - offsetColumn;
        var expected = patternRow >= 0 && patternRow < pattern.length
          && patternColumn >= 0 && patternColumn < pattern[0].length
          ? pattern[patternRow][patternColumn]
          : null;
        var actual = grid[row * gridSize + column];
        if ((actual ? actual.item : null) !== expected) return false;
      }
    }
    return true;
  }

  function matchRecipePattern(grid, gridSize, definition) {
    if (!recipeFitsGrid(definition, gridSize)) return false;
    var dimensions = patternDimensions(definition);
    var variants = [definition.pattern, mirroredPattern(definition.pattern)];
    for (var variantIndex = 0; variantIndex < variants.length; variantIndex += 1) {
      for (var row = 0; row <= gridSize - dimensions.rows; row += 1) {
        for (var column = 0; column <= gridSize - dimensions.columns; column += 1) {
          if (gridMatchesPattern(grid, gridSize, variants[variantIndex], row, column)) return true;
        }
      }
    }
    return false;
  }

  function correctPatternPlacementCount(grid, gridSize, definition) {
    if (!recipeFitsGrid(definition, gridSize)) return 0;
    var dimensions = patternDimensions(definition);
    var variants = [definition.pattern, mirroredPattern(definition.pattern)];
    var bestCount = 0;
    for (var variantIndex = 0; variantIndex < variants.length; variantIndex += 1) {
      var pattern = variants[variantIndex];
      for (var offsetRow = 0; offsetRow <= gridSize - dimensions.rows; offsetRow += 1) {
        for (var offsetColumn = 0; offsetColumn <= gridSize - dimensions.columns; offsetColumn += 1) {
          var count = 0;
          for (var row = 0; row < pattern.length; row += 1) {
            for (var column = 0; column < pattern[row].length; column += 1) {
              var expected = pattern[row][column];
              if (!expected) continue;
              var actual = grid[(row + offsetRow) * gridSize + column + offsetColumn];
              if (actual && actual.item === expected) count += 1;
            }
          }
          bestCount = Math.max(bestCount, count);
        }
      }
    }
    return bestCount;
  }

  function Base2DUICrafting() {
    this.defaults = {
      seed: DEFAULT_SEED,
      difficulty: DEFAULT_DIFFICULTY,
      maxDifficulty: MAX_DIFFICULTY,
    };
    this.urlConfig = Core.config.readUrl(this.defaults);
    this.mouse = { x: LOGIC_WIDTH / 2, y: LOGIC_HEIGHT / 2, dx: 0, dy: 0, left: false, right: false };
    this.pointerGesture = null;
    this.paused = false;
    this.runtime = { resetCount: 0, episodeCount: 0, lastResetMethod: null };
    this.bestMetrics = { bestPrimaryScore: 0 };
    Core.terminal.initialize(this);
    this.bindInput();
    Core.lifecycle.bindResetKeys(this);
    this.beginEpisode({}, false);
    this.startLoop();
  }

  Base2DUICrafting.prototype.normalizeOptions = function normalizeOptions(options) {
    return Core.config.normalizeOptions(options || {}, MAX_DIFFICULTY);
  };

  Base2DUICrafting.prototype.resolveEpisodeConfig = function resolveEpisodeConfig(normalized) {
    return Core.config.mergeEpisode(this.urlConfig, normalized);
  };

  Base2DUICrafting.prototype.beginEpisode = function beginEpisode(options, countAsReset, flags) {
    var episodeFlags = flags || {};
    var normalized = this.normalizeOptions(options || {});
    var config = this.resolveEpisodeConfig(normalized);

    Core.lifecycle.resetEpisode(this);
    this.currentConfig = Core.config.cloneEpisode(config);
    Core.terminal.clear(this, episodeFlags);
    Core.domains.beginEpisode(this, config, PERTURBATION_CONTRACT, DEFAULT_SEED);
    this.sceneLayout = Core.domains.sample(this, "scene", "layout", { template: "bench_left" });
    this.sceneRng = Core.domains.gameplayRng(this, "scene", "entity_spawn");
    this.difficulty = config.difficulty;
    this.mode = config.autostart ? "playing" : "paused";
    this.inventory = new Array(INVENTORY_SLOT_COUNT).fill(null);
    this.craftGrid = [];
    this.furnaceInput = null;
    this.furnaceFuel = null;
    this.furnaceOutput = null;
    this.equipment = { head: null, chest: null, legs: null, feet: null, offhand: null };
    this.furnaceProgressMs = 0;
    this.furnaceBurnRemainingMs = 0;
    this.furnaceBurnTotalMs = 0;
    this.cursorStack = null;
    this.currentRecipe = null;
    this.lastSelectorRecipe = null;
    this.lastFurnaceRecipe = null;
    this.lastEquipmentRequest = null;
    this.interfaceMode = "workbench";
    this.gridSize = 3;
    this.recipeBookOpen = false;
    this.recipeBookCategory = "all";
    this.bookEntries = [];
    this.targetCrafts = 0;
    this.craftedItems = 0;
    this.wrongCrafts = 0;
    this.invalidActions = 0;
    this.transfers = 0;
    this.manualPlacements = 0;
    this.recipeBookOpens = 0;
    this.recipeBookRewards = 0;
    this.correctMaterialPlacements = 0;
    this.correctMaterialReward = 0;
    this.recipeAutofills = 0;
    this.furnaceRounds = 0;
    this.equipmentRounds = 0;
    this.correctEquipmentSelections = 0;
    this.equipmentEquipped = 0;
    this.smeltedItems = 0;
    this.furnaceFuelConsumed = 0;
    this.leftClicks = 0;
    this.rightClicks = 0;
    this.roundIndex = 0;
    this.stepCount = 0;
    this.gameTimeMs = 0;
    this.taskEvents = [];
    this.lastAction = "reset";
    this.feedback = null;
    this.feedbackUntilMs = 0;
    this.mouse.left = false;
    this.mouse.right = false;
    this.mouse.dx = 0;
    this.mouse.dy = 0;
    this.pointerGesture = null;
    Core.reward.resetEpisode(this);
    this.terminal = { isTerminal: false, outcome: null, reason: null };
    T2D.visuals.configure(this, config, {
      defaultAssetPack: Workshop.pack,
      baseWidth: DISPLAY_WIDTH,
      baseHeight: DISPLAY_HEIGHT,
      view: view,
    });
    this.startRound();

    this.runtime.episodeCount += 1;
    if (countAsReset !== false) this.runtime.resetCount += 1;
    this.runtime.lastResetMethod = countAsReset === false ? "init" : "inplace_reset";

    this.render();
    return {
      accepted: normalized,
      applied: {
        seed: this.seed,
        difficulty: this.difficulty,
        autostart: config.autostart,
        asset_pack: this.assetPack,
        perturb: config.perturb,
      },
      notes: [],
    };
  };

  Base2DUICrafting.prototype.decoyLevel = function decoyLevel() {
    return Math.max(1, Math.min(MAX_DIFFICULTY, Math.ceil(this.difficulty)));
  };

  Base2DUICrafting.prototype.availableRecipes = function availableRecipes() {
    return RECIPES;
  };

  Base2DUICrafting.prototype.availableFurnaceRecipes = function availableFurnaceRecipes() {
    return FURNACE_RECIPES;
  };

  Base2DUICrafting.prototype.availableEquipmentRequests = function availableEquipmentRequests() {
    return EQUIPMENT_REQUESTS;
  };

  Base2DUICrafting.prototype.addEvent = function addEvent(type, detail) {
    this.taskEvents.push({ step: this.stepCount, type: type, detail: detail || null });
    if (this.taskEvents.length > 32) this.taskEvents.shift();
  };

  Base2DUICrafting.prototype.createBookEntries = function createBookEntries() {
    if (this.interfaceMode === "equipment") return [];
    var self = this;
    var allRecipes = this.interfaceMode === "furnace" ? FURNACE_RECIPES : RECIPES;
    var count = Math.min(allRecipes.length, 15);
    var candidates = allRecipes.filter(function fitsCurrentInterface(definition) {
      return self.interfaceMode === "furnace" || recipeFitsGrid(definition, self.gridSize);
    });
    var entries = [this.currentRecipe];
    shuffledCopy(candidates, this.sceneRng).forEach(function addCandidate(definition) {
      if (entries.length >= count || definition.id === self.currentRecipe.id) return;
      entries.push(definition);
    });
    return shuffledCopy(entries, this.sceneRng);
  };

  Base2DUICrafting.prototype.startRound = function startRound() {
    var available = this.availableRecipes();
    var selectorRecipe = this.sceneRng.choiceExcept(available, this.lastSelectorRecipe) || available[0];
    var furnaceRecipes = this.availableFurnaceRecipes();
    var equipmentRequests = this.availableEquipmentRequests();
    var useEquipment = equipmentRequests.length > 0 && this.sceneRng.next() < 0.2;
    var useFurnace = !useEquipment && !!(FURNACE_ROUND_MARKERS[selectorRecipe.id] && furnaceRecipes.length);
    this.lastSelectorRecipe = selectorRecipe;
    if (useEquipment) {
      this.currentRecipe = this.sceneRng.choiceExcept(equipmentRequests, this.lastEquipmentRequest)
        || equipmentRequests[0];
      this.lastEquipmentRequest = this.currentRecipe;
    } else if (useFurnace) {
      this.currentRecipe = this.sceneRng.choiceExcept(furnaceRecipes, this.lastFurnaceRecipe) || furnaceRecipes[0];
      this.lastFurnaceRecipe = this.currentRecipe;
    } else {
      this.currentRecipe = selectorRecipe;
    }
    this.interfaceMode = this.currentRecipe.mode;
    this.gridSize = this.interfaceMode === "inventory" ? 2 : (this.interfaceMode === "workbench" ? 3 : 0);
    this.roundIndex += 1;
    if (useFurnace) this.furnaceRounds += 1;
    if (useEquipment) this.equipmentRounds += 1;
    this.cursorStack = null;
    this.craftGrid = new Array(this.gridSize * this.gridSize).fill(null);
    this.furnaceInput = null;
    this.furnaceFuel = null;
    this.furnaceOutput = null;
    this.equipment = { head: null, chest: null, legs: null, feet: null, offhand: null };
    this.furnaceProgressMs = 0;
    this.furnaceBurnRemainingMs = 0;
    this.furnaceBurnTotalMs = 0;
    this.inventory = new Array(INVENTORY_SLOT_COUNT).fill(null);
    this.recipeBookOpen = false;
    this.recipeBookCategory = "all";
    this.roundRecipeBookRewarded = false;
    this.roundCorrectPlacementsRewarded = 0;
    this.roundEquipmentSelectionRewarded = false;
    this.roundRequiredMaterialCount = recipeMaterialCount(this.currentRecipe);

    var decoyLevel = this.decoyLevel();
    var inventoryStacks;
    if (this.interfaceMode === "equipment") {
      inventoryStacks = [makeStack(this.currentRecipe.output, 1)];
      var equipmentDecoyCount = decoyItemCount(decoyLevel, equipmentRequests.length - 1);
      shuffledCopy(equipmentRequests, this.sceneRng).forEach(function addEquipmentDecoy(definition) {
        if (definition.id === this.currentRecipe.id || inventoryStacks.length >= 1 + equipmentDecoyCount) return;
        inventoryStacks.push(makeStack(definition.output, 1));
      }, this);
    } else if (this.interfaceMode === "furnace") {
      inventoryStacks = [
        makeStack(this.currentRecipe.input, 1),
        makeStack("coal", this.sceneRng.randint(4, 8)),
      ];
      var furnaceDecoyPool = MATERIAL_IDS.concat(FURNACE_RECIPES.map(function furnaceInput(definition) {
        return definition.input;
      })).filter(function uniqueFurnaceDecoy(itemId, index, items) {
        return itemId !== this.currentRecipe.input && itemId !== "coal" && items.indexOf(itemId) === index;
      }, this);
      var furnaceDecoyStacks = shuffledCopy(furnaceDecoyPool, this.sceneRng).map(function createFurnaceDecoy(itemId) {
        return makeStack(itemId, this.sceneRng.randint(1, 4));
      }, this);
      inventoryStacks = inventoryStacks.concat(
        furnaceDecoyStacks.slice(0, decoyItemCount(decoyLevel, furnaceDecoyStacks.length))
      );
    } else {
      var required = ingredientCounts(this.currentRecipe);
      inventoryStacks = Object.keys(required).map(function materialStack(itemId) {
        var extra = this.sceneRng.randint(0, 2);
        return makeStack(itemId, required[itemId] + extra);
      }, this);
      var requiredIds = Object.keys(required);
      var decoyPool = MATERIAL_IDS.filter(function isDecoy(itemId) { return requiredIds.indexOf(itemId) < 0; });
      var decoyCount = decoyItemCount(decoyLevel, decoyPool.length);
      var decoyStacks = shuffledCopy(decoyPool, this.sceneRng).map(function createDecoy(itemId) {
        return makeStack(itemId, this.sceneRng.randint(1, 4));
      }, this);
      inventoryStacks = inventoryStacks.concat(decoyStacks.slice(0, decoyCount));
    }

    var slots = shuffledCopy(new Array(INVENTORY_SLOT_COUNT).fill(0).map(function slotIndex(_, index) {
      return index;
    }), this.sceneRng);
    inventoryStacks.forEach(function placeInitialStack(value, index) {
      this.inventory[slots[index]] = value;
    }, this);

    this.bookEntries = this.createBookEntries();
    this.lastAction = "new_request";
    this.addEvent("request_spawned", {
      recipe_id: this.currentRecipe.id,
      output: this.currentRecipe.output,
      interface_mode: this.interfaceMode,
      round_index: this.roundIndex,
    });
  };

  Base2DUICrafting.prototype.startPlaying = function startPlaying(actionLabel) {
    if (this.paused || this.mode !== "paused") return false;
    this.mode = "playing";
    this.lastAction = actionLabel || "start";
    return true;
  };

  Base2DUICrafting.prototype.step = function step() {
    if (this.mode !== "playing") return false;
    this.updateFurnace(STEP_MS);
    this.stepCount += 1;
    this.gameTimeMs = this.stepCount * STEP_MS;
    this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, this.getPrimaryScore());
    return true;
  };

  Base2DUICrafting.prototype.layout = function layout() {
    var panel = {
      x: this.recipeBookOpen ? UI.openMainX : UI.closedX,
      y: UI.panelY,
      w: UI.panelW,
      h: UI.panelH,
    };
    var bookOnRight = this.sceneLayout.template === "book_right";
    if (this.recipeBookOpen && bookOnRight) panel.x = UI_OFFSET_X + uiPx(76);
    if (!this.recipeBookOpen && this.sceneLayout.template === "bench_right") panel.x += uiPx(96);
    if (!this.recipeBookOpen && this.sceneLayout.template === "bench_left") panel.x -= uiPx(72);
    var mainX = panel.x + UI.mainInset;
    var inventoryMode = this.interfaceMode === "inventory";
    var equipmentMode = this.interfaceMode === "equipment";
    var avatarMode = inventoryMode || equipmentMode;
    var furnaceMode = this.interfaceMode === "furnace";
    var result = {
      panel: panel,
      mainX: mainX,
      book: { x: bookOnRight ? panel.x + panel.w + uiPx(44) : UI.bookX, y: panel.y, w: UI.bookW, h: panel.h },
      title: furnaceMode ? "Furnace" : null,
      titleX: mainX + uiPx(62),
      titleY: panel.y + uiPx(10),
      craftLabelY: panel.y + uiPx(8),
      bookToggle: {
        kind: "book_toggle",
        id: "recipe_book_toggle",
        x: avatarMode ? mainX + uiPx(260) : mainX,
        y: avatarMode ? panel.y + uiPx(152) : panel.y + uiPx(84),
        w: UI.craftSlot,
        h: UI.craftSlot,
      },
      craftX: avatarMode ? mainX + uiPx(206) : mainX + uiPx(62),
      craftY: panel.y + uiPx(36),
      arrowY: avatarMode ? panel.y + uiPx(72) : panel.y + uiPx(96),
      output: {
        kind: "output",
        id: furnaceMode ? "furnace_output" : "craft_output",
        x: mainX + uiPx(avatarMode ? 384 : 306),
        y: panel.y + uiPx(avatarMode ? 60 : 84),
        w: UI.craftSlot,
        h: UI.craftSlot,
      },
      furnaceInput: {
        kind: "furnace_input",
        id: "furnace_input",
        x: mainX + uiPx(110),
        y: panel.y + uiPx(40),
        w: UI.craftSlot,
        h: UI.craftSlot,
      },
      furnaceFuel: {
        kind: "furnace_fuel",
        id: "furnace_fuel",
        x: mainX + uiPx(110),
        y: panel.y + uiPx(112),
        w: UI.craftSlot,
        h: UI.craftSlot,
      },
      furnaceFlame: {
        x: mainX + uiPx(124),
        y: panel.y + uiPx(89),
        w: uiPx(20),
        h: uiPx(22),
      },
      furnaceArrow: {
        x: mainX + uiPx(212),
        y: panel.y + uiPx(95),
        w: uiPx(48),
        h: uiPx(26),
      },
      avatar: null,
      equipmentSlots: [],
      offhand: null,
      inventoryLabelY: avatarMode ? null : panel.y + uiPx(190),
      inventoryX: mainX,
      inventoryY: panel.y + uiPx(216),
      hotbarY: panel.y + uiPx(368),
    };
    if (avatarMode) {
      result.avatar = {
        x: mainX + uiPx(56),
        y: panel.y + uiPx(16),
        w: uiPx(132),
        h: uiPx(192),
      };
      for (var index = 0; index < 4; index += 1) {
        result.equipmentSlots.push({
          kind: "equipment",
          slotId: EQUIPMENT_SLOT_ORDER[index],
          id: "equipment_" + EQUIPMENT_SLOT_ORDER[index],
          x: mainX,
          y: panel.y + uiPx(16) + index * UI.craftSlot,
          w: UI.craftSlot,
          h: UI.craftSlot,
        });
      }
      result.offhand = {
        kind: "equipment",
        slotId: "offhand",
        id: "equipment_offhand",
        x: mainX + uiPx(196),
        y: panel.y + uiPx(160),
        w: UI.craftSlot,
        h: UI.craftSlot,
      };
    }
    if (this.sceneLayout.template === "inventory_upper") {
      // Keep the four-row inventory and the complete native station intact while
      // exchanging their vertical positions. Every hit region consumes this layout.
      var stationShift = uiPx(220);
      result.craftY += stationShift;
      result.craftLabelY += stationShift;
      result.arrowY += stationShift;
      [result.bookToggle, result.output, result.furnaceInput, result.furnaceFuel,
        result.furnaceFlame, result.furnaceArrow, result.avatar, result.offhand]
        .concat(result.equipmentSlots).forEach(function shiftStation(region) {
          if (region) region.y += stationShift;
        });
      result.inventoryY = panel.y + uiPx(16);
      result.hotbarY = panel.y + uiPx(168);
    }
    return result;
  };

  Base2DUICrafting.prototype.gridRegion = function gridRegion(kind, index, x, y, size, columns) {
    return {
      kind: kind,
      index: index,
      id: kind + "_" + index,
      x: x + (index % columns) * size,
      y: y + Math.floor(index / columns) * size,
      w: size,
      h: size,
    };
  };

  Base2DUICrafting.prototype.bookEntryRegion = function bookEntryRegion(index, definition, layout) {
    var size = UI.bookEntrySize;
    var gap = UI.bookEntryGap;
    var columns = UI.bookEntryColumns;
    var rowWidth = columns * size + (columns - 1) * gap;
    return {
      kind: "book_entry",
      index: index,
      id: "recipe_" + definition.id,
      recipeId: definition.id,
      x: layout.book.x + Math.round((layout.book.w - rowWidth) * 0.5) + (index % columns) * (size + gap),
      y: layout.book.y + uiPx(84) + Math.floor(index / columns) * (size + gap),
      w: size,
      h: size,
    };
  };

  Base2DUICrafting.prototype.bookCategories = function bookCategories() {
    return this.interfaceMode === "furnace" ? FURNACE_BOOK_CATEGORIES : CRAFTING_BOOK_CATEGORIES;
  };

  Base2DUICrafting.prototype.bookCategoryRegion = function bookCategoryRegion(index, definition, layout) {
    return {
      kind: "book_category",
      index: index,
      id: "recipe_category_" + definition.id,
      categoryId: definition.id,
      label: definition.label,
      icon: definition.icon,
      x: layout.book.x - UI.bookCategoryOffset,
      y: layout.book.y + uiPx(40) + index * (UI.bookCategorySize + uiPx(4)),
      w: UI.bookCategorySize,
      h: UI.bookCategorySize,
    };
  };

  Base2DUICrafting.prototype.recipeMatchesBookCategory = function recipeMatchesBookCategory(definition) {
    var category = this.recipeBookCategory;
    if (category === "all") return true;
    var outputKind = ITEMS[definition.output].kind;
    if (this.interfaceMode === "furnace") {
      if (category === "food") return outputKind === "food";
      if (category === "materials") return outputKind !== "food";
      return false;
    }
    if (category === "tools") return outputKind === "tool";
    if (category === "gear") return outputKind === "tool" || outputKind === "armor";
    return false;
  };

  Base2DUICrafting.prototype.visibleBookEntries = function visibleBookEntries() {
    return this.bookEntries.filter(function categoryMatch(definition) {
      return this.recipeMatchesBookCategory(definition);
    }, this);
  };

  Base2DUICrafting.prototype.regions = function regions() {
    var layout = this.layout();
    var regions = [];
    if (this.interfaceMode !== "equipment") regions.push(layout.bookToggle, layout.output);
    if (this.interfaceMode === "furnace") {
      regions.push(layout.furnaceInput, layout.furnaceFuel);
    }
    if (this.interfaceMode === "equipment") {
      layout.equipmentSlots.forEach(function addEquipmentSlot(region) { regions.push(region); });
      regions.push(layout.offhand);
    }
    for (var craftIndex = 0; craftIndex < this.craftGrid.length; craftIndex += 1) {
      regions.push(this.gridRegion("craft", craftIndex, layout.craftX, layout.craftY, UI.craftSlot, this.gridSize));
    }
    for (var inventoryIndex = 0; inventoryIndex < INVENTORY_SLOT_COUNT; inventoryIndex += 1) {
      var inventoryRow = Math.floor(inventoryIndex / INVENTORY_COLUMNS);
      var inventoryY = inventoryIndex >= HOTBAR_START
        ? layout.hotbarY
        : layout.inventoryY + inventoryRow * UI.inventorySlot;
      regions.push(this.gridRegion(
        "inventory",
        inventoryIndex % INVENTORY_COLUMNS,
        layout.inventoryX,
        inventoryY,
        UI.inventorySlot,
        INVENTORY_COLUMNS
      ));
      regions[regions.length - 1].index = inventoryIndex;
      regions[regions.length - 1].id = "inventory_" + inventoryIndex;
    }
    if (this.recipeBookOpen) {
      this.bookCategories().forEach(function addBookCategory(definition, index) {
        regions.push(this.bookCategoryRegion(index, definition, layout));
      }, this);
      this.visibleBookEntries().forEach(function addBookEntry(definition, index) {
        regions.push(this.bookEntryRegion(index, definition, layout));
      }, this);
    }
    return regions;
  };

  Base2DUICrafting.prototype.hitRegion = function hitRegion(point) {
    var regions = this.regions();
    for (var index = regions.length - 1; index >= 0; index -= 1) {
      if (pointInRect(point, regions[index])) return regions[index];
    }
    return null;
  };

  Base2DUICrafting.prototype.stackAt = function stackAt(region) {
    if (!region) return null;
    if (region.kind === "inventory") return this.inventory[region.index];
    if (region.kind === "craft") return this.craftGrid[region.index];
    if (region.kind === "furnace_input") return this.furnaceInput;
    if (region.kind === "furnace_fuel") return this.furnaceFuel;
    if (region.kind === "equipment") return this.equipment[region.slotId];
    if (region.kind === "output") return this.outputStack();
    return null;
  };

  Base2DUICrafting.prototype.setStackAt = function setStackAt(region, value) {
    if (region.kind === "inventory") this.inventory[region.index] = value;
    else if (region.kind === "craft") this.craftGrid[region.index] = value;
    else if (region.kind === "furnace_input") {
      var previousItem = this.furnaceInput ? this.furnaceInput.item : null;
      this.furnaceInput = value;
      if (previousItem !== (value ? value.item : null)) this.furnaceProgressMs = 0;
    }
    else if (region.kind === "furnace_fuel") this.furnaceFuel = value;
    else if (region.kind === "equipment") this.equipment[region.slotId] = value;
  };

  Base2DUICrafting.prototype.inventoryItemCount = function inventoryItemCount(itemId, includeGrid) {
    var count = 0;
    this.inventory.forEach(function countInventory(value) {
      if (value && value.item === itemId) count += value.count;
    });
    if (includeGrid) {
      this.craftGrid.forEach(function countGrid(value) {
        if (value && value.item === itemId) count += value.count;
      });
      if (this.furnaceInput && this.furnaceInput.item === itemId) count += this.furnaceInput.count;
      if (this.furnaceFuel && this.furnaceFuel.item === itemId) count += this.furnaceFuel.count;
    }
    return count;
  };

  Base2DUICrafting.prototype.addStackToInventory = function addStackToInventory(input) {
    var remaining = cloneStack(input);
    if (!remaining) return null;
    var maxStack = ITEMS[remaining.item].maxStack || MAX_STACK;
    for (var index = 0; index < this.inventory.length && remaining.count > 0; index += 1) {
      var value = this.inventory[index];
      if (!value || value.item !== remaining.item || value.count >= maxStack) continue;
      var merged = Math.min(maxStack - value.count, remaining.count);
      value.count += merged;
      remaining.count -= merged;
    }
    for (var emptyIndex = 0; emptyIndex < this.inventory.length && remaining.count > 0; emptyIndex += 1) {
      if (this.inventory[emptyIndex]) continue;
      var placed = Math.min(maxStack, remaining.count);
      this.inventory[emptyIndex] = makeStack(remaining.item, placed);
      remaining.count -= placed;
    }
    return remaining.count > 0 ? remaining : null;
  };

  Base2DUICrafting.prototype.returnGridToInventory = function returnGridToInventory() {
    for (var index = 0; index < this.craftGrid.length; index += 1) {
      if (!this.craftGrid[index]) continue;
      var remainder = this.addStackToInventory(this.craftGrid[index]);
      if (remainder) return false;
      this.craftGrid[index] = null;
    }
    return true;
  };

  Base2DUICrafting.prototype.removeInventoryItem = function removeInventoryItem(itemId, count) {
    var remaining = count;
    for (var index = 0; index < this.inventory.length && remaining > 0; index += 1) {
      var value = this.inventory[index];
      if (!value || value.item !== itemId) continue;
      var removed = Math.min(value.count, remaining);
      value.count -= removed;
      remaining -= removed;
      if (value.count <= 0) this.inventory[index] = null;
    }
    return remaining === 0;
  };

  Base2DUICrafting.prototype.currentFurnaceRecipe = function currentFurnaceRecipe() {
    return this.furnaceInput ? FURNACE_RECIPE_BY_INPUT[this.furnaceInput.item] || null : null;
  };

  Base2DUICrafting.prototype.canFurnaceOutputAccept = function canFurnaceOutputAccept(definition) {
    if (!definition) return false;
    if (!this.furnaceOutput) return true;
    if (this.furnaceOutput.item !== definition.output) return false;
    return this.furnaceOutput.count + definition.outputCount
      <= (ITEMS[definition.output].maxStack || MAX_STACK);
  };

  Base2DUICrafting.prototype.furnaceCanSmelt = function furnaceCanSmelt() {
    var definition = this.currentFurnaceRecipe();
    return !!(definition && this.furnaceInput.count > 0 && this.canFurnaceOutputAccept(definition));
  };

  Base2DUICrafting.prototype.consumeFurnaceFuel = function consumeFurnaceFuel() {
    if (!this.furnaceFuel || this.furnaceFuel.item !== "coal" || this.furnaceFuel.count <= 0) return false;
    this.furnaceFuel.count -= 1;
    if (this.furnaceFuel.count <= 0) this.furnaceFuel = null;
    this.furnaceBurnRemainingMs = FURNACE_FUEL_MS;
    this.furnaceBurnTotalMs = FURNACE_FUEL_MS;
    this.furnaceFuelConsumed += 1;
    this.addEvent("furnace_fuel_ignited", { fuel: "coal", burn_ms: FURNACE_FUEL_MS });
    return true;
  };

  Base2DUICrafting.prototype.finishFurnaceItem = function finishFurnaceItem(definition) {
    this.furnaceInput.count -= 1;
    if (this.furnaceInput.count <= 0) this.furnaceInput = null;
    if (this.furnaceOutput) this.furnaceOutput.count += definition.outputCount;
    else this.furnaceOutput = makeStack(definition.output, definition.outputCount);
    this.furnaceProgressMs = 0;
    this.smeltedItems += definition.outputCount;
    this.lastAction = "smelt_complete_" + definition.output;
    this.addEvent("item_smelted", {
      item: definition.output,
      recipe_id: definition.id,
      smelted_items: this.smeltedItems,
    });
  };

  Base2DUICrafting.prototype.updateFurnace = function updateFurnace(deltaMs) {
    if (this.interfaceMode !== "furnace") return;
    var duration = Math.max(0, Number(deltaMs) || 0);
    var definition = this.currentFurnaceRecipe();
    var canSmelt = this.furnaceCanSmelt();

    if (canSmelt && this.furnaceBurnRemainingMs <= 0) this.consumeFurnaceFuel();
    var poweredMs = Math.min(duration, this.furnaceBurnRemainingMs);
    if (this.furnaceBurnRemainingMs > 0) {
      this.furnaceBurnRemainingMs = Math.max(0, this.furnaceBurnRemainingMs - duration);
    }
    if (!canSmelt || poweredMs <= 0) {
      if (!definition) this.furnaceProgressMs = 0;
      return;
    }

    this.furnaceProgressMs += poweredMs;
    if (this.furnaceProgressMs + 0.001 >= definition.smeltMs) this.finishFurnaceItem(definition);
  };

  Base2DUICrafting.prototype.returnFurnaceInputToInventory = function returnFurnaceInputToInventory() {
    if (!this.furnaceInput) return true;
    var remainder = this.addStackToInventory(this.furnaceInput);
    if (remainder) return false;
    this.furnaceInput = null;
    this.furnaceProgressMs = 0;
    return true;
  };

  Base2DUICrafting.prototype.canAutofill = function canAutofill(definition) {
    if (!definition) return false;
    if (definition.mode === "furnace") {
      return this.interfaceMode === "furnace" && this.inventoryItemCount(definition.input, true) >= 1;
    }
    if (this.interfaceMode === "furnace" || !recipeFitsGrid(definition, this.gridSize)) return false;
    var required = ingredientCounts(definition);
    return Object.keys(required).every(function enough(itemId) {
      return this.inventoryItemCount(itemId, true) >= required[itemId];
    }, this);
  };

  Base2DUICrafting.prototype.correctMaterialPlacementCount = function correctMaterialPlacementCount() {
    if (this.interfaceMode === "equipment") return 0;
    if (this.interfaceMode === "furnace") {
      var count = this.furnaceInput && this.furnaceInput.item === this.currentRecipe.input ? 1 : 0;
      if (this.currentRecipe.fuel && this.furnaceFuel && this.furnaceFuel.item === this.currentRecipe.fuel) count += 1;
      return count;
    }
    return correctPatternPlacementCount(this.craftGrid, this.gridSize, this.currentRecipe);
  };

  Base2DUICrafting.prototype.rewardNewCorrectMaterialPlacements = function rewardNewCorrectMaterialPlacements() {
    var correctCount = this.correctMaterialPlacementCount();
    var newlyCorrect = correctCount - this.roundCorrectPlacementsRewarded;
    if (newlyCorrect <= 0 || this.roundRequiredMaterialCount <= 0) return 0;
    this.roundCorrectPlacementsRewarded = correctCount;
    this.correctMaterialPlacements += newlyCorrect;
    var reward = this.interfaceMode === "furnace"
      ? rewardConfig.constants.furnaceMaterialReward * newlyCorrect
      : rewardConfig.constants.correctMaterialsReward * newlyCorrect / this.roundRequiredMaterialCount;
    this.correctMaterialReward += reward;
    Core.reward.add(this, reward);
    this.addEvent("correct_material_placed", {
      count: newlyCorrect,
      correct_count: correctCount,
      required_count: this.roundRequiredMaterialCount,
      reward: reward,
    });
    return reward;
  };

  Base2DUICrafting.prototype.autofillRecipe = function autofillRecipe(definition) {
    if (!this.canAutofill(definition)) {
      this.recordInvalid("recipe_unavailable");
      return false;
    }
    if (definition.mode === "furnace") {
      if (!this.returnFurnaceInputToInventory()) {
        this.recordInvalid("inventory_full");
        return false;
      }
      this.removeInventoryItem(definition.input, 1);
      this.furnaceInput = makeStack(definition.input, 1);
      this.furnaceProgressMs = 0;
      this.recipeAutofills += 1;
      this.transfers += 1;
      this.lastAction = "autofill_" + definition.id;
      this.addEvent("recipe_autofilled", { recipe_id: definition.id });
      this.rewardNewCorrectMaterialPlacements();
      return true;
    }
    if (!this.returnGridToInventory()) {
      this.recordInvalid("inventory_full");
      return false;
    }
    var dimensions = patternDimensions(definition);
    var offsetRow = Math.floor((this.gridSize - dimensions.rows) / 2);
    var offsetColumn = Math.floor((this.gridSize - dimensions.columns) / 2);
    for (var row = 0; row < dimensions.rows; row += 1) {
      for (var column = 0; column < dimensions.columns; column += 1) {
        var itemId = definition.pattern[row][column];
        if (!itemId) continue;
        this.removeInventoryItem(itemId, 1);
        this.craftGrid[(row + offsetRow) * this.gridSize + column + offsetColumn] = makeStack(itemId, 1);
      }
    }
    this.recipeAutofills += 1;
    this.transfers += Object.keys(ingredientCounts(definition)).length;
    this.lastAction = "autofill_" + definition.id;
    this.addEvent("recipe_autofilled", { recipe_id: definition.id });
    this.rewardNewCorrectMaterialPlacements();
    return true;
  };

  Base2DUICrafting.prototype.matchingRecipe = function matchingRecipe() {
    if (this.interfaceMode === "furnace") return null;
    for (var index = 0; index < RECIPES.length; index += 1) {
      if (matchRecipePattern(this.craftGrid, this.gridSize, RECIPES[index])) return RECIPES[index];
    }
    return null;
  };

  Base2DUICrafting.prototype.outputStack = function outputStack() {
    if (this.interfaceMode === "equipment") return null;
    if (this.interfaceMode === "furnace") return cloneStack(this.furnaceOutput);
    var definition = this.matchingRecipe();
    return definition ? makeStack(definition.output, definition.outputCount) : null;
  };

  Base2DUICrafting.prototype.consumeCraftGrid = function consumeCraftGrid() {
    for (var index = 0; index < this.craftGrid.length; index += 1) {
      if (!this.craftGrid[index]) continue;
      this.craftGrid[index].count -= 1;
      if (this.craftGrid[index].count <= 0) this.craftGrid[index] = null;
    }
  };

  Base2DUICrafting.prototype.canCursorAccept = function canCursorAccept(value) {
    if (!this.cursorStack) return true;
    if (!value || this.cursorStack.item !== value.item) return false;
    return this.cursorStack.count + value.count <= (ITEMS[value.item].maxStack || MAX_STACK);
  };

  Base2DUICrafting.prototype.recordInvalid = function recordInvalid(reason) {
    this.invalidActions += 1;
    this.lastAction = "invalid_" + reason;
    Core.reward.add(this, -rewardConfig.constants.invalidActionPenalty);
    this.addEvent("invalid_action", { reason: reason });
  };

  Base2DUICrafting.prototype.takeFurnaceOutput = function takeFurnaceOutput() {
    var output = cloneStack(this.furnaceOutput);
    if (!output) {
      this.recordInvalid("output_unavailable");
      return false;
    }
    if (!this.canCursorAccept(output)) {
      this.recordInvalid("cursor_full");
      return false;
    }
    var definition = FURNACE_RECIPE_BY_OUTPUT[output.item];
    this.furnaceOutput = null;
    if (this.cursorStack) this.cursorStack.count += output.count;
    else this.cursorStack = output;
    this.craftedItems += output.count;
    this.transfers += 1;
    this.lastAction = "take_smelted_" + output.item;
    this.addEvent("smelted_item_taken", { item: output.item, count: output.count });

    if (output.item === this.currentRecipe.output) {
      this.targetCrafts += 1;
      Core.reward.add(this, rewardConfig.constants.targetCraftReward);
      this.feedback = {
        item: output.item,
        label: ITEMS[output.item].label,
        verb: "SMELTED",
        reward: rewardConfig.constants.targetCraftReward,
      };
      this.feedbackUntilMs = this.gameTimeMs + 650;
      this.addEvent("target_smelted", {
        item: output.item,
        target_crafts: this.targetCrafts,
      });
      this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, this.getPrimaryScore());
      this.startRound();
    } else {
      this.wrongCrafts += 1;
      Core.reward.add(this, -rewardConfig.constants.wrongCraftPenalty);
      this.addEvent("wrong_item_smelted", {
        item: output.item,
        recipe_id: definition ? definition.id : null,
        requested_item: this.currentRecipe.output,
      });
    }
    return true;
  };

  Base2DUICrafting.prototype.takeOutput = function takeOutput() {
    if (this.interfaceMode === "furnace") return this.takeFurnaceOutput();
    var definition = this.matchingRecipe();
    var output = definition ? makeStack(definition.output, definition.outputCount) : null;
    if (!output) {
      this.recordInvalid("output_unavailable");
      return false;
    }
    if (!this.canCursorAccept(output)) {
      this.recordInvalid("cursor_full");
      return false;
    }
    this.consumeCraftGrid();
    if (this.cursorStack) this.cursorStack.count += output.count;
    else this.cursorStack = output;
    this.craftedItems += 1;
    this.transfers += 1;
    this.lastAction = "craft_" + definition.id;
    this.addEvent("item_crafted", { item: definition.output, recipe_id: definition.id });

    if (definition.output === this.currentRecipe.output) {
      this.targetCrafts += 1;
      Core.reward.add(this, rewardConfig.constants.targetCraftReward);
      this.feedback = {
        item: definition.output,
        label: ITEMS[definition.output].label,
        verb: "CRAFTED",
        reward: rewardConfig.constants.targetCraftReward,
      };
      this.feedbackUntilMs = this.gameTimeMs + 650;
      this.addEvent("target_crafted", {
        item: definition.output,
        target_crafts: this.targetCrafts,
      });
      this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, this.getPrimaryScore());
      this.startRound();
    } else {
      this.wrongCrafts += 1;
      Core.reward.add(this, -rewardConfig.constants.wrongCraftPenalty);
      this.addEvent("wrong_item_crafted", {
        item: definition.output,
        requested_item: this.currentRecipe.output,
      });
    }
    return true;
  };

  Base2DUICrafting.prototype.pickWholeStack = function pickWholeStack(region) {
    var value = this.stackAt(region);
    if (!value) {
      this.recordInvalid("empty_slot");
      return false;
    }
    this.cursorStack = value;
    this.setStackAt(region, null);
    this.transfers += 1;
    this.lastAction = "pick_" + value.item;
    this.rewardCorrectEquipmentSelection(region, value);
    return true;
  };

  Base2DUICrafting.prototype.isStorageRegion = function isStorageRegion(region) {
    return !!region && ["inventory", "craft", "furnace_input", "furnace_fuel", "equipment"].indexOf(region.kind) >= 0;
  };

  Base2DUICrafting.prototype.canPlaceItemAt = function canPlaceItemAt(region, itemId) {
    if (!this.isStorageRegion(region)) return false;
    if (region.kind === "furnace_input") return !!FURNACE_RECIPE_BY_INPUT[itemId];
    if (region.kind === "furnace_fuel") return itemId === "coal";
    if (region.kind === "equipment") return ITEMS[itemId].equipmentSlot === region.slotId;
    return true;
  };

  Base2DUICrafting.prototype.rewardCorrectEquipmentSelection = function rewardCorrectEquipmentSelection(region, value) {
    if (this.interfaceMode !== "equipment" || region.kind !== "inventory" || !value) return false;
    if (value.item !== this.currentRecipe.output || this.roundEquipmentSelectionRewarded) return false;
    this.roundEquipmentSelectionRewarded = true;
    this.correctEquipmentSelections += 1;
    Core.reward.add(this, rewardConfig.constants.equipmentSelectionReward);
    this.addEvent("correct_equipment_selected", {
      item: value.item,
      slot: this.currentRecipe.equipmentSlot,
      reward: rewardConfig.constants.equipmentSelectionReward,
    });
    return true;
  };

  Base2DUICrafting.prototype.completeEquipmentPlacement = function completeEquipmentPlacement(region) {
    if (this.interfaceMode !== "equipment" || region.kind !== "equipment") return false;
    var equipped = this.equipment[region.slotId];
    if (!equipped || equipped.item !== this.currentRecipe.output || region.slotId !== this.currentRecipe.equipmentSlot) {
      return false;
    }
    this.equipmentEquipped += 1;
    Core.reward.add(this, rewardConfig.constants.equipmentEquipReward);
    this.feedback = {
      item: equipped.item,
      label: ITEMS[equipped.item].label,
      verb: "EQUIPPED",
      reward: rewardConfig.constants.equipmentEquipReward,
    };
    this.feedbackUntilMs = this.gameTimeMs + 650;
    this.addEvent("target_equipped", {
      item: equipped.item,
      slot: region.slotId,
      equipment_equipped: this.equipmentEquipped,
    });
    this.bestMetrics.bestPrimaryScore = Math.max(this.bestMetrics.bestPrimaryScore, this.getPrimaryScore());
    this.startRound();
    return true;
  };

  Base2DUICrafting.prototype.placeWholeStack = function placeWholeStack(region) {
    if (!this.canPlaceItemAt(region, this.cursorStack.item)) {
      this.recordInvalid("slot_rejects_item");
      return false;
    }
    var destination = this.stackAt(region);
    if (!destination) {
      this.setStackAt(region, this.cursorStack);
      this.cursorStack = null;
    } else if (destination.item === this.cursorStack.item) {
      var maxStack = ITEMS[destination.item].maxStack || MAX_STACK;
      var moved = Math.min(maxStack - destination.count, this.cursorStack.count);
      if (moved <= 0) {
        this.recordInvalid("stack_full");
        return false;
      }
      destination.count += moved;
      this.cursorStack.count -= moved;
      if (this.cursorStack.count <= 0) this.cursorStack = null;
    } else {
      this.setStackAt(region, this.cursorStack);
      this.cursorStack = destination;
    }
    this.transfers += 1;
    if (["craft", "furnace_input", "furnace_fuel", "equipment"].indexOf(region.kind) >= 0) {
      this.manualPlacements += 1;
    }
    this.lastAction = "place_" + region.kind;
    this.rewardNewCorrectMaterialPlacements();
    this.completeEquipmentPlacement(region);
    return true;
  };

  Base2DUICrafting.prototype.activateLeft = function activateLeft(region) {
    if (region.kind === "output") return this.takeOutput();
    if (!this.isStorageRegion(region)) return false;
    return this.cursorStack ? this.placeWholeStack(region) : this.pickWholeStack(region);
  };

  Base2DUICrafting.prototype.activateRight = function activateRight(region) {
    if (region.kind === "output") return this.takeOutput();
    if (!this.isStorageRegion(region)) return false;
    var destination = this.stackAt(region);
    if (!this.cursorStack) {
      if (!destination) {
        this.recordInvalid("empty_slot");
        return false;
      }
      var taken = Math.ceil(destination.count / 2);
      this.cursorStack = makeStack(destination.item, taken);
      destination.count -= taken;
      if (destination.count <= 0) this.setStackAt(region, null);
      this.transfers += 1;
      this.lastAction = "split_" + this.cursorStack.item;
      this.rewardCorrectEquipmentSelection(region, this.cursorStack);
      return true;
    }
    if (!this.canPlaceItemAt(region, this.cursorStack.item)) {
      this.recordInvalid("slot_rejects_item");
      return false;
    }
    if (!destination) {
      this.setStackAt(region, makeStack(this.cursorStack.item, 1));
    } else if (destination.item === this.cursorStack.item
      && destination.count < (ITEMS[destination.item].maxStack || MAX_STACK)) {
      destination.count += 1;
    } else {
      this.recordInvalid(destination && destination.item !== this.cursorStack.item ? "different_stack" : "stack_full");
      return false;
    }
    this.cursorStack.count -= 1;
    if (this.cursorStack.count <= 0) this.cursorStack = null;
    this.transfers += 1;
    if (["craft", "furnace_input", "furnace_fuel", "equipment"].indexOf(region.kind) >= 0) {
      this.manualPlacements += 1;
    }
    this.lastAction = "place_one_" + region.kind;
    this.rewardNewCorrectMaterialPlacements();
    this.completeEquipmentPlacement(region);
    return true;
  };

  Base2DUICrafting.prototype.activateRegion = function activateRegion(region, button) {
    if (button === "right") this.rightClicks += 1;
    else this.leftClicks += 1;
    if (!region) {
      this.recordInvalid("outside_slot");
      return false;
    }
    if (region.kind === "book_toggle") {
      if (button === "right") {
        this.recordInvalid("book_right_click");
        return false;
      }
      this.recipeBookOpen = !this.recipeBookOpen;
      if (this.recipeBookOpen) {
        this.recipeBookOpens += 1;
        if (!this.roundRecipeBookRewarded) {
          this.roundRecipeBookRewarded = true;
          this.recipeBookRewards += 1;
          Core.reward.add(this, rewardConfig.constants.recipeBookReward);
          this.addEvent("recipe_book_rewarded", {
            round_index: this.roundIndex,
            reward: rewardConfig.constants.recipeBookReward,
          });
        }
      }
      this.lastAction = this.recipeBookOpen ? "open_recipe_book" : "close_recipe_book";
      this.addEvent("recipe_book_toggled", { open: this.recipeBookOpen });
      return true;
    }
    if (region.kind === "book_category") {
      if (button === "right") {
        this.recordInvalid("category_right_click");
        return false;
      }
      this.recipeBookCategory = region.categoryId;
      this.lastAction = "filter_recipe_book_" + region.categoryId;
      this.addEvent("recipe_book_filtered", { category: region.categoryId });
      return true;
    }
    if (region.kind === "book_entry") {
      if (button === "right") {
        this.recordInvalid("recipe_right_click");
        return false;
      }
      return this.autofillRecipe(RECIPE_BY_ID[region.recipeId]);
    }
    return button === "right" ? this.activateRight(region) : this.activateLeft(region);
  };

  Base2DUICrafting.prototype.handlePointerClick = function handlePointerClick(point, button) {
    if (this.mode === "paused") this.startPlaying("mouse_" + (button || "left"));
    if (this.mode !== "playing") return false;
    this.mouse.x = U.math.clamp(point.x, 0, LOGIC_WIDTH);
    this.mouse.y = U.math.clamp(point.y, 0, LOGIC_HEIGHT);
    return this.activateRegion(this.hitRegion(this.mouse), button || "left");
  };

  Base2DUICrafting.prototype.handleDrag = function handleDrag(sourcePoint, destinationPoint, button) {
    if (button === "right") return this.handlePointerClick(destinationPoint, "right");
    if (this.mode === "paused") this.startPlaying("drag");
    if (this.mode !== "playing") return false;
    var source = this.hitRegion(sourcePoint);
    var destination = this.hitRegion(destinationPoint);
    if (this.cursorStack) return this.activateRegion(destination, "left");
    if (!this.isStorageRegion(source)) {
      return this.activateRegion(null, "left");
    }
    this.leftClicks += 1;
    if (!this.pickWholeStack(source)) return false;
    return this.activateRegion(destination, "left");
  };

  Base2DUICrafting.prototype.canvasPoint = function canvasPoint(event) {
    return T2D.viewport.clientToLogic(canvas, event.clientX, event.clientY, LOGIC_WIDTH, LOGIC_HEIGHT);
  };

  Base2DUICrafting.prototype.bindInput = function bindInput() {
    var self = this;
    canvas.addEventListener("mousemove", function onMouseMove(event) {
      var point = self.canvasPoint(event);
      self.mouse.dx += point.x - self.mouse.x;
      self.mouse.dy += point.y - self.mouse.y;
      self.mouse.x = point.x;
      self.mouse.y = point.y;
      if (self.pointerGesture) {
        var dx = point.x - self.pointerGesture.start.x;
        var dy = point.y - self.pointerGesture.start.y;
        if (Math.sqrt(dx * dx + dy * dy) >= DRAG_THRESHOLD) self.pointerGesture.moved = true;
      }
    });

    canvas.addEventListener("mousedown", function onMouseDown(event) {
      if (event.button !== 0 && event.button !== 2) return;
      var point = self.canvasPoint(event);
      var button = event.button === 2 ? "right" : "left";
      self.mouse.x = point.x;
      self.mouse.y = point.y;
      self.mouse[button] = true;
      self.pointerGesture = { start: point, moved: false, button: button };
      event.preventDefault();
    });

    window.addEventListener("mouseup", function onMouseUp(event) {
      if ((event.button !== 0 && event.button !== 2) || !self.pointerGesture) return;
      var gesture = self.pointerGesture;
      var expectedButton = event.button === 2 ? "right" : "left";
      if (gesture.button !== expectedButton) return;
      var point = self.canvasPoint(event);
      self.pointerGesture = null;
      self.mouse[gesture.button] = false;
      self.mouse.x = point.x;
      self.mouse.y = point.y;
      Core.reward.resetStep(self);
      if (gesture.moved) self.handleDrag(gesture.start, point, gesture.button);
      else self.handlePointerClick(point, gesture.button);

      self.render();
      event.preventDefault();
    });

    canvas.addEventListener("contextmenu", function onContextMenu(event) {
      event.preventDefault();
    });
  };

  Base2DUICrafting.prototype.normalizeAction = function normalizeAction(action) {
    var id = Core.actions.readId(action, { lowercase: true });
    var mode = id === "control" ? Core.actions.readMouseMode(action) : "";
    var move = id === "move_pointer" || (id === "control" && mode === "relative");
    var dx = 0;
    var dy = 0;
    if (move) {
      var normalizedDx = id === "control"
        ? Core.actions.readMouseNumber(action, "dx", 0)
        : Core.actions.readNumber(action, "dx", 0);
      var normalizedDy = id === "control"
        ? Core.actions.readMouseNumber(action, "dy", 0)
        : Core.actions.readNumber(action, "dy", 0);
      dx = T2D.input.relativeDeltaToLogic(view, normalizedDx, "x");
      dy = T2D.input.relativeDeltaToLogic(view, normalizedDy, "y");
    }
    var directButton = Core.actions.readButton(action, "");
    var leftClick = (id === "mouse_left" && directButton === "left")
      || (id === "mouse_click" && directButton === "left")
      || (id === "control" && Core.actions.hasMouseButton(action, "left"));
    var rightClick = (id === "mouse_right" && directButton === "right")
      || (id === "mouse_click" && directButton === "right")
      || (id === "control" && Core.actions.hasMouseButton(action, "right"));
    return {
      id: id || "wait",
      dx: dx,
      dy: dy,
      move: move,
      leftClick: leftClick,
      rightClick: rightClick,
      wait: !move && !leftClick && !rightClick,
    };
  };

  Base2DUICrafting.prototype.applyAction = function applyAction(normalized) {
    Core.reward.resetStep(this);
    if (normalized.move) {
      var nextX = this.mouse.x + normalized.dx;
      var nextY = this.mouse.y + normalized.dy;
      var pointer = T2D.input.clampPointToVisibleBounds(view, nextX, nextY, LOGIC_WIDTH, LOGIC_HEIGHT);
      this.mouse.dx += pointer.x - this.mouse.x;
      this.mouse.dy += pointer.y - this.mouse.y;
      this.mouse.x = pointer.x;
      this.mouse.y = pointer.y;
      this.lastAction = "move_pointer";
    }
    if (normalized.leftClick || normalized.rightClick) {
      var button = normalized.rightClick ? "right" : "left";
      this.mouse[button] = true;
      this.handlePointerClick(this.mouse, button);
      this.mouse[button] = false;
    } else if (this.mode === "paused") {
      this.startPlaying(normalized.wait ? "wait" : normalized.id);
    } else if (normalized.wait) {
      this.lastAction = "wait";
    }
  };

  Base2DUICrafting.prototype.advanceSimulation = function advanceSimulation(ms) {
    return this.advanceTime(ms, false);
  };

  Base2DUICrafting.prototype.advanceTime = function advanceTime(ms, render) {
    var duration = Number(ms);
    if (!Number.isFinite(duration) || duration <= 0 || this.paused) {

      if (render !== false) this.render();
      return this.getStatePayload();
    }
    this.ensureSimulationRunner().advance(duration, { render: false });
    this.mouse.dx = 0;
    this.mouse.dy = 0;

    if (render !== false) this.render();
    return this.getStatePayload();
  };

  Base2DUICrafting.prototype.ensureSimulationRunner = function ensureSimulationRunner() {
    if (this.simulationRunner) return this.simulationRunner;
    var self = this;
    this.simulationRunner = Core.createFixedStepRunner({
      game: this,
      stepMs: STEP_MS,
      update: function update() { return self.step(); },
      render: function render() {

        self.render();
      },
      isActive: function isActive() { return self.mode === "playing" && !self.paused; },
    });
    return this.simulationRunner;
  };

  Base2DUICrafting.prototype.startLoop = function startLoop() {
    this.ensureSimulationRunner().start();
  };

  Base2DUICrafting.prototype.pause = function pause() {
    Core.lifecycle.pause(this);

    this.render();
    return this.getPauseState();
  };

  Base2DUICrafting.prototype.resume = function resume() {
    Core.lifecycle.resume(this);

    this.render();
    return this.getPauseState();
  };

  Base2DUICrafting.prototype.getPauseState = function getPauseState() {
    return { ok: true, source: "game", paused: this.paused, runtime_paused: this.paused };
  };

  Base2DUICrafting.prototype.getPrimaryScore = function getPrimaryScore() {
    return rewardConfig.computePrimaryScore(this);
  };

  Base2DUICrafting.prototype.completedTargets = function completedTargets() {
    return this.targetCrafts + this.equipmentEquipped;
  };

  Base2DUICrafting.prototype.recipePayload = function recipePayload() {
    var output = this.outputStack();
    return {
      id: this.currentRecipe.id,
      output: this.currentRecipe.output,
      output_label: ITEMS[this.currentRecipe.output].label,
      output_count: this.currentRecipe.outputCount,
      interface_mode: this.interfaceMode,
      grid_size: this.interfaceMode === "furnace" || this.interfaceMode === "equipment" ? null : this.gridSize,
      pattern: this.interfaceMode === "furnace" || this.interfaceMode === "equipment"
        ? null
        : this.currentRecipe.pattern.map(function cloneRow(row) { return row.slice(); }),
      input: this.currentRecipe.input || null,
      fuel: this.currentRecipe.fuel || null,
      equipment_slot: this.currentRecipe.equipmentSlot || null,
      smelt_ms: this.currentRecipe.smeltMs || null,
      output_ready: !!(output && output.item === this.currentRecipe.output),
      recipe_book_open: this.recipeBookOpen,
      recipe_book_category: this.recipeBookCategory,
    };
  };

  Base2DUICrafting.prototype.furnacePayload = function furnacePayload() {
    if (this.interfaceMode !== "furnace") return null;
    var definition = this.currentFurnaceRecipe() || this.currentRecipe;
    var smeltMs = definition && definition.smeltMs || FURNACE_SMELT_MS;
    return {
      input: stackPayload(this.furnaceInput),
      fuel: stackPayload(this.furnaceFuel),
      output: stackPayload(this.furnaceOutput),
      burning: this.furnaceBurnRemainingMs > 0,
      active: this.furnaceBurnRemainingMs > 0 && this.furnaceCanSmelt(),
      progress_ms: finiteRounded(this.furnaceProgressMs),
      progress: finiteRounded(U.math.clamp(this.furnaceProgressMs / smeltMs, 0, 1)),
      smelt_ms: smeltMs,
      burn_remaining_ms: finiteRounded(this.furnaceBurnRemainingMs),
      burn_total_ms: finiteRounded(this.furnaceBurnTotalMs),
    };
  };

  Base2DUICrafting.prototype.equipmentPayload = function equipmentPayload() {
    var payload = {};
    EQUIPMENT_SLOT_ORDER.forEach(function copyEquipmentSlot(slot) {
      payload[slot] = stackPayload(this.equipment[slot]);
    }, this);
    return payload;
  };

  Base2DUICrafting.prototype.bookPayload = function bookPayload() {
    return this.bookEntries.map(function toBookEntry(definition) {
      return {
        recipe_id: definition.id,
        output: definition.output,
        output_label: ITEMS[definition.output].label,
        available: this.canAutofill(definition),
        visible: this.recipeMatchesBookCategory(definition),
      };
    }, this);
  };

  Base2DUICrafting.prototype.slotPayload = function slotPayload() {
    var self = this;
    return this.regions().map(function toPayload(region) {
      var definition = region.kind === "book_entry" ? RECIPE_BY_ID[region.recipeId] : null;
      return {
        id: region.id,
        type: region.kind,
        index: region.index === undefined ? null : region.index,
        slot_id: region.slotId || null,
        recipe_id: region.recipeId || null,
        x: finiteRounded(region.x),
        y: finiteRounded(region.y),
        width: finiteRounded(region.w),
        height: finiteRounded(region.h),
        stack: stackPayload(self.stackAt(region)),
        available: definition ? self.canAutofill(definition) : null,
      };
    });
  };

  Base2DUICrafting.prototype.visualPayload = function visualPayload() {
    return T2D.visuals.sync(this);
  };

  Base2DUICrafting.prototype.buildStatePayload = function buildStatePayload() {
    T2D.visuals.sync(this);
    var viewport = T2D.viewport.state(this, LOGIC_WIDTH, LOGIC_HEIGHT);
    return {
      schemaVersion: "2.0",
      gameId: GAME_ID,
      seed: this.seed,
      timestampMs: Date.now(),
      gameTimeMs: U.math.finiteNumber(this.gameTimeMs),
      status: this.terminal.isTerminal ? "terminal" : this.mode,
      paused: this.mode === "paused" || this.paused,
      runtime_paused: this.paused,
      is_actionable: !this.terminal.isTerminal && (this.mode === "paused" || this.mode === "playing"),
      terminal: {
        isTerminal: this.terminal.isTerminal,
        outcome: this.terminal.outcome,
        reason: this.terminal.reason,
      },
      game_state: {
        score: this.getPrimaryScore(),
        level: null,
        player: {
          cursor_x: finiteRounded(this.mouse.x),
          cursor_y: finiteRounded(this.mouse.y),
          mouse_left: this.mouse.left,
          mouse_right: this.mouse.right,
          cursor_stack: stackPayload(this.cursorStack),
        },
        environment: {
          phase: this.terminal.isTerminal ? "terminal" : this.mode,
          viewport_width: viewport.width,
          viewport_height: viewport.height,
          logic_width: LOGIC_WIDTH,
          logic_height: LOGIC_HEIGHT,
          difficulty: this.difficulty,
          scene_version: Workshop.version,
          scene_layout: this.sceneLayout,
          asset_pack: this.assetPack,
          asset: T2D.visuals.assetPayload(this),
          request: this.recipePayload(),
          craft_grid: cloneSlots(this.craftGrid),
          furnace: this.furnacePayload(),
          equipment: this.equipmentPayload(),
          inventory: cloneSlots(this.inventory),
          recipe_book: this.bookPayload(),
          recipe_book_category: this.recipeBookCategory,
          perturb_active: Core.perturbations.isActive(this),
          visual_perturbations: this.visualPayload(),
        },
        entities: this.slotPayload(),
      },
      metrics: {
        env_reward_step: this.envRewardStep,
        env_reward_episode: this.envRewardEpisode,
        primary_positive_score: rewardConfig.computePrimaryPositiveScore(this),
        primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(this),
        primary_score: this.getPrimaryScore(),
        targets_completed: this.completedTargets(),
        target_crafts: this.targetCrafts,
        crafted_items: this.craftedItems,
        wrong_crafts: this.wrongCrafts,
        invalid_actions: this.invalidActions,
        transfers: this.transfers,
        manual_placements: this.manualPlacements,
        recipe_book_opens: this.recipeBookOpens,
        recipe_book_rewards: this.recipeBookRewards,
        correct_material_placements: this.correctMaterialPlacements,
        correct_material_reward: finiteRounded(this.correctMaterialReward),
        recipe_autofills: this.recipeAutofills,
        furnace_rounds: this.furnaceRounds,
        equipment_rounds: this.equipmentRounds,
        correct_equipment_selections: this.correctEquipmentSelections,
        equipment_equipped: this.equipmentEquipped,
        smelted_items: this.smeltedItems,
        furnace_fuel_consumed: this.furnaceFuelConsumed,
        furnace_burning: this.furnaceBurnRemainingMs > 0,
        furnace_progress: this.interfaceMode === "furnace"
          ? finiteRounded(U.math.clamp(this.furnaceProgressMs / (this.currentRecipe.smeltMs || FURNACE_SMELT_MS), 0, 1))
          : 0,
        left_clicks: this.leftClicks,
        right_clicks: this.rightClicks,
        round_index: this.roundIndex,
        current_recipe_id: this.currentRecipe.id,
        requested_item: this.currentRecipe.output,
        interface_mode: this.interfaceMode,
        recipe_book_open: this.recipeBookOpen,
        recipe_book_category: this.recipeBookCategory,
        cursor_item: this.cursorStack ? this.cursorStack.item : null,
        cursor_count: this.cursorStack ? this.cursorStack.count : 0,
        best_primary_score: this.bestMetrics.bestPrimaryScore,
        step_count: this.stepCount,
        episode_count: this.runtime.episodeCount,
        difficulty: this.difficulty,
      },
      debug: {
        mode: this.mode,
        last_action: this.lastAction,
        last_reset_method: this.runtime.lastResetMethod,
        reset_count: this.runtime.resetCount,
        paused: this.paused,
        runtime_paused: this.paused,
        visible_status: this.mode,
      },
    };
  };

  Base2DUICrafting.prototype.getStatePayload = function getStatePayload() {
    var latched = Core.terminal.consume(this);
    if (latched) return latched;
    return this.buildStatePayload();
  };

  Base2DUICrafting.prototype.renderGameToText = function renderGameToText() {
    return JSON.stringify({
      coordinate_system: "origin=(0,0) top-left, +x right, +y down, logic_size="
        + LOGIC_WIDTH + "x" + LOGIC_HEIGHT,
      status: this.mode,
      cursor: { x: finiteRounded(this.mouse.x), y: finiteRounded(this.mouse.y) },
      cursor_stack: stackPayload(this.cursorStack),
      request: this.recipePayload(),
      craft_grid: cloneSlots(this.craftGrid),
      furnace: this.furnacePayload(),
      equipment: this.equipmentPayload(),
      inventory: cloneSlots(this.inventory),
      recipe_book: this.bookPayload(),
      recipe_book_category: this.recipeBookCategory,
      rewards: {
        env_reward_step: this.envRewardStep,
        env_reward_episode: this.envRewardEpisode,
        primary_positive_score: rewardConfig.computePrimaryPositiveScore(this),
        primary_penalty_score: rewardConfig.computePrimaryPenaltyScore(this),
        primary_score: this.getPrimaryScore(),
      },
      progress: {
        targets_completed: this.completedTargets(),
        target_crafts: this.targetCrafts,
        crafted_items: this.craftedItems,
        wrong_crafts: this.wrongCrafts,
        invalid_actions: this.invalidActions,
        recipe_book_rewards: this.recipeBookRewards,
        correct_material_placements: this.correctMaterialPlacements,
        correct_material_reward: finiteRounded(this.correctMaterialReward),
        furnace_rounds: this.furnaceRounds,
        equipment_rounds: this.equipmentRounds,
        correct_equipment_selections: this.correctEquipmentSelections,
        equipment_equipped: this.equipmentEquipped,
        smelted_items: this.smeltedItems,
        furnace_fuel_consumed: this.furnaceFuelConsumed,
        round_index: this.roundIndex,
      },
      difficulty: this.difficulty,
      visual_perturbations: this.visualPayload(),
    });
  };

  Base2DUICrafting.prototype.getObservation = function getObservation() {
    return {
      type: "rgb_screenshot",
      width: DISPLAY_WIDTH,
      height: DISPLAY_HEIGHT,
      text: JSON.parse(this.renderGameToText()),
    };
  };

  Base2DUICrafting.prototype.buildInfo = function buildInfo(state) {
    return {
      score: state.metrics.primary_score,
      time_steps: state.metrics.step_count,
      targets_completed: state.metrics.targets_completed,
      target_crafts: state.metrics.target_crafts,
      crafted_items: state.metrics.crafted_items,
      wrong_crafts: state.metrics.wrong_crafts,
      invalid_actions: state.metrics.invalid_actions,
      recipe_book_rewards: state.metrics.recipe_book_rewards,
      correct_material_placements: state.metrics.correct_material_placements,
      correct_material_reward: state.metrics.correct_material_reward,
      furnace_rounds: state.metrics.furnace_rounds,
      equipment_rounds: state.metrics.equipment_rounds,
      correct_equipment_selections: state.metrics.correct_equipment_selections,
      equipment_equipped: state.metrics.equipment_equipped,
      smelted_items: state.metrics.smelted_items,
      furnace_fuel_consumed: state.metrics.furnace_fuel_consumed,
      task_events: this.taskEvents.slice(),
    };
  };

  Base2DUICrafting.prototype.buildStepInfo = function buildStepInfo(state, stepOptions, normalized) {
    var info = Core.terminal.withInfo(this, state, this.buildInfo(state));
    info.action = { type: "game_step_action", id: normalized.id, args: normalized.args || {} };
    info.durationMs = stepOptions.durationMs;
    info.source = stepOptions.source;
    return info;
  };

  Base2DUICrafting.prototype.resetGym = function resetGym(options) {
    this.beginEpisode(options || {}, true);
    var state = this.getStatePayload();
    return { observation: this.getObservation(), reward: 0, done: false, info: this.buildInfo(state) };
  };

  Base2DUICrafting.prototype.domainColor = function domainColor(base, background) {
    var active = this.visualPerturbations && this.visualPerturbations.active;
    var stream = background ? "background" : "palette";
    var appearance = this.domainState && this.domainState.applied
      ? this.domainState.applied.appearance || {}
      : {};
    if (Core.domains.isActive(this, "appearance")) {
      return Core.perturbations.transformColor(base, appearance[stream]);
    }
    if (active && (background ? active.bgColor : active.entityColor)) {
      return Core.perturbations.transformColor(base, LEGACY_COLOR_PERTURBATION[stream]);
    }
    return base;
  };

  Base2DUICrafting.prototype.palette = function palette() {
    var self = this;
    var result = {};
    var theme = this.assetContext.pack.variations.themes.find(function selected(candidate) {
      return candidate.id === self.assetContext.theme;
    });
    var themePalette = theme ? theme.palette : {};
    Object.keys(BASE_COLORS).forEach(function copyColor(key) {
      var base = themePalette[key] === undefined ? BASE_COLORS[key] : themePalette[key];
      result[key] = self.domainColor(base, key.indexOf("world") === 0);
    });
    return result;
  };

  Base2DUICrafting.prototype.tooltipForRegion = function tooltipForRegion(region) {
    if (!region) return null;
    if (region.kind === "book_toggle") return "Recipe Book";
    if (region.kind === "book_category") return region.label;
    if (region.kind === "book_entry") {
      var definition = RECIPE_BY_ID[region.recipeId];
      return ITEMS[definition.output].label;
    }
    var value = this.stackAt(region);
    if (!value) return null;
    return ITEMS[value.item].label + (value.count > 1 ? " x" + value.count : "");
  };

  Base2DUICrafting.prototype.render = function render() {
    T2D.visuals.sync(this);
    presentation.render(this);
    if (this.infoPanel) this.infoPanel.update();
  };

  Base2DUICrafting.prototype.resetFromAPI = function resetFromAPI(options) {
    return this.beginEpisode(options || {}, true);
  };

  async function start() {
    await T2D.assets.preload(Workshop.pack, ASSET_REQUIREMENTS);
    view = await T2D.createStage(canvas, {
      width: LOGIC_WIDTH,
      height: LOGIC_HEIGHT,
      background: 0x202a30,
    });
    if (!view) throw new Error("Three.js 2D engine unavailable");
    presentation = Workshop.create(view, UI, ITEMS, LOGIC_WIDTH, LOGIC_HEIGHT);
    var game = new Base2DUICrafting();
    Core.createRuntime({
      game: game,
      presentation: {
        title: "2D Crafting",
        controls: "Left-click picks up or places stacks and takes output; right-click splits or places one item. The Recipe Book can autofill ingredients.",
        read: function readPresentation() {
          var request = game.recipePayload(), furnace = game.furnacePayload();
          var interfaceName = game.interfaceMode === "workbench" ? "Workbench 3×3"
            : (game.interfaceMode === "inventory" ? "Inventory 2×2"
              : (game.interfaceMode === "equipment" ? "Equipment" : "Furnace"));
          var details = [["Request", request.output_label], ["Interface", interfaceName],
            ["Completed", game.completedTargets()], ["Produced", game.craftedItems],
            ["Wrong crafts", game.wrongCrafts], ["Invalid actions", game.invalidActions],
            ["Recipe book", game.recipeBookOpen ? "Open" : "Closed"]];
          if (furnace) {
            var furnaceStatus = furnace.output ? "Output ready" : (furnace.active
              ? "Smelting " + Math.round(furnace.progress * 100) + "%"
              : (furnace.input && !furnace.fuel && furnace.burn_remaining_ms <= 0 ? "Needs fuel" : "Idle"));
            details.splice(2, 0, ["Furnace", furnaceStatus]);
          } else if (game.interfaceMode === "equipment") {
            details.splice(2, 0, ["Equipment slot", request.equipment_slot]);
          } else {
            details.splice(2, 0, ["Output", request.output_ready ? "Ready" : "Not ready"]);
          }
          return {
            status: game.paused ? "paused" : game.mode,
            primaryScore: game.getPrimaryScore(),
            stepReward: game.envRewardStep,
            episodeReward: game.envRewardEpisode,
            difficulty: game.difficulty,
            seed: game.seed,
            perturbation: Core.perturbations.label(game),
            details: details,
          };
        },
      },
      renderer: T2D,
      gameId: GAME_ID,
      defaultSeed: DEFAULT_SEED,
      maxDifficulty: MAX_DIFFICULTY,
      defaultStepMs: 200,
      assets: { engine: T2D.assets, requiredAssetIds: ASSET_REQUIREMENTS },
    });
  }

  Core.lifecycle.boot(start);
})();
