# Player-1 integration patches

This source tree is based on official verl **v0.9.0**, commit
`483b8a009ba3a97563edee3a19887e4862b8094a` from
[verl-project/verl](https://github.com/verl-project/verl/tree/483b8a009ba3a97563edee3a19887e4862b8094a).
Upstream licenses and notices are retained. Player-1 integrations use the outer
`player1/training` package and official extension points where available.

| ID | Included behavior | Principal owner within `verl/` | Purpose |
| --- | --- | --- | --- |
| VERL-001 | Explicit per-output rewards, turn-expanded optimizer batch accounting, critic training token budget and empty-output errors | `trainer/ppo/v1/agent_loop_tq.py`, `trainer/ppo/v1/trainer_base.py` | Exact-context training integration |
| VERL-003 | Post-GAE normalization and episode-metric hooks | `trainer/ppo/v1/trainer_base.py` | Apply the paper's per-environment advantage normalization in the outer package and report training metrics |
| VERL-004 | Multimodal cache resets and port reservation release before binding | `workers/rollout/vllm_rollout/vllm_async_server.py` | Visual runtime compatibility |
| VERL-006 | Fixed AgentLoop class target, synchronous worker completion and worker cleanup | `experimental/agent_loop/agent_loop.py`, `trainer/ppo/v1/agent_loop_tq.py` | Player-1 worker integration |
| VERL-007 | Multimodal jagged mRoPE batch slicing and reconstruction | `utils/tensordict_utils.py` | Visual batch correctness |
| VERL-010 | Per-sequence state isolation for Qwen3.5 packed torch-fallback kernels | `models/transformers/qwen3_5.py` | Packed model correctness |

Six runtime files differ from the fixed upstream commit; several serve multiple
groups. Review their behavior together when refreshing upstream. PPO/GAE,
GRPO/GSPO and actor/critic loss implementations are unchanged from upstream.
The Player-1 PPO example applies per-environment advantage normalization after
native GAE and uses native `seq-mean-token-mean` loss reduction for both actor
and critic. Base Qwen3.5 support and global critic loss normalization are also
upstream capabilities. Native validation,
critic-warmup scheduling and tracking implementations are retained.
The SFT example uses the native SFT engine, with Player-1 data, sampling and
checkpoint identity handling in the outer package.

Focused regression coverage is under `tests/trainer`, `tests/workers`,
`tests/experimental/agent_loop` and `tests/test_protocol_v2_on_cpu.py` in this
vendor tree. Player-1 episode, reward, masking, history and SFT data regression
tests are maintained locally.

The Player-1 examples use synchronous FSDP, with vLLM for RL rollout generation.
Other upstream engines remain bundled capabilities and require their own
dependencies and validation. Full-model numerical equivalence, MoE and
multi-node behavior need separate validation beyond focused unit tests.
