# Reverse-engineering layer

What we learn about the original game's code, kept so it can be found and reused: names for
functions, globals and structure fields, and notes on how systems work. It sits on top of the
recompilation; nothing here changes the recompiled code itself.

## What may live here

Facts about the binary: addresses, names, sizes, field offsets, calling conventions, and prose
describing behaviour, with the evidence that established them. Not the game's code or data:
no disassembly listings, no decompiled pseudocode copied out of the game, no assets. Short
instruction references in evidence ("`call 005C5988` at 001F6DE4") are fine.

## Layout

| Path | Contents |
|---|---|
| `symbols/<image>.json` | per image (`default.xbe`, the game; `ige.xbe`, the map editor): functions, globals, structs; bound to the image's SHA-256 |
| `notes/<SYSTEM>.md` | how a system works (input, camera, movies, ...), linking symbols by name |
| `../tools/re_db.py` | validate, look up, generate |

## Entries

```json
{"va": "0x001F6C00", "name": "Input_PollPads", "kind": "function",
 "confidence": "likely", "evidence": "calls XInputGetState (005C5988) for each of 4 ports ...",
 "notes": "optional", "see": "notes/INPUT-CAMERA.md"}
```

- `kind`: `function`, `global`, `vtable`, `string`.
- `confidence`:
  - `verified`: shown by behaviour (a hook that changes what the name says, a trace, a data watch);
  - `likely`: read from the code, consistent with everything seen, not exercised;
  - `guess`: a working label.
  Names are hypotheses until verified; say what would confirm one in `notes`.
- `evidence`: what established it. Required.
- Names: `System_Action` for functions (`Camera_BuildViews`), `g_` for globals, `Type` for structs.
  Unknown parts stay neutral; an unnamed function stays `sub_<va>`.

Structs: `"structs": {"InputManager": {"size": "0x460", "confidence": ..., "evidence": ..., "fields":
[{"offset": "0x20C", "name": "rightX", "type": "float[4]", "confidence": ..., "evidence": ...}]}}`.

XDK library functions come from the signature matcher (`tools/sigmatch.py`, whose header the game
build writes) and the hand-verified pins (`data/default.pins.json`); `tools/re_db.py` merges them as
kind `library`, so they are not repeated here.

## Tools

```
python -B tools/re_db.py check              validate every file; generated files up to date
python -B tools/re_db.py find <va|name>      one entry (accepts sub_XXXXXXXX)
python -B tools/re_db.py list [image]        everything for an image, by address
python -B tools/re_db.py gen                 write src/re_names.c and src/re_symbols.h
```

`re_names.c` puts the names on the recompiled code's diagnostics: stops, profiles, data watches
and host call chains print `sub_001F6C00 (Input_PollPads)`. `re_symbols.h` gives host code
(hooks, input) named addresses, `RE_GAME_<NAME>`, for `verified` and `likely` entries only.

## Finding things

The diagnostics that found what is here:
`RECOMP_FCI_MEMDUMP` (guest RAM at given times; compare dumps around an action),
`RECOMP_FCI_DATA_WATCH` (`*<global>+<offset>` follows a pointer; `_RW=1` catches reads), probes and
the CPU oracle (`tools/oracle.py`), and the disassembly listings of your own lift
(`build/lift/default/disasm`).
