# Display mode

Image: default.xbe. Symbols: `XGetVideoFlags` (004F8019), `XGetVideoStandard` (004F8062),
`XGetAVPack` (004F8167), `Video_Setup` (00241880). Found 2026-10-16.

## How FCI picks 4:3 or 16:9

There is no widescreen option in the game; like other Xbox titles it follows the dashboard's
setting, which the console keeps in its EEPROM.

- `XGetVideoFlags` (XAPI, lifted) reads the EEPROM's `XC_VIDEO` setting (index 8) through
  `ExQueryNonVolatileSetting` and returns `value >> 16 & 0x5F`: 0x01 widescreen, 0x02 720p,
  0x04 1080i, 0x08 480p, 0x10 letterbox, 0x40 PAL 60 Hz. Without the HDTV AV pack
  (`XGetAVPack` == 1) the HD modes are cleared. Nothing else in the game reads index 8.
- `Video_Setup` (00241880; called from 0024147F, 00241491) fills the device's present parameters:
  - The back buffer is always 640x480 (0x280 x 0x1E0). FCI has no 720p or 1080i mode.
  - NTSC (`XGetVideoStandard` != 3, from `XC_FACTORY_AV_REGION`): with 0x01 the flags get 0x10
    (`D3DPRESENTFLAG_WIDESCREEN`) and the view's pixel aspect, `this+0x6AC`, is
    (16 / 640) / (9 / 480) = 1.333 from the constants 16.0 (0062A794) and 9.0 (0062AAE8); without
    it, (4 / 640) / (3 / 480) = 1.0. 0x08 (480p) adds 0x40 (progressive), else 0x20 (interlaced).
  - PAL takes 60 Hz from 0x40 and stays 4:3.
  So a widescreen console gets an anamorphic 640x480 buffer: the game widens its view (the
  first-person hands spread further apart; nothing is stretched) and lays its HUD out for 16:9,
  and the TV stretches the picture.

## The recomp (fci_display.c, the runtime patch video-flags, fci_xbr_glue.cpp)

The runtime's kernel answered `XC_VIDEO` with 0x03, the decoded flag values, so the game saw no
setting at all. `fci_video_flags` now stores 0x00400000 (60 Hz) plus 0x00010000 (widescreen) with
`RECOMP_FCI_ASPECT=16:9`. The host Direct3D layer takes `D3DPRESENTFLAG_WIDESCREEN` from
CreateDevice and shows the picture at 16:9, rendering the anamorphic buffer with more columns than
lines (a 1920x1080 picture renders at 3 x 2.25 of 640x480), so nothing is lost to the stretch.

The map editor's XGetVideoFlags (004A56C3) and video setup (0017ED60) do the same.

Checks (2026-10-16): with 16:9 the log shows CreateDevice flags 0x30 (widescreen, interlaced)
instead of 0x20. Captures of the intro fly-over and the Training tunnel at 1920x1080 show
unstretched palms, ship and hands, a round radar and crosshair, and the HUD at the widescreen
layout.
