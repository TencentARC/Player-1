import asyncio
from contextlib import nullcontext
from types import SimpleNamespace


from verl.experimental.agent_loop import agent_loop as agent_loop_module










def test_worker_runs_fixed_agent_loop_target_without_agent_name(monkeypatch):
    captured = {}

    class FakeAgentLoop:
        async def run(self, sampling_params, **kwargs):
            del sampling_params, kwargs
            return object()

    async def postprocess(output, validate, **kwargs):
        del output, validate, kwargs
        return "done"

    worker = agent_loop_module.AgentLoopWorker.__new__(agent_loop_module.AgentLoopWorker)
    worker.config = SimpleNamespace(data={})
    worker.llm_client = object()
    worker.tokenizer = object()
    worker.processor = object()
    worker.dataset_cls = object()
    worker.tools = []
    worker.fixed_agent_loop_target = "external.agent.FixedAgentLoop"
    worker._agent_loop_postprocess = postprocess

    def instantiate(**kwargs):
        captured.update(kwargs)
        return FakeAgentLoop()

    monkeypatch.setattr(agent_loop_module.hydra.utils, "instantiate", instantiate)
    monkeypatch.setattr(agent_loop_module, "rollout_trace_attr", lambda **kwargs: nullcontext())

    result = asyncio.run(
        worker._run_agent_loop(
            {},
            {"step": 1, "sample_index": 2, "rollout_n": 0, "validate": False},
            trace=False,
        )
    )

    assert result == "done"
    assert captured["config"] == {"_target_": "external.agent.FixedAgentLoop"}


def test_worker_close_runs_fixed_agent_loop_cleanup(monkeypatch):
    events = []

    class FixedAgentLoop:
        @staticmethod
        async def close_worker_resources():
            events.append("closed")

    worker = agent_loop_module.AgentLoopWorker.__new__(agent_loop_module.AgentLoopWorker)
    worker.fixed_agent_loop_target = "external.agent.FixedAgentLoop"
    monkeypatch.setattr(agent_loop_module.hydra.utils, "get_class", lambda _: FixedAgentLoop)

    asyncio.run(worker.close())

    assert events == ["closed"]
