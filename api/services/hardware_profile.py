#!/usr/bin/env python3
"""
Hardware profile service — host detection + profile table (LB4-U1).

Extracted verbatim from api/routers/inventory.py so pure services
(api/services/model_fit.py) can consume hardware detection without
importing from a router. The router re-exports these names, so existing
imports (`from api.routers.inventory import detect_hardware`) keep working
and behavior is pinned by the existing inventory tests.
"""

import os
import subprocess

import psutil


def _host_ram_gb() -> int:
    """Total host RAM in GB. Prefers ENCLAVE_HOST_RAM_GB (compose injects
    this from sysctl/proc) over psutil, which on Docker Desktop sees only
    the Linux VM's allocation rather than the real machine."""
    env = os.getenv("ENCLAVE_HOST_RAM_GB", "").strip()
    if env.isdigit():
        return int(env)
    return round(psutil.virtual_memory().total / (1024**3))


def _host_cpu_cores() -> int:
    """Host physical core count. Same env-var-first pattern as RAM."""
    env = os.getenv("ENCLAVE_HOST_CPU_CORES", "").strip()
    if env.isdigit():
        return int(env)
    return psutil.cpu_count() or 0


def _host_cpu_brand() -> str:
    """Host CPU brand string, injected by compose (sysctl machdep.cpu.brand_string)."""
    return os.getenv("ENCLAVE_HOST_CPU_BRAND", "").strip()


def _host_gpu() -> str:
    """Host GPU model string (e.g. "NVIDIA RTX 4000 Blackwell").

    Set by `scripts/host-preset.sh` on hosts with a discrete GPU. Empty
    string indicates CPU-only inference. The SPA surfaces this in the
    system strip so the operator can see GPU acceleration is live.
    """
    return os.getenv("ENCLAVE_HOST_GPU", "").strip()


HARDWARE_PROFILES = {
    "ms01": {
        "name": "Minisforum MS-01",
        "cpu": "Intel i9-13900H (6P+8E/20T, 5.4GHz)",
        "threads": 20,
        "ram_gb": 64,
        "max_model_ram_gb": 50,
    },
    "bd790i": {
        "name": "ASRock BD790i (Ryzen 9 7945HX)",
        "cpu": "AMD Ryzen 9 7945HX (16C/32T, 5.4GHz)",
        "threads": 32,
        "ram_gb": 96,
        "max_model_ram_gb": 80,
    },
    "mac-m4": {
        "name": "Mac M4 Pro",
        "cpu": _host_cpu_brand() or "Apple M4 Pro",
        "threads": _host_cpu_cores() or 12,
        "ram_gb": _host_ram_gb(),
        "max_model_ram_gb": round(_host_ram_gb() * 0.75),
    },
}


def detect_hardware() -> dict:
    """Auto-detect which hardware profile matches this machine.

    When running in a container, `sysctl` and /proc/cpuinfo describe
    the container kernel — useless for picking the right profile.
    The host's docker-compose entry sets ENCLAVE_HOST_CPU_BRAND /
    ENCLAVE_HOST_RAM_GB / ENCLAVE_HOST_CPU_CORES / ENCLAVE_HOST_GPU
    via scripts/host-preset.sh, so we prefer those when present and
    fall back to native detection only outside containers.
    """
    import platform

    host_cpu = os.environ.get("ENCLAVE_HOST_CPU_BRAND", "").strip()
    host_ram = os.environ.get("ENCLAVE_HOST_RAM_GB", "").strip()
    host_cores = os.environ.get("ENCLAVE_HOST_CPU_CORES", "").strip()
    host_gpu = os.environ.get("ENCLAVE_HOST_GPU", "").strip()
    host_platform = os.environ.get("ENCLAVE_HOST_PLATFORM", "").strip()

    cpu_brand = host_cpu
    if not cpu_brand:
        try:
            if platform.system() == "Darwin":
                result = subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                cpu_brand = result.stdout.strip()
            else:
                with open("/proc/cpuinfo") as f:
                    for line in f:
                        if "model name" in line:
                            cpu_brand = line.split(":")[1].strip()
                            break
        except Exception:
            cpu_brand = platform.processor() or ""
    # Final fallback so the UI never shows an empty "Detected: " label.
    if not cpu_brand:
        cpu_brand = platform.processor() or platform.machine() or "unknown CPU"

    cpu_lower = cpu_brand.lower()
    try:
        total_ram = int(host_ram) if host_ram else _host_ram_gb()
    except ValueError:
        total_ram = _host_ram_gb()
    try:
        thread_count = int(host_cores) if host_cores else _host_cpu_cores()
    except ValueError:
        thread_count = _host_cpu_cores()

    # Match known profiles — keyword scan against the CPU brand string.
    if "7945hx" in cpu_lower or "bd790i" in cpu_lower:
        profile_key = "bd790i"
    elif "13900h" in cpu_lower or ("i9" in cpu_lower and total_ram <= 64):
        profile_key = "ms01"
    elif (
        "apple" in cpu_lower
        or "m4" in cpu_lower
        or "m3" in cpu_lower
        or "m2" in cpu_lower
        or host_platform == "darwin"
    ):
        profile_key = "mac-m4"
    else:
        profile_key = "auto"

    if profile_key == "auto" or profile_key not in HARDWARE_PROFILES:
        return {
            "profile": "auto",
            "name": f"Detected: {cpu_brand}",
            "cpu": cpu_brand,
            "threads": thread_count,
            "ram_gb": total_ram,
            "max_model_ram_gb": round(total_ram * 0.75),
            "gpu": host_gpu or "",
        }

    profile = HARDWARE_PROFILES[profile_key].copy()
    profile["profile"] = profile_key
    # Override RAM + cores + GPU with detected values so the UI shows
    # the host's reality rather than a hardcoded profile sample.
    profile["ram_gb"] = total_ram
    profile["threads"] = thread_count
    # The profile's max_model_ram_gb is sized for the profile's *sample* RAM
    # (e.g. the bd790i spec assumes 96 GB). If this physical host actually has
    # less RAM than the sample, clamp so we never advertise a model budget the
    # box can't hold — otherwise the model-fit filter (size <= max_model_ram_gb)
    # would surface models that OOM. Preserves the invariant max_model <= ram.
    profile["max_model_ram_gb"] = min(
        profile["max_model_ram_gb"], round(total_ram * 0.75)
    )
    if host_gpu:
        profile["gpu"] = host_gpu
    # Make the CPU string explicit even on a matched profile.
    profile["cpu"] = cpu_brand or profile.get("cpu", "")
    return profile
