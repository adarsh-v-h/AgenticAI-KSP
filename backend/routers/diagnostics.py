"""
TEMPORARY hardware/environment diagnostics endpoint.

Purpose: answer "what is the underlying Catalyst AppSail hardware/OS/GPU
support" by reading it directly from inside the running container — this is
the only way to inspect Catalyst's infra since AppSail exposes no
shell/SSH access to us. Not a permanent feature.

Supervisor-only (same pattern as /api/audit-log in routers/governance.py).
Read-only: no writes, no destructive commands, short subprocess timeouts so a
missing/hanging tool can't stall the request.

DELETE THIS FILE (and its one line in main.py) once you've captured what you
need — it exposes low-sensitivity but non-zero infra detail (kernel version,
CPU model, container runtime) that has no reason to stay reachable long-term.
"""

import os
import platform
import subprocess

from fastapi import APIRouter, Depends

from auth.role_guard import require_role

router = APIRouter()


# CONTRACT
# takes:  cmd (list[str]) — command and args to run, timeout (float) — max seconds to wait
# returns: (str) — combined stdout, or a short error string if the command fails/is missing/times out
# raises:  nothing
def _run(cmd: list[str], timeout: float = 3.0) -> str:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        return out if out else (err if err else "<empty output>")
    except FileNotFoundError:
        return "<command not found>"
    except subprocess.TimeoutExpired:
        return "<timed out>"
    except Exception as e:  # noqa: BLE001 — diagnostics must never 500
        return f"<error: {e}>"


# CONTRACT
# takes:  path (str) — filesystem path to read
# returns: (str) — file contents, or a short error string if unreadable
# raises:  nothing
def _read_file(path: str, max_chars: int = 4000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)
        return content.strip() if content.strip() else "<empty>"
    except FileNotFoundError:
        return "<not present>"
    except Exception as e:  # noqa: BLE001
        return f"<error: {e}>"


# CONTRACT
# takes:  nothing
# returns: (dict) — GPU-presence signals gathered from multiple independent sources
# raises:  nothing
def _detect_gpu() -> dict:
    """
    No single reliable check works across all container setups, so this
    gathers several independent signals rather than trusting one:
      - nvidia-smi: only present if NVIDIA drivers are installed and exposed
        into the container.
      - /dev/nvidia*: device nodes exist only if the GPU is actually passed
        through to this container (drivers alone don't guarantee this).
      - /proc/driver/nvidia: kernel-level driver presence.
      - lspci: lists PCI devices INCLUDING the host's, in a container this can
        be misleading (shows host hardware even if not passed through) — kept
        as a secondary signal, not the primary one.
    """
    dev_nodes = []
    try:
        dev_nodes = [f for f in os.listdir("/dev") if "nvidia" in f.lower()]
    except Exception:
        pass

    return {
        "nvidia_smi": _run(["nvidia-smi"]),
        "dev_nvidia_nodes": dev_nodes if dev_nodes else "<none found>",
        "proc_driver_nvidia": _read_file("/proc/driver/nvidia/version"),
        "lspci_vga_3d": _run(["sh", "-c", "lspci 2>/dev/null | grep -iE 'vga|3d|display'"]),
        "note": (
            "lspci in a container often reflects the HOST's PCI devices, not "
            "what's actually passed through to this container — nvidia_smi "
            "and dev_nvidia_nodes are the more trustworthy signals for "
            "whether THIS container can actually use a GPU."
        ),
    }


@router.get("/api/diagnostics/hardware")
async def get_hardware_diagnostics(officer: dict = Depends(require_role("supervisor"))) -> dict:
    """
    Supervisor-only. Read-only inspection of the container this backend is
    actually running in: CPU, memory, OS/kernel, container runtime, and GPU
    presence signals. TEMPORARY — see module docstring.
    """
    cpu_count_logical = os.cpu_count()

    return {
        "python": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "<not reported by platform module>",
            "python_version": platform.python_version(),
        },
        "os": {
            "uname": _run(["uname", "-a"]),
            "os_release": _read_file("/etc/os-release"),
        },
        "cpu": {
            "logical_core_count": cpu_count_logical,
            "cpuinfo_summary": _run(
                ["sh", "-c", "grep -m1 'model name' /proc/cpuinfo; grep -c ^processor /proc/cpuinfo"]
            ),
            "cpuinfo_raw_head": _read_file("/proc/cpuinfo", max_chars=2000),
        },
        "memory": {
            "meminfo_summary": _run(
                ["sh", "-c", "grep -E '^(MemTotal|MemFree|MemAvailable):' /proc/meminfo"]
            ),
        },
        "container": {
            # Presence of these files/env vars indicates containerization;
            # their absence doesn't prove otherwise, but combined they're a
            # decent signal of the AppSail sandbox's nature.
            "cgroup_head": _read_file("/proc/1/cgroup", max_chars=1000),
            "dockerenv_present": os.path.exists("/.dockerenv"),
            "hostname": _run(["hostname"]),
            # Names only, NEVER values — several CATALYST_* vars hold live
            # secrets (API tokens, OAuth client secret/refresh token). We only
            # care whether Catalyst/container-related env vars are PRESENT as
            # a platform signal, not their content.
            "infra_related_env_var_names": sorted(
                k for k in os.environ
                if any(tag in k.upper() for tag in ("CATALYST", "APPSAIL", "KUBERNETES", "CONTAINER"))
            ),
        },
        "gpu": _detect_gpu(),
        "disk": {
            "df_h": _run(["df", "-h"]),
        },
    }
