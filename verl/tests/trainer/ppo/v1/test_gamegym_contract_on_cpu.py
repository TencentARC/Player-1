# Copyright 2024 Bytedance Ltd. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
from collections import defaultdict
from types import SimpleNamespace

import pytest

if sys.platform == "darwin":
    pytest.skip(
        "The synchronous trainer imports the FSDP/DTensor stack, which is unsupported on macOS",
        allow_module_level=True,
    )

from verl.trainer.ppo.v1 import agent_loop_tq
from verl.trainer.ppo.v1 import replay_buffer as replay_module
from verl.trainer.ppo.v1 import trainer_base as main_ppo_sync
from verl.trainer.ppo.v1.trainer_sync import PPOTrainerSync as PPOTrainer


class _CriticUpdateDispatched(Exception):
    pass


class _CriticUpdateFuture:
    def get(self):
        raise _CriticUpdateDispatched


class _CriticWorkerGroup:
    def __init__(self):
        self.batch = None

    def train_mini_batch(self, batch):
        self.batch = batch
        return _CriticUpdateFuture()


class _Batch:
    def __init__(self, size):
        self.size = size
        self.extra_info = {}

    def __len__(self):
        return self.size


class _CriticConfigDispatched(Exception):
    pass


class _ResourcePoolManager:
    def __init__(self):
        self.pool = object()
        self.resource_pool_dict = {"global_pool": self.pool}

    def create_resource_pool(self):
        pass

    def get_resource_pool(self, _role):
        return self.pool


class _Config(SimpleNamespace):
    def get(self, name, default=None):
        return getattr(self, name, default)


class _FakeTransferQueue:
    def __init__(self, partitions):
        self.partitions = defaultdict(dict, {partition_id: dict(items) for partition_id, items in partitions.items()})
        self.clear_calls = []

    def kv_clear(self, *, keys, partition_id):
        keys = list(keys)
        self.clear_calls.append((partition_id, keys))
        partition = self.partitions[partition_id]
        for key in keys:
            partition.pop(key, None)

    def kv_list(self):
        return {partition_id: dict(items) for partition_id, items in self.partitions.items()}


def _replay_buffer_with_items(items):
    return replay_module.ReplayBuffer(
        trainer_mode="sync", trainer_config={}, max_off_policy_threshold=1,
        max_off_policy_strategy="wait", sampler_kwargs={}, poll_interval=0.0,
    )


def test_empty_agent_loop_outputs_raise_contract_error():
    with pytest.raises(agent_loop_tq.AgentLoopContractError, match="prompt prompt-1_2"):
        agent_loop_tq._normalize_agent_loop_outputs([], uid="prompt-1", session_id=2)


def test_multi_output_reward_backfill_preserves_explicit_targets():
    outputs = [
        SimpleNamespace(reward_score=3.0, extra_fields={"reward_extra_info": {"source": "turn"}}),
        SimpleNamespace(reward_score=None, extra_fields={}),
        SimpleNamespace(reward_score=9.0, extra_fields={"reward_extra_info": {"source": "trajectory"}}),
    ]

    agent_loop_tq._backfill_multi_output_rewards(outputs)

    assert outputs[0].reward_score == 3.0
    assert outputs[0].extra_fields["reward_extra_info"] == {"source": "turn"}
    assert outputs[1].reward_score == 9.0
    assert outputs[1].extra_fields["reward_extra_info"] == {"source": "trajectory"}


def test_replay_buffer_refresh_drops_consumed_keys_without_background_snapshot(monkeypatch):
    key = "prompt-1_0_0"
    tag = {"global_steps": 29, "status": "success"}
    replay_buffer = _replay_buffer_with_items({key: tag})
    fake_tq = _FakeTransferQueue({"train": {key: tag}})
    monkeypatch.setattr(replay_module, "tq", fake_tq)
    replay_buffer._sync_metadata_from_transfer_queue()
    assert key in replay_buffer.partitions["train"]
    fake_tq.kv_clear(partition_id="train", keys=[key])
    replay_buffer._sync_metadata_from_transfer_queue()
    assert key not in replay_buffer.partitions["train"]


def test_old_log_prob_bypass_returns_batch_and_uses_rollout_log_probs(monkeypatch):
    trainer = PPOTrainer.__new__(PPOTrainer)
    trainer.config = SimpleNamespace(algorithm={"rollout_correction": {"bypass_mode": True}})
    batch = SimpleNamespace(keys=["sample-0"], partition_id="train")
    rollout_log_probs = object()
    stored_fields = {}

    def fake_get(*, keys, partition_id, select_fields):
        assert keys == batch.keys
        assert partition_id == batch.partition_id
        assert select_fields == ["rollout_log_probs"]
        return {"rollout_log_probs": rollout_log_probs}

    def fake_put(*, keys, partition_id, fields):
        assert keys == batch.keys
        assert partition_id == batch.partition_id
        stored_fields.update(fields)

    monkeypatch.setattr(main_ppo_sync.tq, "kv_batch_get", fake_get)
    monkeypatch.setattr(main_ppo_sync.tq, "kv_batch_put", fake_put)

    result = trainer._compute_old_log_prob(batch, metrics={})

    assert result is batch
    assert stored_fields == {"old_log_probs": rollout_log_probs}


def test_update_critic_propagates_rollout_temperature():
    trainer = PPOTrainer.__new__(PPOTrainer)
    trainer.config = SimpleNamespace(
        data=_Config(gen_batch_size=8, train_batch_size=8),
        critic=SimpleNamespace(
            ppo_mini_batch_size=2,
            ppo_epochs=1,
            data_loader_seed=7,
            shuffle=True,
            loss_agg_mode="seq-mean-token-mean",
        ),
        actor_rollout_ref=SimpleNamespace(rollout=SimpleNamespace(n=8, temperature=0.7)),
    )
    trainer.critic_wg = _CriticWorkerGroup()
    batch = _Batch(size=96)

    with pytest.raises(_CriticUpdateDispatched):
        trainer._update_critic(batch, metrics={})

    assert trainer.critic_wg.batch is batch
    assert batch.extra_info["temperature"] == 0.7
    assert batch.extra_info["num_mini_batch"] == 4
    assert batch.extra_info["global_batch_size"] == 24


def test_multi_output_batch_preserves_configured_optimizer_step_count():
    trainer = PPOTrainer.__new__(PPOTrainer)
    trainer.config = SimpleNamespace(
        data=_Config(gen_batch_size=8, train_batch_size=8),
        actor_rollout_ref=SimpleNamespace(rollout=SimpleNamespace(n=8)),
    )

    single_output = trainer._get_mini_batch_info(batch_size=64, ppo_mini_batch_size=8)
    multi_output = trainer._get_mini_batch_info(batch_size=1600, ppo_mini_batch_size=8)

    assert single_output == {"global_batch_size": 64, "num_mini_batch": 1}
    assert multi_output == {"global_batch_size": 1600, "num_mini_batch": 1}


def test_multi_output_batch_padding_aligns_each_dp_rank_with_num_mini_batches():
    trainer = PPOTrainer.__new__(PPOTrainer)
    trainer.config = SimpleNamespace(
        data=_Config(gen_batch_size=8, train_batch_size=8),
        actor_rollout_ref=SimpleNamespace(
            actor=SimpleNamespace(ppo_mini_batch_size=2),
            rollout=SimpleNamespace(n=8),
        ),
        trainer=SimpleNamespace(critic_warmup=0),
    )
    trainer.use_critic = False
    trainer.global_steps = 1

    assert trainer._get_required_batch_multiple(dp_size=16) == 64


def test_init_workers_keeps_critic_train_and_infer_token_limits_distinct(monkeypatch):
    actor_cls = object()
    critic_cls = object()
    engine_config = SimpleNamespace()
    critic_config = _Config(
        ppo_max_token_len_per_gpu=16_384,
        ppo_infer_max_token_len_per_gpu=32_768,
        engine=engine_config,
        model=object(),
        optim=object(),
        checkpoint=object(),
    )
    trainer = PPOTrainer.__new__(PPOTrainer)
    trainer.resource_pool_manager = _ResourcePoolManager()
    trainer.role_worker_mapping = {
        main_ppo_sync.Role.ActorRollout: actor_cls,
        main_ppo_sync.Role.Critic: critic_cls,
    }
    trainer.config = _Config(actor_rollout_ref=object(), critic=critic_config)
    trainer.use_critic = True
    for name in ("_init_tokenizer", "_init_dataloader", "_init_dump_executor", "_init_resource_pool_mgr"):
        monkeypatch.setattr(trainer, name, lambda: None)

    monkeypatch.setattr(main_ppo_sync, "omega_conf_to_dataclass", lambda config: config)

    def capture_critic_config(*, cls, config, **_kwargs):
        if cls is critic_cls:
            assert config.engine_config is engine_config
            raise _CriticConfigDispatched
        return object()

    monkeypatch.setattr(main_ppo_sync, "RayClassWithInitArgs", capture_critic_config)

    with pytest.raises(_CriticConfigDispatched):
        trainer._setup()

    assert engine_config.max_token_len_per_gpu == 16_384
    assert engine_config.infer_max_token_len_per_gpu == 32_768
