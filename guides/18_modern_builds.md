# 18 · Building a modern variant

This guide tells you how to make a reconstructed game work well on
modern systems. One source tree gives two builds:

- The **release** build is the retail game. It is the only build that
  you score, byte for byte.
- The **modern** build is the same source with one compile-time switch
  defined, for example `<GAME>_MODERN`. It adds fixes and new features.

The status of each feature in each game is project status, which is in
the `docs/MODERN.md` of that project. For tools, see
[17 · Decompiling the dev tools](17_applications.md).

## 1. Principles

### Keep the release build byte-identical

The README rule applies:
[Never change what the retail code does](README.md#never-change-what-the-retail-code-does).
To add a modern change, do these steps:

1. Put the new code in an `#ifdef <GAME>_MODERN` block.
2. Keep the retail code unchanged in the `#else` part.
3. Put new class members in a block of their own.
4. Make sure that the release score loses nothing, and that the modern
   build plays.

### Build the release from a stripped copy

An old compiler does not always ignore the lines that it skips. Thus, a
skipped `#ifdef` block can change the release binary.

Example: in nolfsrc, new blocks in one source file changed the order of
two out-of-line inline functions in the release DLL. Every release token
stayed the same, and `#line` directives did not help (tools e660460).

Thus, compile the release from a copy of the tree. In the copy, resolve
each variant block to its release side and remove its directives. This
works only if you add nothing outside a block, not even a blank line.
Make a script that lists such lines. Its output must be empty.

NOTE: Other inputs can also change the binary. Example: in nolfsrc, the
game DLLs changed with the length of the checkout path (tools e660460).
Build from a fixed path, for example a drive letter of its own.

### Retail bugs, third-party code and the toolchain

Write each retail bug in `RETAIL_BUGS.md`, as it is in the release
build. Fix it only in the modern build, and refer to the bug entry.

Fan patches show *what* is wrong and *why*. Give them credit item by
item. Their code often has no licence, so do not copy it, not even one
line. Between sibling games, check each item again against the code of
that game.

Build the modern variant with the release compiler. Use platform calls
and direct source changes, not frameworks or hooking libraries.

If the old SDK does not declare something, declare the types by hand.
Find the function at run time with `GetProcAddress`, and give a
fallback. Examples: raw input, the XInput types, `SetProcessDPIAware`.

NOTE: A replacement for a third-party binary can use a modern compiler,
because that binary is not part of the score.

CAUTION: Do not commit game data. Write a data change as a recipe that
a script applies to the retail file.

## 2. Presentation

Give full screen, a window with a frame, and a borderless window at the
desktop resolution.

### V-sync and present intervals under a compatibility layer

Measure the time of each part of the frame before you tune it, for
example the present and the limiter. Two problems occur with a windowed
Direct3D device under Wine or Proton:

1. **The default present interval can act as a v-sync.** Native
   Direct3D 8 requires the default interval in a window. Wine can read
   it as a wait for each refresh. Thus, the frame rate stays at the
   monitor rate. If v-sync is off, ask for an immediate present.
2. **A window gets one back buffer.** With v-sync, a frame that is a
   little too long waits for the next refresh. Thus, the frame rate falls
   to half. The compositor already prevents tearing in a window. Thus,
   present immediately, and let the frame limiter cap the rate at the
   refresh rate of the display.

Keep the real v-sync wait in full screen. Apply each fix only on the
platform that needs it. Example: nolf2src M-E62 and M-E70.

### DPI awareness

If an old game declares nothing about DPI, Windows virtualises the
window coordinates above 100% scaling. Then the cursor moves only in
part of the screen, or the clicks miss the menu items.

Declare DPI awareness in `WinMain`, before any window exists. Find the
function in `user32.dll` at run time. Try per-monitor v2 first, then
per-monitor, then system-wide (nolfsrc 602b0b1). A launcher dialog can stay unaware,
because Windows scales it.

### Widescreen, aspect ratio and field of view

Do these steps:

1. List every display mode that is at least as wide as 4:3.
2. Make the horizontal FOV wider for the screen (Hor+). Scale
   `tan(fov/2)` by the aspect ratio divided by 4/3.
3. Apply the scale only to the scene that the renderer gets. Then the
   zoom and the effects of the game still work.
4. Move the menus and the HUD so that they are correct at wide ratios.
5. Give an FOV setting.
6. Give an option to show cinematics at 4:3, with bars at the sides.

### Anisotropic filtering and anti-aliasing

Give anisotropic filtering up to 16x and anti-aliasing up to 8x. Examine
the retail code first, because these settings can contain retail bugs.

Example: nolf2src wrote an anisotropic degree of 1, which is bilinear
(M-G45). Its anti-aliasing never worked. A window got the copy swap
effect, and each device asked for a lockable back buffer. Direct3D 8
cannot multisample either of them (M-E13).

## 3. Input

### Do not enumerate devices

Old input code often enumerates every device on the machine. On modern
systems, this enumeration can crash inside the system DLL.

If the game needs only the keyboard and the mouse, create them by GUID.
Get the name, GUID and type of each device from the device itself. Then
the bindings find the same devices as before. Example: nolf2src M-E33
fixed an access violation inside `dinput.dll` on Windows 11.

### The mouse

Give raw mouse input through `WM_INPUT`. If the game already subclasses
its window, handle the message there.

Look for mouse code that reads one event at a time. Such code can use
the last value of an axis again in later frames. Then the turn increases
with the frame rate. To fix it, do these steps:

1. Read the full input buffer each frame.
2. Add the motion of each axis for the frame.
3. Apply the sum one time.
4. Make the buffer large enough for a 1000 Hz mouse at a low frame rate.
5. Calculate the scale of the sensitivity slider again.

Example: nolf2src M-E3. At 60 fps, one event turned the view about three
times its motion. The buffer increased from 64 to 1024 events.

### Modern controllers through an adapter

Do not change the bindings code to add a modern controller. Make an
adapter that shows the old API to the engine, for example an XInput pad
as a fake DirectInput device. Then nothing above the adapter changes:

1. Implement the old device interface, and answer from the XInput state.
2. Give the axes and the buttons in the data format that the engine sets.
3. Load the XInput DLL at run time, and try each version.
4. Remove the same pad from the old device list. If not, the game reads
   it two times.
5. Examine empty slots on a separate thread, not in the frame.
6. Let a file give the pad state for scripted tests.

NOTE: A query to XInput about an empty slot can take milliseconds.

## 4. Frame rate

To unlock the frame rate is easy. To find what it breaks is the work.

### Find every per-frame constant and loop

Search for each amount that the code applies one time in each frame.
Examples are speed limits, minimum moves, dampings, aim perturbation,
particles and debris. Change each one to a per-time amount, for example
an amount for each 60th of a second.

CAUTION: An emitter that owes less than one particle in each frame can
emit nothing at high rates. Keep the fraction from frame to frame
(nolfsrc 9780977).

### Use a fixed simulation tick

If the client runs a server tick in each frame, the world speed can
change with the frame rate. The same mechanism can fail in the opposite
direction in a sibling game, so measure each game again. Example: NOLF
ran fast above 100 fps, but NOLF 2 AI ran slow at 300 fps.

The fix: run a tick only when 10 ms passed since the last tick. Run
packets and the network in each frame. If the time goes backwards, for
example in a new world, run the tick immediately.

### Selectable limits

Look for a limiter that only debug builds compile. Give these limits:
60, 120, 144, 240, and unlimited. To make the limiter accurate, sleep
while more than 2 ms remain. Then spin for the remaining time.

Test multiplayer at each limit. Compare the fire rate and the animation
clock at 60 fps and at a high rate. If you did not test a rate, limit
multiplayer to 60 fps.

### How to measure

Do not guess from what you see. Add a temporary log for each frame. Run
scripted tests with no world drawn, to get very high rates. Record each
fix at 60 fps and at a high rate, before and after. To run the game in
scripts, see
[05 · Reconstructing executables and engine binaries](05_exe_and_engine.md).

## 5. Proprietary middleware

Replace video, audio and codec libraries with open-source ones. Keep
the ABI that the game expects.

Do these steps:

1. Make sure that the game uses the library. A file in the install can
   be unused.
2. Find the entry points that the game calls. They are the contract.
3. Implement only those, with only the open-source parts that you need.
4. Keep the original importable, so that a user can put it back.

Example: the engine finds its video library by name at run time, with
12 entry points. Thus, a replacement DLL on the FFmpeg decoders works
with no change to the game.

A system codec can also fail. Example: under Wine, the system MP3 codec
played the streamed speech of Contract JACK as a drone. Thus, the modern
sound driver decodes MP3 itself (cjacksrc EN-50).

NOTE: Test a codec swap outside the game first. Whole and streamed
decodes must give the same bytes for every file.

## 6. Portability

### Settings and saves next to the executable

Write settings and saves next to the executable, not to the registry or
APPDATA. Then the install is portable, and the settings survive a Proton
prefix change. A move to a different registry key does not meet this
rule.

### The launcher

Make the main executable start the game directly, as the Launch button
does. Give the launcher a different name. Example: in nolfsrc,
`NOLF.exe` starts the game, and `NOLFLauncher.exe` is the launcher.

Steam watches the program that it starts. When that program exits, the
overlay and Remote Play stop. Thus, the launcher must wait until the
game exits. Start the game with `CreateProcess`, to get a process
handle. Hide the launcher windows. Wait with `MsgWaitForMultipleObjects`,
and handle window messages. Apply the wait to each start path.

### 32-bit colour defaults

Change 16-bit defaults to 32-bit, also in the mode lists and the
fallback mode. A changed default gets only to a new install. To change
existing configs, add a one-time config upgrade with a version number.

### Restored online services

If the master server of the game is gone, use a replacement. Example:
OpenSpy replaces GameSpy. Make the server address a setting. Test
against a local stub first, and then against the real service.

## 7. Recording

Give each change an id in `docs/MODERN.md`. For each item, write these
data:

- what retail does, and why it is wrong;
- the credit and the files that changed;
- how you tested it, and what you did *not* test;
- the status.

Name the item in each code block, for example `// MODERN.md M-E1: ...`.
If the item fixes a retail bug, also add an entry to `RETAIL_BUGS.md`.
