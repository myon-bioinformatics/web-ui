"""Parity between legacy subprocess Node helpers and vendored node_launch."""
from __future__ import annotations

import errno
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import NamedTuple, Union

import pytest

import web_ui as ui

ROOT = Path(__file__).resolve().parents[1]
_STDIN_CLOSED_PAYLOAD = "x" * 70000 + "\n"
_BINARY_STDOUT = b"\xff\xfetest"


class _FakeNodeSpec(NamedTuple):
    version: str
    on_eval: str
    close_stdin_unread: bool = False
    stdin_close_exit_code: int = 3
    stdin_close_stdout: bytes = b""
    stdout_bytes: bytes = b""


_FAKE_NODE_SPECS: dict[str, _FakeNodeSpec] = {}


def _fake_node_key(path: Union[Path, str]) -> str:
    return str(Path(path).resolve())


class _StdinClosesEarly:
    def __init__(self, pipe_byte_limit: int = 4096) -> None:
        self._limit = pipe_byte_limit
        self._written = 0

    def write(self, data: bytes) -> int:
        if self._written >= self._limit:
            raise BrokenPipeError()
        remaining = self._limit - self._written
        if len(data) > remaining:
            self._written = self._limit
            raise BrokenPipeError()
        self._written += len(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


def _run_fake_on_eval(on_eval: str) -> tuple[bytes, bytes, int]:
    from io import StringIO

    stdout = StringIO()
    stderr = StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    code = 0
    try:
        sys.stdout = stdout
        sys.stderr = stderr
        exec(on_eval, {"sys": sys})  # noqa: S102
    except SystemExit as exc:
        if exc.code is None:
            code = 0
        elif isinstance(exc.code, int):
            code = exc.code
        else:
            code = 1
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    return (
        stdout.getvalue().encode("utf-8", errors="replace"),
        stderr.getvalue().encode("utf-8", errors="replace"),
        code,
    )


class _FakeNodePopen:
    def __init__(
        self,
        command: list[str],
        on_eval: str,
        *,
        close_stdin_unread: bool = False,
        stdin_close_exit_code: int = 3,
        stdin_close_stdout: bytes = b"",
        stdout_bytes: bytes = b"",
        **_kwargs: object,
    ) -> None:
        self.args = command
        self._on_eval = on_eval
        self._close_stdin_unread = close_stdin_unread
        self._stdin_close_exit_code = stdin_close_exit_code
        self._stdin_close_stdout = stdin_close_stdout
        self._stdout_bytes = stdout_bytes
        stdout_r, stdout_w = os.pipe()
        stderr_r, stderr_w = os.pipe()
        if close_stdin_unread:
            self.stdin = _StdinClosesEarly()
            self._stdin_r = None
        else:
            stdin_r, stdin_w = os.pipe()
            self.stdin = os.fdopen(stdin_w, "wb")
            self._stdin_r = stdin_r
        self.stdout = os.fdopen(stdout_r, "rb")
        self.stderr = os.fdopen(stderr_r, "rb")
        self._stdout_w = stdout_w
        self._stderr_w = stderr_w
        self.returncode: int | None = None
        self._done = threading.Event()

        def worker() -> None:
            if self._close_stdin_unread:
                try:
                    if self._stdin_close_stdout:
                        os.write(self._stdout_w, self._stdin_close_stdout)
                    if self._stdin_close_exit_code != 0:
                        os.write(self._stderr_w, b"boom\n")
                finally:
                    os.close(self._stdout_w)
                    os.close(self._stderr_w)
                    self.returncode = self._stdin_close_exit_code
                    self._done.set()
                return

            def drain_stdin() -> None:
                try:
                    with os.fdopen(self._stdin_r, "rb") as stream:
                        while stream.read(65536):
                            pass
                except OSError:
                    pass

            threading.Thread(target=drain_stdin, daemon=True).start()
            stdout, stderr, rc = _run_fake_on_eval(self._on_eval)
            if self._stdout_bytes:
                stdout = self._stdout_bytes
            try:
                if stdout:
                    os.write(self._stdout_w, stdout)
                if stderr:
                    os.write(self._stderr_w, stderr)
            finally:
                os.close(self._stdout_w)
                os.close(self._stderr_w)
                self.returncode = rc
                self._done.set()

        threading.Thread(target=worker, daemon=True).start()

    def wait(self, timeout: float | None = None) -> int:
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.returncode if self.returncode is not None else -1

    def kill(self) -> None:
        self.returncode = -9
        self._done.set()


def _complete_fake_run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    spec = _FAKE_NODE_SPECS[_fake_node_key(argv[0])]
    proc = _FakeNodePopen(
        argv,
        spec.on_eval,
        close_stdin_unread=spec.close_stdin_unread,
        stdin_close_exit_code=spec.stdin_close_exit_code,
        stdin_close_stdout=spec.stdin_close_stdout,
        stdout_bytes=spec.stdout_bytes,
    )
    input_data = kwargs.get("input")
    if input_data is not None:
        payload = input_data.encode("utf-8") if isinstance(input_data, str) else input_data
        if proc.stdin is not None and hasattr(proc.stdin, "write"):
            try:
                proc.stdin.write(payload)
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
    timeout = kwargs.get("timeout")
    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise
    stdout = proc.stdout.read() if proc.stdout else b""
    stderr = proc.stderr.read() if proc.stderr else b""
    return subprocess.CompletedProcess(tuple(argv), rc, stdout, stderr)


@pytest.fixture(autouse=True)
def _node_launch_process_layer_stub(monkeypatch):
    node_launch = ui._node_launch_module()
    real_run = node_launch.subprocess.run
    real_popen = node_launch.subprocess.Popen

    def fake_run(args, *pargs, **kwargs):
        if args and not isinstance(args, (str, bytes)):
            argv = list(args)
        else:
            argv = [args, *pargs]
        spec = _FAKE_NODE_SPECS.get(_fake_node_key(argv[0])) if argv else None
        if spec is not None and len(argv) >= 2 and argv[1] == "--version":
            return subprocess.CompletedProcess(
                tuple(argv), 0, (spec.version + "\n").encode(), b""
            )
        if spec is not None and not (len(argv) >= 2 and argv[1] == "--version"):
            return _complete_fake_run(argv, **kwargs)
        return real_run(args, *pargs, **kwargs)

    def fake_popen(command, **kwargs):
        argv = [os.fspath(part) for part in command]
        spec = _FAKE_NODE_SPECS.get(_fake_node_key(argv[0])) if argv else None
        if spec is None:
            return real_popen(command, **kwargs)
        return _FakeNodePopen(
            argv,
            spec.on_eval,
            close_stdin_unread=spec.close_stdin_unread,
            stdin_close_exit_code=spec.stdin_close_exit_code,
            stdin_close_stdout=spec.stdin_close_stdout,
            stdout_bytes=spec.stdout_bytes,
            **kwargs,
        )

    monkeypatch.setattr(node_launch.subprocess, "run", fake_run)
    monkeypatch.setattr(node_launch.subprocess, "Popen", fake_popen)
    yield
    _FAKE_NODE_SPECS.clear()


def _write_fake_node(
    tmp_path: Path,
    *,
    version: str,
    on_eval: str = "pass",
    close_stdin_unread: bool = False,
    stdin_close_exit_code: int = 3,
    stdin_close_stdout: bytes = b"",
    stdout_bytes: bytes = b"",
) -> Path:
    name = "fake_node.exe" if os.name == "nt" else "fake_node"
    dest = tmp_path / name
    dest.write_bytes(b"")
    _FAKE_NODE_SPECS[_fake_node_key(dest)] = _FakeNodeSpec(
        version,
        on_eval,
        close_stdin_unread=close_stdin_unread,
        stdin_close_exit_code=stdin_close_exit_code,
        stdin_close_stdout=stdin_close_stdout,
        stdout_bytes=stdout_bytes,
    )
    return dest


def _legacy_run_node(
    *argv: str | Path,
    timeout: float | None = 30,
    node: str | Path | None = None,
    input: str | bytes | None = None,
) -> subprocess.CompletedProcess[str]:
    executable = os.fspath(node) if node is not None else shutil.which("node")
    if executable is None:
        raise FileNotFoundError("node executable not found on PATH")
    command = [executable, *[str(argument) for argument in argv]]
    spec = _FAKE_NODE_SPECS.get(_fake_node_key(executable))
    if spec is not None:
        proc = _complete_fake_run(command, input=input, timeout=timeout)
        return subprocess.CompletedProcess(
            proc.args,
            proc.returncode,
            proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace"),
        )
    return subprocess.run(
        command,
        input=input,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _proc_bytes(proc: subprocess.CompletedProcess) -> tuple[int, bytes, bytes]:
    stdout = proc.stdout if isinstance(proc.stdout, bytes) else proc.stdout.encode()
    stderr = proc.stderr if isinstance(proc.stderr, bytes) else proc.stderr.encode()
    return proc.returncode, stdout, stderr


def _assert_same_outcome(old_call, new_call):
    try:
        old_value = old_call()
    except BaseException as old_exc:
        try:
            new_call()
        except BaseException as new_exc:
            assert type(old_exc) is type(new_exc), (old_exc, new_exc)
            if isinstance(old_exc, FileNotFoundError):
                assert new_exc.errno == old_exc.errno
            elif isinstance(old_exc, subprocess.TimeoutExpired):
                assert new_exc.timeout == old_exc.timeout
                assert new_exc.cmd == old_exc.cmd
            else:
                assert str(old_exc) == str(new_exc), (old_exc, new_exc)
            return
        raise AssertionError(f"legacy raised {old_exc!r}, new succeeded")
    new_value = new_call()
    assert _proc_bytes(old_value) == _proc_bytes(new_value)


def test_normal_run_matches_legacy(tmp_path):
    script = _write_fake_node(
        tmp_path,
        version="v24.0.0",
        on_eval="import sys; sys.stdout.write('ok\\n')",
    )
    script_path = tmp_path / "demo.js"
    script_path.write_text("export {}", encoding="utf-8")

    def old():
        return _legacy_run_node(script_path, node=script, timeout=30)

    def new():
        return ui.run_node(script_path, node=script, timeout=30)

    _assert_same_outcome(old, new)


def test_explicit_missing_node_path_raises_file_not_found(tmp_path):
    missing = tmp_path / "definitely-not-node"
    assert not missing.exists()
    script = tmp_path / "demo.js"
    script.write_text("", encoding="utf-8")

    def old():
        return _legacy_run_node(script, node=missing, timeout=30)

    def new():
        return ui.run_node(script, node=missing, timeout=30)

    with pytest.raises(FileNotFoundError) as old_exc:
        old()
    with pytest.raises(FileNotFoundError) as new_exc:
        new()
    assert new_exc.value.errno == errno.ENOENT
    assert str(missing) in (new_exc.value.filename or "")


def test_node_not_on_path_raises_runtime_error(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)
    ui._node_launch_module().clear_probe_cache()
    script = ROOT / "tests" / "navigation.node.js"

    with pytest.raises(FileNotFoundError, match="node executable not found on PATH"):
        _legacy_run_node(script, timeout=30)
    with pytest.raises(RuntimeError, match=r"Node 24 or newer.*not found on PATH"):
        ui.run_node(script, timeout=30)


def test_node_v20_on_path_names_found_version(tmp_path, monkeypatch):
    script = _write_fake_node(tmp_path, version="v20.0.0", on_eval="pass")
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name, **kw: str(script) if name == "node" else None,
    )
    ui._node_launch_module().clear_probe_cache()
    with pytest.raises(RuntimeError, match=r"Node 24 or newer.*found Node 20"):
        ui.run_node(ROOT / "tests" / "navigation.node.js")


def test_node_v20_rejected_while_legacy_would_run(tmp_path):
    script = _write_fake_node(
        tmp_path,
        version="v20.0.0",
        on_eval="import sys; sys.stdout.write('legacy\\n')",
    )
    entry = tmp_path / "demo.js"
    entry.write_text("", encoding="utf-8")
    legacy = _legacy_run_node(entry, node=script, timeout=30)
    assert legacy.stdout == "legacy\n"
    with pytest.raises(RuntimeError, match=r"Node 24 or newer.*found Node 20"):
        ui.run_node(entry, node=script, timeout=30)


def test_nonzero_exit_preserves_stderr(tmp_path):
    script = _write_fake_node(
        tmp_path,
        version="v24.0.0",
        on_eval="import sys; sys.stderr.write('diag\\n'); sys.exit(3)",
    )
    entry = tmp_path / "demo.js"
    entry.write_text("", encoding="utf-8")

    def old():
        return _legacy_run_node(entry, node=script, timeout=30)

    def new():
        return ui.run_node(entry, node=script, timeout=30)

    _assert_same_outcome(old, new)


def test_timeout_cmd_includes_resolved_node(tmp_path, monkeypatch):
    script = _write_fake_node(tmp_path, version="v24.0.0", on_eval="import time; time.sleep(60)")
    entry = tmp_path / "demo.js"
    entry.write_text("", encoding="utf-8")
    node_launch = ui._node_launch_module()

    def hang(*args, **kwargs):
        raise node_launch.LaunchError(
            "node_launch: Node process timed out",
            code="ELAUNCHFAILURE",
            stdout=b"",
            stderr=b"",
        )

    monkeypatch.setattr(node_launch, "run", hang)
    with pytest.raises(subprocess.TimeoutExpired) as info:
        ui.run_node(entry, node=script, timeout=7)
    assert info.value.timeout == 7
    assert info.value.cmd == [str(script), str(entry)]


def test_timeout_matches_legacy(monkeypatch, tmp_path):
    script = _write_fake_node(tmp_path, version="v24.0.0", on_eval="pass")
    entry = tmp_path / "demo.js"
    entry.write_text("", encoding="utf-8")
    cmd = [str(script), str(entry)]
    timeout = 11.0
    node_launch = ui._node_launch_module()

    def launch_timeout(*args, **kwargs):
        raise node_launch.LaunchError(
            "node_launch: Node process timed out",
            code="ELAUNCHFAILURE",
            stdout=b"",
            stderr=b"",
        )

    monkeypatch.setattr(node_launch, "run", launch_timeout)

    def old():
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    def new():
        return ui._web_ui_node_run(entry, node=script, timeout=timeout, check=False)

    _assert_same_outcome(old, new)


def test_stdin_closed_nonzero_returns_legacy_stderr(tmp_path):
    script = _write_fake_node(tmp_path, version="v24.0.0", close_stdin_unread=True)
    entry = tmp_path / "demo.js"
    entry.write_text("", encoding="utf-8")

    def old():
        return _legacy_run_node(entry, input=_STDIN_CLOSED_PAYLOAD, node=script, timeout=30)

    def new():
        return ui._web_ui_node_run(
            entry, input=_STDIN_CLOSED_PAYLOAD, node=script, timeout=30, check=False
        )

    old_proc = old()
    new_proc = new()
    assert old_proc.returncode == new_proc.returncode == 3
    assert new_proc.stderr == "boom\n"


def test_stdin_closed_zero_exit_returns_stdout(tmp_path):
    script = _write_fake_node(
        tmp_path,
        version="v24.0.0",
        close_stdin_unread=True,
        stdin_close_exit_code=0,
        stdin_close_stdout=b"done\n",
    )
    entry = tmp_path / "demo.js"
    entry.write_text("", encoding="utf-8")

    def old():
        return _legacy_run_node(entry, input=_STDIN_CLOSED_PAYLOAD, node=script, timeout=30)

    def new():
        return ui._web_ui_node_run(
            entry, input=_STDIN_CLOSED_PAYLOAD, node=script, timeout=30, check=False
        )

    _assert_same_outcome(old, new)


def test_bytes_stdout_preserved(tmp_path):
    script = _write_fake_node(
        tmp_path,
        version="v24.0.0",
        on_eval="pass",
        stdout_bytes=_BINARY_STDOUT,
    )
    entry = tmp_path / "demo.js"
    entry.write_text("", encoding="utf-8")
    node_launch = ui._node_launch_module()
    raw = node_launch.run(entry, node=script, timeout=30, check=False)
    assert raw.stdout == _BINARY_STDOUT
    done = ui.run_node(entry, node=script, timeout=30)
    assert done.stdout == _BINARY_STDOUT.decode("utf-8", errors="replace")


def test_run_node_without_argv_matches_legacy_bare_node(tmp_path):
    script = _write_fake_node(
        tmp_path,
        version="v24.0.0",
        on_eval="import sys; sys.stdout.write('bare\\n')",
    )

    def old():
        return _legacy_run_node(node=script, timeout=30)

    def new():
        return ui.run_node(node=script, timeout=30)

    _assert_same_outcome(old, new)
