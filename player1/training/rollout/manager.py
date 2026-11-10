"""Synchronous visual rollouts with one active episode per worker."""

import ray
from tensordict import TensorDict
from verl.trainer.ppo.v1.agent_loop_tq import AgentLoopManagerTQ
from verl.utils import tensordict_utils as tu

from ..metrics.optimization import (
    aggregate_joint_optimization_metrics, aggregate_training_metrics,
    final_session_indices, whiten_advantages_by_environment,
)
from ..metrics.rollout import aggregate_rollout_timing_metrics
from .config import PlayerOneManagerConfig

PLAYER1_AGENT_LOOP_TARGET = "player1.training.rollout.loop.PlayerOneAgentLoop"


class PlayerOneAgentLoopManager(AgentLoopManagerTQ):
    def __init__(self, config, *args, **kwargs):
        self.manager_config = PlayerOneManagerConfig.from_trainer_config(config)
        super().__init__(config, *args, **kwargs)

    async def _init_agent_loop_workers(self):
        self.agent_loop_workers = [
            self.agent_loop_workers_class.remote(
                self.config, self.llm_client, self.teacher_client, self.reward_loop_worker_handles,
                fixed_agent_loop_target=PLAYER1_AGENT_LOOP_TARGET,
            )
            for _ in range(self.manager_config.train_num_workers)
        ]

    def generate_sequences(self, prompts):
        if "validate" in prompts and bool(tu.unwrap_non_tensor_data(prompts["validate"])):
            return super().generate_sequences(prompts)
        self._environment_ids(prompts)
        if not len(prompts):
            raise ValueError("Rollout batch must be non-empty")
        workers = self.agent_loop_workers
        for start in range(0, len(prompts), len(workers)):
            ray.get([
                worker.generate_sequences.remote(prompts[index:index + 1], wait_for_completion=True)
                for index, worker in zip(range(start, len(prompts)), workers)
            ])

    def close(self):
        workers = self.agent_loop_workers
        self.agent_loop_workers = []
        try:
            ray.get([worker.close.remote() for worker in workers])
        finally:
            for worker in workers:
                ray.kill(worker)

    @staticmethod
    def _environment_ids(prompts: TensorDict) -> list[str]:
        try:
            extra_infos = prompts["extra_info"]
        except (KeyError, TypeError) as exc:
            raise ValueError("Player-1 rollout batch is missing extra_info") from exc
        if hasattr(extra_infos, "tolist"):
            extra_infos = extra_infos.tolist()
        environment_ids: list[str] = []
        for index, extra_info in enumerate(extra_infos):
            if not isinstance(extra_info, dict):
                raise ValueError(f"Player-1 rollout row {index} is missing structured extra_info")
            environment_id = str(extra_info.get("environment_id") or "").strip()
            if not environment_id:
                raise ValueError(f"Player-1 rollout row {index} is missing extra_info.environment_id")
            environment_ids.append(environment_id)
        return environment_ids

    def postprocess_advantages(self, data, *, batch):
        """Apply the configured Player-1 advantage normalization after native GAE."""

        if self.manager_config.advantage_normalization == "global":
            return data, {}

        try:
            import transfer_queue as tq
        except ImportError:
            from verl.utils.transferqueue_utils import tq

        source_data = tq.kv_batch_get(
            keys=batch.keys,
            partition_id=batch.partition_id,
            select_fields=["data_source"],
        )
        data_sources = source_data["data_source"]
        data_source_rows = data_sources.tolist() if hasattr(data_sources, "tolist") else list(data_sources)
        data_source_rows = [str(tu.unwrap_non_tensor_data(source)) for source in data_source_rows]
        advantages, metrics = whiten_advantages_by_environment(
            advantages=data.batch["advantages"],
            response_mask=data.batch["response_mask"],
            data_sources=data_source_rows,
        )
        data.batch["advantages"] = advantages
        return data, metrics

    def compute_training_metrics(self, batch) -> dict[str, float]:
        """Aggregate episode telemetry and per-environment optimization diagnostics."""

        metrics: dict[str, float] = {}
        indices = final_session_indices(batch.keys, batch.tags)
        try:
            import transfer_queue as tq
        except ImportError:
            from verl.utils.transferqueue_utils import tq

        if indices:
            keys = [batch.keys[index] for index in indices]
            data = tq.kv_batch_get(
                keys=keys,
                partition_id=batch.partition_id,
                select_fields=["data_source", "extra_fields"],
            )
            data_sources = data["data_source"]
            extra_fields = data["extra_fields"]
            data_sources_list = data_sources.tolist() if hasattr(data_sources, "tolist") else list(data_sources)
            extra_fields_list = extra_fields.tolist() if hasattr(extra_fields, "tolist") else list(extra_fields)
            metrics.update(
                aggregate_training_metrics(
                    data_sources=data_sources_list,
                    extra_fields=extra_fields_list,
                )
            )
            metrics.update(aggregate_rollout_timing_metrics(extra_fields_list))

        active_indices = [index for index, tag in enumerate(batch.tags) if not tag.get("is_padding", False)]
        if not active_indices:
            return metrics
        fields = ["data_source", "response_mask"]
        if self.manager_config.advantage_estimator == "gae":
            fields.extend(["values", "returns"])
        optimization_data = tq.kv_batch_get(
            keys=[batch.keys[index] for index in active_indices],
            partition_id=batch.partition_id,
            select_fields=fields,
        )

        def _rows(value):
            return list(value.unbind()) if hasattr(value, "unbind") else list(value)

        optimization_sources = optimization_data["data_source"]
        metrics.update(
            aggregate_joint_optimization_metrics(
                data_sources=(
                    optimization_sources.tolist()
                    if hasattr(optimization_sources, "tolist")
                    else list(optimization_sources)
                ),
                response_masks=_rows(optimization_data["response_mask"]),
                values=_rows(optimization_data["values"]) if "values" in optimization_data else None,
                returns=_rows(optimization_data["returns"]) if "returns" in optimization_data else None,
            )
        )
        return metrics
