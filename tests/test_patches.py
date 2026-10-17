"""tools/patches.py: applying unified diffs exactly, and the project's series on the pinned toolkit"""

import pytest

import patches


def diff(path, body):
    return f"--- a/{path}\n+++ b/{path}\n{body}".encode()


def test_replaces_lines_and_keeps_crlf(tmp_path):
    (tmp_path / "f.c").write_bytes(b"one\r\ntwo\r\nthree\r\n")
    (tmp_path / "p.patch").write_bytes(diff("f.c", "@@ -1,3 +1,3 @@\n one\r\n-two\r\n+TWO\r\n three\r\n"))
    for path, hunks in patches.parse((tmp_path / "p.patch").read_bytes()):
        out = patches.apply_hunks((tmp_path / path).read_bytes(), hunks, path)
    assert out == b"one\r\nTWO\r\nthree\r\n"


def test_insertion_goes_after_the_named_line():
    ((path, hunks),) = patches.parse(diff("f", "@@ -1,0 +2,1 @@\n+new\n"))
    assert patches.apply_hunks(b"a\nb\n", hunks, path) == b"a\nnew\nb\n"


def test_no_newline_at_end_of_file():
    ((path, hunks),) = patches.parse(
        diff("f", "@@ -1,2 +1,2 @@\n a\n-b\n\\ No newline at end of file\n+c\n\\ No newline at end of file\n")
    )
    assert patches.apply_hunks(b"a\nb", hunks, path) == b"a\nc"


def test_moved_context_is_found_but_changed_context_fails():
    ((path, hunks),) = patches.parse(diff("f", "@@ -1,2 +1,2 @@\n x\n-y\n+Y\n"))
    assert patches.apply_hunks(b"pad\nx\ny\n", hunks, path) == b"pad\nx\nY\n"
    with pytest.raises(patches.PatchError):
        patches.apply_hunks(b"x\nz\n", hunks, path)


def test_series_are_numbered_and_described():
    for name in ("runtime", "lifter"):
        files = patches.series(name)
        assert files, name
        for n, f in enumerate(files, 1):
            assert f.name.startswith(f"{n:04d}-")
            assert f.read_bytes().startswith(b"Subject: ")


def test_lifter_series_applies(lifter_toolkit):
    lifter = (lifter_toolkit / "tools" / "recomp" / "lifter.py").read_text(encoding="utf-8")
    assert '"bp", "sp"' in lifter  # movsx from bp and sp sign-extends
    functions = (lifter_toolkit / "tools" / "disasm" / "functions.py").read_text(encoding="utf-8")
    assert "if nxt in cond_targets:" in functions and "jmp_sources" in functions
    assert (lifter_toolkit / "tools" / "recomp" / "fci_direct.py").exists()
