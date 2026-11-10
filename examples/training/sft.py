"""Supervised fine-tuning from a prepared Player-1-Data directory."""

import json
import os
import sys
from pathlib import Path

from hydra import compose, initialize_config_module
from omegaconf import OmegaConf

from player1.training.sft.action_balanced_sampler import sampling_config
from player1.training.sft.checkpoint_export import DEFAULT_OUTPUT, export_checkpoint

DATASET = Path(os.environ.get("PLAYER1_DATASET_ROOT", "downloads/Player-1-Data")).resolve()
MODEL = os.environ.get("PLAYER1_MODEL_PATH", "Qwen/Qwen3.5-9B")
OUTPUT = Path(os.environ.get("PLAYER1_OUTPUT", DEFAULT_OUTPUT)).resolve()
BATCH_SIZE = int(os.environ.get("PLAYER1_BATCH_SIZE", "16"))
TRAIN_STEPS = int(os.environ.get("PLAYER1_TRAIN_STEPS", "100"))


def make_config(overrides=()):
    settings = [
        f"model.path={MODEL}", "model.use_remove_padding=True",
        "model.enable_gradient_checkpointing=True",
        "engine.strategy=fsdp2", "engine.model_dtype=bfloat16",
        f"data.train_files=[{DATASET}/data/train.parquet]",
        "data.val_files=null",
        f"data.train_batch_size={BATCH_SIZE}", "data.micro_batch_size_per_gpu=1",
        "data.max_length=8192", "data.max_token_len_per_gpu=12288", "data.use_dynamic_bsz=True",
        "data.num_workers=0", "++data.shuffle=False", "++data.image_key=images",
        "++data.apply_chat_template_kwargs.enable_thinking=True",
        "data.custom_cls.path=pkg://player1.training.sft.player1_control_dataset",
        "data.custom_cls.name=PlayerOneControlQwen35SFTDataset",
        f"++data.player1_control_dataset_root={DATASET}",
        "++data.history_context_turns=2", "++data.history_context_old_turns=2",
        "++data.history_sampling=uniform_0_2", "optim.lr=5e-7",
        "optim.lr_warmup_steps_ratio=0.03", "optim.lr_scheduler_type=constant",
        "trainer.test_freq=-1", "trainer.save_freq=10", "trainer.total_epochs=100",
        f"trainer.total_training_steps={TRAIN_STEPS}", "trainer.logger=[console]",
        "trainer.project_name=player1", "trainer.experiment_name=sft",
        f"trainer.default_local_dir={OUTPUT}",
    ]
    for key, value in sampling_config(None, seed=42).items():
        if isinstance(value, dict):
            settings.extend(f"++data.sampling.{key}.{name}={json.dumps(weight)}" for name, weight in value.items())
        else:
            settings.append(f"++data.sampling.{key}={json.dumps(value)}")
    with initialize_config_module(config_module="verl.trainer.config", version_base=None):
        config = compose(config_name="sft_trainer_engine", overrides=[*settings, *overrides])
    return config


def main():
    from player1.training.sft.train import train
    config = make_config(sys.argv[1:])
    output = Path(config.trainer.default_local_dir)
    output.mkdir(parents=True, exist_ok=True)
    if int(os.environ.get("RANK", "0")) == 0:
        OmegaConf.save(config, output / "config.yaml")
    train(config)
    if int(os.environ.get("RANK", "0")) == 0:
        print(f"SFT model for RL: {export_checkpoint(output)}", flush=True)


if __name__ == "__main__":
    main()
