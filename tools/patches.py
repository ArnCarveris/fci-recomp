"""Apply this project's patch series (patches/<series>/*.patch) to a copy of the xboxrecomp toolkit.

  python -B tools/patches.py <series> <toolkit copy>     apply runtime or lifter patches in place

The patches are unified diffs, applied in file name order. Each hunk must match exactly (line endings
included), so a patch that no longer fits the pinned toolkit fails loudly instead of fuzzing. The same
files apply with `git apply` to an xboxrecomp checkout at the pinned commit.
"""

from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[1]
PATCHES = REPO / "patches"
HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(Exception):
    pass


def series(name):
    return sorted((PATCHES / name).glob("*.patch"))


def parse(data):
    """[(path, [(old_start, old_lines, new_lines)])]; lines keep their endings"""
    files, lines, i = [], data.splitlines(keepends=True), 0
    while i < len(lines):
        if not lines[i].startswith(b"--- ") or i + 1 >= len(lines) or not lines[i + 1].startswith(b"+++ "):
            i += 1
            continue
        path = lines[i + 1][4:].rstrip(b"\r\n").decode()
        path = path[2:] if path.startswith("b/") else path
        hunks, i = [], i + 2
        while i < len(lines) and lines[i].startswith(b"@@"):
            m = HUNK.match(lines[i])
            if not m:
                raise PatchError(f"malformed hunk header in {path}")
            old_count = int(m.group(2) or 1)
            new_count = int(m.group(4) or 1)
            old, new, i = [], [], i + 1
            while (len(old) < old_count or len(new) < new_count) and i < len(lines):
                tag, text = lines[i][:1], lines[i][1:]
                if tag in (b" ", b"-"):
                    old.append(text)
                if tag in (b" ", b"+"):
                    new.append(text)
                if tag not in (b" ", b"-", b"+"):
                    raise PatchError(f"unexpected line in a hunk of {path}: {lines[i][:40]!r}")
                i += 1
                if i < len(lines) and lines[i].startswith(b"\\"):  # no newline at end of file
                    for side in (old,) if tag == b"-" else (new,) if tag == b"+" else (old, new):
                        side[-1] = side[-1].rstrip(b"\r\n")
                    i += 1
            hunks.append((int(m.group(1)), old, new))
        files.append((path, hunks))
    if not files:
        raise PatchError("no file changes found")
    return files


def apply_hunks(text, hunks, name):
    lines, offset = text.splitlines(keepends=True), 0
    for start, old, new in hunks:
        start = start if not old else start - 1  # an insertion's header names the line before it
        at = start + offset
        if lines[at : at + len(old)] != old:  # tolerate moved code, never changed code
            found = [k for k in range(len(lines) - len(old) + 1) if lines[k : k + len(old)] == old]
            if len(found) != 1:
                raise PatchError(f"{name}: hunk at line {start + 1} does not match")
            at = found[0]
        lines[at : at + len(old)] = new
        offset = at - start + len(new) - len(old)
    return b"".join(lines)


def apply_series(name, root):
    """apply every patch of the series to the toolkit copy at root; returns the patch file names"""
    root, applied = Path(root), []
    for patch in series(name):
        for path, hunks in parse(patch.read_bytes()):
            target = root / path
            before = target.read_bytes() if target.exists() else b""
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(apply_hunks(before, hunks, f"{patch.name}: {path}"))
        applied.append(patch.name)
    return applied


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    try:
        print("\n".join(apply_series(sys.argv[1], sys.argv[2])))
    except PatchError as e:
        raise SystemExit(f"error: {e}")
