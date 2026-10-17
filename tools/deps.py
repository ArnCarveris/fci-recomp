"""Fetch the two upstream projects the build uses, at the commits this project is tested with.

  python -B tools/deps.py <dir>                fetch into <dir>/<name> (skips one already there and verified)
  python -B tools/deps.py <dir> --from <path>  clone from local checkouts in <path>/<name> instead (offline)

  xboxrecomp      sp00nz's recompiler toolkit and runtime: the lifter, the Xbox kernel, devices
  xbe-recomp      TGP482's Xbox XBE Recomp: its XDK 5849 signature list (the D3D and DirectSound
                  layer it also provides is vendored in src/xbr)

Each is checked against a digest of its files (SHA-256 over every path and file content, as stored in
git), so a zip download and a git clone are verified the same way. With git on the PATH the tool
clones; otherwise it downloads GitHub's zip of the commit. Line endings are kept as stored: the
lifter fixes and runtime patches match the files byte for byte.
"""

import argparse
import hashlib
import io
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

DEPS = {
    "xboxrecomp": {
        "repo": "sp00nznet/xboxrecomp",
        "commit": "193e2995ffaec871bb3be43a43bd66aa5fccfeb1",  # v0.13.1
        "digest": "313cdb5fa5ca42110a99511fdd930fc4d41c901f1c1cdfcaf351aee48155b8e8",
    },
    "xbe-recomp": {
        "repo": "TGP482/Xbox-XBERecomp",
        "commit": "65e959d4a5fd0c171dc7b17f3f9b44bab00928e6",
        "digest": "25ab7d19cf05f2a981cf535e60c8a2e2654163111fb7d56239dc4533bbd9d1fc",
    },
}


def tree_digest(root):
    """SHA-256 over the sorted relative paths and contents of every file under root, .git excluded"""
    h = hashlib.sha256()
    files = sorted(p for p in Path(root).rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts)
    for p in files:
        h.update(p.relative_to(root).as_posix().encode() + b"\0")
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def git_fetch(source, commit, dst):
    run = lambda *a: subprocess.run(["git", "-c", "core.autocrlf=false", *a], check=True, capture_output=True)  # noqa: E731
    run("clone", "--quiet", "--no-checkout", source, str(dst))
    run("-C", str(dst), "checkout", "--quiet", "--detach", commit)


def zip_fetch(repo, commit, dst):
    url = f"https://codeload.github.com/{repo}/zip/{commit}"
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        top = z.namelist()[0].split("/")[0]  # <repo>-<commit>/
        z.extractall(dst.parent / "_unpack")
    shutil.move(str(dst.parent / "_unpack" / top), str(dst))
    shutil.rmtree(dst.parent / "_unpack")


def fetch(name, root, local=None):
    dep = DEPS[name]
    dst = Path(root) / name
    if dst.exists():
        if tree_digest(dst) == dep["digest"]:
            print(f"{name}: present, verified")
            return dst
        raise SystemExit(f"error: {dst} exists but does not match {name} at {dep['commit'][:8]}; move it aside")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if local:
        git_fetch(str(Path(local) / name), dep["commit"], dst)
    elif shutil.which("git"):
        git_fetch(f"https://github.com/{dep['repo']}.git", dep["commit"], dst)
    else:
        zip_fetch(dep["repo"], dep["commit"], dst)
    got = tree_digest(dst)
    if got != dep["digest"]:
        raise SystemExit(f"error: {name} at {dep['commit'][:8]} does not match its digest ({got}); not using it")
    print(f"{name}: fetched {dep['commit'][:8]}, verified")
    return dst


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dir")
    ap.add_argument("--from", dest="local", help="a folder with local checkouts named like the dependencies")
    a = ap.parse_args()
    for name in DEPS:
        fetch(name, a.dir, a.local)


if __name__ == "__main__":
    sys.exit(main())
