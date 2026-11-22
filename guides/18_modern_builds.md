# 18 · The modern build

Each game project has two builds of one source:

- The **release** build is the retail game. We score it byte for byte.
- The **modern** build is the same source with `<REPO>SRC_MODERN`
  defined (`NOLFSRC_MODERN`, `NOLF2SRC_MODERN`, `CJACKSRC_MODERN`,
  `AVP2SRC_MODERN`, `TRON20SRC_MODERN`).

The modern build adds these features:

- widescreen;
- window modes;
- high frame rates;
- controllers;
- open-source middleware;
- a launcher that stays open while the game runs;
- settings and saves next to the executable, not in APPDATA or the
  registry;
- the fixes for the bugs in `RETAIL_BUGS.md`.

The `docs/MODERN.md` of each project is its inventory, with an id for
each item. This guide gives what is the same from one game to the next:
the rules, and the techniques that solved the same problem in each
engine.

Each repo has its own item ids:

- nolfsrc: `M-P<n>-<nn>`;
- nolf2src: `M-E` (engine), `M-G` (game), `M-L` (launcher), `M-X`
  (middleware);
- cjacksrc: `EN-`, `CL-`, `APPS-`, `X-`;
- avp2src: `M-<n>`, and `M-X<n>` (middleware);
- tron20src: no ids yet.

## Never change what the release build compiles

The rule comes from the README. The target is the retail behaviour,
together with its bugs. Put a fix behind `#ifdef <REPO>SRC_MODERN`. Keep
the retail code unchanged in the `#else`. Two things make this rule more
difficult than it looks.

**A skipped `#ifdef` block can also change the release binary.** VC6
does not fully ignore the lines that it skips. Five work packages added
blocks to `GameClientShell.cpp` in nolfsrc. These blocks changed the
order of two out-of-line inline functions in the release `CShell.dll`.
Every release token stayed the same. `#line` directives that restored
the retail line numbers did not help (tools e660460).

Thus, the release build does not compile `src/`. It compiles
`out/release-tree/` (`tools/releasesrc.py`). This is a mirror of `src/`
in which each variant block is resolved and its directives are removed.
This method works only if **you add nothing outside a block, not even a
blank line**. `releasesrc.py diff` lists exactly those lines. Its output
must be empty (nolf2src `docs/MODERN.md`, "Release unchanged").

The same commit found that the game DLLs also changed with the length of
the path of the checkout. The commit fixed this: the game DLLs compile
from a drive letter of their own.

**Other people match the game code.** Put each modern change in
`src/Game/` inside a block. Put new members of a class in a block of
their own (nolf2src `docs/MODERN.md`, "Rules").

After each change, do these checks:

1. Make sure that `make` and `make progress` lose nothing.
2. Make sure that the modern build builds and plays
   (`tools/playtest.sh`).

Each `MODERN.md` also gives these rules:

- **Implement again. Do not copy.** Fan patches (most of all, the NOLF
  and NOLF 2 Modernizers) are the best source of *what* is wrong and
  *why*. We give them credit item by item. But their code has no licence.
  We do not copy it, not even a fix of one line. The same rule applies
  between our own games. We check each item again against the code of
  that game. In cjacksrc, "As nolf2src's M-E33" means *the same idea,
  verified here*.
- **The retail toolchain.** The modern build uses the compilers of the
  release build: VC6 for NOLF, NOLF2, AvP2 and Tron; VC .NET 2003 for CJ.
  The Modernizers use SDL2, Detours and C++11. We use Win32 calls and
  direct changes to our engine source in their place. If the old SDK does
  not have a declaration, declare it by hand and find the function at run
  time. Examples:
  - `RAWINPUTDEVICE` and `GetRawInputData` (nolfsrc "Rules");
  - the types of XInput (nolf2src M-E20);
  - `SetProcessDPIAware` (M-E71).

  Only the replacements for third-party binaries use a modern compiler
  (`build/ext.sh`, `zig cc`).
- **Do not commit game data.** A data change is a recipe that we apply to
  the retail file (nolfsrc `src/modern/data/`).

## Windowed Direct3D under Wine

We found two problems in nolf2src and ported the fixes unchanged to
cjacksrc. We found both when we read where the time of the frame went.
`FrameTimeLog` (M-E58) gives the time for each part of the frame,
`present` and `limit` among them.

1. **Under Wine, `D3DPRESENT_INTERVAL_DEFAULT` is a v-sync.** Retail uses
   it for every window, borderless full screen too. It does not look at
   `VSyncOnFlip`. Native Direct3D 8 requires this value in a window. Wine
   can read it as a v-sync. Thus, with `MaxFPS 0`, the frame rate stayed
   at the rate of the monitor, and all the time went into `present`. The
   fix applies only under Wine. If v-sync is off, the modern build asks
   for `D3DPRESENT_INTERVAL_IMMEDIATE`. On Windows, the build keeps the
   default (nolf2src M-E62, cjacksrc EN-43). The Wine trace shows the
   result: `wglSwapIntervalEXT(1)` before, `0` after.
2. **With v-sync in a window, a long frame halves the frame rate.** A
   window gets one back buffer. With v-sync, a frame that is a little
   longer than a refresh waits for the next refresh. Thus, with Shadows
   on High, the frame rate fell to half. In a window, the compositor
   already prevents tearing. The fix, under Wine:
   - A window always presents immediately.
   - If `VSyncOnFlip` is on, the **frame limiter** sets the limit. The
     limit is the refresh rate of the display (`GetDeviceCaps(VREFRESH)`,
     60 for "default"), or `MaxFPS` if it is lower.
   - Thus, a slow frame costs some frames, not half of the frames.
   - Full screen keeps the real wait (nolf2src M-E70, cjacksrc EN-62).

The lesson: **measure the frame before you tune it**. Apply a fix only on
the platform that needs it.

## Declare DPI awareness at run time

Retail declares nothing about DPI. Thus, above 100% display scaling,
Windows virtualises the coordinates of the window. The results:

- In nolfsrc, the cursor could move only in the top-left part of the
  screen.
- In nolf2src, borderless at 3840x2160 and 150%, the cursor that Windows
  drew moved correctly. But the game read the position scaled down, and
  no menu item could be clicked.

Now `WinMain` declares DPI awareness before any window exists. It finds
the function in `user32.dll` at run time:

- nolfsrc: per-monitor v2, then per-monitor, then system-wide if the
  newer one is not available (nolfsrc 602b0b1, M-P1-30);
- nolf2src: `SetProcessDPIAware` (M-E71, checked on Windows 11 at 150%);
- avp2src: per-monitor v2, then per-monitor, then system-wide (M-27).

We do not change the launcher. Windows scales its dialog, and the only
result is that the dialog is not sharp.

## Input

**Do not enumerate DirectInput devices.** `input_Init` called
`EnumDevices`, which examines every HID device on the machine. A crash
report from Windows 11 shows an access violation in `RtlAllocateHeap`
inside `dinput.dll` at that point. The modern build needs only the
keyboard and the mouse from DirectInput. Thus, it creates
`GUID_SysKeyboard` and `GUID_SysMouse` directly. It describes each device
with its own `GetDeviceInfo`. This gives the name, GUID and type that the
enumeration gave. Bindings, profiles and Configure controls find devices
by type or by that name, so they do not change (nolfsrc M-P7-09,
nolf2src M-E33, cjacksrc EN-22).

**XInput as a fake DirectInput device.** The controller is an object
behind `IDirectInputDevice2A` (NOLF) or `IDirectInputDevice8A` (NOLF2,
CJ). It answers the gamepad calls of the engine from the state of
XInput. It gives six absolute axes and sixteen named buttons. It buffers
them in the data format that the engine sets. Nothing above it changes:
bindings, buffered reads, the capture of Configure controls, and the
gamepad code of the game. Important details:

- The object loads `xinput1_4`, `1_3` or `9_1_0` at run time.
- It removes the own joysticks of DirectInput from the device list. Under
  Wine, the same pad is also among them, and the game would read it two
  times (nolf2src M-E21, cjacksrc EN-21).
- A thread examines empty slots one time each second, never in the frame.
  A question to XInput about an empty slot can take milliseconds
  (nolf2src M-E59).
- A file can give the pad state (`<REPO>SRC_PADTEST`) for scripted tests
  (nolfsrc M-P7-01, nolf2src M-E20, cjacksrc EN-20).

**Mouse look.** The retail mouse is not correct, and two games found two
different answers:

- nolfsrc replaced it with raw input: `WM_INPUT` on the window that the
  game shell already subclasses (M-P1-03).
- nolf2src found the cause in the engine (M-E3). The engine read the
  mouse one DirectInput event at a time. Every later pass of the frame,
  and the next frames, used the last value of each axis again, until the
  value became too old. Thus, at 60 fps, one event turned the view about
  three times its motion, and more at higher rates.

The nolf2src fix reads the full buffer. It adds the motion of each axis
for the frame and gives it on one time. The buffer increases from 64 to
1024 events, because a 1000 Hz mouse overflowed it at low frame rates.
This fix changes the sensitivity: 1.1 to 3.8 times less turn for each
setting. Thus, we calculated the scale of the slider again. We did not
keep the old scale. cjacksrc lists the same fix as planned.

## High frame rates

**The limiter existed but never ran.** `MaxFPS` works only outside the
final build. `cm_HandleMaxFPS` is in the retail `Lithtech.exe` (CJ
0x40e6b0). But `CClientMgr::Update` calls it only under `#ifndef _FINAL`.
Thus, retail ran with no limit (nolf2src M-E4, cjacksrc EN-40). The
modern limiter sleeps while more than 2 ms remain, and spins for the
remaining time. The default is 240. The choices are 60, 120, 144, 240 and
none (nolfsrc M-P1-25, cjacksrc CL-40, avp2src M-13).

To unlock the rate is easy. To find what it breaks is the work.
**nolfsrc found each class first.** Each port measured the class again,
because the same mechanism can fail in the opposite direction:

- **The server tick.** In single player, the client runs a server tick
  each frame.
  - In NOLF1, a tick took at least 10 ms of game time. Thus, above 100
    fps the world ran *fast* (1.6 times at 159 fps).
  - In NOLF2 and CJ, an AI that updated each 10 ms moved by the time of
    one tick. Thus, it ran *slow* (one third of its speed at 300 fps).
  - The fix is the same in all three games. A tick runs only after 10 ms
    since the last tick. Packets and the network still run each frame.
    If the time goes backwards (a new world), the tick runs immediately.
    If not, the new world stops for as long as the old world ran
    (nolfsrc M-P1-23, nolf2src M-E4, cjacksrc EN-41; nolf2src
    `docs/engine/PLAN.md`, "16. fps").
- **Amounts for each frame become amounts for each 60th of a second.**
  Examples: the speed limit of the player (the player walked 7% slower
  at 300 fps than at 60 fps), the minimum move, dampings, aim
  perturbation, fire sparks, debris (nolf2src M-E4; cjacksrc CL-41 to
  CL-45; avp2src M-14).
- **Emitters that owe less than one particle in each frame** emitted
  nothing (nolfsrc 9780977, ported as nolf2src M-E4, cjacksrc CL-44).
- **Measure. Do not guess from what you see.** Use a temporary log for
  each frame, and scripted runs under Xvfb with no world drawn. These runs
  get to more than 700 fps. Each fix gives its numbers at 60 fps and at
  300 fps (nolf2src `docs/engine/PLAN.md`, "How it was measured").

Multiplayer is different in each game:

- nolfsrc runs multiplayer at all rates, after the animation clock kept
  its fractions. The fire rate is the same at 60 and at 140 (M-P6-15).
- nolf2src and cjacksrc limit multiplayer to 60, "where faster is
  untried".
- avp2src offers the limits for single player and multiplayer (M-13).

## Middleware

| | NOLF | NOLF2 | CJ |
|---|---|---|---|
| Bink | our FFmpeg player | the same, extended | NOLF2's, unchanged |
| Miles | OpenMiles | none in retail | none in retail |
| MP3 | -- | -- | minimp3 in `SndDrv.dll` |

**Bink.** The engine finds Bink by name at run time. In NOLF2 and CJ,
there are 12 entry points, `_BinkOpen@8` to `_BinkDX8SurfaceType@4`
(`binkvideomgrimpl.cpp`). No game DLL imports Bink. Thus, the
replacement is a `binkw32.dll` on the Bink demuxer and decoders of
FFmpeg. `build/ext.sh` builds it with only those parts of FFmpeg (no
GPL).

- nolf2src took the player of nolfsrc. It added what NOLF2 needs
  (`BinkDX8SurfaceType` and the 24-bit and alpha copies). It removed the
  entry points that NOLF2 never calls (nolf2src "Open middleware", M-X1).
- cjacksrc took the player of nolf2src unchanged, except for its header
  (cjacksrc X-1).

**Find what the engine calls before you write a replacement.** The export
list is the contract.

**Check before you replace.** NOLF2 and CJ have no Miles. Their
`snddrv.dll` plays through DirectSound. No retail binary imports or
loads `mss32.dll` (nolf2src M-X2, cjacksrc "Open middleware").

**MP3 speech.** The voice lines of CJ are MP3 in WAV (661 of the 686
`VOICE/` files). Windows decodes them through ACM, with the codec that
the system has.

- Under Wine, the codec is `winemp3.acm`. It plays streamed lines as a
  drone of their first samples.
- If there is no codec, the sound driver does not start.

The modern `SndDrv.dll` decodes MP3 with minimp3. Minimp3 is one header,
and the 2003 compiler builds it into the driver. The FFmpeg decoder
would be a second DLL from a different compiler. The driver decodes at
each `acmStream*` call site for format 0x55, for whole and streamed
sounds. We tested it outside the game: all 661 files decoded to the same
bytes in the two modes (cjacksrc EN-50).

## Other features, by game

The table shows what each `MODERN.md` shows. In avp2src, most items are
done, but M-4 and M-5 are not implemented yet. tron20src has the define
and the builds. Only its launcher split is done. Its other items are
planned.

The method is the same in each game:

- Make the horizontal FOV wider for the screen (Hor+). Scale
  `tan(fov/2)` by the aspect ratio over 4:3. Do this only for the scene
  that the renderer gets, so the zoom and effects of the game still work.
- List every mode that is at least as wide as 4:3.
- Give a window mode: full screen, a window with a frame, or a borderless
  window at the resolution of the desktop.
- Show 4:3 cinematics with side bars and the letterbox.

| Feature | nolfsrc | nolf2src | cjacksrc | avp2src | tron20src |
|---|---|---|---|---|---|
| Hor+ field of view | M-P0-01 | M-E1 | EN-30 | M-1 | planned |
| Wide resolutions | M-P1-07 | M-G1 | CL-31, APPS-30 | M-1 | planned |
| Menus and HUD at wide resolutions | M-P3-01..M-P3-04 | M-G2 | CL-30 | M-1, M-15, M-16 | planned |
| Field-of-view setting | -- | M-G4 | -- | M-3 | planned |
| 4:3 cinematics | M-P3-08 | M-G36 | CL-35 | M-2 | planned |
| Movies keep their shape | M-P1-27 | -- | -- | -- | -- |
| Window mode, borderless | M-P1-22 | M-E30, M-G70, M-L5 | EN-32, CL-32, APPS-31 | M-9 | planned |
| Frame limiter | M-P1-23, M-P1-25 | M-E4 | EN-40, CL-40 | M-13, M-14 | planned |
| V-sync in a window (Wine) | -- | M-E62, M-E70 | EN-43, EN-62 | -- | -- |
| DPI awareness | M-P1-30 | M-E71 | -- | M-27 | -- |
| Mouse | M-P1-03 (raw input) | M-E3 (buffer summed) | planned | M-6 (raw input) | planned |
| XInput controller | M-P7-01 | M-E20 | EN-20 | M-7 | planned |
| No device enumeration | M-P7-09 | M-E33 | EN-22 | -- | -- |
| Anisotropic filtering | M-P1-09 | M-G45 | -- | M-4 (not implemented yet) | planned |
| Antialiasing | M-P1-18 | M-E13 | -- | M-5 (not implemented yet) | planned |
| New renderers | M-P0-04, M-P0-05 | -- | -- | -- | -- |
| 32-bit by default | M-P1-24 | -- | -- | -- | -- |
| Internet play (OpenSpy) | M-P6-02 | M-E6 (todo) | planned | M-17..M-20 | planned |
| Launcher split | `docs/BUILDING.md` | shown in M-L9 | shown in APPS-51 | M-8 | done (no id) |
| Launcher stays open while the game runs (Steam) | M-P1-31 | M-L9 | APPS-51 | M-22 | not documented |
| Settings and saves next to the executable, not in APPDATA or the registry | M-P1-28 (launcher only) | not met: M-L7, M-G71 (user's registry key) | not met: APPS-7 (user's registry key) | partly: M-8 | not documented |
| No disc, no CD key | M-P1-15 | M-L4, M-G17 | APPS-4, APPS-6 | M-8, M-18 | rules |

Notes on the rows:

- **AF and AA were partly retail bugs.**
  - The Performance screen of NOLF2 wrote `Anisotropic` 1. This is degree
    one, which is not better than bilinear (M-G45).
  - The NOLF2 engine had `AntiAliasFSOverSample`. But a window always got
    `D3DSWAPEFFECT_COPY`, and Direct3D 8 multisamples only with
    `DISCARD`. Also, each device asked for a lockable back buffer. A
    multisampled back buffer is never lockable, so the device was refused
    (M-E13). Its `IDS_ANTIALIAS` strings are not used in retail.
  - The `d3d.ren` of NOLF (DirectX 7) has no AA. Thus, M-P1-18 is only in
    our `d3d9.ren` and `opengl.ren`.
- **New renderers** (nolfsrc). `d3d9.ren` is the modern default. It comes
  from the same core as `opengl.ren`. Our `d3d.ren` ships next to them as
  `d3d7.ren`, so you can compare the three (M-P0-05).
- **Master server.**
  - nolfsrc implements the GameSpy master protocol against a
    configurable `MasterServer` (default `master.openspy.net`). We tested
    it against a local stub. We checked it one time against OpenSpy
    (M-P6-02).
  - The nolf2src equivalent (`ServerDir.dll`, behind `IServerDirectory`)
    is not done yet (M-E6).
  - avp2src has the client console variable `MasterServer` (empty:
    `master.openspy.net`), with no WON and no CD key (M-17, M-18).
- **Launcher split.** The modern `<GAME>.exe` starts the game directly,
  as Launch in the launcher does. A different exe is the launcher.
  - nolfsrc: `NOLF.exe` starts the game with the settings of the
    launcher. `NOLFLauncher.exe` is the launcher (`docs/BUILDING.md`).
  - nolf2src: `NOLF2.exe` starts the game directly. The launcher window
    is `NOLF2Launcher.exe` (M-L9).
  - cjacksrc: `ContractJack.exe` has a direct start without the launcher
    window (APPS-51).
  - avp2src: `AVP2.exe` and `PrimalHunt.exe` start the game directly.
    `AVP2Launcher.exe` and `PrimalHuntLauncher.exe` are the launchers
    (M-8).
  - tron20src: `Tron.exe` starts the game when the game is installed.
    `TronLauncher.exe` is the launcher (`docs/MODERN.md`, "Done").
- **The launcher stays open.** Steam watches the program that it starts.
  When that program exits, Steam thinks that the game ended, and the
  overlay and Remote Play stop. The retail launchers exit when they start
  the engine. The modern launcher waits until the engine (or the
  dedicated server) exits, and then exits. The wait handles the messages
  of the window (`MsgWaitForMultipleObjects`).
  - avp2src did it first (M-22, GitHub issue #5). The launcher hides its
    windows and waits. The command-line starts (host, join, find, play,
    server) also wait. The launcher starts the dedicated server with
    `CreateProcess`, not `WinExec`, to get a process to wait for.
  - nolf2src M-L9 and cjacksrc APPS-51 do the same as avp2src M-22.
  - nolfsrc M-P1-31 waits from the dialog and from the direct start.
  - In all four games, the direct start already waited.
  - tron20src: not documented.
- **Settings and saves next to the executable.** No launcher or game must
  write settings to APPDATA or to the registry. Settings and saves must
  go next to the executable. This keeps the game portable, and keeps the
  settings when the Proton version changes. The `MODERN.md` files show
  this:
  - nolfsrc M-P1-28: `NOLF.exe`, `NOLFLauncher.exe` and `NolfServ.exe`
    write the launcher settings to `launcher.ini` next to the program.
    They do not read or write the registry. But the game still reads
    `Language` from the registry (`VersionMgr`). The docs do not say
    where saves go.
  - nolf2src M-L7 and M-G71: the launcher and the game move their
    settings from `HKEY_LOCAL_MACHINE` to the same path under
    `HKEY_CURRENT_USER`. They still use the registry, so the requirement
    is not met.
  - cjacksrc APPS-7: the launcher, the game DLLs and the dedicated
    server move their values to `HKEY_CURRENT_USER`, as nolf2src does.
    The requirement is not met.
  - avp2src M-8: the programs do not need the registry. But the launcher
    still keeps its settings in the registry when the key is there.
    Nothing creates the key. The docs do not say where saves go.
  - tron20src: not documented.

  The docs of the five games do not mention APPDATA.
- **32-bit.**
  - The textures of nolfsrc were 16-bit by default (`32BitTextures` 0,
    and no config set it). Now `defaults.cfg` sets it. A one-time config
    upgrade sets it in old configs (M-P1-24).
  - The mode lists do not show 16-bit modes (M-P1-07).
  - The fallback mode is 800x600x32, not 640x480x16 (M-P1-08).
- **Old configs.** A changed default gets only to a new install. To get
  it to existing configs, use a one-time upgrade with a version (nolfsrc
  M-P1-12, used by M-P1-24 and M-P1-25).

## Recording it

The `MODERN.md` row of each item gives these data:

- what retail does, and why it is wrong;
- the credit (the commits of a fan patch, or "ours");
- the files that changed;
- how we tested it, and what we did *not* test ("not yet on the Windows
  machine that crashed");
- its status.

Each code block names its item (`// MODERN.md M-E1: ...`). If the item
fixes a retail bug, that bug is also an entry in `RETAIL_BUGS.md`. The
entry describes the bug as it is in the release build, which keeps it.
