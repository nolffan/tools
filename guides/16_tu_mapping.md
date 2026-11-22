# 16 · Mapping a binary into its translation units

A stripped retail image has one `.text`. But the linker made it from
objects, and each object was one `.cpp`, compiled with one set of flags.
Until you know where these objects start and stop, you must guess three
things that decide byte identity:

1. Which functions are in the same file. This gives the definition order,
   the inliner horizon and the set of statics.
2. Which flags compiled each file.
3. The order in which the linker put the files.

This guide gives the signals that recover this structure from the bytes
only. It also gives the procedure that combines the signals, and the ways
in which each signal can give a wrong result.

This guide is between [05](05_exe_and_engine.md) (the enumeration and the
method without symbols) and [13](13_cluster_recon.md) (one cluster at a
time). The map that you make here tells a cluster where its file starts.

One signal is not sufficient:

- Padding shows only some boundaries.
- Initialisers show only the files with globals.
- `.bss` shows only the files with zero-initialised data.

The map is correct where several signals agree.

## The signals

### 1. Padding: 0x90 is the compiler's, 0xCC is the linker's

VC6 at `/O2` (and `/Ox`) puts each function in a 16-aligned COMDAT. The
**compiler** pads this COMDAT with `0x90`. At `/O1` (`/Os`), COMDATs have
align 1 and no padding. Thus `/O1` functions are next to each other at odd
addresses. If `/O2` code follows an `/O1` sequence, the **linker** must
align the next COMDAT. The linker fills with `0xCC`. Thus:

* A sequence of `int3` between functions is an object boundary (an `/O1`
  object, then an `/O2` object).
* A function that starts at an address that is not aligned is `/O1` code.
* The flag does not change in a translation unit. Thus each `/O1`↔`/O2`
  change in the function list is a boundary, also where there is no CC.

The example is the Primal Hunt `d3d.ren` (avp2src 58e9ab5,
`docs/D3D_OBJECTS.md`, "How the boundaries were found"). Test compiles with
cl 8966 proved the rule first. Of 1,301 rows, 315 are `/O2`, 966 are `/O1`
and 20 are ambiguous. An ambiguous row is aligned *and* stops exactly on a
16-byte boundary. To read it:

```sh
python3 ext/tools/exedump.py out/reference/d3d.ren 0x10008c68 0x10008c82
#  10008c74:  cc   int3      ... to 0x10008c7f
#  10008c80:  c3   ret       <- the next object (TU05, /O2) starts aligned
```

The AvP2 1.0.9.6 renderer has the same 12 CC fills at the same object
changes (avp2src `docs/AVP2_D3D_OBJECTS.md` §3). This padding showed that
the renderer is not an Intel build: it has no Intel `lea`-nop pads. It is
cl 8168.

Padding cannot show these boundaries:

- An `/O2` object, followed by any object. The compiler already padded to
  16, thus there is no gap.
- An `/O1` object, followed by another `/O1` object. There is nothing
  between them.

These boundaries need the signals below. We built each object again with
its own measured flags. This took the renderer from 154 to 730 identical
(avp2src e7c7c23, 791eb9c).

### 2. The CRT initialiser table: runs of entries open a file's globals

`__xc_a` .. `__xc_z` (`.CRT$XCU`) holds one pointer for each global that has
a dynamic initialiser, **in link order**. In the PH `d3d.ren`, the table is
at 0x1004a000..0x1004a370. It has 219 entries in 40 groups. Each group is
the top of the globals of one file.

The shape of the initialiser also gives the flag. Test compiles made the
two shapes again:

- Under `/O2`, it is one 22-byte or 25-byte COMDAT.
- Under `/O1`, it is a 5-byte `jmp` stub, plus a 26-byte or 30-byte body.

The `/O1` shape makes a `jmp` over padding. [13](13_cluster_recon.md#jmp-over-padding-into-a-zero-initialiser-is-__e-not-a-mystery)
describes this as the `??__E` entry.

```sh
python3 ext/tools/dataref.py out/reference/d3d.ren 0x1004a004 0x1004a008 0x1004a00c
#  0x1004a004  = 0x10001030 ...
```

The target of each slot is at the start of the code range of its object.
Where the targets jump from one region of `.text` to a different region, a
new object starts. The initialiser counts for each object then become a
fingerprint. The AvP2 renderer has 218 and the PH renderer has 219. They
are equal object for object, except the one in `fogvolume.cpp`. AvP2 does
not have that file.

### 3. `.bss` (and the `.data` string pool) step through link order

VC6 C++ makes no communals. A test showed that `int g;` goes to the own
`.bss` of the object. Thus the `.bss` of each object is **one block, in link
order**. Collect each `.bss` address that each function references. The
blocks increase monotonically through the object list. A decrease is a
boundary or an incorrect grouping.

A variable that only one function reads is not always the variable of that
function. An extern that is read one time looks the same. Thus use the
blocks, not single addresses.

The exception is also evidence. Static arrays in inline or template
functions are COMDAT `.bss`. The linker puts them **after the runtime
`.bss`, in reverse order** (PH `d3d.ren` 0x10099fc0..0x1009a960 for rows
52..59). The rows that use this storage are inline or template code. They
are not part of the object that contains them. Several files call them.

The same rule applies to the referenced `.data` strings. PH has 427 of
them, and their first uses are in increasing row order. There is one
inversion, and it was two rows of one function. The shared initialised
tables (cvar defaults, function-pointer tables) do not obey the rule.

### 4. Dead code: an unreferenced function proves a non-`/Gy` object

`/O1` and `/O2` imply `/Gy`. Then `/OPT:REF` removes each COMDAT that
nothing references. Thus a function that nothing calls, points to or
exports is in a plain `.text`. Its object was built **without** `/Gy`. In
the PH renderer, only TU02 is such an object, if you ignore the exports and
the extent defects. TU02 has two packed functions at
0x10004620..0x10004656. This is the evidence that TU02 was a separate run.

`/Ox` does not imply `/Gy`, and cl 13.10 has no `/Gy-`. Thus an image that
is all `/Ox` keeps all its functions. The Contract J.A.C.K. `SndDrv.dll` and
`GameSpy.dll` keep functions that nothing calls. The out-of-line functions
of each object stay in one `.text`, in the order that the compiler
completed them. This includes the functions that nothing calls (cjacksrc
`docs/PLAN.md` "3. small", `progress/COMPILERS.md`). The enumerator cannot
find these functions from calls. We put their start addresses into
`progress/extent-splits.csv` by hand.

### 5. `<string>`'s guarded initialiser ends every file that includes it

With the VC6 STL, each translation unit that includes `<string>` ends in a
guarded initialiser of `std::ctype<unsigned short>::id`. It has a
guard-bit test, then a `jmp` to a separate function. That function
registers an empty destructor with `atexit`. Under `/O2` it is 44 bytes
(avp2src `docs/PLAN.md`, PH `lithtech.exe`, guard 0x004f8014, ~95 copies):

```
  401760:  8a 0d 14 80 4f 00   mov    0x4f8014,%cl
  ...
  401774:  e9 07 00 00 00      jmp    0x401780        <- over 0x90 padding
  401780:  68 90 17 40 00      push   $0x401790       <- the empty dtor
  401785:  e8 .. .. .. ..      call   atexit
  40178a:  59 c3               pop %ecx ; ret
```

Under `/O1` (PH `server.dll` 0x10008bd2), the guard is 21 bytes. It has a
`jmp +0` directly into the 12-byte thunk. The code of the next object
follows with no gap. This is why the guard is important: it shows the end
of a file exactly where padding shows nothing.

How we used it:

* Each reconstructed object that has a guard in its retail range got
  `#include <string>` (behind `PRIMAL_HUNT`). This gave +39 identical on
  `lithtech.exe` only, with no loss (avp2src 56bb52b, ee3bd8a).
* A guard in retail, with no file of ours around it that has a guard,
  means that **our file merges two retail files**. We split these files
  out. In one round, this took the unwritten count of `lithtech.exe` from
  27 to 5 (b194edc). The splits were `sprite.cpp` out of `cmodelload.cpp`
  and `csvis.cpp`, `videomgr.cpp` and `visquery.cpp` out of `fntdraw.cpp`,
  and more. The same work took server.dll from 13 to 4 (859f495). In
  613d790, the guard of each new unit is identical at the retail address
  (`lithtech.exe` 0x4428e0, 0x449f70, 0x4a01c0).
* The enumerator joins the guard to the thunk that it jumps to. This makes
  one row where there are two symbols. avp2src 65b2599 added 140 of these
  splits to `progress/extent-splits.csv`. The file now has 141: 95 for
  `lithtech.exe` and 46 for `server.dll`.

Images built against STLport (AvP2 1.0.9.6) do not have this guard.

### 6. Header initialisers at the start of a range name the header

A header can define constants with a dynamic initialiser. Examples are
`const float PI = (float)(4*atan(1.0));` and `const LTVector3f
WORLD_UP(...)` in `math_phys.h`. These constants have internal linkage.
Thus each object that sees them makes its own initialiser pairs at the
**start** of its code range. You can read this in two ways:

* A file built outside the precompiled header has its own copy. The Tron
  2.0 `SubroutineDataMgr.cpp` has the `math_phys.h` initialisers at
  CShell.dll 0x10084080..0x10084222. The fix was `# SUBTRACT CPP /YX /Yc
  /Yu` for that one file in the `.dsp` (tron20src 5aca299).
* A range that starts with the initialiser pairs of a header shows that the
  file included that header. Three Tron TUs (`TronHUDMgr`,
  `TronInterfaceMgr`, `TRONPlayerStats`) start with `kDefaultPos` from
  `BaseScreen.h`, and `SLICE_SIZE`/`PRIM_SIZE` from `ScreenSubroutines.h`
  (0x1009ad40, 0x1009c980, 0x100a8f60). We added
  `#include "ScreenSubroutines.h"`. This gave the two missing pairs in each
  TU, and all were identical (tron20src d5dbb42).

The precompiled header changes more than the initialisers. With `/YX`, the
inlines of the header go to the end of the object and keep their EH. An
example is the PH ButeMgr. The full library became identical when we built
it with `/YX`, as the release project did (avp2src 2a08ad1). The `AVP2.exe`
launcher uses the PCH for all files except `LauncherDlg.cpp`. We proved
this: without the PCH, the unwind states of the inlined MFC destructors are
different (avp2src `progress/COMPILERS.md`, `AVP2.exe` row).

### 7. Anchored functions in address order give the project

When you know the names of some functions (from strings, vtables or a
scorer pairing), list them by address. Write the source file of each
function next to it. The order of the files is the order of the link line,
and the link line is the project file:

* **The Contract J.A.C.K. game DLLs** have their code in the alphabetical
  order of *all* their sources. The sources of the TO2 project and of the
  shared library are mixed. The libraries follow, in the alphabetical order
  of their projects. Two projects linked together give two alphabetical
  sequences. One sequence means **one project for each DLL**. We wrote the
  cjacksrc `Object.dsp` and `ClientShellDLL.dsp` on that basis (cjacksrc
  `docs/PLAN.md` "4. game").
* **The NOLF2 engine** has `controlfilemgr` first. Then it has
  `bindmgr` .. `world_shared_bsp` in alphabetical order, then an "ILT
  interface" group. This is exactly the Jupiter `EXE_Lithtech` file list.
  The NOLF2 **renderer** is not in alphabetical order, and it is not in the
  order of the CMake list. It is in the order of the NOLF2 `.dsp` (nolf2src
  `docs/engine/fear_mapping.md` §2c). A file order that is not alphabetical
  is the list of the IDE, as the developer wrote it.
* The same anchoring works between games. The PH renderer objects, paired
  with the nolfsrc symbols that have names for the NOLF addresses, are in
  the order of the NOLF `.dsp` (avp2src `docs/D3D_OBJECTS.md` item 6).

Names to use as anchors: the NOLF2 engine registers each interface with a
`define_holder`/`instantiate_implementation` dynamic initialiser. This
initialiser pushes the name of the interface. These initialisers are at
the **start of the code of each object**. There are 48 interface names in
the exe and 25 in the DLL (nolf2src `docs/engine/anatomy.md` §3). The Mac
port is not stripped. It is a different source of names and file groups,
but not of addresses.

**The import order is also the link order.** The import table lists the
DLLs in the order of the first use of their import libraries on the link
line. The libraries of the project come first, then the default list of the
IDE. This gives the Contract J.A.C.K. `SndDrv.dll` the retail imports:
ltmem, winmm, msacm32, dxguid, eaxguid, then the defaults (cjacksrc
`docs/PLAN.md` "3. small"). The link line of the server has `server.lib`
before `winmm.lib`. This puts `server.DLL` first (cjacksrc
`progress/COMPILERS.md`).

A `#pragma comment(lib, ...)` adds the library after the command line.
The `wsock32.lib` of `GameSpy.dll` comes from a pragma in `nonport.c`. This
is why WSOCK32 is the last of its imports (cjacksrc `docs/PLAN.md`,
GameSpy.dll).

### 8. The Rich header bounds the object count

`tools/richhdr.py` counts the objects for each tool build. The AvP2
renderer has 73 C++ objects: 3 StdLith objects and 70 renderer objects. Of
the renderer objects, 46 have code and 24 have no code that remains. These
24 are header-only, have no cvars, or `/OPT:REF` removed all their code.

The count does not place objects. But a map with more code objects than the
header permits is wrong. The count also showed that the stray tool rows
(DirectX SDK `ddraw.lib`, `dxguid.lib`) are library objects and not missing
source (avp2src `docs/AVP2_D3D_OBJECTS.md` §2-3).

## Function order within a translation unit

The map gives each file its range. The compiler decides the order in the
range.

* **VC6**: the COMDAT section order is the source definition order
  ([03](03_reading_disassembly.md), [09](09_codegen_patterns.md)).
  The definition order also changes the code, not only its position:
  - The inliner looks only forward
    ([09](09_codegen_patterns.md#the-inliner-is-forward-only-and-inline-is-what-admits-a-big-helper)).
  - The AvP2 cl 9044 allocates the registers of a caller around the
    callees that come earlier in the same file. Thus put the definitions in
    the retail order (avp2src 4cd90f8: `ComputeRadius`,
    `at_UpdateStringKeys` into `modelanim.cpp`).
  - Under `/GX`, VC6 removes a state store before a call if it already
    compiled the callee (avp2src `docs/PLAN.md`).
* **VC7.1** (Visual C++ .NET 2003, Contract J.A.C.K.) compiles a function
  only after it compiles each function that the function calls and that
  comes later in the file. A forward call delays the function. It does not
  cause an inline. Template instantiations come at the end, in the order of
  call depth (cjacksrc `docs/PLAN.md` "3. small", `SndDrv.dll`). Thus, if a
  function in a VC7.1 image is out of order, first look for a forward call.
  It is not evidence of a different file.
* **COMDATs go with their first user.** Several objects can make the same
  inline or template function. The linker puts it in the first of these
  objects in link order. The PH `_CVector` `+`/`*` are in `fogvolume.obj`.
  AvP2 does not have that file, and it has them in `drawpolygrid`, the next
  first user (avp2src `docs/AVP2_D3D_OBJECTS.md` §3 notes). A sequence of
  shared helpers in a range is not a separate file.

## Pinning the app range

Before you make the map, remove the code that the toolchain supplied. Each
row after the app code must match a member of the runtime libraries **at
its own address**, masked by its relocations. `tools/libscan.py` does this
check:

```sh
python3 ext/tools/libscan.py out/reference/CShell.dll \
    ext/toolchains/msvc-6.00-8168/LIB/libcmt.lib ext/toolchains/msvc-6.00-8168/LIB/libcpmt.lib \
    ext/toolchains/msvc-6.00-8168/LIB/libcimt.lib ext/toolchains/msvc-6.00-8168/LIB/oldnames.lib
```

The start of the first runtime sequence is the end of the app range. We
did this for four images (avp2src a0dd817). It removed these rows from the
count, and the unwritten count went from 827 to 536:

- 99 rows of CShell.dll.
- 89 rows of Object.lto.
- 108 rows of PHObject.lto.

Also remove the DirectX import thunks and their data (avp2src 15467cc,
30378bf). An example is the `lithtech.exe` DINPUT thunk at 0x4ba2a0. The
row at 0x4ba2b0 is the `dinput.lib` data formats, which is a NOT A FUNCTION
row. Write the evidence next to the range in `progress/targets.py`.

## Proving enumeration errors: `enumproof.py`

A map can only be as correct as the rows below it. `tools/enumproof.py`
decodes each unwritten or near row by recursive descent. If the next row is
provably not a function, it proposes the fix for that row. It finds these
cases:

- A conditional branch from the row before goes to the start of the row.
- An instruction goes across the start of the row.
- The previous row continues directly into the row.
- For splits: code after padding, which nothing from the start of the row
  reached, is the target of a branch.

The tool is conservative. Nothing else can reference the later row, and the
earlier row must be proven (tools 892868a).

```sh
python3 ext/tools/enumproof.py --target lithtech.exe          # print proposals
python3 ext/tools/enumproof.py --target lithtech.exe --write  # append them
```

`--target` takes a label or a stem, and you can give it more than one
time. `--csv` gives the statuses. The default is
`out/progress/functions.csv`, thus run the scorer first. `--write` adds the
proposals to `progress/<stem>-screen-exclude.csv` and
`progress/extent-splits.csv`
([14](14_progress.md#when-the-enumeration-is-wrong-the-csvs)). Read each
proposal before you commit it.

## Procedure

1. **Pin the app range** with `libscan.py`. Record it with its evidence.
2. **Fix the enumeration** near the ranges that you work on. Use
   `enumproof.py`, then use `extentcheck.py` by hand. Split each
   guard/atexit pair.
3. **Classify each row by its padding.** Aligned with 0x90 is `/O2`. Not
   aligned is `/O1`. Aligned and stopping on 16 is ambiguous. Mark each CC
   sequence and each flag change as a boundary.
4. **Mark the other markers.** These are the head of each `__xc_a` group
   and each `<string>` guard (the end of a file). They are also each
   sequence of header-constant initialisers or `define_holder`
   registrations (the start of a file).
5. **Do a check with the data.** The `.bss` blocks and the `.data` string
   pool must increase monotonically across your objects. Move the
   boundaries until they do. Keep the COMDAT `.bss` rows separate as inline
   or template code.
6. **Name the objects** from strings, error tags, vtables and anchored
   pairings. Compare the file order with the project (alphabetical, `.dsp`,
   the source list of the era). Compare the import order with the link
   line.
7. **Compare the count** with the Rich header.
8. **Write the map.** Write one row for each object
   (`start,end,name,flags,evidence`, as `progress/d3d-objects.csv` does).
   Give a confidence for each row. List the splits that you could not
   prove as not proven.
9. **Build to the map.** Make one file for each retail object, in link
   order, each with its own flags. Split the files that our tree merged.
   Include the headers that the ranges show. Score again. A boundary is
   proven when the functions on the two sides of it are identical at the
   retail addresses.

## Pitfalls

* **0x90 does not prove "same object".** Each `/O2` object has 0x90-padded
  alignment after it, whatever comes next. Also, `/O2` objects can contain
  packed code. Two examples:
  - The PH TU02 (0x10004620..0x10004656, packed, not referenced) has 0x90
    after it, up to the `/O2` TU03. `ph/` builds TU01-TU03 as one
    `d3d_modelvb.cpp`.
  - The AvP2 `d3d_init` ends with one packed 30-byte function (0x1001bee5)
    after 23 aligned functions. The PH `d3d_init` is the same.

  It is a judgement whether such a sequence is a separate object. Write
  your decision in the map.
* **A stand-in include can cost a function.** We added `<string>` to most
  of the files whose ranges have a guard, but not to `tcpdriver`. There it
  costs `TCPDriver::StartQuery` (avp2src 859f495). Score the two images
  again after each change.
* **Expect the "unplaced" count to increase** when you put a real guard or
  initialiser in its position. Similar functions that the scorer paired
  incorrectly with those slots become unplaced (b194edc: 118 → 130;
  859f495). This shows that the map is more accurate.
* **Generic shapes make incorrect pairs**, and an incorrect pair moves a
  boundary. The inline deleting destructors of `smgr.obj` are a 28-byte
  shape that occurs at 58 locations in `server.dll`. The scorer recorded
  three of them as identical in the runtime, on the `logic_error`
  destructors of `string.obj` (avp2src 15467cc). In `d3d.ren`,
  `sub_1001f3b0` matched only because it had the deleting-destructor shape
  of the allocator. Its vtable belongs to a different class (58e9ab5).
  Before you use a short match as an anchor, examine its vtable or its
  caller.
* **Other builds give code, not addresses.** The NOLF2 multiplayer demo
  engine links rezmgr, the sound driver and D3D init earlier than retail
  does: "use the mpdemo for code and data, never for addresses" (nolf2src
  `docs/engine/anatomy.md` §2).
* **Header-only objects and dead objects leave no code.** The Rich header
  can count objects that the map never shows (24 in the AvP2 renderer). Do
  not add boundaries for them.
* **Identical-code folding moves code.** Under `/OPT:ICF`, the linker keeps
  one copy of identical COMDATs. The copy that it keeps decides the
  position of the code. The template tail of the Contract J.A.C.K.
  `SndDrv.dll` still keeps the other copy of two pairs from retail
  (cjacksrc `docs/PLAN.md`). If a function in a template tail is in the
  wrong position, first examine the folding, then the map.
