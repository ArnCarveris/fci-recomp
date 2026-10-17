"""Shared fixtures. Tests that need the toolkit or a compiler are skipped when there is none.

FCI_TOOLKIT    an xboxrecomp checkout at the pinned commit (default: build/deps/xboxrecomp, which
               BuildGame.cmd or tools/deps.py fetches)
"""

import os
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))


@pytest.fixture(scope="session")
def lifter_toolkit(tmp_path_factory):
    """a copy of the toolkit with the lifter patches, importable as `tools.recomp`"""
    import lift

    source = Path(os.environ.get("FCI_TOOLKIT", REPO / "build" / "deps" / "xboxrecomp"))
    if not (source / "tools" / "recomp").is_dir():
        pytest.skip(f"no xboxrecomp toolkit at {source} (set FCI_TOOLKIT or run tools/deps.py build/deps)")
    dst = tmp_path_factory.mktemp("toolkit") / "xboxrecomp"
    lift.prepare_toolkit(source, dst)
    sys.path.insert(0, str(dst))
    return dst


@pytest.fixture(scope="session")
def msvc():
    """the toolchain description from tools/toolchain.py (Visual Studio, or build/toolchain)"""
    import toolchain

    try:
        return toolchain.discover(REPO / "build" / "toolchain")
    except toolchain.ToolchainError as e:
        pytest.skip(str(e))
