# 18 · The modern build

Every game project has two builds of one source. The **release** build is
the retail game, scored byte for byte; the **modern** build is the same
source with `<PROJECT>_MODERN` defined (`NOLFSRC_MODERN`,
`NOLF2SRC_MODERN`, `CJACK_MODERN`, `AVP2SRC_MODERN`, `TRON20_MODERN`):
widescreen, window modes, high frame rates, controllers, open-source
middleware, and the fixes for the bugs in `RETAIL_BUGS.md`. Each project's
`docs/MODERN.md` is its inventory, with an id per item. This guide is what
carries from one game to the next: the rules, and the techniques that
turned out to be the same problem in each engine.

Item ids below are each repo's own: nolfsrc `M-P<n>-<nn>`, nolf2src
`M-E` (engine), `M-G` (game), `M-L` (launcher), `M-X` (middleware),
cjacksrc `EN-`, `CL-`, `APPS-`, `X-`.

## Never change what the release build compiles

The rule is the README's: retail behaviour is the target, bugs included,
and a fix goes behind `#ifdef <PROJECT>_MODERN` with the retail code kept
unchanged in the `#else`. Two things make it harder than it sounds.

**A skipped `#ifdef` block can still change the release binary.** VC6 is
not blind to the lines it skips: the blocks five work packages added to
nolfsrc's `GameClientShell.cpp` reordered two out-of-line inline
functions in the release `CShell.dll` with every release token unchanged,
and `#line` directives restoring the retail line numbers did not help
(tools e660460). So the release build doesn't compile `src/`: it compiles
`out/release-tree/`, a mirror with every variant block resolved and its
directives removed (`tools/releasesrc.py`). That only works if **nothing
is added outside a block, not even a blank line**; `releasesrc.py diff`
lists exactly those lines and must be empty (nolf2src `docs/MODERN.md`,
"Release unchanged"). The same commit found the game DLLs also depended on
the length of the checkout's path, and fixed it by compiling from a drive
letter of their own.

**Game code is matched by others.** A modern change in `src/Game/` is
only ever inside a block, and new members of a class go in a block of
their own (nolf2src `docs/MODERN.md`, "Rules").

After every change: `make` and `make progress` lose nothing, and the
modern build builds and plays (`tools/playtest.sh`).

The other rules every `MODERN.md` repeats:

- **Reimplement, never copy.** Fan patches (the NOLF and NOLF 2
  Modernizers above all) are the best source of *what* is wrong and *why*,
  and are credited item by item; their code carries no licence and is not
  copied, not even a one-line fix. The same holds between our own games:
  each item is re-checked against that game's code ("As nolf2src's M-E33"
  in cjacksrc means *the same idea, verified here*).
- **The retail toolchain.** The modern build uses the release build's
  compilers (VC6 for NOLF, NOLF2, AvP2, Tron; VC .NET 2003 for CJ). The
  Modernizers' SDL2, Detours and C++11 become Win32 calls and direct
  changes to our engine source. Anything the old SDK predates is declared
  by hand and looked up at run time: `RAWINPUTDEVICE` and
  `GetRawInputData` (nolfsrc "Rules"), XInput's types (nolf2src M-E20),
  `SetProcessDPIAware` (M-E71). Only the replacements for third-party
  binaries are built with a modern compiler (`build/ext.sh`, `zig cc`).
- **No game data committed.** A data change is a recipe against the
  retail file (nolfsrc `src/modern/data/`).

## Windowed Direct3D under Wine

Two findings in nolf2src, ported unchanged to cjacksrc, both from
reading where the frame went (`FrameTimeLog`, M-E58: time per part of the
frame, `present` and `limit` among them).

1. **`D3DPRESENT_INTERVAL_DEFAULT` is a v-sync under Wine.** Retail passes
   it for every window, borderless full screen included, whatever
   `VSyncOnFlip` says. Native Direct3D 8 requires it in a window; Wine can
   take it as synchronised, so `MaxFPS 0` sat at the monitor's rate with
   all the time in `present`. Under Wine only, the modern build asks for
   `D3DPRESENT_INTERVAL_IMMEDIATE` when v-sync is off; Windows keeps the
   default (nolf2src M-E62, cjacksrc EN-43). Verified by Wine's trace:
   `wglSwapIntervalEXT(1)` before, `0` after.
2. **A windowed v-sync halves the frame rate when a frame runs long.** A
   window gets one back buffer, so with v-sync a frame slightly longer
   than a refresh waits for the next one: Shadows on High dropped to half
   rate. The compositor already prevents tearing in a window, so under
   Wine a window always presents immediately and, with `VSyncOnFlip` on,
   the **frame limiter** caps at the display's refresh rate
   (`GetDeviceCaps(VREFRESH)`, 60 for "default") or `MaxFPS` if lower: a
   slow frame costs a few frames, not half. Full screen keeps the real
   wait (nolf2src M-E70, cjacksrc EN-62).

The lesson: **measure the frame before tuning it**, and make a fix
conditional on the platform that needs it.

## Declare DPI awareness at run time

Retail declares nothing about DPI, so above 100% display scaling Windows
virtualises the window's coordinates: in nolfsrc the cursor was held to
the top-left part of the screen; in nolf2src, borderless at 3840x2160
and 150%, the cursor Windows draws moved normally but the game read it
scaled down, and no menu item could be clicked. `WinMain` now declares
DPI awareness before any window exists, looked up in `user32.dll` at run
time: nolfsrc per-monitor v2, falling back to per-monitor and then
system-wide (nolfsrc 602b0b1, M-P1-30); nolf2src `SetProcessDPIAware`
(M-E71, checked on Windows 11 at 150%). The launcher is left alone:
Windows scales its dialog, which only blurs it.

## Input

**Don't enumerate DirectInput devices.** `input_Init` called
`EnumDevices`, which walks every HID device on the machine; a Windows 11
crash report shows an access violation in `RtlAllocateHeap` inside
`dinput.dll` there. The modern build needs only the keyboard and mouse
from DirectInput, so it creates `GUID_SysKeyboard` and `GUID_SysMouse`
directly and describes each with its own `GetDeviceInfo` -- the name, GUID
and type enumeration would have given -- so bindings, profiles and
Configure controls, which find devices by type or that name, are unchanged
(nolfsrc M-P7-09, nolf2src M-E33, cjacksrc EN-22).

**XInput as a fake DirectInput device.** The controller is an object
behind `IDirectInputDevice2A` (NOLF) or `IDirectInputDevice8A` (NOLF2, CJ)
that answers the calls the engine makes of a gamepad from XInput's state:
six absolute axes and sixteen named buttons, buffered in whatever data
format the engine sets. Everything above it -- bindings, buffered reads,
Configure controls' capture, the game's own gamepad code -- is untouched.
Details that mattered: `xinput1_4`, `1_3` or `9_1_0` loaded at run time;
DirectInput's own joysticks dropped from the device list (under Wine the
same pad appears among them too, and would be read twice: nolf2src M-E21,
cjacksrc EN-21); empty slots polled once a second from a thread, never in
the frame, since asking XInput about an empty slot can take milliseconds
(nolf2src M-E59); a file-driven pad state (`<PROJECT>_PADTEST`) for
scripted tests (nolfsrc M-P7-01, nolf2src M-E20, cjacksrc EN-20).

**Mouse look.** Two different answers to "the retail mouse is wrong":
nolfsrc replaced it with raw input (`WM_INPUT` on the window the game
shell already subclasses, M-P1-03). nolf2src found the cause in the
engine (M-E3): the mouse was read one DirectInput event at a time and each
axis's last value was reused by every later pass of the frame and the
next frames until it aged out, so one event turned the view about three
times its motion at 60 fps, more at higher rates. The fix reads the whole
buffer, sums each axis's motion for the frame and hands it on once; the
buffer grows from 64 to 1024 events (a 1000 Hz mouse overflowed it at low
frame rates). That changes sensitivity (1.1 to 3.8 times less turn per
setting), so the slider's scale was re-derived, not left. cjacksrc lists
the same fix as planned.

## High frame rates

**The limiter existed and never ran.** `MaxFPS` works only outside the
final build: `cm_HandleMaxFPS` is in retail's `Lithtech.exe` (CJ
0x40e6b0) but `CClientMgr::Update` calls it only under `#ifndef _FINAL`,
so retail ran unlimited (nolf2src M-E4, cjacksrc EN-40). The modern
limiter sleeps while more than 2 ms are left and spins the rest; default
240, with 60, 120, 144, 240 and none on offer (nolfsrc M-P1-25,
cjacksrc CL-40).

Unlocking the rate is the easy part; finding what breaks is the work.
**nolfsrc found each class first**, and each port re-measured it, because
the same mechanism can fail in the opposite direction:

- **The server tick.** In single player the client runs a server tick
  every frame. In NOLF1 a tick took at least 10 ms of game time, so above
  100 fps the world ran *fast* (1.6 times at 159 fps). In NOLF2 and CJ an
  AI updated every 10 ms stepped by one tick's time, so it ran *slow* (a
  third of its speed at 300). Same fix in all three: a tick runs only once
  10 ms have passed since the last (packets and network still every
  frame), and time that runs backwards (a new world) ticks at once, else
  the new world stalls as long as the old one ran (nolfsrc M-P1-23,
  nolf2src M-E4, cjacksrc EN-41; nolf2src `docs/engine/PLAN.md`, "16.
  fps").
- **Per-frame amounts become per-60th-of-a-second amounts**: the player's
  speed cap (walk 7% slower at 300 than at 60), the minimum move, dampings,
  aim perturbation, fire sparks, debris (nolf2src M-E4; cjacksrc CL-41 to
  CL-45).
- **Emitters that owe less than one particle a frame** emitted nothing
  (nolfsrc 9780977, ported as nolf2src M-E4, cjacksrc CL-44).
- **Measure, don't eyeball**: a temporary per-frame log and scripted runs
  under Xvfb with the world not drawn reach 700+ fps, and each fix states
  its numbers at 60 and at 300 (nolf2src `docs/engine/PLAN.md`, "How it
  was measured").

Multiplayer differs per game: nolfsrc runs it at any rate once the
animation clock kept its fractions (fire rate measured equal at 60 and
140, M-P6-15); nolf2src and cjacksrc hold it to 60, "where faster is
untried".

## Middleware

| | NOLF | NOLF2 | CJ |
|---|---|---|---|
| Bink | our FFmpeg player | the same, extended | NOLF2's, unchanged |
| Miles | OpenMiles | none in retail | none in retail |
| MP3 | -- | -- | minimp3 in `SndDrv.dll` |

**Bink.** The engine looks Bink up by name at run time (NOLF2 and CJ: 12
entry points, `binkvideomgrimpl.cpp`, `_BinkOpen@8` to
`_BinkDX8SurfaceType@4`); no game DLL imports it. So the replacement is a
`binkw32.dll` on FFmpeg's Bink demuxer and decoders, built by
`build/ext.sh` with only those parts of FFmpeg (no GPL). nolf2src took
nolfsrc's player and added what NOLF2 asks for (`BinkDX8SurfaceType` and
the 24-bit and alpha copies), dropping the entry points it never calls
(nolf2src "Open middleware", M-X1); cjacksrc took nolf2src's unchanged but
for its header (cjacksrc X-1). **Find out what the engine calls before
writing a replacement**: the export list is the contract.

**Check before you replace.** NOLF2 and CJ have no Miles at all: their
`snddrv.dll` plays through DirectSound and no retail binary imports or
loads `mss32.dll` (nolf2src M-X2, cjacksrc "Open middleware").

**MP3 speech.** CJ's voice lines are MP3 in WAV (661 of 686 `VOICE/`
files), decoded through Windows' ACM by whatever codec the system has;
under Wine that is `winemp3.acm`, which plays streamed lines as a drone of
their first samples, and with no codec the sound driver doesn't start.
The modern `SndDrv.dll` decodes it with minimp3 (one header the 2003
compiler builds into the driver; FFmpeg's would be a second DLL by another
compiler), at every `acmStream*` call site for format 0x55, whole and
streamed. Tested outside the game: all 661 files decoded both ways to the
same bytes (cjacksrc EN-50).

## Other features, by game

What each `MODERN.md` shows (avp2src and tron20src have the define and
the builds but nothing implemented yet; their items are planned). The
approach is shared: widen the horizontal FOV to the screen (Hor+:
`tan(fov/2)` scaled by aspect over 4:3, only for the scene the renderer
is given, so game-side zoom and effects still work); list every mode at
least as wide as 4:3; a window mode of full screen, framed window or
borderless window at the desktop's resolution; 4:3 cinematics as
side bars with the letterbox.

| Feature | nolfsrc | nolf2src | cjacksrc | avp2src | tron20src |
|---|---|---|---|---|---|
| Hor+ field of view | M-P0-01 | M-E1 | EN-30 | M-1 | planned |
| Wide resolutions | M-P1-07 | M-G1 | CL-31, APPS-30 | M-1 | planned |
| Menus and HUD at wide resolutions | M-P3-01..M-P3-04 | M-G2 | CL-30 | M-1 | planned |
| Field-of-view setting | -- | M-G4 | -- | M-3 | planned |
| 4:3 cinematics | M-P3-08 | M-G36 | CL-35 | M-2 | planned |
| Movies keep their shape | M-P1-27 | -- | -- | -- | -- |
| Window mode, borderless | M-P1-22 | M-E30, M-G70, M-L5 | EN-32, CL-32, APPS-31 | M-9 | planned |
| Frame limiter | M-P1-23, M-P1-25 | M-E4 | EN-40, CL-40 | M-9 | planned |
| V-sync in a window (Wine) | -- | M-E62, M-E70 | EN-43, EN-62 | -- | -- |
| DPI awareness | M-P1-30 | M-E71 | -- | -- | -- |
| Mouse | M-P1-03 (raw input) | M-E3 (buffer summed) | planned | M-6 | planned |
| XInput controller | M-P7-01 | M-E20 | EN-20 | M-7 | planned |
| No device enumeration | M-P7-09 | M-E33 | EN-22 | -- | -- |
| Anisotropic filtering | M-P1-09 | M-G45 | -- | M-4 | planned |
| Antialiasing | M-P1-18 | M-E13 | -- | M-5 | planned |
| New renderers | M-P0-04, M-P0-05 | -- | -- | -- | -- |
| 32-bit by default | M-P1-24 | -- | -- | -- | -- |
| Internet play (OpenSpy) | M-P6-02 | M-E6 (todo) | planned | M-9 | planned |
| Launcher split | `docs/BUILDING.md` | -- | -- | M-8 | planned |
| No disc, no CD key | M-P1-15 | M-L4, M-G17 | APPS-4, APPS-6 | rules | rules |

Notes on the rows:

- **AF and AA were partly retail bugs.** NOLF2's Performance screen wrote
  `Anisotropic` 1, degree one, no better than bilinear (M-G45). NOLF2's
  engine had `AntiAliasFSOverSample` but a window always got
  `D3DSWAPEFFECT_COPY` (Direct3D 8 multisamples only with `DISCARD`) and
  every device asked for a lockable back buffer, which a multisampled one
  never is, so the device was refused (M-E13; its `IDS_ANTIALIAS` strings
  are unused in retail). NOLF's `d3d.ren` (DirectX 7) has no AA, so
  M-P1-18 is in our `d3d9.ren` and `opengl.ren` only.
- **New renderers** (nolfsrc): `d3d9.ren` is the modern default, from the
  same core as `opengl.ren`; our `d3d.ren` ships beside them as
  `d3d7.ren`, so the three can be compared (M-P0-05).
- **Master server.** nolfsrc implements the GameSpy master protocol
  against a configurable `MasterServer` (default `master.openspy.net`),
  tested against a local stub and checked once against OpenSpy (M-P6-02).
  nolf2src's equivalent (`ServerDir.dll`, behind `IServerDirectory`) is
  still todo (M-E6).
- **Launcher split.** Only nolfsrc has it so far: modern `NOLF.exe` starts
  the game directly with the launcher's settings, `NOLFLauncher.exe` is
  the launcher (`docs/BUILDING.md`); avp2src and tron20src plan the same
  (`AVP2Launcher.exe`, `TronLauncher.exe`).
- **32-bit.** nolfsrc's textures defaulted to 16-bit (`32BitTextures` 0,
  set by no config); `defaults.cfg` now sets it and a one-time config
  upgrade sets it in old configs (M-P1-24). The mode lists drop 16-bit
  modes (M-P1-07), and the fallback mode is 800x600x32, not 640x480x16
  (M-P1-08).
- **Old configs.** A changed default only reaches a fresh install unless
  a versioned one-time upgrade carries it to existing configs (nolfsrc
  M-P1-12, used by M-P1-24 and M-P1-25).

## Recording it

Each item names, in its `MODERN.md` row: what retail does and why it is
wrong, the credit (a fan patch's commits, or "ours"), the files changed,
how it was tested (and what was *not* tested: "not yet on the Windows
machine that crashed"), and its status. Each code block names its item
(`// MODERN.md M-E1: ...`). A retail bug the item fixes is also an entry
in `RETAIL_BUGS.md`, as found in the release build, which keeps it.
