# Movies

Image: default.xbe. Symbols: `Movie_Play` (00220200), `Boot_PlayLogos` (001FD760), `sprintf`
(004EAAFB), `g_strDataRoot` (00644524).

## Playing a movie

`Movie_Play` (cdecl, first argument a path) plays a Bink file from start to end and returns; while
it runs it polls the controllers (`Input_PollPads`). Callers build the path first:
`sprintf(buffer, "%s%s", g_strDataRoot, "Videos\\<name>.bik")`.

| Movie | Played by | Length on this build |
|---|---|---|
| `Ubisoft.bik`, `Crytek.bik` | `Boot_PlayLogos` | to about 5 s and 17 s after start |
| `Intro_FCI.bik` | 00048F57 (startup, after the logos) | to about 31 s |
| `StartMenu_boat.bik` | the title screen's background (not through `Movie_Play` at this point) | loops |

Pressing A or Start does not end the logos or the intro (presses every second from 3 s did not
change when each movie opened).

## Skipping (RECOMP_FCI_SKIP_INTROS, RECOMP_FCI_SKIP_MOVIES)

`Movie_Play` is gated (tools/compile.py `REPLACE`, kind `gate`; `fci_gate_00220200` in
src/fci_disk.c): a listed movie returns at once with eax 0 (callers ignore the result),
and the title goes on as if it had played. With the three startup movies skipped the title screen
is up 8 s after start instead of about 31 s.

Tried first and dropped: failing the movie's file open (path redirected to a missing file). The
title then waited for good after the failed open of `Ubisoft.bik`.
