"""Teacher-forced SFT using the native verl FSDP engine and checkpoints."""

import json
from pathlib import Path

import torch
from omegaconf import OmegaConf
from torchdata.stateful_dataloader import StatefulDataLoader
from verl.trainer.sft_trainer import SFTTrainer
from verl.utils.checkpoint import CheckpointHandler
from verl.utils.dataset.dataset_utils import SFTTensorCollator
from verl.utils.device import auto_set_device
from verl.utils.distributed import destroy_global_process_group, initialize_global_process_group

from .action_balanced_sampler import RankBatchSampler, build_train_sampler
from .history_context_sampling import UniformHistoryBatchSampler
from .player1_control_training_contract import load_player1_control_training_contract


class PlayerOneCheckpointHandler(CheckpointHandler):
    """Bind native checkpoints to their dataset and optimization contract."""

    def __init__(self, *args, identity, **kwargs):
        super().__init__(*args, **kwargs)
        self.identity = identity

    def save_checkpoint(self, step):
        super().save_checkpoint(step)
        if self.rank == 0:
            path = Path(self.default_local_dir) / f"global_step_{step}" / "player1.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.identity, sort_keys=True, indent=2) + "\n")
            temporary.replace(path)
        torch.distributed.barrier()

    def _determine_resume_path(self):
        path = super()._determine_resume_path()
        if path is not None:
            identity_path = Path(path) / "player1.json"
            if not identity_path.is_file() or json.loads(identity_path.read_text()) != self.identity:
                raise ValueError("SFT checkpoint is incomplete or belongs to another data/training contract")
        return path

    def _load_dataloader_state(self, checkpoint_path):
        state_path = Path(checkpoint_path) / f"data_{self.dp_rank}.pt"
        if not state_path.is_file():
            raise ValueError("SFT recovery requires the saved dataloader state")
        if self.resume_global_step % len(self.train_dataloader) == 0:
            # Native fit starts the next epoch at a boundary. Restoring the
            # previous epoch's consumed iterator would skip this whole epoch.
            torch.load(state_path, map_location="cpu", weights_only=False)
            return
        return super()._load_dataloader_state(checkpoint_path)


class PlayerOneSFTTrainer(SFTTrainer):
    def _build_dataset(self):
        self.release_contract = load_player1_control_training_contract(self.config.data)
        super()._build_dataset()

    def _build_dataloader(self):
        super()._build_dataloader()
        config = self.config.data
        self.global_batch_size = int(config.train_batch_size)
        size, rank = self.engine.get_data_parallel_size(), self.engine.get_data_parallel_rank()
        sampler = build_train_sampler(
            self.train_dataset, global_batch_size=self.global_batch_size,
            data_parallel_size=size, sampling=config.sampling,
        )
        if config.history_sampling == "uniform_0_2":
            sampler = UniformHistoryBatchSampler(sampler)
        elif config.history_sampling != "fixed":
            raise ValueError("history_sampling must be fixed or uniform_0_2")
        self.train_sampler = RankBatchSampler(sampler, rank=rank, size=size)
        self.train_batch_size_per_dp = self.global_batch_size // size
        self.train_dataloader = StatefulDataLoader(
            self.train_dataset, batch_sampler=self.train_sampler,
            collate_fn=SFTTensorCollator(config.pad_mode), num_workers=0, pin_memory=False,
        )
        self.release_contract.assert_metadata_current()

    def _init_engine(self):
        super()._init_engine()
        if not 0 < self.total_training_steps <= self.steps_per_epoch * self.config.trainer.total_epochs:
            raise ValueError("SFT horizon must fit the configured number of complete training batches")

    def _build_ckpt_handler(self):
        trainer = self.config.trainer
        identity = {
            "data": self.release_contract.resume_identity(),
            "model": OmegaConf.to_container(self.config.model, resolve=True),
            "engine": OmegaConf.to_container(self.config.engine, resolve=True),
            "optimizer": OmegaConf.to_container(self.config.optim, resolve=True),
            "sampling": OmegaConf.to_container(self.config.data.sampling, resolve=True),
            "history_sampling": self.config.data.history_sampling,
            "batch_size": self.global_batch_size,
            "max_length": self.config.data.max_length,
            "world_size": torch.distributed.get_world_size(),
            "total_training_steps": self.total_training_steps,
        }
        self.ckpt_handler = PlayerOneCheckpointHandler(
            engine=self.engine, train_dataloader=self.train_dataloader,
            default_local_dir=trainer.default_local_dir,
            max_ckpt_to_keep=trainer.max_ckpt_to_keep,
            resume_mode=trainer.resume_mode, resume_from_path=trainer.resume_from_path,
            lora_train_meta=self._get_lora_train_meta(), identity=identity,
        )


def train(config):
    auto_set_device(config)
    if set(config.checkpoint.save_contents) != {"model", "optimizer", "extra"}:
        raise ValueError("SFT requires native model, optimizer and extra checkpoint state")
    if list(config.checkpoint.load_contents) != list(config.checkpoint.save_contents):
        raise ValueError("SFT must restore the complete native checkpoint")
    initialize_global_process_group()
    try:
        trainer = PlayerOneSFTTrainer(config)
        if trainer.resume_global_step < trainer.total_training_steps:
            trainer.fit()
    finally:
        destroy_global_process_group()
