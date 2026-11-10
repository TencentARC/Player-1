"""Player-1 entrypoint for the synchronous verl trainer."""

import logging

import hydra
import ray
from verl.trainer.main_ppo import TaskRunnerV1, run_ppo
from verl.trainer.ppo.v1 import trainer_base as upstream
from verl.trainer.ppo.v1.trainer_sync import PPOTrainerSync
from verl.utils.config import validate_config
from verl.utils.device import auto_set_device

from omegaconf import OmegaConf, open_dict
from torchdata.stateful_dataloader import StatefulDataLoader
from verl.trainer.ppo.utils import create_rl_dataset, create_rl_sampler
from verl.utils.dataset.rl_dataset import collate_fn

from .rollout.config import PlayerOneManagerConfig, configure_vllm_worker

logger = logging.getLogger(__name__)


class PlayerOnePPOTrainer(PPOTrainerSync):
    """Close rollout workers and tracking when training finishes or fails."""

    def _init_dataloader(self):
        """Allow training without a validation dataset; otherwise use native loading."""
        if self.config.data.val_files:
            return super()._init_dataloader()
        self.train_dataset = create_rl_dataset(
            self.config.data.train_files,
            self.config.data,
            self.tokenizer,
            self.processor,
            is_train=True,
            max_samples=self.config.data.get("train_max_samples", -1),
        )
        # Exact refill counts require single-prompt dataloader fetches.
        filter_groups = self.config.algorithm.get("filter_groups", None)
        dapo_enabled = bool(filter_groups is not None and filter_groups.get("enable", False))
        sync_refill_failed_groups = bool(self.config.trainer.v1.sampler.get("sync_refill_failed_groups", False))
        requires_exact_refill = self.trainer_mode != "sync" or dapo_enabled or sync_refill_failed_groups
        if requires_exact_refill:
            user_gen_batch_size = self.config.data.get("gen_batch_size", None)
            if user_gen_batch_size not in (None, 1):
                logger.warning(f"data.gen_batch_size={user_gen_batch_size} is overridden to 1.")
            elif user_gen_batch_size is None:
                logger.info("data.gen_batch_size defaulted to 1.")
            with open_dict(self.config):
                self.config.data.gen_batch_size = 1

        # use gen_batch_size as the batch size for the dataloader if set, otherwise use train_batch_size
        gen_batch_size = self.config.data.get("gen_batch_size", None) or self.config.data.train_batch_size
        self.train_dataloader = StatefulDataLoader(
            dataset=self.train_dataset,
            batch_size=gen_batch_size,
            num_workers=self.config.data["dataloader_num_workers"],
            drop_last=True,
            collate_fn=collate_fn,
            sampler=create_rl_sampler(self.config.data, self.train_dataset),
        )
        self.train_dataloader_it = None
        self.steps_per_epoch = len(self.train_dataset) // self.config.data.train_batch_size

        # adjust total_training_steps
        total_training_steps = self.steps_per_epoch * self.config.trainer.total_epochs
        if self.config.trainer.total_training_steps is not None:
            total_training_steps = self.config.trainer.total_training_steps
        self.total_training_steps = total_training_steps
        logger.info(f"Total training steps: {self.total_training_steps}")

        # The LR scheduler steps once per local update, and each global step performs
        # ``parameter_sync_step`` local updates (see ``PPOTrainer.step``). The optimizer's
        # schedule horizon must therefore count optimizer updates.
        optim_total_training_steps = total_training_steps * self.parameter_sync_step
        try:
            OmegaConf.set_struct(self.config, True)
            with open_dict(self.config):
                if OmegaConf.select(self.config, "actor_rollout_ref.actor.optim"):
                    self.config.actor_rollout_ref.actor.optim.total_training_steps = optim_total_training_steps
                if OmegaConf.select(self.config, "critic.optim"):
                    self.config.critic.optim.total_training_steps = optim_total_training_steps
        except Exception as e:
            logger.warning(f"Warning: Could not set total_training_steps in config. Structure missing? Error: {e}")

    def _finish_tracking(self, *, exit_code: int) -> None:
        tracking = getattr(self, "logger", None)
        backends = getattr(tracking, "logger", None)
        if not isinstance(backends, dict):
            return
        for name in tuple(backends):
            backend = backends.pop(name, None)
            finish = getattr(backend, "finish", None)
            if not callable(finish):
                continue
            try:
                if name in {"wandb", "vemlp_wandb"}:
                    finish(exit_code=exit_code)
                else:
                    finish()
            except Exception:
                logger.exception("Failed to finish Player-1 tracking backend %s", name)

    def fit(self, agent_loop_manager):
        exit_code = 0
        try:
            return super().fit(agent_loop_manager)
        except BaseException:
            exit_code = 1
            raise
        finally:
            cleanup_error = None
            for label, close in (
                ("rollout manager", agent_loop_manager.close),
                ("dump executor", self._shutdown_dump_executor),
            ):
                try:
                    close()
                except Exception as exc:
                    logger.exception("Failed to close Player-1 %s", label)
                    cleanup_error = cleanup_error or exc
            self._finish_tracking(exit_code=exit_code or int(cleanup_error is not None))
            if cleanup_error is not None and not exit_code:
                raise cleanup_error


def _upstream_task_runner_class() -> type:
    task_runner_class = getattr(getattr(TaskRunnerV1, "__ray_metadata__", None), "modified_class", None)
    if task_runner_class is None:
        raise RuntimeError("verl synchronous TaskRunner no longer exposes its Ray controller class")
    return task_runner_class


@ray.remote
class PlayerOneTaskRunner:
    """Install the Player-1 trainer inside the remote controller process."""

    def run(self, config) -> None:
        upstream.TRAINER_REGISTRY["sync"] = PlayerOnePPOTrainer
        if config.trainer.v1.trainer_mode != "sync":
            raise ValueError("Player-1 synchronous entrypoint requires trainer.v1.trainer_mode=sync")
        _upstream_task_runner_class()().run(config)


@hydra.main(config_path="pkg://verl.trainer.config", config_name="ppo_trainer", version_base=None)
def main(config) -> None:
    PlayerOneManagerConfig.from_trainer_config(config)
    configure_vllm_worker(config.actor_rollout_ref.rollout)
    auto_set_device(config)
    config.transfer_queue.enable = True
    validate_config(
        config=config,
        use_reference_policy=upstream.need_reference_policy(config),
        use_critic=upstream.need_critic(config),
    )
    run_ppo(config, task_runner_class=PlayerOneTaskRunner)


if __name__ == "__main__":
    main()
