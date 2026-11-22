# 19 · DirectDraw and Direct3D

This guide tells you how to find, read and rebuild the graphics part of
DirectX 6 to 9 in a game binary. It also tells you what breaks on modern
systems, and how to fix it in a modern build. For the modern variant in
general, read [18 · Building a modern variant](18_modern_builds.md) first.
This guide does not repeat it.

Our projects met three generations of the API:

| API | Runtime DLL | Where we met it |
|---|---|---|
| DirectDraw 7 and Direct3D 7 | `ddraw.dll` | the `d3d.ren` render DLL of NOLF and AvP2 |
| Direct3D 8 | `d3d8.dll`, with `d3dx8.lib` linked in | the engine of NOLF 2 and Contract J.A.C.K. |
| Direct3D 9 | `d3d9.dll`, with `d3dx9.lib` linked in | the engine of Tron 2.0; the new nolfsrc `d3d9.ren` |

## 1. Recognise the component

### The imports tell you the generation

Read the import table of each image first:

- **DirectX 7.** `ddraw.dll` exports `DirectDrawCreateEx`. The game asks it
  for `IID_IDirectDraw7`. Direct3D 7 has no DLL entry of its own. The game
  gets `IDirect3D7` from DirectDraw with `QueryInterface`.
- **Direct3D 8.** `d3d8.dll` exports `Direct3DCreate8`. Its argument is the
  `D3D_SDK_VERSION` of the headers. The DirectX 8.1 SDK sets 220 (`0xdc`).
- **Direct3D 9.** `d3d9.dll` exports `Direct3DCreate9`. The DirectX 9.0 SDK
  sets 31 (`0x1f`).

An entry point that is new in a later runtime can come from
`GetProcAddress`, not from the import table. Example: NOLF's `d3d.ren`
gets `DirectDrawEnumerateExA` from the loaded `DDRAW.DLL` by name. If the
call fails, it uses the old `DirectDrawEnumerateA` (nolfsrc
`src/engine/d3d/d3dr3b.cpp`). Thus, search the strings for entry-point
names too.

The form of the call also shows the header. A call through the import
address table (`call *0x1008801c`) comes from a `__declspec(dllimport)`
declaration, as `windows.h` gives. A `call` to a `jmp` thunk comes from
a plain declaration, as `ddraw.h` gives. Copy the form that the binary
shows.

### The interface IDs tell you the interface versions

COM interface IDs are 16-byte constants in `.rdata`. In NOLF's `d3d.ren`
they are contiguous, directly after the import address table
(`0x10088128`..`0x100881a7`). Search `.rdata` for the first four bytes of
each known IID, in little-endian order. Example: `IID_IDirectDraw7`
{15E65EC0-3B9C-11D2-...} starts with `c0 5e e6 15` in the file.

The highest interface number that the code asks for is the lowest runtime
that the game needs. It is not the SDK of the build. A DirectX 7 renderer
can also ask for `IID_IDirectDraw4`, for example.

### Structure sizes tell you the structure version

DirectX structures start with `dwSize`. The code writes it as an
immediate operand. Thus, `movl $0x7c,-0x100(%ebp)` is a
`DDSURFACEDESC2` (124 bytes), and `movl $0x64,...` is a `DDBLTFX`
(100 bytes). The DirectX 7 `DDCAPS` is `0x17c` bytes. A
`rep stos` over the same block is the `memset` before the size is set.
Use the size to select the structure, and the structure to name the
fields that the code reads.

### Old compilers have old headers

Visual C++ 6.0 ships DirectX 5 headers and a `dxguid.lib` without the
DirectX 7 names. If the game used a later SDK, add that SDK to the
toolchain (nolf2src, tron20src). If you cannot, declare the structures,
interfaces and IIDs by hand, with `extern "C"` and the SDK spelling
(nolfsrc `src/engine/d3d/d3dguid.cpp`).

### Statically linked SDK libraries are middleware

The D3DX helper library is static in DirectX 8 and 9. Its code is in the
game image, but you do not reconstruct it. Screen it out:

1. Read the Rich header (see
   [01 · The build environment](01_environment.md#which-toolchain-built-a-given-retail-binary)).
   Objects of a later compiler in a VC6 image are a sign. Example: NOLF 2's
   `Lithtech.exe` lists 68 C++ objects of cl 13.00.9178 (Visual C++ .NET).
2. Run `compid.py` on the SDK libraries. In the DirectX 8.1 SDK,
   `d3dx8.lib` is C++ 9178. `dinput8.lib` holds the `c_dfDI*` data
   formats as C 9178 objects. `dxguid.lib` holds data only.
3. Link a small test program against the same libraries. Its Rich header
   must show the same entries.
4. Run `libscan.py` to find where each library function sits in the
   image. Mark these address ranges `middleware` in `progress/targets.py`.

Example: nolf2src `progress/COMPILERS.md` places 322 `d3dx8.lib`
functions in two blocks of `Lithtech.exe`. The same section shows that
eight `d3dx8.lib` members (the SSE paths) were compiled by Intel C/C++.
They have no Rich entry. Tron 2.0 links `d3dx9.lib` of a DirectX 9 SDK in
the same way: cl 13.00.9178 and 13.10 objects in a VC6 image (tron20src
`progress/COMPILERS.md`).

### Find which compiler built the renderer

Do not assume that a renderer uses the compiler of the engine. NOLF's
`d3d.ren` was compiled by Intel C/C++ 4.0, with different flags for each
file. The AvP2 `d3d.ren` comes from the same code family, but cl 8168
compiled it (avp2src 80034dc). For the signs, read
[01 · The build environment](01_environment.md#which-toolchain-built-a-given-retail-binary)
and [16 · Mapping a binary into its translation units](16_tu_mapping.md).
For the Intel codegen, read the `icl` entries in
[09 · Codegen patterns](09_codegen_patterns.md#icls-register-calling-convention-is-qip-and-it-is-reproducible).

## 2. Read the COM calls

### The shape of a call

Every DirectX method is `__stdcall`. The interface pointer is the first
stack argument. It is not in `%ecx`. A call has this shape:

```
mov    0x1008d988,%eax        # the device pointer, a global
push   $0x0                   # the value
push   $0x1c                  # D3DRENDERSTATE_FOGENABLE (28)
mov    (%eax),%ecx            # the vtable
push   %eax                   # the interface pointer
call   *0x50(%ecx)            # IDirect3DDevice7::SetRenderState
```

A C++ virtual call of the game's own classes puts `this` in `%ecx`, and
the callee removes the arguments. Thus, you can tell the two kinds apart
in the same function (nolfsrc `src/engine/d3d/d3dbatcha.cpp`).

The C macro (`IDirectDraw7_Blt(p, ...)`, which is
`p->lpVtbl->Blt(p, ...)`) and the C++ call (`p->Blt(...)`) give the same
argument list. Select the form that reproduces the bytes.

### Name the slot from the offset

The vtables of DirectX interfaces are in the system DLLs, not in the game.
Thus, [07 · Naming anonymous functions from vtables](07_vtables.md) does
not find them. Name the method from the call offset instead:

1. Count the methods in the SDK header, from the `IUnknown` methods on.
   The slot index is the offset divided by 4.
2. Confirm the interface with a second call on the same pointer. The
   argument count must agree too.
3. Write the interface as a struct of function pointers, with padding for
   the slots that the code does not use.

These offsets come from the SDK headers:

| Interface | Methods (offset) |
|---|---|
| `IUnknown` (all) | `QueryInterface` 0x00, `AddRef` 0x04, `Release` 0x08 |
| `IDirectDraw7` | `CreateSurface` 0x18, `EnumDisplayModes` 0x20, `GetCaps` 0x2c, `SetCooperativeLevel` 0x50, `SetDisplayMode` 0x54 |
| `IDirectDrawSurface7` | `Blt` 0x14, `Flip` 0x2c, `IsLost` 0x60, `Lock` 0x64, `Restore` 0x6c, `Unlock` 0x80 |
| `IDirect3DDevice7` | `GetCaps` 0x0c, `BeginScene` 0x14, `SetViewport` 0x34, `SetRenderState` 0x50, `DrawPrimitive` 0x64, `SetTexture` 0x8c, `SetTextureStageState` 0x94 |
| `IDirect3DDevice8` | `GetDeviceCaps` 0x1c, `Reset` 0x38, `Present` 0x3c, `SetGammaRamp` 0x48, `SetRenderState` 0xc8, `SetTextureStageState` 0xfc, `DrawPrimitiveUP` 0x120 |
| `IDirect3DDevice9` | `Reset` 0x40, `Present` 0x44, `SetGammaRamp` 0x54, `SetRenderState` 0xe4, `SetSamplerState` 0x114, `DrawPrimitiveUP` 0x14c |

### HRESULTs, QueryInterface and Release

- `if (hr != DD_OK)` compiles to `test %eax,%eax` and a `jne`.
  `FAILED(hr)` tests the sign. Copy the test that the binary shows.
- `QueryInterface` gets a later interface from an object. Example: NOLF
  gets `IDirectDrawGammaControl` from the primary surface with slot
  `0x00`, and then calls slot `0x10` of the result.
- `Release` is slot `0x08`. Code often stores `NULL` in the pointer
  directly after it.

### Enums and flags in immediate operands

Render states, texture-stage states and flags are immediate operands.
Look them up in the SDK header of the generation that the call belongs to:

- Render-state numbers stay the same from DirectX 7 to 9. Example:
  `ZENABLE` is 7 and `FOGENABLE` is 28 in all three.
- Direct3D 9 moved the filter and address states to `SetSamplerState`,
  with new numbers. Example: `D3DTSS_MAXANISOTROPY` is 21, but
  `D3DSAMP_MAXANISOTROPY` is 10.
- One value can mean different flags in different fields. Example: `0x1000`
  is `DDCAPS2_WIDESURFACES` in `DDCAPS.dwCaps2`, but `DDSCL_FPUPRESERVE`
  in a cooperative level. The field selects the name.
- Split a combined flag into its bits. Example: `0x13` in
  `SetCooperativeLevel` is
  `DDSCL_EXCLUSIVE | DDSCL_ALLOWREBOOT | DDSCL_FULLSCREEN`.

### Caps checks

A caps check is a `test` of a bit at a fixed offset of a caps structure.
Name the field from the offset, then the bit from the field. Example:
`test $0x8000` on the raster caps of `D3DDEVICEDESC7` is
`D3DPRASTERCAPS_ZBUFFERLESSHSR` (nolfsrc `w38_100322c0_qip.cpp`).

CAUTION: Make sure that the offset is the field that the code must test.
Tron 2.0 tests the anisotropic bits at `D3DCAPS9 +0x124`, which is
`VertexTextureFilterCaps`. No card of the time had them, so anisotropic
filtering never switched on (tron20src `docs/RETAIL_BUGS.md`).

### Enumeration, locks and gamma

- **Enumeration callbacks** are `__stdcall`. The `ret $n` gives the
  argument count. Example: `LPDDENUMCALLBACKEXA` ends with `ret $0x14`,
  and `LPDDENUMCALLBACKA` with `ret $0x10`.
- **Surface locks** pass a `DDSURFACEDESC2` with its `dwSize` set. The
  code reads `lpSurface` and `lPitch` from it after the call.
- **Gamma ramps** are 0x600 bytes: three tables of 256 words. A `fread`
  of 0x600 bytes, or a 0x600-byte local, is a ramp. DirectDraw sets it
  through `IDirectDrawGammaControl`. Direct3D 8 and 9 set it on the
  device.

### Tools for a renderer

These tools are in this repository. They were written for NOLF's
`d3d.ren` and NOLF 2's renderer:

| Tool | Use |
|---|---|
| `d3dcheck.py` | Compare our objects with the shipped bytes at known addresses. Use it when functions are too short for `exematch`. |
| `d3dflags.sh` | Compile each file at `/O2` and at `/Os`, and list the files that match better at `/Os`. Use it for an image with mixed flags. |
| `d3dsplit.py` | Move named functions to a companion file, so that each half can have its own flags. |
| `d3dwork.py` | Rank the remaining functions by value. |
| `d3ddata.py` | Define the globals of the DLL from the shipped image, so that the whole DLL links. |
| `d3dloadtest.c` | Load a linked render DLL at an occupied base, and call its exports. This tests the relocations and the export table without a window. |
| `rendertest/` | Link a test program with the engine objects, and run it under Wine and Xvfb. It tests mode lists, clears, blits and draw primitives without the game. |

## 3. What breaks today, and the fixes

Most items give the symptom, the cause, the fix, the test and an example.

### DirectDraw is the weakest path under Wine and Proton

- **Symptom.** A DirectX 7 game is slow under Proton, the Steam overlay
  does not show, or the picture stays black after Alt+Tab.
- **Cause.** Wine translates DirectDraw and Direct3D 7 through WineD3D.
  This path is the least complete. Direct3D 9 goes through DXVK under
  Proton.
- **Fix.** Make small fixes for each fault first. Then write a new
  renderer on a later API (see the next item).
- **Test.** Compare the frame rate with the Wine `+fps` trace. Ask a
  player to check the overlay in Steam, because Xvfb has none.
- **Examples.** AvP2 locked a corner of the back buffer before each flip.
  Under Wine, this copies the surface back to memory each frame. Without
  the lock, the frame rate increased (avp2src M-23). Under Proton, the
  overlay showed only with the retail flip, `DDFLIP_WAIT`. A
  `DDFLIP_NOVSYNC` flip or a `Blt` hid it (avp2src M-24). After Alt+Tab, the restarted renderer
  drew nothing (avp2src M-21). NOLF 2 has the same lock before present
  (nolf2src M-E63).

NOTE: Old drivers can also fail on native Windows. Example: with Intel's
DirectX 7 driver, NOLF's screen went black under water, and the screen
tints did not show (nolfsrc M-P1-10). The new renderers do not need that
workaround.

### A new renderer: one core, several backends

nolfsrc replaced the DirectX 7 renderer with two new render DLLs from one
core: `opengl.ren` and `d3d9.ren` (nolfsrc `src/modern/render/README.md`,
M-P0-04, M-P0-05). The core draws through a small fixed-function device
interface. Each backend implements that interface. Keep the retail
renderer as a third choice, so that you can compare pictures (nolfsrc
installs it as `d3d7.ren`). Write a regression set of scenes, and compare
each new renderer with the retail one.

These points apply to any renderer that replaces a retail one.

#### Set the FPU precision that the retail renderer set

- **Symptom.** Physics changes with the renderer. In NOLF, the player got
  stuck on the railings of a bridge, but only with the new renderers
  (nolfsrc issue #43).
- **Cause.** The engine runs its physics on the render thread. The retail
  `d3d.ren` set the x87 FPU to single precision (24 bits) at the start
  of each scene (`fnstcw`, `and $0xfcff`, `fldcw`). The engine did the
  same at startup. The physics was only ever tested at that precision.
  The new renderers left the FPU at double precision. Then borderline
  collision tests gave the opposite result.
- **Fix.** Set single precision at the start of each scene, in every
  backend (`mr_SetFPUPrecision24`, nolfsrc `src/modern/render/mr_scene.cpp`).
- **Test.** Use a save at the fault. Swap the binaries one at a time
  between the two builds to find the one that matters.

CAUTION: Without `D3DCREATE_FPU_PRESERVE`, Direct3D 8 and 9 set single
precision on the thread that creates the device. NOLF 2's engine creates
its device without the flag. Thus, examine the device flags of the retail
renderer too, not only its own FPU code. If a new renderer gives
`D3DCREATE_FPU_PRESERVE`, it must set the precision itself. nolfsrc's
`d3d9.ren` does both.

#### Depth range and pixel centres

OpenGL clip space has depth from `-w` to `w`. Direct3D has `0` to `w`.
Direct3D 9 samples pixels at integer coordinates, and OpenGL at the pixel
centres. If a backend takes OpenGL-shaped state, multiply its projection
by a matrix that maps the depth and moves the image by half a pixel.
nolfsrc uses depth scale 0.5, depth offset 0.5, and an offset of
`-1/width`, `+1/height` (`src/modern/render/d3d9/d3d9_device.cpp`).
Compare a 2D menu pixel by pixel with the retail renderer.

#### Depth clamping for the player's weapon

- **Symptom.** The weapon shows its back faces through its front (an
  inside-out gun), or a menu model disappears behind a flat panel.
- **Cause.** The retail renderer draws really-close objects into the
  depth buffer of the scene, with the scene's mapping, clipped at 0.01.
  Parts nearer than the near plane get a depth below 0. A clamp gives
  them all the same depth, and the draw order then decides.
- **Fix.** Draw the scene into the back 15/16 of the depth range. Put
  the near parts into the free front part, in order by `1/w`. Direct3D 9
  has no depth clamp, so `d3d9.ren` transforms these vertices itself. The
  OpenGL backend draws each batch two times, once for each part.
- **Test.** Look at the weapon from the side, and at the main menu.
- **Example.** nolfsrc c137962, e70bf08, e537b54.

#### Texture levels of the wrong size

The engine can give a mipmap level that is not half of the level above.
OpenGL accepts any size. Direct3D sizes the levels itself, so the copy
wrote past the end of a level, and the game crashed later at a level
change. End the mipmap chain at a level of the wrong size, and never copy
more than Direct3D allocated (nolfsrc 0fff96f: 4 crashes in 13 runs
before, none in 14 after).

#### Other code can ask for the old interfaces

Look for code outside the renderer that gets a raw DirectDraw pointer from
it. In NOLF, the movie players ask the renderer for `LPDIRECTDRAW` and
`BACKBUFFER`. The new renderers answer with small stand-ins in the
DirectDraw vtable layout (nolfsrc `src/modern/render/mr_movie.cpp`).

### Present intervals and v-sync

For the present interval and v-sync in a window, read
[18 · V-sync and present intervals](18_modern_builds.md#v-sync-and-present-intervals-under-a-compatibility-layer).
For DirectDraw, look also for a surface lock directly before the flip
(see above).

### Windows and borderless windows

- **Symptom.** The window is larger than the mode, the clicks miss the
  menu items, or a window must have the size of a display mode.
- **Cause.** Old renderers size and centre the window themselves. Examples:
  AvP2 makes the rectangle larger for a frame that the window does not
  have, and it calculates the top from the widths. NOLF 2's renderer
  needs a display mode of the window's size even in a window.
- **Fix.** Give three modes: full screen, a window, and a borderless
  window at the resolution of the desktop. Set the window style for each
  mode. In a window, accept any size. Use the primary monitor for the
  desktop size, because the Wine desktop window covers all monitors.
- **Test.** Start in each mode, and change the mode in the menu.
- **Examples.** avp2src M-9 (`RETAIL_BUGS.md`), nolf2src M-E2, M-E30,
  nolfsrc M-P1-22, cjacksrc EN-31, EN-32.

A windowed device does not need to stop when the window loses the focus.
Stop and restart the renderer only for full screen (nolf2src M-G41,
cjacksrc EN-2, avp2src M-21).

### Widescreen and field of view

For the general steps, read
[18 · Widescreen](18_modern_builds.md#widescreen-aspect-ratio-and-field-of-view).
In the renderer, find the function that makes the projection from the
field of view. Widen the horizontal angle there, from the width and height
of the scene rectangle.

Models with a field of view of their own, for example the player's
weapon, need a separate fix. In NOLF, the renderer gives them the game's
4:3 angle, and divides their X scale by the widening factor (nolfsrc
M-P0-01). Contract J.A.C.K. had a stretched weapon because its
really-close projection used a fixed aspect (cjacksrc EN-9).

### Mode lists and refresh rates

- **Mode filters.** Look for a filter that keeps only exact 4:3 modes.
  Keep every mode that is at least 640x480 (nolfsrc M-P1-07, nolf2src
  M-G1). Make sure that a skipped mode still advances the loop. In one
  fan patch, it did not, and the loop did not end (nolfsrc M-P1-07).
- **An empty list.** A display with only 5:4 modes gave NOLF 2 an empty
  list, and the Display screen read index -1 (nolf2src M-E31).
- **Very large modes.** At 3840x2160, NOLF 2 crashed in its text layout,
  not in the renderer (nolf2src M-E31). Test the largest mode.
- **Refresh rates.** `EnumDisplaySettings` gives one entry for each
  refresh rate. Remove the duplicates of each size and depth
  (`mr_AddMode`, nolfsrc `src/modern/render/mr_main.cpp`). The retail
  renderers ask for no refresh rate: `SetDisplayMode` gets 0, and
  Direct3D 8 gets `D3DPRESENT_RATE_DEFAULT`. Then the driver selects it.
  If the frame limiter needs the rate, read it from the display. NOLF 2
  reads `GetDeviceCaps(VREFRESH)`, and uses 60 when the driver says
  "default" (nolf2src M-E70).

### Anisotropic filtering and anti-aliasing

For the general rule, read
[18 · Anisotropic filtering and anti-aliasing](18_modern_builds.md#anisotropic-filtering-and-anti-aliasing).
Examine the retail code first. Our projects found these faults:

- NOLF 2 wrote an anisotropic degree of 1. This is not better than
  bilinear (nolf2src M-G45).
- Tron 2.0 tested the wrong caps field, so anisotropic filtering never
  switched on (tron20src `RETAIL_BUGS.md`).
- Direct3D 8 multisamples only with `D3DSWAPEFFECT_DISCARD` and a back
  buffer that is not lockable. NOLF 2 asked for a lockable back buffer and
  used `COPY` in a window. Thus, its anti-aliasing never worked (nolf2src
  M-E13).
- DirectX 7 has no multisampled anti-aliasing. nolfsrc gives it only in
  the new renderers. They draw into a multisampled target and resolve it
  before each flip or read (M-P1-18).

CAUTION: Test anti-aliasing on more than one GPU vendor. On Intel Arc, a
blend with a `ZERO` or `INV_SRC_COLOR` factor into a multisampled target
dropped pixels. The text became outlines with holes. nolfsrc draws that
blend mode as an alpha blend when it multisamples (cfb88fd).

### 16-bit and 32-bit

For the general rule, read
[18 · 32-bit colour defaults](18_modern_builds.md#32-bit-colour-defaults).
In a renderer, the display depth and the texture depth are two settings.
NOLF's renderers read `32BitTextures`, which defaults to 0 (nolfsrc
M-P1-24). Change the display modes, the fallback mode and the texture
depth.

### Gamma in a window

- **Symptom.** The gamma setting has no effect in a window or a
  borderless window.
- **Cause.** A gamma ramp changes the hardware palette of the whole
  display. Direct3D 8 and 9 apply it only in full screen
  (`D3DCAPS2_FULLSCREENGAMMA`). NOLF 2 sets its gamma with
  `IDirect3DDevice8::SetGammaRamp`. NOLF's `LOADGAMMA` command uses the
  windowed primary surface in a window.
- **Fix.** Apply the ramp to the picture, for example in a last pass
  before the present. None of our projects does this yet.
- **Test.** Change the gamma in a window, and compare a screenshot.

## 4. Where the fixes are

| Fix | Project | Id | Commit |
|---|---|---|---|
| FPU single precision at each scene in new renderers | nolfsrc | M-P0-05, issue #43 | ba3faab |
| OpenGL renderer from one core | nolfsrc | M-P0-04 | f20460c, cccceea |
| Direct3D 9 renderer, the default; `d3d7.ren` kept; anti-aliasing | nolfsrc | M-P0-05, M-P1-18 | 8497977, 1fdc1a7 |
| Weapon depth nearer than the near plane | nolfsrc | M-P0-04, M-P0-05 | c137962, e70bf08, e537b54 |
| Texture levels of the wrong size in Direct3D 9 | nolfsrc | M-P0-05 | 0fff96f |
| `MASK` blend under multisampling (Intel Arc) | nolfsrc | M-P1-18 | cfb88fd |
| Hor+ field of view in `d3d.ren`; colour-fill `FillRect` | nolfsrc | M-P0-01, M-P0-03 | c4159e3 |
| Widescreen modes; anisotropic option | nolfsrc | M-P1-07, M-P1-09 | 7f1884d |
| Launcher mode list | nolfsrc | M-P1-14 | a17b51d |
| Window mode: full screen, window, borderless | nolfsrc | M-P1-22 | 549ea60 |
| 32-bit textures by default | nolfsrc | M-P1-24 | bc52297 |
| Movies keep their shape | nolfsrc | M-P1-27 | 5dbbd21 |
| Intel DirectX 7 workaround only with `d3d7.ren` | nolfsrc | M-P1-10 | 39d8636 |
| Hor+ field of view | nolf2src | M-E1 | d344e83 |
| Widescreen modes | nolf2src | M-G1 | 6cd85a9 |
| Window at any size | nolf2src | M-E2 | af861a1 |
| Anti-aliasing; anisotropic degree (retail bug) | nolf2src | M-E13, M-G45 | 1c2c58d |
| Window modes | nolf2src | M-E30, M-G70 | ec5e613 |
| Crash at 3840x2160 and with no mode listed | nolf2src | M-E31 | b491306 |
| V-sync in a window under Wine: off is off; on is a cap | nolf2src | M-E62, M-E70 | 3dd4c4b, dcd50ad |
| Draw-primitive viewport, batched quad colours (retail bugs) | nolf2src | M-E68 | 0125281 |
| Widescreen, window modes | cjacksrc | EN-30..EN-34 | 65bf272 |
| Draw-primitive quad colours and viewport (retail bugs) | cjacksrc | EN-6, EN-8 | 680b56c |
| Player-view model aspect | cjacksrc | EN-9 | 36fdcaa |
| V-sync in a window under Wine: off is off; on is a cap | cjacksrc | EN-43, EN-62 | e7e0e29, ab4f837 |
| Widescreen, 4:3 cinematics, field of view | avp2src | M-1..M-3 | 538922a |
| Window placed for a frame it does not have (retail bug) | avp2src | M-9 | 37f0e09 |
| Alt+Tab in a window under WineD3D | avp2src | M-21 | b06b6fc |
| No back-buffer lock before each flip | avp2src | M-23 | e2c27d3 |
| `VSync` and the Steam overlay in full screen | avp2src | M-24 | 692150a, 5742a6b, e772cfc |
| Renderer retail bugs | avp2src | M-B20..M-B26 | a32cce0 |
| Anisotropic filtering tests the vertex caps (retail bug) | tron20src | `RETAIL_BUGS.md` | 3602c42, dfe35ad |
| Draw-primitive camera viewport (retail bug) | tron20src | `RETAIL_BUGS.md` | 8c1feb6 |
