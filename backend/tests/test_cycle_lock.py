"""Only one daily cycle may run on a machine: two at once slow each other and lock the database."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from tmon.tasks.cycle import lock_path, single_instance


def test_second_holder_is_refused_until_the_first_leaves(tmp_path: Path) -> None:
    lock = tmp_path / "cycle.lock"
    with single_instance(lock) as first:
        assert first
        with single_instance(lock) as second:
            assert not second
    with single_instance(lock) as again:
        assert again


def test_lock_dies_with_its_process(tmp_path: Path) -> None:
    """A cycle that was killed must not block the next one."""
    lock = tmp_path / "cycle.lock"
    code = (
        "import sys, pathlib;"
        "from tmon.tasks.cycle import single_instance;"
        "cm = single_instance(pathlib.Path(sys.argv[1]));"
        "assert cm.__enter__();"
        "print('held', flush=True);"
        "sys.stdin.read()"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(lock)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "held"
        with single_instance(lock) as during:
            assert not during
    finally:
        child.kill()
        child.wait()
    for _ in range(50):  # the system frees a dead process's lock a moment after it exits
        with single_instance(lock) as after:
            if after:
                return
        time.sleep(0.1)
    raise AssertionError("the lock of a dead process was never released")


def test_lock_file_follows_the_object_store_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMON_OBJECT_STORE_DIR", str(tmp_path))
    assert lock_path() == tmp_path / "tmon-cycle.lock"
