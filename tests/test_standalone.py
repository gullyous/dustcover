"""Runs each battle-tested standalone suite in its own subprocess.

Every script owns a QApplication and monkeypatches module state, so isolation
per-process is the correct execution model (and mirrors how they were written).
A script passes when it exits 0; its full output is shown on failure.
"""

import glob
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = sorted(glob.glob(os.path.join(HERE, "standalone", "test_*.py")))


@pytest.mark.parametrize("script", SCRIPTS,
                         ids=[os.path.basename(s) for s in SCRIPTS])
def test_standalone(script):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([sys.executable, script], capture_output=True,
                       text=True, env=env, timeout=300)
    assert r.returncode == 0, (
        f"\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}")
