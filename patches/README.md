# Patches to xboxrecomp

This project's changes to [xboxrecomp](https://github.com/sp00nznet/xboxrecomp) at the pinned commit
(`tools/deps.py`), applied in file name order to a copy of the toolkit during the build:

- `lifter/`: the lifter (`tools/`, `templates/`), applied before the game's code is translated.
  `fci_direct.py` is copied in beside the translator.
- `runtime/`: the Xbox runtime (`src/`), applied before it is compiled.

Each patch starts with a description of the change and why it is needed. `tools/patches.py` applies them
without needing git, and requires every hunk to match exactly; they also apply with `git apply` to an
xboxrecomp checkout at the pinned commit:

```
git -c core.autocrlf=false apply path/to/patches/runtime/*.patch
```

Git leaves the patch files byte for byte as committed (`.gitattributes`), since every line must match
the toolkit's. To change a patch, edit the patched file in a checkout and regenerate the diff, keeping one
topic per patch.

## Licences

The patches are licensed like the files they change. xboxrecomp is MIT except for the files it took
from [xemu](https://xemu.app), which are LGPL-2.1-or-later (its `NOTICE` lists them: `src/apu/apu_core.c`,
`apu_dsp.c`, `apu_vp.c` and their headers, and `src/nv2a/nv2a_regs.h`). The hunks of
`runtime/0005-guest-cpu-interrupts.patch`, `runtime/0010-physical-addresses.patch` and
`runtime/0013-audio.patch` that change those files are LGPL-2.1-or-later; everything else here is MIT,
like the rest of this repository.
