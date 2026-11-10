"""vLLM worker for Player-1 RL rollouts."""

from pathlib import Path
from tempfile import TemporaryDirectory

from vllm.v1.worker.gpu_worker import Worker


class PlayerOneVLLMWorker(Worker):
    def init_device(self):
        # A single-rank replica needs no TCP rendezvous. The upstream mp
        # executor releases its probed port before spawning this worker, so
        # another socket can claim it. Keep a unique FileStore directory alive
        # for the lifetime of the process groups instead.
        if self.parallel_config.world_size_across_dp == 1:
            self._rendezvous_directory = TemporaryDirectory(prefix="player1-vllm-rendezvous-")
            self.distributed_init_method = (Path(self._rendezvous_directory.name) / "store").as_uri()
        return super().init_device()
