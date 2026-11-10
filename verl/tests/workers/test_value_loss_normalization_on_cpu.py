from types import SimpleNamespace

import pytest
import torch
from tensordict import TensorDict

from verl.utils import tensordict_utils as tu
from verl.utils.metric import AggregationType, Metric
from verl.workers.utils.losses import value_loss


def _compute_partition_loss(
    parameter: torch.Tensor,
    returns: torch.Tensor,
    response_mask: torch.Tensor,
    row_slice: slice,
    loss_agg_mode: str,
) -> tuple[torch.Tensor, dict]:
    partition_returns = returns[row_slice]
    partition_mask = response_mask[row_slice]
    batch_size, response_length = partition_returns.shape
    prompt_length = 1
    data = TensorDict(
        {
            "prompts": torch.ones(batch_size, prompt_length, dtype=torch.long),
            "responses": torch.ones(batch_size, response_length, dtype=torch.long),
            "attention_mask": torch.ones(batch_size, prompt_length + response_length, dtype=torch.long),
            "values": torch.zeros_like(partition_returns),
            "returns": partition_returns,
            "response_mask": partition_mask,
        },
        batch_size=batch_size,
    )
    tu.assign_non_tensor(data, dp_size=1)
    tu.assign_non_tensor(data, batch_num_tokens=int(response_mask.sum().item()))
    tu.assign_non_tensor(data, global_batch_size=response_mask.shape[0])

    model_values = parameter.expand(batch_size * (prompt_length + response_length))
    config = SimpleNamespace(cliprange_value=100.0, loss_agg_mode=loss_agg_mode, loss_scale_factor=None)
    return value_loss(config, {"values": model_values}, data)


@pytest.mark.parametrize("loss_agg_mode", ["token-mean", "seq-mean-token-mean"])
def test_value_loss_wrapper_is_invariant_to_microbatch_partition(loss_agg_mode: str):
    returns = torch.tensor(
        [
            [1.0, 2.0, 0.0],
            [3.0, 4.0, 5.0],
            [6.0, 0.0, 0.0],
        ]
    )
    response_mask = torch.tensor(
        [
            [1.0, 1.0, 0.0],
            [1.0, 1.0, 1.0],
            [1.0, 0.0, 0.0],
        ]
    )

    full_parameter = torch.tensor(0.25, requires_grad=True)
    full_loss, full_metrics = _compute_partition_loss(
        full_parameter,
        returns,
        response_mask,
        slice(0, 3),
        loss_agg_mode,
    )
    full_loss.backward()

    partitioned_parameter = torch.tensor(0.25, requires_grad=True)
    first_loss, _ = _compute_partition_loss(
        partitioned_parameter,
        returns,
        response_mask,
        slice(0, 1),
        loss_agg_mode,
    )
    second_loss, _ = _compute_partition_loss(
        partitioned_parameter,
        returns,
        response_mask,
        slice(1, 3),
        loss_agg_mode,
    )
    partitioned_loss = first_loss + second_loss
    partitioned_loss.backward()

    assert isinstance(full_metrics["critic/vf_loss"], Metric)
    assert full_metrics["critic/vf_loss"].aggregation == AggregationType.SUM
    torch.testing.assert_close(partitioned_loss, full_loss)
    torch.testing.assert_close(partitioned_parameter.grad, full_parameter.grad)
