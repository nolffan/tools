# 17 · Decompiling the dev tools

Monolith shipped its editors and compilers -- DEdit, ModelEdit, the world
Processors, LithRez, the 3ds Max and Maya plug-ins -- as stripped release
binaries, like the engine. The loop is the same one
([02](02_the_loop.md), [05](05_exe_and_engine.md)), and so is the
standard: byte identity, function by function. What differs is where the
source comes from, the MFC application they are built on, and how you
show that a tool *behaves* as the shipped one does. The cases are from
lithtools' `legacy/talon/` (the Talon-era tools for NOLF and AvP2: DEdit,
ModelEdit, two Processors, the plug-ins) and its `tools/lithrez/`
(format readers checked against the shipped games).

## Start from the nearest descendant and walk back

No source of any version of the Talon tools survives. Most of what they
are made of does survive, in later or neighbouring trees, and each target
starts from the nearest one and is brought back to what shipped
(lithtools `legacy/talon/README.md`, "Where the source comes from"):

- the LithTech Jupiter SDK (build 51, March 2002): the shared libraries
  with their own VC6 project files, and the engine SDK headers;
- Build 69's tools source (2006), taken file by file
  (`build/takeb69.py`). For the Update 2 plug-ins this is very nearly the
  answer: they are, apart from a few bytes, the SDK build 51 plug-ins,
  whose descendants are Build 69's (`docs/PLAN.md` §1: every function of
  the plug-ins' own objects identical but three nears);
- for DEdit, ModelEdit and the Processors, where no version's source
  exists: the AvP2 source release's LT2 SDK and libraries, nolfsrc's
  reconstruction of the LT2 engine, and Build 69's DEdit, ModelEdit and
  PreProcessor as *a map of their structure*.

The procedure, as DEdit went (`docs/PLAN.md` §3):

1. **Make the descendant link first.** Build 69's DEdit, with the
   processors' 2001 world headers, ModelEdit's 2001 model code and the
   2001 libraries, set up as a VC6 project in the **image's module order**
   (`src/LT2/tools/DEdit/DEdit.dsw`). It linked with nothing unresolved
   and scored 2,499 identical functions (38.6% of the bytes) before a
   single file had been taken back.
2. **Quarantine what 2001 doesn't have.** Build 69's later features that
   the newer code calls go in a **link group of their own** ("Build 69
   only"), and code the image has but nobody has written yet becomes a
   **stand-in**, marked `talon: stand-in` in the source and listed in the
   map's last section (`progress/DEdit_map.md`) until it is replaced. The
   project links throughout, so the score is measurable throughout.
3. **Walk each file back on image evidence.** Every change cites the
   address that justifies it. lithtools 714af93 takes `DEdit.cpp` back:
   the 2001 options object of ten option sets, 0x4c bytes, from
   `CDEditApp` at 0x41653e; no hot keys or model manager; the world saved
   through `CRegionDoc::SaveRegion` (0x44f4dc), because 0x417568, 0x4179ff
   and 0x417c41 call it. As the 2001 code replaces Build 69's, stand-ins
   lose their last callers and go (`GetModelMgr`, `SetHotKeyDB`, ...).
4. **Then drop the group.** lithtools 7a5d6ab: the "Build 69 only" group
   and every other Build 69-only source out, links clean.

**Module order is evidence, use it.** A file's place in the link is read
off the image, and it settles questions the strings can't. In 7a5d6ab
the module the map had as unknown at 0x46db7a..0x46eb58 is the world tree
(PreWorld's load and save call its `LoadLayout` and `SaveLayout`), and it
sits between `viewrender` and `WorldInfoDlg` *by name*: DEdit's modules
lie in the project's order, its Project Bar group first and then the rest
alphabetically by file name (the nine parts below are that group, A-C, D,
E, F-N, ...).
`InitTracker` goes into `RegionView.cpp` after its message map, because
0x452bb7 follows `GetMessageMap` at 0x452bb1.

**Split parallel work by image range, and give each part its headers.**
DEdit's walk back was nine parts by image range (`docs/PLAN.md` §3,
"in nine parts"), one agent each, and **each part owns the headers of its
modules**, so no two agents edit one header. The round took DEdit from
2,499 identical functions to 3,855 of 4,402 (80.1% of the bytes);
ModelEdit's seven parts took it from 1,001 to 1,664. The general rules
for parallel clusters are [13](13_cluster_recon.md)'s.

**Commit every file as taken, and each change as its own commit**
(`README.md`). The diff of a file against its Build 69 original is then
the record of what 2001 was, readable change by change.

**A descendant is a guide to shapes, not a source of matches.** The
processors' world code is in DEdit too (under `DIRECTEDITOR_BUILD`), but
the Processor's objects (cl 8966 `/O2`) don't match DEdit's (cl 9044
`/O1`) byte for byte (`progress/DEdit_map.md`). Same source, other
compiler: trust it for structure, re-verify it for bytes.

## The static MFC library is not your code

The editors link MFC statically (`nafxcw.lib`). Its functions are real,
in the image, and **will match** if your objects instantiate the same
header code: that does not make them yours. lithtools 8f752f3 corrected
the scoring: 157 functions left `identical.txt`, 150 of them matches past
DEdit's and ModelEdit's own code (the MFC library's, DEdit past 0x48d740,
ModelEdit past 0x437170) and 7 inside another identical function (a
shorter body's masked shape coinciding with the inside of a longer one).
Every one is listed with its reason in `progress/corrections.txt`.

- **Bound the app region from the link map of the image, not from the
  first MFC function you notice.** DEdit's own code is not one range: the
  libraries resume after MFC, and the second scored range starts at
  CryptMgr's constructor, 0x4a25e0 (`docs/PLAN.md` §3).
- **An MFC header function instantiated by your objects can still land
  inside your range**: 9ca3cdf screens out `CStringArray::GetAt`
  (0x43b391), byte-identical in `nafxcw.lib`.

## VC6 catch blocks are interior rows

VC6 places a function's `catch` blocks *after* its body. The enumeration
sees an unreferenced block of code and makes it a row; it ends with
`mov eax,<continuation>; ret`, and the continuation is an address back
inside the function, where the EH runtime resumes. lithtools 9ca3cdf
screened out 117 such interior rows of DEdit (with mid-instruction rows
and branch targets), each with the function's true extent checked with
`tools/extentcheck.py` (`progress/DEdit-screen-exclude.csv`), and added 13
starts the enumeration missed (`progress/extent-splits.csv`).
**Signature: a row with no caller whose `mov eax,imm32; ret` immediate
points into the row above.** Merge it into its function; never write it
as a function of its own. [13](13_cluster_recon.md)'s extent defects all
apply as well.

## Message maps

A `CCmdTarget`'s message map is a table in `.rdata` reached through the
`GetMessageMap` virtual, and it is to an MFC class what the vtable is to
an interface ([07](07_vtables.md)): **the list of handlers the class had**.
Read it before writing the class. It decides membership both ways:
7a5d6ab took `OnSelectionScale` and two update handlers out of
`RegionView` because the 2001 message map (0x4dbb40) doesn't name them,
and ModelEdit's main dialog was rebuilt against its 90-entry message map
at 0x4750f8 (lithtools b336b87).

## Resources: decompile, prove the round trip, score them apart

An MFC tool's dialogs, menus, accelerators, string tables and icons are
part of what shipped. Don't retype them: decompile them.

```sh
python3 tools/rsrc2rc.py out/reference/DEdit.exe DEdit.rc --resource-h=resource.h
python3 tools/rsrcdiff.py <our DEdit.exe> out/reference/DEdit.exe
```

`rsrc2rc.py` writes the `.rc` (with `resource.h`'s names where it has
them) and the binary resources beside it; `rsrcdiff.py` compares each
resource's payload keyed by type, name and language, ignoring the
section's layout. All 224 of DEdit's resources and all 86 of ModelEdit's
are byte-identical (`README.md`'s `:rsrc` rows). `rsrc2rc.py` still has
three output fixes pending (TOOLBAR statements, cursor and icon order,
`WS_TABSTOP` comboboxes: `docs/PLAN.md` §3) -- the round trip is proved
on the payloads, not on how readable the `.rc` is.

Score resources as **their own targets** (`progress/targets.py`'s
`:rsrc` targets, 8f752f3), **outside the code total**: a resource is not
a function, and 289,504 bytes of DEdit dialogs and bitmaps must not move
the code percentage.

## One image, several compilers

Do not assume one compiler per image. NOLF Tools 001's `Processor.exe`
is **Intel C/C++ 4.0** `/O1` for its own code (the Rich header's 82
objects without a `@comp.id`; icl's frames, padding and `.data1`), except
`PreWorld.cpp`, VC6 SP3 (8447) `/O1`; its LT2 libraries, MFC and CRT are
VC6 SP3's (`docs/PLAN.md` §2, "What built it"). `tools/dsp2mk.py` takes a
compiler per source: `CL_<project>__<source's base name>`, overriding
`CL_<project>`. `progress/Processor_nolf_map.md`, "How icl 4.0 compiled
it", is the case law for that compiler (`/EHa`; nothing inlined into or
out of an EH-framed function; the `X$$1` realigning second entry).

## Behaviour tests: control them with retail against retail

`make progress` proves code; `make test` (`legacy/talon/tests/`) runs the
shipped tool and ours on the same inputs and compares what they write.
They catch what byte scoring cannot: two *near* functions in the AvP2
Processor computed something else (`DoBrushesIntersect`'s edge normal,
`MakePortal`'s rounding) and were fixed when our exe's `.dat` output for
the seven sample worlds was compared with the shipped exe's
(`docs/PLAN.md` §2).

**Before you trust a comparison, run it retail against retail.** The
physics BSP's T-junction splits write uninitialised vertex colours, which
follow the heap, and the heap follows the length of the exe's path
(`RETAIL_BUGS.md`, "The physics BSP's T-junction splits keep uninitialised
vertex colours"). lithtools 59a7aac: on Sample_DM two runs of the
*shipped* exe from paths of different lengths differ in 2,637 colour
bytes of 519 polies, including polies all 255 in one run and garbage in
the other. That killed the plausible rule "skip a poly uninitialised in
both" before it was relied on, and exposed that the old `datcmp.py`
could never fail (it accepted a difference only if both bytes were non-255
-- two unequal bytes never both are).

So a test:

1. **states what it normalises**, exactly: here any physics BSP colour
   byte, nothing else; every other byte is compared raw;
2. **says so in its verdict**: "equal but for N physics BSP vertex colour
   bytes in M polies", never "identical";
3. **is controlled**: a second shipped run, from another path, must pass
   the same comparison against the first, on every run (Sample_DM always,
   every world with `CONTROL=1`);
4. **keeps both sides' conditions equal**: same inputs, fresh working
   directories (the Processor reads `processor.opt` from its own), paths of
   the same length (`tests/README.md`).

## File formats: read the version check *and* the writer

When a tool reads or writes a game's files, the format limits come from
the binaries, not from headers: **the check that prints the error, and the
constant written next to it** (lithtools `FORMATS.md`). NOLF Tools 001's
Processor writes 0x42 (66), AvP2 1.0's 0x46 (70), and NOLF's engine
refuses any world that isn't 66: so NOLF needs its own Processor.

Read what the check actually tests. NOLF2's and CJ's engines check only a
**minimum** model version, `cmp eax,0x17` / `jae` before "fileversion %d
is not supported" (SDK build 51's checks 18), while Build 69's
`Model_Packer.exe` writes `mov ebx,0x19` (25), the 2003 tools 0x17 (23).
A v25 model passes the 2003 check, but version 24 changed how per-model
OBBs are stored, so a 2003 engine would misread it: Build 69's tools
cannot make these games' models as they are. The `MODEL_FILE_VERSION 25`
in nolf2src's and cjacksrc's trees is Build 69's header carried over, not
what their retail engines check (`FORMATS.md`, "The newer engine").

**Verify each reader against every shipped asset.** Every reader in
`tools/lithrez` comes with a `<format>_verify` that reads every file of
that type in a game's archives (`renderstyle_verify`, lithtools d84f023:
every render style, `.ltb` type 5; `lip_verify`, bf68799: every `.lip`
against its voice line; also `abc_verify`, `ltb_verify`, `spr_verify`,
`texfx_verify`, ...). They read the games' archives, which are never
committed, so they sit outside `ctest` (`tools/lithrez/README.md`,
"Checks against the shipped games"). A unit test on one sample proves the
reader reads that sample. A census of the shipped versions
(`scripts/fmtversions.py`) is the same idea one level up: it is what found
NOLF's one v11 and two v9 models beside 692 v12s (`FORMATS.md`, "Shipped
assets").

## Tools' retail bugs: document now, fix later

Our sources reproduce the retail tools' bugs on purpose, like the games'.
They go in `legacy/talon/RETAIL_BUGS.md` (88 so far), each read off the
retail bytes at the address it names and stating how well our function
matches there. Unlike the games, which fix theirs in a modern build of the
same source ([18](18_modern_builds.md)), **the tools are not given a
modern variant**: they are to be re-implemented later with the fixes
applied, and that list is what the re-implementation starts from. Don't
fix a tool's bug in the reconstruction.
