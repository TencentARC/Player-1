(function () {
  "use strict";

  var U = window.BaseGameletCommon;
  var constants = Object.freeze({
    recipeBookReward: 1,
    correctMaterialsReward: 2,
    furnaceMaterialReward: 1,
    targetCraftReward: 3,
    equipmentSelectionReward: 1,
    equipmentEquipReward: 2,
    invalidActionPenalty: 0,
    wrongCraftPenalty: 0,
  });

  function computePrimaryPositiveScore(metrics) {
    var recipeBookRewards = U.metrics.readNumber(metrics, ["recipeBookRewards", "recipe_book_rewards"], 0);
    var correctMaterialReward = U.metrics.readNumber(metrics, ["correctMaterialReward", "correct_material_reward"], 0);
    var targetCrafts = U.metrics.readNumber(metrics, ["targetCrafts", "target_crafts"], 0);
    var correctEquipmentSelections = U.metrics.readNumber(
      metrics,
      ["correctEquipmentSelections", "correct_equipment_selections"],
      0
    );
    var equipmentEquipped = U.metrics.readNumber(metrics, ["equipmentEquipped", "equipment_equipped"], 0);
    return recipeBookRewards * constants.recipeBookReward
      + correctMaterialReward
      + targetCrafts * constants.targetCraftReward
      + correctEquipmentSelections * constants.equipmentSelectionReward
      + equipmentEquipped * constants.equipmentEquipReward;
  }

  function computePrimaryPenaltyScore(metrics) {
    var invalidActions = U.metrics.readNumber(metrics, ["invalidActions", "invalid_actions"], 0);
    var wrongCrafts = U.metrics.readNumber(metrics, ["wrongCrafts", "wrong_crafts"], 0);
    return invalidActions * constants.invalidActionPenalty
      + wrongCrafts * constants.wrongCraftPenalty;
  }

  window.Base2DUICraftingRewardConfig = Object.freeze({
    version: 5,
    gameId: "base_2d_ui_crafting",
    constants: constants,
    computePrimaryPositiveScore: computePrimaryPositiveScore,
    computePrimaryPenaltyScore: computePrimaryPenaltyScore,
    computePrimaryScore: function computePrimaryScore(metrics) {
      return computePrimaryPositiveScore(metrics) - computePrimaryPenaltyScore(metrics);
    },
  });
})();
