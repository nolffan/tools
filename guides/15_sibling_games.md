# 15 · Starting a game from a sibling

This guide tells you how to start a new LithTech game from a sibling game
that is already far along. We started every game after NOLF this way:

- AvP2 from the nolfsrc engine.
- The NOLF2 engine from the Jupiter tree.
- Contract J.A.C.K. from nolf2src.
- Tron 2.0 from nolf2src, together with the Monolith dev snapshot of Tron.

The sibling gives you tens of thousands of lines that are almost correct.
Most of the early work is to find *where* these lines are wrong. The
interfaces and the struct layouts show this at the lowest cost. The
functions do not.

The steps below are in the order that gave the best results:

1. Choose the base.
2. Prove the toolchain.
3. Import the code.
4. Use the first build as a gate.
5. Fix the interfaces and the layouts.
6. Work on the functions only after that.

## Day 1: the scoreboard before any source

All four repos started in the same way. Each has an empty commit, then a
plan and a scoreboard, and only then the first imported source (tron20src
27b3b66, avp2src 4f8f24f, cjacksrc b9ca749):

- The rez repository (`~/src/rez`) installs the target release. Rez is
  not a submodule of the project. `make reference` extracts
  each binary with its function tables and vtable tables.
  `progress/targets.py` gives the location of the code of each image.
  Provisional boundaries are satisfactory (see
  [14-progress](14_progress.md#adapting-it-to-another-project)).
- The tools do not know a binary by its name. They read `targets.py`
  through `tools/tgt.py` (nolf2src `docs/SETUP_NOTES.md`, "A shared
  `decomp` submodule?").
- `make progress` records the first baseline, with all functions
  unwritten (Tron: 39,790). We measure each import and each port against
  that baseline.
- `progress/COMPILERS.md` gets the Rich-header reading for each image
  ([01](01_environment.md#which-toolchain-built-a-given-retail-binary)).
  `RETAIL_BUGS.md` and `MODERN.md` start empty.
- Add the data check, the float-constant check and the vtable check
  while nothing is built (tron20src 47fc194). Then the checks already run
  when the first image appears.

**Choose the target release before you choose a base.** Pick the last
release that contains all the content (the GOTY/EU rule). Avp2src chose
Primal Hunt 1.0.2.2. It has all the AvP2 patches and newer engine binaries.
Avp2src kept the game DLLs of AvP2 1.0.9.6 as separate targets, because
Primal Hunt plays only its own campaigns. The 1.0.9.6 engine then became a
second witness (avp2src 469525b). We have no GOTY or EU release of Tron.
Thus the Tron target is the USA v1.030 (27b3b66).

## Step 1: date the base, don't assume it

A sibling tree is the correct base only if the game shipped *that revision*
of the shared code. Measure this before you import.

**Count the literals that only one candidate has, then find them in
retail.** Tron had two candidates for the shared server code:

- The `ObjectDLL` of Build 51 (March 2002).
- The `ObjectShared` of NOLF2 1.3 (late 2002).

Retail `Object.lto` contains 417 of the string literals that only NOLF2 1.3
has. The literals that retail does not contain are mostly the last
multiplayer additions of NOLF2. Thus the base is NOLF2 1.3. This is true
although the Tron Build 69 snapshot is a May 2002 tree on the Build 51 API
(tron20src `docs/PLAN.md` §4, 789512a).

**For an engine, compare the strings, the object order and the imports.**
We started the Contract J.A.C.K. engine from the nolf2src engine (2002
engine, D3D8). We did not use the newer 2006 Jupiter tree. Three facts
decided this (cjacksrc `docs/PLAN.md` §6):

1. The strings of the single-player demo engine are almost all the NOLF2
   strings.
2. Its object order (string anchors, interface registrations) is the
   NOLF2 order, module for module.
3. It imports `d3d8.dll`/`dinput8.dll` and links D3DX8.

**Measure how much of the image a tree covers.** The nolf2src study of the
2006 Jupiter tree (`docs/engine/fear_mapping.md`) found that the tree
covered approximately 90% of `Lithtech.exe` and 95% of `server.dll`. The
study came before the decision to cut the tree back to 2002.

**Use the newer tree for additions only, through a three-way merge.**
Contract J.A.C.K. is NOLF2 plus one year. It took the changes of the 2006
tree to the shared game code as a three-way merge, with the NOLF2 release
as the base. The merge was approximately 1,000 lines in 109 files (cjacksrc
`docs/PLAN.md`, "Port"). Contract J.A.C.K. did not change its base. It did
not take some features, because retail does not have them. An example is
`kInputSprintfFriendly`: the CJ edit control has no `%` test.

Make two lists. List what the game has and the base does not have. List
what the base has and the game removed. Cjacksrc §6 keeps the two lists,
and they become the work list.

The dev snapshot of a game is usually *older* than retail. The TRON
directories of Build 69 say "TRON Build 20 (05/09/02)". Retail says
"Build 74", 17 months later. Use the snapshot for the code that is specific
to the game. Use the dated sibling for all the shared code.

## Step 2: prove the toolchain on the smallest binaries

Before the game DLLs, build the binaries that contain almost only resources
or one library: `ltmsg.dll`, `SndDrv.dll` (tron20src 379af4a, cjacksrc
463917f). The first score of these binaries tests the compiler, the SDK
headers and the build system, with almost no source. The first build of
the Tron `SndDrv.dll` gave 131 of 284 identical. The remaining functions
were features from the 2006 tree. We recorded them as known (see Step 4).

**Don't inherit the compiler of a component from the sibling.** Read the
Rich header of each image yourself. We thought that the AvP2 `d3d.ren` was
built with Intel C/C++, as the NOLF `d3d.ren` was. It was built with
cl 8168:

- It has 2 Intel lea-padding sequences. The NOLF renderer has 313.
- The C++ 8168 ×73 rows of its Rich header are its own objects.

A rebuild with cl 8168 took it from 10 to 857 identical (avp2src 80034dc,
`progress/COMPILERS.md`). The same repo also found that its game DLLs mix
cl 8168 and cl 8966 file by file (CShell.dll: 105 and 83 sources).
[01](01_environment.md#which-toolchain-built-a-given-retail-binary) tells
you how to read the evidence.

The flags need the same check. The removal of `/GX` from the Contract
J.A.C.K. game projects gave 950 more functions in CShell.dll and 1,760 more
in Object.lto (cjacksrc `docs/PLAN.md`, "Flags").

## Step 3: import, then port in separate commits

**Import the tree "as it is", then change it.** The first commit of each
imported tree is not modified. Examples are tron20src 5eea8c5 ("Import
Build 69's Tron 2.0 game code, as it is") and cjacksrc 833c707 ("Import
nolf2src's engine source, as it is"). Then each subsequent change is a diff
against known source that you can review.

**Remove the variant blocks of the sibling first.** The `*_MODERN` and
`*_DEBUG` blocks of a sibling are not part of the retail source. A block
that the release build skips also moves the lines below it. Because of
this, VC6 can place out-of-line inlines differently. Import the tree as the
release build compiles it, with `tools/releasesrc.py strip <file>`.
Tron did this in tron20src cf7ebf1 and 379af4a: nolf2src 48c2506 with its
blocks resolved out and its `RETAIL` reconstructions kept.

Avp2src used a different method. It renamed the nolfsrc `NOLFSRC_MODERN` to
`AVP2_MODERN` (bef5102). The name is now `AVP2SRC_MODERN`. The two methods
are satisfactory. A block that belongs to the wrong game without a
statement is not satisfactory.

**Rebase the files of an old API with a three-way merge.** Most of the Tron
screens in Build 69 are the TO2 screens of Build 51 with the Tron changes.
We made each of them again with `git merge-file`:

- ours = the NOLF2 1.3 file.
- base = the Build 51 file (the common ancestor).
- theirs = the Tron file.

The result is the NOLF2 API with the Tron intent. 26 of 45 files merged
without conflicts (tron20src df50fb5). If the two sides changed the same
lines, take the side of the game. Keep the side of the sibling next to it
as a `// MERGE:` comment. The byte matching can then decide later.

**Port by hand only what the merge cannot join, and mark each change.**
Some files did not merge correctly. They went back to the Tron Build 69
version, and we ported them by hand (ScreenSingle, HUDCrosshair: 8342ae1).
Each API change has the mark `PORT:`. We made some of these changes with a
mechanical rewrite. Examples are the message accessors and the message id
that moved into the message (789512a).

**Write a note where the file of the sibling is a stand-in.** Retail cannot
have had either version of some files. An example is the Tron multiplayer
screens: the TO2 screens use WON, and retail uses GameSpy. In this case,
the NOLF2 file goes in with a note at its top (8342ae1). Give the stubs for
missing subsystems names that show that they are stubs. The WON
server-directory factory returns no directory until we write the GameSpy
code.

## Step 4: the first build is a gate

When an image links for the first time, score it. Record each of its
*known* differences as `UNREVIEWED`, with the date and the reason. Put
them in `progress/data-known.txt` and `progress/vtab-known.txt`:

- The first build of Object.lto gave 6,963 of 15,577 identical, with 1,912
  unwritten (tron20src 789512a). CShell.dll gave 2,732 of 9,549 (5aa07a9).
- We set `/GR` to match the retail RTTI. This added RTTI for classes that
  retail does not have (stand-in screens, May 2002 classes that Tron
  removed). We recorded these with that reason too (7d946f9).

After that, `datacheck.py` and `vtabcheck.py` make the run fail on each
difference that is *not* in the list
([14](14_progress.md#the-data-check)). This makes the first build a fixed
baseline. Then you see each new string, missing import or incorrect slot
when it first appears. When you find the cause of a difference, give its
entry a real reason or remove the entry.

## Step 5: the interfaces before anything else

A sibling SDK header can have one slot in the wrong position. Then **each**
call after that slot goes to the wrong function. This shows as hundreds of
nears and, at run time, as a crash. Fix the engine interfaces first,
because they give the most functions for each changed line.

**Function-pointer members: read the fill order of the engine.**
`ILTClient` and `ILTServer` are structs of function pointers. The retail
engine fills them in long sequences of `mov [reg+off], imm` stores. These
sequences align one for one with the named assignments of the reference
engine (`CLTClient::InitFunctionPointers`, `winclientde_impl.cpp`,
`serverde_impl.cpp`). Thus the alignment gives the name of each offset.
Compare the result with the offsets that the near functions of the game
call.

For Tron, Lithtech.exe has two sequences (127 stores and 46 stores). The
near calls agreed 63 of 63. Tron kept the Build 51 order where NOLF2 changed
the order (`GetConsoleVar` at +0x18c, not at the NOLF2 offset +0xf8). One
header change gave CShell.dll +166 identical (tron20src 21b556b).
`ILTServer` has one sequence of 107 stores, and the calls agreed 55 of 55
(8d627cf). Record each offset with its evidence
(`progress/engine/*-offsets.csv`).

**Virtuals: find the name of each slot from its body.** Build the reference
engine (the engine of the sibling). Match the body of each retail vtable
slot against it. The calls of the game are fixed points. Identical stub
bodies can make two methods ambiguous. If this occurs, the calls of the
other engine or the order of an older SDK decide.

The Tron `CLTClient` (94 slots) and `CLTServer` (76 slots) have the Build
51 order, with the NOLF2 additions inserted. This gave +300 identical
(0377246). The 17 `IServerShell` virtuals of the server shell have an
order that is specific to Tron (4695d20). Record them in
`progress/engine/*-vtable.csv`. If a header gives the name of the slot but
not its position, use the method in [07](07_vtables.md).

**Do not trust an order rule until calls on the two sides confirm it.** VC6
puts the overloads of a name together, **in the reverse of their
declaration order**. Tron first recorded the opposite rule (8d627cf: "in
declaration order"). It placed the extra Tron `DrawPrim` overload with that
rule, and put the slot of `LT_POLYFT4` in the wrong position. The calls of
the game to `CreateFont` and `SetText` showed the reverse order (b4717cd).
We corrected the `DrawPrim` position against two retail calls, one on each
side of the insertion (CShell.dll 0x1002948a, 0x100220db: 4e170d2).

NOTE: The old rule ("in declaration order") is still in these tron20src
locations. For overloads, it is wrong.

- The first bullet of `docs/PLAN.md` §4a.
- The headers of the `ILTDrawPrim`, `ILTCommon` and `ILTModel` vtable CSVs.
- The docstring of `tools/sdkvtab.py`.

**Compare a header that you edit by hand with the compiler output.** Take a
member pointer to each virtual. VC6 compiles it to a vcall thunk. The
`jmp [eax+N]` of the thunk gives the slot. Thus a small probe file lists
the slots that your header really makes (tron20src `docs/PLAN.md` §4a; its
`out/work/` probe is local and not tracked). The probe shows what your
header does. Only the retail calls show what the header must do. You need
the two.

**A missing slot shows as a crash, not as a near.** The Contract J.A.C.K.
`CLTClient` has a virtual between `AddParticle` and `StartQuery` that the
SDK did not have (`GetUDPSocket`, our name). Thus each `ILTClient` call in
the game after this slot was 4 bytes short. Retail CShell.dll calls
`SetLightGroupColor` through +0x150. With the retail game DLLs, the engine
that we built crashed in its first frames. The crash stopped when we added
the slot (cjacksrc `docs/PLAN.md`, "Round 4", and §8).

## Step 6: layouts, which are most of a port's nears

When the interfaces are correct, most of the remaining nears in a ported
tree come from **struct layout, not from codegen**. In these nears, the
bytes are different only in the displacements from one base. All of the
displacements move by the same quantity. `tools/layoutscan.py` finds this
pattern in the nears of a target.

**Read the displacement pairs from aligned nears, then count.** Align our
near with the retail near, instruction by instruction. Read the (old, new)
displacements. Then count the uses of each candidate in the retail images
of *the two* games to confirm it. Examples from avp2src:

- Three insertions in `CServerMgr` relative to NOLF gave 335 functions
  (ddded5c). The insertions are +4 before the object lists, +0x408 after
  `m_hWorldFile`, and +4 after `m_NetMgr`.
- Two insertions in the object base gave 345 functions (cd16e26).
- Avp2src examined the near list of lithtech.exe group by group ("nearly
  every near was layout rather than codegen"). This added 834 identical,
  with no loss (453a4a9).

**Then write the views again with the offsets of the new game.** Avp2src
first wrote its layout fixes as macros that change a NOLF offset to an
AvP2 offset (`AVP2_MGR`, `AVP2_OBJ`). The pads looked like
`0x5c4 - 0x394 + 4`, and the member comments gave the NOLF offsets. e3eaba7
replaced all of this with the AvP2 offsets and deleted the macros. The
score did not change. Do it that way from the start. The tree belongs to
the new game. It is not the tree of the sibling with a diff on top.

**Constructors and `Save` are the best layout witnesses.** A constructor
touches almost all the members. `Save`/`Load` touch them *in member order*.
Make a list of the offsets that the retail `Save` and the retail
constructor touch, in order. Put our compiled offsets next to it. The two
lists give the layout. Examples from tron20src:

- We did the Tron `CGameServerShell` from its constructor and `Save`
  (4250b3a).
- We matched `CPlayerObj` through `m_hPlayerLure` (0x2e58) for 44
  functions, after `CPlayerScore` had the retail size (02d62c4).

The tron20src helpers for this are `offprobe.sh` (our offsets) and
`savemap.py` (the alignment). They are in its `out/work/`, which is not
tracked. Move them into `tools/` when the next game needs them.

**RTTI gives the name of each vtable, so compare the slot counts first.** A
game built with `/GR` has a complete object locator for each polymorphic
class. A comparison of its slot counts with our slot counts shows which
classes have more or fewer virtuals. You can do this before you read a
function. In cjacksrc, a small number of header changes found in this way
took Object.lto from 5,375 to 5,705 (`docs/PLAN.md`, "Method that pays").
The base-class descriptors also find incorrect hierarchies. Retail RTTI
shows that the Tron `CScanner` derives from `PropType`, not from `Prop`.
This fixed a 0x10 shift in each member (tron20src 0ef3fc3).

**One constant delta is one blocker. Pad against it and continue.** In our
library, the Tron `CButeMgr` is 0x40 bytes larger than in the retail
library. That one fact causes a near in each bute manager (635d3b5). Write
the dependent class at the retail offsets, with a pad array of the size of
the difference. When the base is fixed, the class stops compiling. Thus it
tells you to remove the pad. An example is `SecRezzer` against the
`CDestructibleModel` size, 0x738 instead of 0x728 (f707b07).

## Protected executables: the demo as a stand-in

A SecuROM-wrapped engine has encrypted pages and redirected import calls.
Each `call [IAT]` points to one dispatcher. Thus retail does not show which
import a call site calls. A demo built from the same source fixes the two
problems:

- The unprotected demo supplies the code of the encrypted pages. For
  NOLF2 these are five pages, with ≈146 UI, ≈60 CRT/thunk and ≈35 D3DX
  functions.
- The demo also supplies the import behind each redirected call (NOLF2:
  all 1,514). Read it from the matching instruction (nolf2src
  `docs/engine/anatomy.md` §2).
- `tools/demoimports.py` makes the map. Before it scores, the scorer
  writes the original `ff 15 <slot>` back. Thus functions with such calls
  can match (cjacksrc 82507cc, for the 91 direct-call variants of
  SecuROM).

**Pick the demo whose Rich header matches retail triple for triple.** For
NOLF2, the multiplayer demo matches. 94.5% of the app instructions of the
exe are the same, but the prerelease build gets only 26.9%. For Contract
J.A.C.K., it is the *single-player* demo. The engine of the multiplayer
demo is a `/GS` build with three more C objects (the objects of the
cookie). Thus it is a different build (cjacksrc `progress/COMPILERS.md`,
"No `/GS`").

**Use the demo for code and data, never for addresses.** The demo links
some objects in a different position (anatomy.md: "Object order differs in
places").

**Look for a port that is not stripped.** The Mac NOLF2 engine has 11,485
text symbols with full Itanium-mangled names. Its strings contain real
source paths. Its `define_holder` interface registrations are at the start
of the code of each object. They are also file anchors in the Windows
image (anatomy.md §3, `tools/macho.py`, `tools/macinventory.py`).

## Porting fixes between sibling repos

When we work on two siblings at the same time, fixes move between them.
Port the fixes **one at a time, and measure each one in the target repo**.
A fix that is correct in one game can be wrong in the other game. Of the
recent nolf2src engine fixes, cjacksrc took one (+1, cfd2625):

- The server interface entries of nolf2src caused a loss of 29 server.dll
  functions. The Contract J.A.C.K. retail really waits on `m_bUpdating`.
- Other fixes changed nothing, or used STLport, which CJ does not link.

For modern-build features, use the same discipline in a table. Put one row
for each upstream commit, with a decision (ported / nothing new / not
applicable, and why). The nolf2src `nolfsync` table (`docs/engine/PLAN.md`
§17) is the model.

## Boot it early

The score cannot see the connections between parts. A vtable can have the
correct size and still have the wrong function in a slot. The first boots
of avp2src found these problems (avp2src f244290, 27eb79d, baebb5b):

- Vtable twins. The `ILTModel` `GetNode` and `GetSocket` were swapped, with
  the same masked bytes.
- A base stub in the position of an override. The `CObjWorldModel`
  `OnFoundInBox` stub made the world render black.
- Structs declared too small, which wrote over the globals after them. The
  `d3d.ren` `g_FormatMgr` was declared as 0x9a8, but it is really 0xb94.

Run the game as soon as it links, and continue to run it. See
[05](05_exe_and_engine.md#running-the-thing--nears-have-to-execute).

## Checklist

1. Start from an empty repo. Add the target release, `targets.py`, the
   first all-unwritten baseline, `COMPILERS.md` from the Rich headers, and
   the checks.
2. Date the base by the literals that only one candidate has. Newer trees
   supply additions only, through a three-way merge.
3. Build the small binaries first. Read the compiler of each component
   yourself.
4. Import the tree without changes. Remove the variant blocks of the
   sibling. Use `git merge-file` on the old-API files. Mark each change
   `MERGE:` or `PORT:`. Mark the stand-ins.
5. At the first link of each image, record the known differences as
   `UNREVIEWED`. Let the checks hold the remaining differences.
6. Interfaces: read the function-pointer fill order. Match the slot bodies
   against the built sibling engine. Confirm the overload order with calls.
   Probe the header.
7. Layouts: use displacement pairs, usage counts, constructor and `Save`
   witnesses, RTTI slot counts, and one pad for each blocker. Use the
   offsets of the new game.
8. Boot the game. Then start work on the functions
   ([13](13_cluster_recon.md)).
