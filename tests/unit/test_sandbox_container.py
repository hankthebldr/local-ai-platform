import shutil
import subprocess
import pytest
from api.services.sandbox import CodeExecSpec
from api.services.sandbox_impl.container import ContainerSandbox


def test_build_cmd_is_hardened():
    sb = ContainerSandbox(runtime="podman", image="enclave-sandbox:latest")
    spec = CodeExecSpec(
        language="python", code="print(1)", scratch_path="/tmp/s", network="none"
    )
    cmd = sb._build_cmd(spec, "/abs/scratch")
    j = " ".join(cmd)
    for flag in [
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=256",
        "--user",
    ]:
        assert flag in j
    assert "-v /abs/scratch:/work:rw" in j and j.endswith("/work/__entry__.py")
    assert (
        sb.capabilities().isolation_tier == 2 and sb.capabilities().can_auto_run is True
    )


def test_allowlist_is_denied_in_v1():
    sb = ContainerSandbox(runtime="podman", image="enclave-sandbox:latest")
    spec = CodeExecSpec(
        language="python", code="print(1)", scratch_path="/tmp/s", network="allowlist"
    )
    cmd = sb._build_cmd(spec, "/abs/scratch")
    assert "--network=none" in cmd and "--network=bridge" not in " ".join(cmd)
    assert sb.capabilities().network_modes == ("none",)


RUNTIME = shutil.which("podman") or shutil.which("docker")


def _image_present(runtime, image="enclave-sandbox:latest"):
    """True only if the sandbox image is already built locally. The image is
    local-only (never published), so without this guard the test reaches for a
    registry and fails — e.g. CI has a runtime (podman) but not the image."""
    if not runtime:
        return False
    try:
        return (
            subprocess.run(
                [runtime, "image", "inspect", image], capture_output=True
            ).returncode
            == 0
        )
    except Exception:
        return False


IMAGE_PRESENT = _image_present(RUNTIME)


@pytest.mark.skipif(
    not (RUNTIME and IMAGE_PRESENT),
    reason="container runtime or enclave-sandbox image not available",
)
def test_container_runs_when_image_present(tmp_path):
    sb = ContainerSandbox(runtime=RUNTIME)
    res = sb.execute(
        CodeExecSpec(
            language="python", code="print('in-container')", scratch_path=str(tmp_path)
        )
    )
    if res.exit_code != 0 and (
        "Unable to find image" in res.stderr
        or "Cannot connect to" in res.stderr
        or "connect: no such file" in res.stderr
        or "docker: command not found" in res.stderr
    ):
        pytest.skip("container daemon not running or image not built")
    assert "in-container" in res.stdout and res.tier_used == 2


def test_build_cmd_cidfile_optional():
    sb = ContainerSandbox(runtime="podman", image="enclave-sandbox:latest")
    spec = CodeExecSpec(language="python", code="print(1)", scratch_path="/tmp/s")
    with_cid = sb._build_cmd(spec, "/abs/scratch", cidfile="/x/.cid")
    assert "--cidfile" in with_cid and "/x/.cid" in with_cid
    without = sb._build_cmd(spec, "/abs/scratch")
    assert "--cidfile" not in without
