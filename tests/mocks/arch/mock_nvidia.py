"""Mock fixtures for NVIDIA architectures (single + multi).

Patches pynvml calls so tests can simulate any GPU topology without
requiring NVIDIA hardware.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from unittest.mock import patch


@dataclass
class _MockGPU:
    name: str = "NVIDIA H100 80GB HBM3"
    vram_total_gb: float = 80.0
    vram_free_gb: float = 80.0
    pcie_gen: int = 4
    compute_capability: Tuple[int, int] = (9, 0)
    mig_mode: bool = False


@dataclass
class _MockState:
    gpus: List[_MockGPU] = field(default_factory=list)
    nvlink_pairs: List[Tuple[int, int]] = field(default_factory=list)
    driver_version: str = "535.129.03"
    cuda_runtime_version: str = "12.2"


def _build_nvml_mocks(state: _MockState):
    """Build dicts of patches for pynvml functions."""
    gpu_count = len(state.gpus)

    def fake_init():
        return None

    def fake_shutdown():
        return None

    def fake_device_count():
        return gpu_count

    def fake_get_handle(i):
        if i >= gpu_count:
            import pynvml

            raise pynvml.NVMLError(pynvml.NVML_ERROR_INVALID_ARGUMENT)
        return i  # handle == index in our mock

    def fake_get_name(handle):
        return state.gpus[handle].name

    def fake_get_memory_info(handle):
        gpu = state.gpus[handle]

        class MemInfo:
            total = int(gpu.vram_total_gb * 1024**3)
            free = int(gpu.vram_free_gb * 1024**3)
            used = total - free

        return MemInfo()

    def fake_get_pcie_gen(handle):
        return state.gpus[handle].pcie_gen

    def fake_get_compute_capability(handle):
        return state.gpus[handle].compute_capability

    def fake_get_driver_version():
        return state.driver_version.encode()

    def fake_get_nvlink_state(handle, link):
        # Return True if (handle, peer_for_this_link) in nvlink_pairs
        for a, b in state.nvlink_pairs:
            if handle in (a, b):
                return 1  # NVML_FEATURE_ENABLED
        return 0

    return {
        "nvmlInit": fake_init,
        "nvmlShutdown": fake_shutdown,
        "nvmlDeviceGetCount": fake_device_count,
        "nvmlDeviceGetHandleByIndex": fake_get_handle,
        "nvmlDeviceGetName": fake_get_name,
        "nvmlDeviceGetMemoryInfo": fake_get_memory_info,
        "nvmlDeviceGetCurrPcieLinkGeneration": fake_get_pcie_gen,
        "nvmlDeviceGetCudaComputeCapability": fake_get_compute_capability,
        "nvmlSystemGetDriverVersion": fake_get_driver_version,
        "nvmlDeviceGetNvLinkState": fake_get_nvlink_state,
    }


@contextlib.contextmanager
def patch_nvidia_single(
    vram_gb: float = 80.0,
    name: str = "NVIDIA A100 80GB",
    pcie_gen: int = 4,
):
    """Pretend we have exactly one NVIDIA GPU."""
    state = _MockState(
        gpus=[
            _MockGPU(
                name=name,
                vram_total_gb=vram_gb,
                vram_free_gb=vram_gb,
                pcie_gen=pcie_gen,
            )
        ]
    )
    mocks = _build_nvml_mocks(state)
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch("sys.platform", "linux"))
        for fname, fn in mocks.items():
            stack.enter_context(patch(f"pynvml.{fname}", side_effect=fn))
        yield state


@contextlib.contextmanager
def patch_nvidia_multi(
    gpus: Optional[List[dict]] = None,
    nvlink_pairs: Optional[List[Tuple[int, int]]] = None,
):
    """Pretend we have N>1 NVIDIA GPUs.

    Example:
        patch_nvidia_multi(
            gpus=[{"vram_gb": 80.0, "name": "H100"}, {"vram_gb": 80.0, "name": "H100"}],
            nvlink_pairs=[(0, 1)],
        )
    """
    if gpus is None:
        gpus = [{"vram_gb": 80.0}, {"vram_gb": 80.0}]
    mock_gpus = [
        _MockGPU(
            name=g.get("name", "NVIDIA H100"),
            vram_total_gb=g.get("vram_gb", 80.0),
            vram_free_gb=g.get("vram_free_gb", g.get("vram_gb", 80.0)),
            pcie_gen=g.get("pcie_gen", 4),
        )
        for g in gpus
    ]
    state = _MockState(gpus=mock_gpus, nvlink_pairs=nvlink_pairs or [])
    mocks = _build_nvml_mocks(state)
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch("sys.platform", "linux"))
        for fname, fn in mocks.items():
            stack.enter_context(patch(f"pynvml.{fname}", side_effect=fn))
        yield state
