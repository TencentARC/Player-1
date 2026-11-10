# Training

Default model: **Qwen/Qwen3.5-9B**. Prepare [SFT data](DATA.md) and Gym training rows before launching. Run from the repository root.

---

## Install

Use Linux x86_64, Python 3.12, the CUDA 12.8 development toolkit (`nvcc` and a C++ compiler), and Chromium system libraries:

```bash
conda create -n verl -c conda-forge --override-channels python=3.12 pip -y
CUDA_HOME=/usr/local/cuda conda run -n verl bash scripts/training/install.sh
```

The installer uses the [training lock](../requirements/training-cu128-py312.lock) and installs Chromium. Configure GPU count, FSDP, and vLLM capacity for your hardware; the commands below select eight GPUs.

---

## SFT

```bash
PLAYER1_DATASET_ROOT=/path/to/Player-1-Data PLAYER1_NPROC_PER_NODE=8 \
  conda run --no-capture-output -n verl bash scripts/training/run_sft.sh \
  trainer.n_gpus_per_node=8
```

Output defaults to `outputs/training/sft`. Training completion exports the latest checkpoint, including tokenizer and processor, to `global_step_<N>/exported-model/`.

---

## RL

Provide `outputs/training/data/train.parquet`, or set `data.train_files=/path/to/train.parquet`. See the standalone [Gym row preparation example](../examples/training/prepare.py).

```bash
conda run --no-capture-output -n verl bash scripts/training/run_rl.sh \
  trainer.n_gpus_per_node=8 actor_rollout_ref.rollout.tensor_model_parallel_size=2
```

RL resolves model paths after applying Hydra overrides. `PLAYER1_MODEL_PATH` sets
the actor and critic defaults. Required paths left unset use the SFT checkpoint
selected by `PLAYER1_SFT_OUTPUT` (default `outputs/training/sft`), whose export is
refreshed when native model weights change. Output defaults to `outputs/training/run`.

PPO is the default; set `PLAYER1_ALGORITHM=grpo` or `gspo` to switch. Both scripts accept `PLAYER1_OUTPUT`, `PLAYER1_BATCH_SIZE`, `PLAYER1_TRAIN_STEPS`, and native Hydra overrides. Edit [rl.py](../examples/training/rl.py), [environments.json](../examples/training/environments.json), and [randomization.json](../examples/training/randomization.json) for the full recipe. RL requires screenshot observations.

---

## One-step check

With prepared SFT and Gym data, use a small model on one GPU:

```bash
PLAYER1_DATASET_ROOT=/path/to/Player-1-Data-smoke \
PLAYER1_MODEL_PATH=Qwen/Qwen3.5-2B PLAYER1_NPROC_PER_NODE=1 \
PLAYER1_BATCH_SIZE=2 PLAYER1_TRAIN_STEPS=1 PLAYER1_OUTPUT=outputs/training/sft-smoke \
  conda run --no-capture-output -n verl bash scripts/training/run_sft.sh \
  trainer.save_freq=1 ++data.sampling.uniform_fraction=1.0

PLAYER1_SFT_OUTPUT=outputs/training/sft-smoke PLAYER1_OUTPUT=outputs/training/rl-smoke \
PLAYER1_TRAIN_STEPS=1 PLAYER1_MAX_ENV_STEPS=2 \
  conda run --no-capture-output -n verl bash scripts/training/run_rl.sh trainer.save_freq=1
```

This check samples uniformly from the subset; full SFT uses action balancing. The SFT → RL save/export path was verified on one H20-3e with Qwen3.5-2B.

---

## Checkpoints and SFT-to-RL

Native checkpoints retain model, optimizer, scheduler, RNG, and dataloader state. SFT saves under `global_step_<N>/`; RL saves `actor/` and PPO `critic/` there. `trainer.resume_mode=auto` resumes the latest save. Keep the SFT data and training configuration unchanged for resume.

Export an RL actor for [inference](MODELS.md) or [evaluation](EVALUATION.md):

```bash
PYTHONPATH=.:./verl conda run -n verl python -m verl.model_merger merge \
  --backend fsdp --local_dir outputs/training/run/global_step_100/actor \
  --target_dir outputs/training/rl-model
```
