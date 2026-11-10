"""Train Player-1 with the bundled synchronous verl trainer."""

import os
import sys
from pathlib import Path

from hydra import compose, initialize_config_module
from omegaconf import OmegaConf

from player1.training.sft.checkpoint_export import DEFAULT_OUTPUT, export_checkpoint

ROOT = Path(__file__).resolve().parents[2]
MODEL = os.environ.get("PLAYER1_MODEL_PATH", "Qwen/Qwen3.5-9B")
ALGORITHM = os.environ.get("PLAYER1_ALGORITHM", "ppo")
OUTPUT = Path(os.environ.get("PLAYER1_OUTPUT", "outputs/training/run")).resolve()
BATCH_SIZE = int(os.environ.get("PLAYER1_BATCH_SIZE", "16"))
MAX_ENV_STEPS = int(os.environ.get("PLAYER1_MAX_ENV_STEPS", "8"))
TRAIN_STEPS = int(os.environ.get("PLAYER1_TRAIN_STEPS", "100"))


def make_config(overrides=(), *, default_model=MODEL):
    if ALGORITHM not in {"ppo", "grpo", "gspo"}:
        raise ValueError("PLAYER1_ALGORITHM must be ppo, grpo or gspo")
    ppo = ALGORITHM == "ppo"
    model_path = default_model if default_model is not None else "null"
    settings = [
        "data.val_files=null",
        f"data.train_files={ROOT}/outputs/training/data/train.parquet",
        f"data.train_batch_size={BATCH_SIZE}", f"data.gen_batch_size={BATCH_SIZE}",
        "data.shuffle=False", "data.return_raw_chat=True", "data.dataloader_num_workers=0",
        f"data.custom_cls.path={ROOT}/player1/training/data/dataset.py",
        "data.custom_cls.name=PlayerOneDataset",
        f"++data.player1_joint_training_config={ROOT}/examples/training/environments.json",
        "++data.apply_chat_template_kwargs.enable_thinking=True",
        "data.max_prompt_length=8192", "data.max_response_length=1024",
        f"algorithm.adv_estimator={'gae' if ppo else 'grpo'}", "algorithm.gamma=1", "algorithm.lam=1",
        "algorithm.use_kl_in_reward=False", "algorithm.rollout_correction.bypass_mode=True",
        f"actor_rollout_ref.model.path={model_path}", "actor_rollout_ref.model.use_remove_padding=True",
        "actor_rollout_ref.model.enable_gradient_checkpointing=True",
        f"actor_rollout_ref.actor.ppo_mini_batch_size={BATCH_SIZE}",
        "actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=1",
        "actor_rollout_ref.actor.use_dynamic_bsz=True",
        "actor_rollout_ref.actor.ppo_max_token_len_per_gpu=12288",
        "actor_rollout_ref.actor.optim.lr=1e-6", "actor_rollout_ref.actor.use_kl_loss=False",
        "actor_rollout_ref.actor.loss_agg_mode=seq-mean-token-mean",
        "actor_rollout_ref.actor.fsdp_config.model_dtype=float32",
        f"actor_rollout_ref.actor.policy_loss.loss_mode={'gspo' if ALGORITHM == 'gspo' else 'vanilla'}",
        "actor_rollout_ref.rollout.name=vllm", "actor_rollout_ref.rollout.mode=async",
        f"actor_rollout_ref.rollout.n={1 if ppo else 2}",
        "actor_rollout_ref.rollout.tensor_model_parallel_size=1",
        "actor_rollout_ref.rollout.gpu_memory_utilization=0.2",
        "actor_rollout_ref.rollout.enforce_eager=True", "actor_rollout_ref.rollout.max_model_len=12288",
        "actor_rollout_ref.rollout.prompt_length=8192", "actor_rollout_ref.rollout.response_length=1024",
        "actor_rollout_ref.rollout.max_num_batched_tokens=12288",
        "actor_rollout_ref.rollout.calculate_log_probs=True",
        "actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=1",
        "actor_rollout_ref.rollout.agent.num_workers=1",
        "++actor_rollout_ref.rollout.agent.agent_loop_manager_class=player1.training.rollout.manager.PlayerOneAgentLoopManager",
        f"++actor_rollout_ref.rollout.custom.player1.agent_loop.max_environment_steps={MAX_ENV_STEPS}",
        "++actor_rollout_ref.rollout.custom.player1.agent_loop.max_turn_tokens=1024",
        "++actor_rollout_ref.rollout.custom.player1.agent_loop.response_mask_mode=think_and_action",
        "++actor_rollout_ref.rollout.custom.player1.agent_loop.history_context_turns=2",
        "++actor_rollout_ref.rollout.custom.player1.agent_loop.history_context_old_turns=2",
        "++actor_rollout_ref.rollout.custom.player1.agent_loop.history_context_old_mode=a",
        "++actor_rollout_ref.rollout.custom.player1.agent_loop.reward.reward_mode=dense",
        "++actor_rollout_ref.rollout.custom.player1.agent_loop.screenshot_max_height=480",
        f"++actor_rollout_ref.rollout.custom.player1.advantage_normalization={'per_environment' if ppo else 'global'}",
        f"critic.enable={ppo}", f"critic.model.path={model_path}", "critic.model.use_remove_padding=True",
        "critic.ppo_micro_batch_size_per_gpu=1", "critic.forward_micro_batch_size_per_gpu=1",
        "critic.use_dynamic_bsz=True", "critic.ppo_max_token_len_per_gpu=12288",
        "critic.loss_agg_mode=seq-mean-token-mean", "critic.optim.lr=1e-5",
        "reward.reward_model.enable=False", "trainer.nnodes=1", "trainer.n_gpus_per_node=1",
        "trainer.v1.trainer_mode=sync", "trainer.val_before_train=False",
        "trainer.test_freq=-1", "trainer.save_freq=10", f"trainer.total_training_steps={TRAIN_STEPS}",
        "trainer.total_epochs=100", "trainer.logger=[console]", "trainer.project_name=player1",
        "trainer.experiment_name=training", f"trainer.default_local_dir={OUTPUT}",
        '++ray_kwargs.ray_init.runtime_env.env_vars.TRANSFER_QUEUE_ENABLE="1"',
    ]
    with initialize_config_module(config_module="verl.trainer.config", version_base=None):
        config = compose(config_name="ppo_trainer", overrides=[*settings, *overrides])
    actor_model, critic_model = config.actor_rollout_ref.model, config.critic.model
    needs_actor = actor_model.path is None
    needs_critic = config.critic.enable and critic_model.path is None
    if needs_actor or needs_critic:
        sft_output = Path(os.environ.get("PLAYER1_SFT_OUTPUT", DEFAULT_OUTPUT)).resolve()
        exported = str(export_checkpoint(sft_output))
        if needs_actor:
            actor_model.path = exported
        if needs_critic:
            critic_model.path = exported
    return config


def main():
    from player1.training.main_ppo_sync import main as train
    config = make_config(sys.argv[1:], default_model=os.environ.get("PLAYER1_MODEL_PATH") or None)
    output = Path(config.trainer.default_local_dir)
    output.mkdir(parents=True, exist_ok=True)
    OmegaConf.save(config, output / "config.yaml")
    train(config)


if __name__ == "__main__":
    main()
