(function fieldcraftWorkshopScene() {
  "use strict";
  var ITEM_IDS = Object.freeze([
    "oak_log", "oak_planks", "stick", "coal", "cobblestone", "iron_ingot", "gold_ingot", "leather", "string",
    "wheat", "redstone", "feather", "iron_ore", "cactus", "potato", "nether_gold_ore", "clay_ball", "beef",
    "birch_wood", "stone", "green_dye", "baked_potato", "brick", "cooked_beef", "charcoal", "smooth_stone",
    "wooden_pickaxe", "stone_pickaxe", "iron_pickaxe", "wooden_sword", "stone_sword", "iron_sword",
    "wooden_axe", "stone_axe", "iron_axe", "wooden_shovel", "stone_shovel", "torch", "crafting_table",
    "furnace", "chest", "shield", "wooden_helmet", "wooden_chestplate", "wooden_leggings", "wooden_boots",
    "iron_helmet", "iron_chestplate", "iron_leggings", "iron_boots", "bread", "bucket",
  ]);
  var ASSETS = ITEM_IDS.map(function assetForItem(id) { return "item_" + id; });
  ASSETS.push("recipe_book", "workshop_cursor", "workshop_avatar", "slot", "slot_active", "slot_paper");
  ["panel", "paper", "metal"].forEach(function frameFamily(family) {
    for (var row = 0; row < 3; row += 1) {
      for (var col = 0; col < 3; col += 1) ASSETS.push("frame_" + family + "_" + row + "_" + col);
    }
  });
  var COLORS = Object.freeze({
    worldWall: 0x1d2d34, worldWallDark: 0x14262e, text: 0x263d45, textLight: 0xf9f0dc,
    muted: 0x91a6a9, green: 0x8cd4ad, greenDark: 0x315f50, amber: 0xeaca87,
    red: 0xdd8c7c, workbench: 0x35515a, slot: 0x213942, slotHint: 0x8dabb3, tooltip: 0x14242c, tooltipBorder: 0x9bb4b4,
  });
  var EQUIPMENT_ICONS = Object.freeze({
    head: "iron_helmet", chest: "iron_chestplate", legs: "iron_leggings", feet: "iron_boots", offhand: "shield",
  });
  var EQUIPMENT_LABELS = Object.freeze({ head: "Head", chest: "Chest", legs: "Legs", feet: "Feet", offhand: "Offhand" });

  function create(view, ui, items, width, height) {
    function image(game, id, x, y, w, h, options) {
      return BaseGameletThree2D.assets.create(id, Object.assign({
        view: view, assetContext: game.assetContext, x: x, y: y, w: w, h: h, anchor: [0, 0],
      }, options || {}));
    }
    function rect(x, y, w, h, color, alpha) {
      return view.fillRect(x, y, w, h, { color: color, alpha: alpha === undefined ? 1 : alpha });
    }
    function text(label, x, y, size, color, options) {
      return view.text(String(label), x, y, Object.assign({
        font: "bold " + size + "px sans-serif", fontFamily: "sans-serif", fill: color, baseline: "top",
      }, options || {}));
    }
    function frame(game, family, bounds, edge) {
      var border = edge || 10;
      var widths = [border, bounds.w - 2 * border, border];
      var heights = [border, bounds.h - 2 * border, border];
      var y = bounds.y;
      for (var row = 0; row < 3; row += 1) {
        var x = bounds.x;
        for (var col = 0; col < 3; col += 1) {
          image(game, "frame_" + family + "_" + row + "_" + col, x, y, widths[col], heights[row], {
            tint: game.domainColor(0xffffff, false),
          });
          x += widths[col];
        }
        y += heights[row];
      }
    }
    function item(game, itemId, x, y, size, alpha) {
      if (!Object.prototype.hasOwnProperty.call(items, itemId)) throw new Error("Unknown workshop item: " + itemId);
      return image(game, "item_" + itemId, x, y, size, size, { alpha: alpha === undefined ? 1 : alpha });
    }
    function count(value, x, y, palette) {
      if (value <= 1) return;
      var label = String(value), labelWidth = 12 * label.length + 8;
      rect(x - labelWidth, y - 24, labelWidth, 24, palette.worldWallDark, 0.94);
      text(label, x - 4, y - 24, 21, palette.textLight, { align: "right" });
    }
    function slotFrame(game, region, palette, active, disabled) {
      rect(region.x + 1, region.y + 1, region.w - 2, region.h - 2, active ? palette.green : palette.slotHint);
      image(game, active ? "slot_active" : "slot", region.x + 1, region.y + 1, region.w - 2, region.h - 2, {
        tint: game.domainColor(0xffffff, false), alpha: disabled ? 0.7 : 1,
      });
      // Keep the textured rim three pixels wide as the interactive slots grow.
      rect(region.x + 4, region.y + 4, region.w - 8, region.h - 8, palette.slot);
    }
    function slot(game, region, value, palette, options) {
      var opts = options || {};
      slotFrame(game, region, palette, opts.hovered || opts.ready, opts.disabled);
      if (opts.ready) view.strokeRect(region.x + 2, region.y + 2, region.w - 4, region.h - 4, palette.green, 1.5);
      if (value) {
        var size = Math.min(region.w, region.h) - 8;
        item(game, value.item, region.x + (region.w - size) / 2, region.y + (region.h - size) / 2,
          size, opts.disabled ? 0.42 : 1);
        count(value.count, region.x + region.w - 4, region.y + region.h - 4, palette);
      } else if (opts.placeholder) {
        item(game, opts.placeholder, region.x + 10, region.y + 10, region.w - 20, opts.disabled ? 0.15 : 0.24);
      }
    }
    function hovered(region, current) { return current && current.id === region.id; }
    function button(game, region, palette, active) {
      slotFrame(game, region, palette, active, false);
      image(game, "recipe_book", region.x + 9, region.y + 8, region.w - 18, region.h - 18);
    }
    function arrow(x, y, w, h, palette, ready) {
      var points = [
        { x: x, y: y + h * 0.28 }, { x: x + w * 0.6, y: y + h * 0.28 },
        { x: x + w * 0.6, y: y }, { x: x + w, y: y + h / 2 },
        { x: x + w * 0.6, y: y + h }, { x: x + w * 0.6, y: y + h * 0.72 },
        { x: x, y: y + h * 0.72 },
      ];
      view.fillPolygon(points, ready ? palette.green : palette.muted);
    }
    function objective(game, palette) {
      var bounds = ui.requestBanner;
      rect(bounds.x, bounds.y, bounds.w, bounds.h, palette.worldWallDark);
      rect(bounds.x, bounds.y, 4, bounds.h, palette.amber);
      var imageSize = 66;
      var imageY = bounds.y + (bounds.h - imageSize) / 2;
      item(game, game.currentRecipe.output, bounds.x + 11, imageY, imageSize);
      count(game.currentRecipe.outputCount, bounds.x + 76, imageY + imageSize, palette);
      text(items[game.currentRecipe.output].label, bounds.x + 87, bounds.y + (bounds.h - 24) / 2, 24, palette.textLight);
    }
    function book(game, layout, palette, current) {
      var bounds = layout.book;
      frame(game, "paper", bounds);
      rect(bounds.x + 15, bounds.y + 53, bounds.w - 30, 32, palette.text, 0.09);
      var categories = game.bookCategories();
      var active = categories.find(function category(value) { return value.id === game.recipeBookCategory; });
      text(active.label.toUpperCase(), bounds.x + 25, bounds.y + 62, 15, palette.text);
      categories.forEach(function category(definition, index) {
        var region = game.bookCategoryRegion(index, definition, layout);
        slot(game, region, { item: definition.icon, count: 1 }, palette, {
          hovered: hovered(region, current), ready: game.recipeBookCategory === definition.id,
        });
      });
      var entries = game.visibleBookEntries();
      entries.forEach(function entry(definition, index) {
        var region = game.bookEntryRegion(index, definition, layout);
        var available = game.canAutofill(definition);
        slot(game, region, { item: definition.output, count: definition.outputCount }, palette, {
          hovered: hovered(region, current), ready: available, disabled: !available,
        });
      });
    }
    function avatar(game, layout, palette, current) {
      var bounds = layout.avatar;
      rect(bounds.x, bounds.y, bounds.w, bounds.h, palette.worldWallDark);
      rect(bounds.x + 4, bounds.y + 4, bounds.w - 8, bounds.h - 8, palette.text, 0.5);
      var height = bounds.h - 12, width = height * 2 / 3;
      image(game, "workshop_avatar", bounds.x + (bounds.w - width) / 2, bounds.y + 7, width, height);
      layout.equipmentSlots.concat([layout.offhand]).forEach(function equipment(region) {
        var interactive = game.interfaceMode === "equipment";
        slot(game, region, game.equipment[region.slotId], palette, {
          hovered: interactive && hovered(region, current), disabled: !interactive,
          placeholder: EQUIPMENT_ICONS[region.slotId],
        });
      });
    }
    function furnace(game, layout, palette, current) {
      var source = layout.furnaceInput, fuel = layout.furnaceFuel, progress = layout.furnaceArrow;
      var housing = { x: source.x - 14, y: source.y - 13, w: source.w + 28, h: fuel.y + fuel.h - source.y + 26 };
      frame(game, "metal", housing, 8);
      slot(game, source, game.furnaceInput, palette, { hovered: hovered(source, current) });
      slot(game, fuel, game.furnaceFuel, palette, { hovered: hovered(fuel, current) });
      var flame = layout.furnaceFlame, burning = game.furnaceBurnRemainingMs > 0;
      var center = flame.x + flame.w / 2, bottom = flame.y + flame.h;
      var pulse = burning ? 1 + 0.08 * Math.sin(game.gameTimeMs * 0.025) : 0.76;
      view.fillPolygon([
        { x: center, y: flame.y - 2 }, { x: center + flame.w * 0.16, y: flame.y + flame.h * 0.4 },
        { x: center + flame.w * 0.35, y: flame.y + flame.h * 0.22 }, { x: center + flame.w * 0.5 * pulse, y: bottom - 5 },
        { x: center + flame.w * 0.27, y: bottom }, { x: center - flame.w * 0.25, y: bottom },
        { x: center - flame.w * 0.5, y: bottom - 6 }, { x: center - flame.w * 0.25, y: flame.y + flame.h * 0.32 },
      ], burning ? 0xea914e : palette.worldWallDark);
      if (burning) view.fillPolygon([
        { x: center, y: flame.y + 8 }, { x: center + 7, y: bottom - 5 },
        { x: center + 2, y: bottom - 1 }, { x: center - 7, y: bottom - 5 },
      ], 0xffe9a3);
      var ready = !!game.outputStack();
      var ratio = ready ? 1 : Math.max(0, Math.min(1, game.furnaceProgressMs / game.currentRecipe.smeltMs));
      rect(progress.x - 3, progress.y - 3, progress.w + 6, progress.h + 6, palette.text, 0.2);
      rect(progress.x, progress.y, progress.w, progress.h, palette.worldWallDark);
      if (ratio > 0) rect(progress.x, progress.y, progress.w * ratio, progress.h, palette.amber);
    }
    function main(game, layout, palette, current) {
      rect(layout.panel.x + 8, layout.panel.y + 9, layout.panel.w, layout.panel.h, palette.worldWallDark, 0.72);
      frame(game, "panel", layout.panel);
      rect(layout.panel.x + 10, layout.panel.y + 10, layout.panel.w - 20, layout.panel.h - 20, palette.workbench);
      if (game.recipeBookOpen) book(game, layout, palette, current);
      var craftMode = game.interfaceMode === "inventory" || game.interfaceMode === "workbench";
      if (game.interfaceMode !== "equipment") button(game, layout.bookToggle, palette,
        game.recipeBookOpen || hovered(layout.bookToggle, current));
      var output = game.outputStack();
      if (game.interfaceMode === "furnace") {
        furnace(game, layout, palette, current);
      } else if (game.interfaceMode === "equipment") {
        avatar(game, layout, palette, current);
        item(game, game.currentRecipe.output, layout.craftX + 38, layout.craftLabelY + 105, 94);
      } else if (craftMode) {
        if (layout.avatar) avatar(game, layout, palette, current);
        game.regions().filter(function craftRegion(region) { return region.kind === "craft"; }).forEach(function craft(region) {
          slot(game, region, game.stackAt(region), palette, { hovered: hovered(region, current) });
        });
        var craftRight = layout.craftX + game.gridSize * ui.craftSlot;
        var gap = layout.output.x - craftRight;
        arrow(craftRight + (gap - ui.craftArrowWidth) / 2, layout.arrowY, ui.craftArrowWidth, 29, palette, !!output);
      }
      if (game.interfaceMode !== "equipment") {
        slot(game, layout.output, output, palette, { hovered: hovered(layout.output, current), ready: !!output });
      }
      game.regions().filter(function inventoryRegion(region) { return region.kind === "inventory"; }).forEach(function inventory(region) {
        slot(game, region, game.stackAt(region), palette, { hovered: hovered(region, current) });
      });
      rect(layout.inventoryX, layout.hotbarY - 9, ui.inventorySlot * 9, 2, palette.muted, 0.45);
    }
    function tooltip(game, current, palette) {
      var value = game.tooltipForRegion(current);
      if (!value && current && current.kind === "equipment") value = EQUIPMENT_LABELS[current.slotId] + " slot";
      if (!value) return;
      var lines = value.split("  (");
      if (lines.length > 1) lines[1] = "(" + lines[1];
      var longest = Math.max.apply(null, lines.map(function length(line) { return line.length; }));
      var boxWidth = Math.max(140, Math.min(480, longest * 12 + 24));
      var boxHeight = 34 + (lines.length - 1) * 25;
      var x = Math.max(8, Math.min(width - boxWidth - 8, game.mouse.x + 27));
      var y = Math.max(8, Math.min(height - boxHeight - 8, game.mouse.y + 34));
      rect(x, y, boxWidth, boxHeight, palette.tooltip);
      view.strokeRect(x, y, boxWidth, boxHeight, palette.tooltipBorder, 2);
      lines.forEach(function line(label, index) { text(label, x + 12, y + 6 + index * 25, 20, palette.textLight); });
    }
    return {
      render: function render(game) {
        var palette = game.palette();
        view.clear(palette.worldWall);
        objective(game, palette);
        var current = game.hitRegion(game.mouse);
        main(game, game.layout(), palette, current);
        tooltip(game, current, palette);
        if (game.cursorStack) {
          var heldX = Math.max(6, Math.min(width - 66, game.mouse.x - 30));
          var heldY = Math.max(6, game.mouse.y - 72);
          rect(heldX - 2, heldY - 2, 66, 66, palette.worldWallDark, 0.9);
          item(game, game.cursorStack.item, heldX, heldY, 62);
          count(game.cursorStack.count, heldX + 60, heldY + 60, palette);
        }
        image(game, "workshop_cursor", game.mouse.x, game.mouse.y, 25, 32);
        view.render();
      },
    };
  }
  window.WorkshopScene = Object.freeze({ create: create, assets: Object.freeze(ASSETS), itemIds: ITEM_IDS,
    colors: COLORS, pack: "gym-workshop", version: "fieldcraft-workshop-1" });
})();
