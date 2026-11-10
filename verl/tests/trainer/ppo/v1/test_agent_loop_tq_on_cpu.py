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

import asyncio
import weakref
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import torch

from verl.experimental.agent_loop.agent_loop import AgentLoopMetrics, AgentLoopOutput
from verl.trainer.ppo.v1 import agent_loop_tq
from verl.trainer.ppo.v1.agent_loop_tq import _settle_session_tasks


def test_settle_session_tasks_waits_for_siblings_after_failure():
    async def run():
        settled = asyncio.Event()

        async def fail():
            raise RuntimeError("session failed")

        async def finish_later():
            await asyncio.sleep(0.01)
            settled.set()

        tasks = [asyncio.create_task(fail()), asyncio.create_task(finish_later())]
        errors = await _settle_session_tasks(tasks)

        assert settled.is_set()
        assert all(task.done() for task in tasks)
        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeError)

    asyncio.run(run())


@pytest.mark.parametrize("validate", [False, True], ids=["training", "validation"])
@pytest.mark.parametrize("turn_count", [1, 3])
def test_postprocess_releases_only_validation_visual_payload(monkeypatch, validate, turn_count):
    outputs = [
        AgentLoopOutput(
            prompt_ids=[10] * (i + 1), response_ids=[20, 21], response_mask=[1, 1],
            reward_score=float(i + 1), num_turns=turn_count if i == turn_count - 1 else 1,
            multi_modal_data={"images": ["original-observation"]}, metrics=AgentLoopMetrics(),
            extra_fields={"step_index": i, "validation_trace_log": "trace.jsonl"},
        )
        for i in range(turn_count)
    ]
    pixel_refs, captured = [], {}

    def compute_images(output, input_ids):
        assert output.multi_modal_data == {"images": ["original-observation"]}
        pixels = torch.ones(8, 12)
        pixel_refs.append(weakref.ref(pixels))
        return {"pixel_values": pixels, "image_grid_thw": torch.tensor([[1, 2, 4]])}

    def compute_positions(input_ids, attention_mask, multi_modal_inputs):
        assert multi_modal_inputs["image_grid_thw"].tolist() == [[1, 2, 4]]
        assert multi_modal_inputs["pixel_values"].shape == (8, 12)
        return torch.arange(input_ids.shape[-1]).repeat(1, 4, 1)

    async def put(**kwargs):
        # Check release at enqueue time, before the worker method returns.
        assert all((reference() is None) == validate for reference in pixel_refs)
        captured.update(kwargs)

    monkeypatch.setattr(agent_loop_tq.tq, "async_kv_batch_put", put)
    worker = SimpleNamespace(
        _compute_score=AsyncMock(), _compute_teacher_logprobs=AsyncMock(),
        _compute_multi_modal_inputs=compute_images, _compute_position_ids=compute_positions,
    )
    method = agent_loop_tq.AgentLoopWorkerTQ.__ray_metadata__.modified_class._agent_loop_postprocess
    asyncio.run(method(worker, outputs, validate, uid="episode", session_id=0, global_steps=7))

    assert captured["partition_id"] == ("val" if validate else "train")
    assert captured["keys"] == [f"episode_0_{i}" for i in range(turn_count)]
    assert len(pixel_refs) == turn_count
    worker._compute_score.assert_awaited_once_with(
        outputs, kwargs={"uid": "episode", "session_id": 0, "global_steps": 7}
    )
    worker._compute_teacher_logprobs.assert_awaited_once()
    for i, row in enumerate(captured["fields"].unbind(0)):
        assert "multi_modal_data" not in row
        assert row["prompts"].tolist() == outputs[i].prompt_ids
        assert row["responses"].tolist() == outputs[i].response_ids
        assert row["loss_mask"].tolist() == [1, 1]
        assert row["rm_scores"].tolist() == [0, float(i + 1)]
        assert row.get_non_tensor("num_turns") == outputs[i].num_turns
        assert row.get_non_tensor("extra_fields") == outputs[i].extra_fields
        assert torch.equal(row["position_ids"], torch.arange(i + 3).repeat(4, 1))
        assert captured["tags"][i]["status"] == "success"
        assert captured["tags"][i]["seq_len"] == i + 3
        images = row.get_non_tensor("multi_modal_inputs")
        if validate:
            assert images == {}
        else:
            assert torch.equal(images["pixel_values"], torch.ones(8, 12))
            assert images["image_grid_thw"].tolist() == [[1, 2, 4]]
