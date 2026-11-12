# 16 · Mapping a binary into its translation units

A stripped retail image is one `.text`, but it was linked from objects, and
every object was one `.cpp` compiled with one set of flags. Until you know
where those objects begin and end you are guessing at three things that
decide byte identity: which functions share a file (and so a definition
order, an inliner horizon and a set of statics), which flags each file was
built with, and in what order the files were linked. This guide is the set
of signals that recover that structure from the bytes alone, the procedure
that combines them, and the ways each one misleads.

It sits between [05](05_exe_and_engine.md) (the enumeration and the
symbol-less method) and [13](13_cluster_recon.md) (one cluster at a time):
the map built here is what tells a cluster where its file starts.

No single signal is enough. Padding sees only some boundaries; initialisers
only files with globals; `.bss` only files with zero-initialised data. The
map is right where several agree.

## The signals

### 1. Padding: 0x90 is the compiler's, 0xCC is the linker's

VC6 at `/O2` (and `/Ox`) puts every function in a 16-aligned COMDAT that the
**compiler** pads with `0x90`. At `/O1` (`/Os`) COMDATs are align 1 and
unpadded, so `/O1` functions sit back to back at odd addresses. Where an
`/O1` run is followed by `/O2` code, the **linker** has to align the next
COMDAT itself, and it fills with `0xCC`. So:

* a run of `int3` between functions is an object boundary (`/O1` object,
  then `/O2` object);
* a function that starts unaligned is `/O1` code;
* the flag does not change within a translation unit, so every
  `/O1`↔`/O2` change in the function list is a boundary even where there is
  no CC.

The case: Primal Hunt's `d3d.ren` (avp2src 58e9ab5, `docs/D3D_OBJECTS.md`,
"How the boundaries were found"), proved first with test compiles of cl 8966.
Of 1,301 rows, 315 are `/O2`, 966 `/O1` and 20 ambiguous (aligned *and*
ending exactly on a 16-byte boundary). Reading it:

```sh
python3 tools/exedump.py out/reference/d3d.ren 0x10008c68 0x10008c82
#  10008c74:  cc   int3      ... to 0x10008c7f
#  10008c80:  c3   ret       <- the next object (TU05, /O2) starts aligned
```

AvP2 1.0.9.6's renderer has the same 12 CC fills at the same object changes
(avp2src `docs/AVP2_D3D_OBJECTS.md` §3), and it was this padding (no Intel
`lea`-nop pads anywhere) that showed that renderer is not Intel-built at all
but cl 8168.

What padding cannot see: an `/O2` object followed by any object (the compiler
already padded to 16, so there is no gap), and an `/O1` object followed by
another `/O1` object (nothing between them). Those boundaries need the
signals below. Rebuilding each object with its own measured flags took that
renderer from 154 to 730 identical (avp2src e7c7c23, 791eb9c).

### 2. The CRT initialiser table: runs of entries open a file's globals

`__xc_a` .. `__xc_z` (`.CRT$XCU`) holds one pointer per global with a
dynamic initialiser, **in link order**. In PH's `d3d.ren` that is
0x1004a000..0x1004a370, 219 entries, falling into 40 groups: each group is
the top of one file's globals. The initialiser's shape also gives the flag:
under `/O2` it is one 22- or 25-byte COMDAT, under `/O1` a 5-byte `jmp` stub
plus a 26- or 30-byte body (both reproduced by test compiles). The `jmp`
over padding that this produces is [13's `??__E`
entry](13_cluster_recon.md#jmp-over-padding-into-a-zero-initialiser-is-__e-not-a-mystery).

```sh
python3 tools/dataref.py out/reference/d3d.ren 0x1004a004 0x1004a008 0x1004a00c
#  0x1004a004  = 0x10001030 ...
```

Each slot's target sits at the start of its object's code range; where the
targets jump from one region of `.text` to another, a new object begins.
The per-object initialiser counts then become a fingerprint: AvP2's renderer
has 218 to PH's 219, equal object for object except `fogvolume.cpp`'s one,
the file AvP2 does not have.

### 3. `.bss` (and the `.data` string pool) step through link order

VC6 C++ emits no communals (tested: `int g;` goes to the object's own
`.bss`), so each object's `.bss` is **one block, in link order**. Collect
every `.bss` address each function references; the blocks step up
monotonically through the object list, and a step down is a boundary or a
wrong grouping. A variable read by a single function is not necessarily that
function's own (an extern read once looks the same), so use the blocks, not
single addresses.

The exception is itself evidence: static arrays inside inline or template
functions are COMDAT `.bss`, placed **after the runtime's, in reverse
order** (PH `d3d.ren` 0x10099fc0..0x1009a960 for rows 52..59). Rows using
such storage are inline/template code, not the object they sit in, and they
turn out to be called from several files.

The same holds for referenced `.data` strings: PH's 427 are first used in
increasing row order, with one inversion that turned out to be two rows of
one function. The shared initialised tables (cvar defaults, function-pointer
tables) do not follow it.

### 4. Dead code: an unreferenced function proves a non-`/Gy` object

`/O1` and `/O2` imply `/Gy`, and `/OPT:REF` then removes every COMDAT
nothing references. A function that nothing calls, points at or exports is
therefore in a plain `.text`: its object was built **without** `/Gy`. In PH's
renderer, exports and extent defects aside, that is only TU02 (two packed
functions at 0x10004620..0x10004656), the evidence it was a separate run.

`/Ox` does not imply `/Gy` (and cl 13.10 has no `/Gy-`), so a whole image
built `/Ox` keeps everything: Contract J.A.C.K.'s `SndDrv.dll` and
`GameSpy.dll` keep functions nothing calls, and each object's out-of-line
functions stay in one `.text` in the order the compiler finished them,
uncalled ones included (cjacksrc `docs/PLAN.md` "3. small",
`progress/COMPILERS.md`). The enumerator cannot find such functions from
calls; their starts went into `progress/extent-splits.csv` by hand.

### 5. `<string>`'s guarded initialiser ends every file that includes it

With VC6's own STL, every translation unit that includes `<string>` ends in
a guarded initialiser of `std::ctype<unsigned short>::id`: a guard-bit test,
a `jmp` to a separate function that registers an empty destructor with
`atexit`. Under `/O2` it is 44 bytes (avp2src `docs/PLAN.md`, PH
`lithtech.exe`, guard 0x004f8014, ~95 copies):

```
  401760:  8a 0d 14 80 4f 00   mov    0x4f8014,%cl
  ...
  401774:  e9 07 00 00 00      jmp    0x401780        <- over 0x90 padding
  401780:  68 90 17 40 00      push   $0x401790       <- the empty dtor
  401785:  e8 .. .. .. ..      call   atexit
  40178a:  59 c3               pop %ecx ; ret
```

Under `/O1` (PH `server.dll` 0x10008bd2) the guard is 21 bytes with
`jmp +0` straight into the 12-byte thunk, and the next object's code follows
with no gap. That is what makes it valuable: it marks the end of a file
exactly where padding shows nothing.

How it was used:

* Each reconstructed object whose retail range holds a guard got
  `#include <string>` (behind `PRIMAL_HUNT`): +39 identical on
  `lithtech.exe` alone, none lost (avp2src 56bb52b, ee3bd8a).
* A guard in retail with no guard-bearing file of ours around it means
  **our file merges two of retail's**. Splitting them out took
  `lithtech.exe` unwritten 27 → 5 in one round (b194edc: `sprite.cpp` out of
  `cmodelload.cpp` and `csvis.cpp`, `videomgr.cpp` and `visquery.cpp` out of
  `fntdraw.cpp`, ...), and server.dll 13 → 4 (859f495); in 613d790 each
  new unit's guard is identical at retail's address (`lithtech.exe`
  0x4428e0, 0x449f70, 0x4a01c0).
* The enumerator joins the guard to the thunk it jumps to, one row where
  there are two symbols. avp2src 65b2599 added 140 such splits to
  `progress/extent-splits.csv` (the file now has 141: 95 `lithtech.exe`,
  46 `server.dll`).

Images built against STLport (AvP2 1.0.9.6) do not have this guard.

### 6. Header initialisers at the start of a range name the header

Constants a header defines with a dynamic initialiser (`const float PI =
(float)(4*atan(1.0));`, `const LTVector3f WORLD_UP(...)` in `math_phys.h`)
have internal linkage, so each object that sees them emits its own
initialiser pairs at the **start** of its code range. Two readings:

* A file built outside the precompiled header carries its own copy. Tron
  2.0's `SubroutineDataMgr.cpp` has `math_phys.h`'s initialisers at
  CShell.dll 0x10084080..0x10084222; the fix was `# SUBTRACT CPP /YX /Yc
  /Yu` for that one file in the `.dsp` (tron20src 5aca299).
* A range that begins with a header's initialiser pairs shows the file
  included that header. Three Tron TUs (`TronHUDMgr`, `TronInterfaceMgr`,
  `TRONPlayerStats`) open with `BaseScreen.h`'s `kDefaultPos` and
  `ScreenSubroutines.h`'s `SLICE_SIZE`/`PRIM_SIZE` (0x1009ad40, 0x1009c980,
  0x100a8f60); adding `#include "ScreenSubroutines.h"` gave the two missing
  pairs in each, all identical (tron20src d5dbb42).

The precompiled header changes more than initialisers. Through `/YX` the
header's inlines come at the end of the object and keep their EH (PH's
ButeMgr: the whole library identical once built `/YX` as the release
project had it, avp2src 2a08ad1). `AVP2.exe`'s launcher is proven to use the
PCH for all files but `LauncherDlg.cpp`: without it the inlined MFC
destructors' unwind states differ (avp2src `progress/COMPILERS.md`,
`AVP2.exe` row).

### 7. Anchored functions in address order give the project

Once some functions are named (strings, vtables, a scorer pairing), list
them by address with the source file each comes from. The order of files is
the order of the link line, and the link line is the project file:

* **Contract J.A.C.K.'s game DLLs** have their code in the alphabetical
  order of *all* their sources, the TO2 project's and the shared library's
  mixed, then the libraries in alphabetical order of their projects. Two
  projects linked together would give two alphabetical runs; one run means
  **one project per DLL**, which is how cjacksrc's `Object.dsp` and
  `ClientShellDLL.dsp` were written (cjacksrc `docs/PLAN.md` "4. game").
* **NOLF2's engine** runs `controlfilemgr`, then alphabetical
  `bindmgr` .. `world_shared_bsp`, then an "ILT interface" group: exactly
  Jupiter's `EXE_Lithtech` file list. Its **renderer** is neither
  alphabetical nor the CMake list's order: it is NOLF2's own `.dsp` order
  (nolf2src `docs/engine/fear_mapping.md` §2c). A file order that is not
  alphabetical is the IDE's list, as written.
* The same anchoring works across games: PH's renderer objects, paired with
  nolfsrc's symbols named for NOLF's addresses, run in NOLF's `.dsp` order
  (avp2src `docs/D3D_OBJECTS.md` item 6).

Names to anchor with: NOLF2's engine registers each interface with a
`define_holder`/`instantiate_implementation` dynamic initialiser that pushes
the interface name, and those sit at the **start of each object's code**:
48 interface names in the exe, 25 in the DLL (nolf2src
`docs/engine/anatomy.md` §3). The unstripped Mac port is a separate source
of names and file groupings, not of addresses.

**Import order is link order too.** The import table lists DLLs in the order
their import libraries are first used on the link line: the project's own
libraries, then the IDE's default list. That gives Contract J.A.C.K.'s
`SndDrv.dll` retail's imports (ltmem, winmm, msacm32, dxguid, eaxguid, then
the defaults; cjacksrc `docs/PLAN.md` "3. small"); the server's line naming
`server.lib` before `winmm.lib` puts `server.DLL` first (cjacksrc
`progress/COMPILERS.md`). A `#pragma comment(lib, ...)` adds the library
after the command line: `GameSpy.dll`'s `wsock32.lib` comes from a pragma in
`nonport.c`, which is why WSOCK32 is last among its imports (cjacksrc
`docs/PLAN.md`, GameSpy.dll).

### 8. The Rich header bounds the object count

`tools/richhdr.py` counts objects per tool build. AvP2's renderer has 73 C++
objects: 3 StdLith + 70 renderer objects, of which 46 have code and 24 have
none left (header-only, cvar-less, or emptied by `/OPT:REF`). The count does
not place anything, but a map with more code objects than the header allows
is wrong, and it is what identified the stray tool rows (DirectX SDK
`ddraw.lib`, `dxguid.lib`) as library objects rather than missing source
(avp2src `docs/AVP2_D3D_OBJECTS.md` §2-3).

## Function order within a translation unit

The map gives each file its range; the order inside is the compiler's.

* **VC6**: COMDAT section order is source definition order
  ([03](03_reading_disassembly.md), [09](09_codegen_patterns.md)).
  Definition order also changes code, not just placement: the inliner is
  forward-only ([09](09_codegen_patterns.md#the-inliner-is-forward-only-and-inline-is-what-admits-a-big-helper)),
  and AvP2's cl 9044 allocates a caller's registers around callees defined
  earlier in the same file, so definitions go in retail's order (avp2src
  4cd90f8: `ComputeRadius`, `at_UpdateStringKeys` into `modelanim.cpp`). Under
  `/GX`, VC6 drops a state store before a call whose callee it has already
  compiled (avp2src `docs/PLAN.md`).
* **VC7.1** (Visual C++ .NET 2003, Contract J.A.C.K.) compiles a function only
  once every function it calls that is defined later in the file has been
  compiled: a forward call defers it, not inlining. Template instantiations
  come at the end, by call depth (cjacksrc `docs/PLAN.md` "3. small",
  `SndDrv.dll`). So an out-of-order function in a VC7.1 image is the first
  thing to check for a forward call, not evidence of a different file.
* **COMDATs sit with their first user**: an inline or template function
  emitted by several objects lands in the first one in link order. PH's
  `_CVector` `+`/`*` are in `fogvolume.obj`; AvP2, which lacks that file,
  has them in `drawpolygrid`, the next first user (avp2src
  `docs/AVP2_D3D_OBJECTS.md` §3 notes). A run of shared helpers inside a
  range is not a file of its own.

## Pinning the app range

Before mapping, cut off what the toolchain supplied. Every row after the
app code should match a member of the runtime libraries **at its own
address**, masked by its relocations. `tools/libscan.py` does exactly that:

```sh
python3 tools/libscan.py out/reference/CShell.dll \
    toolchains/msvc-6.00-8168/LIB/libcmt.lib toolchains/msvc-6.00-8168/LIB/libcpmt.lib \
    toolchains/msvc-6.00-8168/LIB/libcimt.lib toolchains/msvc-6.00-8168/LIB/oldnames.lib
```

The start of the first runtime run is where the app range ends. Doing this
for four images moved 99 rows of CShell.dll, 89 of Object.lto and 108 of
PHObject.lto out of the count, and unwritten went 827 → 536 (avp2src
a0dd817). Also take out the DirectX import thunks and their data:
`lithtech.exe`'s DINPUT thunk at 0x4ba2a0, and 0x4ba2b0, which is
`dinput.lib`'s data formats, a NOT A FUNCTION row (avp2src 15467cc, 30378bf).
Write the evidence beside the range in `progress/targets.py`.

## Proving enumeration errors: `enumproof.py`

A map is only as good as the rows it is drawn on. `tools/enumproof.py`
decodes each unwritten or near row by recursive descent and proposes the
fix for the next row when it is provably not a function: a conditional
branch from the row before lands on its start, an instruction straddles its
start, the previous row runs straight into it, or (for splits) code after
padding that nothing reached from the row's start branches to. It is
conservative: the later row must be referenced nowhere else, and the earlier
one proven (tools 892868a).

```sh
python3 tools/enumproof.py --target lithtech.exe          # print proposals
python3 tools/enumproof.py --target lithtech.exe --write  # append them
```

`--target` takes a label or stem and repeats; `--csv` names the statuses
(default `out/progress/functions.csv`, so run the scorer first). `--write`
appends to `progress/<stem>-screen-exclude.csv` and
`progress/extent-splits.csv` ([14](14_progress.md#when-the-enumeration-is-wrong-the-csvs));
read every proposal before committing it.

## Procedure

1. **Pin the app range** with `libscan.py`; record it with evidence.
2. **Fix the enumeration** near the ranges you care about: `enumproof.py`,
   then `extentcheck.py` by hand. Split every guard/atexit pair.
3. **Class every row by padding**: aligned with 0x90 = `/O2`, unaligned =
   `/O1`, aligned and ending on 16 = ambiguous. Mark every CC run and every
   flag change as a boundary.
4. **Mark the other markers**: the head of each `__xc_a` group, each
   `<string>` guard (end of a file), each run of header-constant
   initialisers or `define_holder` registrations (start of a file).
5. **Check with data**: `.bss` blocks and the `.data` string pool must rise
   monotonically across your objects; move boundaries until they do. Set
   aside the COMDAT `.bss` rows as inline/template code.
6. **Name the objects** from strings, error tags, vtables and anchored
   pairings, and check the file order against the project (alphabetical,
   `.dsp`, era source list) and the import order against the link line.
7. **Check the count** against the Rich header.
8. **Write it down**: one row per object (`start,end,name,flags,evidence`,
   as `progress/d3d-objects.csv` does), with a confidence per row and the
   splits you could not prove listed as such.
9. **Build to the map**: one file per retail object, in link order, each
   with its own flags; split files our tree merged, include the headers the
   ranges say were included. Re-score; a boundary is proved when the
   functions either side of it land identical at retail's addresses.

## Pitfalls

* **0x90 does not prove "same object"**. Any `/O2` object is followed by
  0x90-padded alignment, whatever comes next. And `/O2` objects can hold
  packed code: PH's TU02 (0x10004620..0x10004656, packed, unreferenced) is
  followed by 0x90 to the `/O2` TU03, and `ph/` builds TU01-TU03 as one
  `d3d_modelvb.cpp`; AvP2's `d3d_init` ends with one packed 30-byte function
  (0x1001bee5) after 23 aligned ones, as PH's does. Whether such a run is its
  own object is a judgement call; say so in the map.
* **A stand-in include can cost a function.** `<string>` went into most of
  the files whose ranges hold a guard, but not `tcpdriver`: it costs
  `TCPDriver::StartQuery` (avp2src 859f495). Re-score both images after each.
* **Expect "unplaced" to rise** when you put a real guard or initialiser in
  place: look-alikes that were falsely paired with those slots fall off
  (b194edc: 118 → 130; 859f495). That is the map getting more honest.
* **Generic shapes pair falsely**, and a false pair moves a boundary.
  `smgr.obj`'s inline deleting destructors are a 28-byte shape found at 58
  places in `server.dll`; three of them had been recorded identical inside
  the runtime, on `string.obj`'s `logic_error` destructors (avp2src 15467cc).
  In `d3d.ren`, `sub_1001f3b0` matched only because it had the allocator's
  deleting-destructor shape; its vtable is another class's (58e9ab5). Check a
  short match against its vtable or caller before using it as an anchor.
* **Other builds give code, not addresses.** NOLF2's multiplayer demo engine
  links rezmgr, the sound driver and D3D init earlier than retail: "use the
  mpdemo for code and data, never for addresses" (nolf2src
  `docs/engine/anatomy.md` §2).
* **Header-only and dead objects leave no code.** The Rich header can count
  objects the map will never see (24 in AvP2's renderer); do not invent
  boundaries to account for them.
* **Identical-code folding moves things.** Under `/OPT:ICF` the linker keeps
  one copy of identical COMDATs, and which one decides where code lies:
  Contract J.A.C.K.'s `SndDrv.dll` template tail still keeps the other copy
  of two pairs from retail (cjacksrc `docs/PLAN.md`). A displaced function
  in a template tail is a folding question before it is a mapping one.
