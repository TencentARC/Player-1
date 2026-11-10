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
import socket
from types import SimpleNamespace

import pytest

from verl.utils.net_utils import get_free_port
from verl.workers.rollout.replica import RolloutMode
from verl.workers.rollout.vllm_rollout.vllm_async_server import vLLMHttpServer


class _FakeEngine:
    def __init__(self):
        self.output_processor = SimpleNamespace(request_states={"request-0": object()})
        self.calls = []
        self.pause_calls = []
        self.reset_mm_cache_calls = 0

    async def pause_generation(self, **kwargs):
        self.pause_calls.append(kwargs)

    async def wake_up(self, *, tags):
        self.calls.append(("wake_up", tags))

    async def reset_prefix_cache(self, **kwargs):
        self.calls.append(("reset_prefix_cache", kwargs))

    async def reset_mm_cache(self):
        self.reset_mm_cache_calls += 1
        self.calls.append(("reset_mm_cache", None))


@pytest.mark.parametrize("reset_prefix_cache", [True, False])
def test_abort_all_requests_keeps_multimodal_caches_in_sync(reset_prefix_cache):
    server = vLLMHttpServer.__new__(vLLMHttpServer)
    server.engine = _FakeEngine()

    result = asyncio.run(server.abort_all_requests(reset_prefix_cache=reset_prefix_cache))

    assert result == {"aborted_count": 1, "request_ids": ["request-0"]}
    assert server.engine.pause_calls == [
        {"wait_for_inflight_requests": False, "clear_cache": reset_prefix_cache}
    ]
    assert server.engine.reset_mm_cache_calls == int(reset_prefix_cache)


@pytest.mark.parametrize("rollout_mode", [RolloutMode.HYBRID, RolloutMode.COLOCATED])
def test_wake_up_keeps_multimodal_caches_in_sync(rollout_mode):
    server = vLLMHttpServer.__new__(vLLMHttpServer)
    server.node_rank = 0
    server.rollout_mode = rollout_mode
    server.engine = _FakeEngine()

    asyncio.run(server.wake_up())

    assert server.engine.calls == [
        ("wake_up", ["kv_cache", "weights"]),
        ("reset_prefix_cache", {"reset_connector": True}),
        ("reset_mm_cache", None),
    ]


def test_release_port_reservations_before_vllm_binds():
    server = vLLMHttpServer.__new__(vLLMHttpServer)
    address = "127.0.0.1"
    reserved = []
    ports = []
    for attr in ("_master_sock", "_dp_rpc_sock", "_dp_master_sock"):
        port, sock = get_free_port(address, with_alive_sock=True)
        ports.append(port)
        reserved.append(sock)
        setattr(server, attr, sock)

    server._release_port_reservations()
    server._release_port_reservations()

    assert all(sock.fileno() == -1 for sock in reserved)
    assert all(getattr(server, attr) is None for attr in ("_master_sock", "_dp_rpc_sock", "_dp_master_sock"))

    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((address, port))
