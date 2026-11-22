# 17 · Decompiling the dev tools

Monolith shipped its editors and compilers as stripped release binaries,
as it did the engine. These tools are:

- DEdit;
- ModelEdit;
- the world Processors;
- LithRez;
- the 3ds Max and Maya plug-ins.

The loop is the same loop ([02](02_the_loop.md),
[05](05_exe_and_engine.md)). The standard is also the same: byte
identity, function by function. Three things are different:

- where the source comes from;
- the MFC application that the tools use;
- how you show that a tool *behaves* as the shipped tool does.

The cases come from two parts of lithtools:

- `legacy/talon/`: the Talon-era tools for NOLF and AvP2 (DEdit,
  ModelEdit, two Processors, the plug-ins);
- `tools/lithrez/`: format readers that we check against the shipped
  games.

## Start from the nearest descendant and walk back

No source of any version of the Talon tools is available today. But most
of their parts are available, in later trees or in related trees. Each
target starts from the nearest tree, and we change it back to the shipped
version (lithtools `legacy/talon/README.md`, "Where the source comes
from"). The sources are:

- The LithTech Jupiter SDK (build 51, March 2002). It has the shared
  libraries with their own VC6 project files, and the engine SDK headers.
- The tools source of Build 69 (2006). We take it file by file
  (`build/takeb69.py`). For the Update 2 plug-ins, this source is almost
  the answer. Apart from a few bytes, these plug-ins are the SDK build 51
  plug-ins, and the Build 69 plug-ins descend from them. In the plug-ins'
  own objects, every function is identical, except three near functions
  (`docs/PLAN.md` §1).
- For DEdit, ModelEdit and the Processors, no source of any version is
  available. For these, we use three sources:
  - the LT2 SDK and libraries of the AvP2 source release;
  - the reconstruction of the LT2 engine in nolfsrc;
  - the DEdit, ModelEdit and PreProcessor of Build 69, as *a map of their
    structure*.

The procedure, as we did it for DEdit (`docs/PLAN.md` §3):

1. **Link the descendant first.** Use the DEdit of Build 69 with these
   parts:
   - the 2001 world headers of the processors;
   - the 2001 model code of ModelEdit;
   - the 2001 libraries.

   Set them up as a VC6 project in the **module order of the image**
   (`src/LT2/tools/DEdit/DEdit.dsw`). Our project linked with no
   unresolved symbols. It scored 2,499 identical functions (38.6% of the
   bytes) before we took back one file.
2. **Isolate the code that 2001 does not have.** Some later features of
   Build 69 have callers in the newer code. Put these features in a
   **link group of their own** ("Build 69 only"). Some code is in the
   image, but nobody has written it yet. Write a **stand-in** for this
   code. Mark the stand-in `talon: stand-in` in the source. List it in the
   last section of the map (`progress/DEdit_map.md`) until you replace it.
   The project links at all times, so you can measure the score at all
   times.
3. **Walk each file back on evidence from the image.** Each change gives
   the address that shows why the change is correct. For example,
   lithtools 714af93 takes `DEdit.cpp` back:
   - `CDEditApp` at 0x41653e shows the 2001 options object: ten option
     sets, 0x4c bytes.
   - There are no hot keys and no model manager.
   - The world is saved through `CRegionDoc::SaveRegion` (0x44f4dc),
     because 0x417568, 0x4179ff and 0x417c41 call it.

   The 2001 code replaces the code of Build 69. Thus, stand-ins lose their
   last callers, and you remove them (`GetModelMgr`, `SetHotKeyDB`, ...).
4. **Then remove the group.** In lithtools 7a5d6ab, we removed the
   "Build 69 only" group and all other Build 69-only source. The project
   linked with no errors.

**Use the module order as evidence.** You read the position of a file in
the link from the image. This position answers questions that the
strings cannot answer. An example from 7a5d6ab:

- The map had an unknown module at 0x46db7a..0x46eb58. This module is the
  world tree: the load and save code of PreWorld calls its `LoadLayout`
  and `SaveLayout`.
- The module is between `viewrender` and `WorldInfoDlg` *by name*. The
  modules of DEdit are in the order of the project. The Project Bar group
  is first. The other modules follow in alphabetical order of file name.
  (The nine parts below are that group, A-C, D, E, F-N, ...)

`InitTracker` goes into `RegionView.cpp` after its message map, because
0x452bb7 follows `GetMessageMap` at 0x452bb1.

**Divide parallel work by image range, and give each part its headers.**
We walked DEdit back in nine parts by image range (`docs/PLAN.md` §3,
"in nine parts"), with one agent for each part. **Each part owns the
headers of its modules**, so no two agents edit the same header. Results
of the round:

- DEdit went from 2,499 identical functions to 3,855 of 4,402 (80.1% of
  the bytes).
- ModelEdit, in seven parts, went from 1,001 to 1,664.

The general rules for parallel clusters are in
[13](13_cluster_recon.md).

**Commit each file when you take it, and each change as its own commit**
(`README.md`). Then the diff of a file against its Build 69 original is
the record of the 2001 version. You can read this record change by
change.

**Use a descendant as a guide to shapes, not as a source of matches.**
The world code of the processors is also in DEdit (under
`DIRECTEDITOR_BUILD`). But the objects of the Processor (cl 8966 `/O2`)
do not match the objects of DEdit (cl 9044 `/O1`) byte for byte
(`progress/DEdit_map.md`). The source is the same, but the compiler is
different. Trust the descendant for structure. Verify its bytes again.

## The static MFC library is not your code

The editors link MFC statically (`nafxcw.lib`). Its functions are real
and are in the image. They **will match** if your objects instantiate the
same header code. This does not make them your functions. Lithtools
8f752f3 corrected the score. 157 functions left `identical.txt`:

- 150 of them are matches after the own code of DEdit and ModelEdit.
  These are functions of the MFC library: in DEdit after 0x48d740, in
  ModelEdit after 0x437170.
- 7 of them are inside another identical function. The masked shape of a
  shorter body was the same as the inside of a longer body.

`progress/corrections.txt` lists each of them with its reason.

- **Find the limits of the app region from the link map of the image.**
  Do not use the first MFC function that you see. The own code of DEdit
  is not one range. The libraries start again after MFC. The second
  scored range starts at the constructor of CryptMgr, 0x4a25e0
  (`docs/PLAN.md` §3).
- **An MFC header function that your objects instantiate can also be in
  your range.** 9ca3cdf removes `CStringArray::GetAt` (0x43b391) from the
  score. This function is byte-identical in `nafxcw.lib`.

## VC6 catch blocks are interior rows

VC6 puts the `catch` blocks of a function *after* its body. The
enumeration sees a block of code that nothing references, and makes it a
row. The block ends with `mov eax,<continuation>; ret`. The continuation
is an address back inside the function, where the EH runtime continues.

Lithtools 9ca3cdf removed 117 such interior rows of DEdit from the score.
It also removed rows that start in the middle of an instruction, and
branch targets. For each row, we checked the true extent of the function
with `tools/extentcheck.py` (`progress/DEdit-screen-exclude.csv`). The
commit also added 13 starts that the enumeration did not find
(`progress/extent-splits.csv`).

**Signature: a row with no caller, where the immediate of
`mov eax,imm32; ret` points into the row above.** Merge the row into its
function. Do not write it as a function of its own. All the extent
defects of [13](13_cluster_recon.md) also apply.

## Message maps

The message map of a `CCmdTarget` is a table in `.rdata`. You get to it
through the `GetMessageMap` virtual. For an MFC class, the message map is
the same as the vtable for an interface ([07](07_vtables.md)): **the list
of the handlers that the class had**. Read the message map before you
write the class. It shows which members the class has, and which it does
not have. Two examples:

- 7a5d6ab removed `OnSelectionScale` and two update handlers from
  `RegionView`, because the 2001 message map (0x4dbb40) does not name
  them.
- We built the main dialog of ModelEdit again against its 90-entry
  message map at 0x4750f8 (lithtools b336b87).

## Resources: decompile, prove the round trip, score them apart

The dialogs, menus, accelerators, string tables and icons of an MFC tool
are part of the shipped tool. Do not type them again. Decompile them.

```sh
python3 tools/rsrc2rc.py out/reference/DEdit.exe DEdit.rc --resource-h=resource.h
python3 tools/rsrcdiff.py <our DEdit.exe> out/reference/DEdit.exe
```

- `rsrc2rc.py` writes the `.rc` file and the binary resources next to it.
  It uses the names from `resource.h` where it has them.
- `rsrcdiff.py` compares the payload of each resource, by type, name and
  language. It ignores the layout of the section.

All 224 resources of DEdit and all 86 resources of ModelEdit are
byte-identical (the `:rsrc` rows in `README.md`).

NOTE: `rsrc2rc.py` has three output fixes that are not done yet: TOOLBAR
statements, the order of cursors and icons, and `WS_TABSTOP` comboboxes
(`docs/PLAN.md` §3). The round trip is proved on the payloads, not on how
easy the `.rc` file is to read.

Score resources as **their own targets** (the `:rsrc` targets in
`progress/targets.py`, 8f752f3). Keep them **outside the code total**. A
resource is not a function. The 289,504 bytes of DEdit dialogs and
bitmaps must not change the code percentage.

## One image, several compilers

Do not think that one image has only one compiler. The `Processor.exe` of
NOLF Tools 001 has these compilers (`docs/PLAN.md` §2, "What built it"):

- Its own code is **Intel C/C++ 4.0** `/O1`. The evidence: the 82 objects
  in the Rich header without a `@comp.id`, and the frames, padding and
  `.data1` of icl.
- `PreWorld.cpp` is the exception: VC6 SP3 (8447) `/O1`.
- Its LT2 libraries, MFC and CRT are from VC6 SP3.

`tools/dsp2mk.py` accepts a compiler for each source:
`CL_<project>__<source's base name>` overrides `CL_<project>`.

`progress/Processor_nolf_map.md`, "How icl 4.0 compiled it", records the
known behaviour of that compiler:

- `/EHa`;
- the compiler inlines nothing into or out of a function with an EH
  frame;
- the `X$$1` second entry, which aligns again.

## Behaviour tests: control them with retail against retail

`make progress` proves the code. `make test` (`legacy/talon/tests/`) runs
the shipped tool and our tool on the same inputs. Then it compares the
output of the two tools. These tests find errors that byte scoring cannot
find. In the AvP2 Processor, two *near* functions calculated a different
result:

- the edge normal of `DoBrushesIntersect`;
- the rounding of `MakePortal`.

We fixed them when we compared the `.dat` output of our exe with that of
the shipped exe, for the seven sample worlds (`docs/PLAN.md` §2).

**Before you trust a comparison, run it retail against retail.** The
T-junction splits of the physics BSP write uninitialised vertex colours.
These colours depend on the heap. The heap depends on the length of the
path of the exe (`RETAIL_BUGS.md`, "The physics BSP's T-junction splits
keep uninitialised vertex colours").

Lithtools 59a7aac shows this on Sample_DM. Two runs of the *shipped* exe,
from paths of different lengths, have 2,637 different colour bytes in 519
polies. In one run, some polies are all 255. In the other run, the same
polies have random values. This result stopped the rule "skip a poly that
is uninitialised in both runs" before we used it. It also showed an error
in the old `datcmp.py`: that script could never fail. It accepted a
difference only if both bytes were not 255, and two unequal bytes are
never both 255.

Thus, a test must do these four things:

1. **State exactly what it normalises.** Here, it normalises only the
   colour bytes of the physics BSP. It compares all other bytes raw.
2. **Say this in its verdict.** Write "equal but for N physics BSP vertex
   colour bytes in M polies", not "identical".
3. **Have a control.** A second shipped run, from a different path, must
   pass the same comparison against the first run, on every run. This
   applies to Sample_DM always, and to every world with `CONTROL=1`.
4. **Keep the conditions of the two sides equal** (`tests/README.md`):
   - the same inputs;
   - new working directories (the Processor reads `processor.opt` from
     its own working directory);
   - paths of the same length.

## File formats: read the version check *and* the writer

When a tool reads or writes the files of a game, the format limits come
from the binaries, not from headers. Look at two things: **the check that
prints the error, and the constant that the writer writes** (lithtools
`FORMATS.md`). For worlds:

- the Processor of NOLF Tools 001 writes 0x42 (66);
- the Processor of AvP2 1.0 writes 0x46 (70);
- the NOLF engine refuses each world that is not 66.

Thus, NOLF needs its own Processor.

Read what the check really tests. The engines of NOLF2 and CJ check only
a **minimum** model version: `cmp eax,0x17` / `jae` before "fileversion
%d is not supported". The check of SDK build 51 is 18. The writers are
different:

- the `Model_Packer.exe` of Build 69 writes `mov ebx,0x19` (25);
- the 2003 tools write 0x17 (23).

A v25 model passes the 2003 check. But version 24 changed how per-model
OBBs are stored, so a 2003 engine reads the model incorrectly. Thus, the
tools of Build 69 cannot make the models of these games correctly. The
`MODEL_FILE_VERSION 25` in the trees of nolf2src and cjacksrc is the
Build 69 header, which we kept. It is not the value that their retail
engines check (`FORMATS.md`, "The newer engine").

**Verify each reader against every shipped asset.** Each reader in
`tools/lithrez` has a `<format>_verify`. This program reads every file of
that type in the archives of a game. Examples:

- `renderstyle_verify` (lithtools d84f023): every render style, `.ltb`
  type 5;
- `lip_verify` (bf68799): every `.lip` against its voice line;
- also `abc_verify`, `ltb_verify`, `spr_verify`, `texfx_verify`, ...

These programs read the archives of the games, and we never commit these
archives. Thus, they are outside `ctest` (`tools/lithrez/README.md`,
"Checks against the shipped games"). A unit test on one sample proves
only that the reader reads that sample.

A census of the shipped versions (`scripts/fmtversions.py`) uses the same
idea at a higher level. The census found that NOLF has one v11 model and
two v9 models, with 692 v12 models (`FORMATS.md`, "Shipped assets").

## Tools' retail bugs: document now, fix later

Our sources keep the bugs of the retail tools on purpose, as they keep
the bugs of the games. The bugs go in `legacy/talon/RETAIL_BUGS.md` (88
at this time). For each bug, the entry gives:

- the address where we read it from the retail bytes;
- how well our function matches at that address.

The games fix their bugs in a modern build of the same source
([18](18_modern_builds.md)). **The tools do not get a modern variant.**
We will implement the tools again later, with the fixes. That list is the
start point for the new implementation. Do not fix the bug of a tool in
the reconstruction.
