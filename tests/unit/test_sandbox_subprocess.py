import os
import pytest
from api.services.sandbox import CodeExecSpec
from api.services.sandbox_impl.subprocess import SubprocessSandbox


def _spec(code, tmp, **kw):
    return CodeExecSpec(language="python", code=code, scratch_path=str(tmp), **kw)


def test_happy_path(tmp_path):
    res = SubprocessSandbox().execute(_spec("print('hi')", tmp_path))
    assert res.exit_code == 0 and "hi" in res.stdout and res.tier_used == 1


def test_timeout_kills(tmp_path):
    res = SubprocessSandbox().execute(
        _spec("import time; time.sleep(30)", tmp_path, timeout_s=1)
    )
    assert res.exit_code != 0 and "timeout" in " ".join(res.violations).lower()


def test_env_is_scrubbed(tmp_path):
    os.environ["ENCLAVE_SECRET"] = "leak-me"
    try:
        res = SubprocessSandbox().execute(
            _spec(
                "import os; print(os.environ.get('ENCLAVE_SECRET', 'ABSENT'))", tmp_path
            )
        )
    finally:
        del os.environ["ENCLAVE_SECRET"]
    assert "ABSENT" in res.stdout and "leak-me" not in res.stdout


def test_captures_produced_files(tmp_path):
    res = SubprocessSandbox().execute(
        _spec("open('out.txt','w').write('done')", tmp_path, files_out=["out.txt"])
    )
    assert "out.txt" in res.files_produced
