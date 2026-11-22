# 15 · Starting from related source

This guide tells you how to start a reconstruction when related source
exists. Related source can be one of these:

- A sibling game on the same engine that is already reconstructed.
- A public SDK, or a source release of an older or newer engine version.
- A developer build or a source snapshot of the game.
- A demo build of the game.

Related source gives you many lines that are almost correct. Most of the
early work is to find *where* these lines are wrong. The interfaces and the
struct layouts show this at the lowest cost. The functions do not.

Do the steps below in their order. The examples come from LithTech games.
The rules apply to all engines that several products share.

## Day 1: the scoreboard before any source

Set up the measurement before you import a line of source. Then you can
measure each import and each port against a known start.

1. Choose the target release. Pick the last release that contains all the
   content.
2. Extract each target binary with its function tables and vtable tables.
3. Write down where the code of each image is. Provisional boundaries are
   satisfactory (see
   [14-progress](14_progress.md#adapting-it-to-another-project)).
4. Record a first baseline, with all functions unwritten.
5. Read the Rich header of each image and record the compiler of each one
   ([01](01_environment.md#which-toolchain-built-a-given-retail-binary)).
6. Start an empty list of retail bugs and an empty list of modern changes.
7. Add the data check, the float-constant check and the vtable check now.
   Then the checks run when the first image appears.

NOTE: Keep the names of the binaries in one table, and make each tool read
it. In this repository, `tools/tgt.py` reads that table.

A product with expansions or patches can have more than one useful
release. Use the newest release as the target. Keep an older release as a
second witness when it contains different content.

Example: avp2src targets the Primal Hunt expansion. It keeps the AvP2
1.0.9.6 game DLLs as targets, because Primal Hunt has only its own levels.

## Step 1: date the base, do not assume it

Related source is the correct base only if the product shipped *that
revision* of the shared code. Measure this before you import.

**Count the literals that only one candidate has, then find them in
retail.** Extract the string literals of each candidate tree. Keep only the
literals that one candidate has and the other does not have. Search the
retail image for each of them. The candidate with the most hits is the
base.

Example: tron20src had two candidates for the shared server code. They
were a March 2002 tree and the NOLF2 1.3 tree from late 2002. Retail
`Object.lto` contains 417 of the literals that only NOLF2 1.3 has. Thus the
base is NOLF2 1.3. This is true although the Tron snapshot is a May 2002
tree on the older API.

**For an engine, compare the strings, the object order and the imports.**
These three facts identify the revision:

1. The strings of the retail engine against the strings of each candidate.
2. The object order: string anchors and interface registrations, module
   for module.
3. The imported DLLs and the linked libraries (for example, the Direct3D
   version).

Example: cjacksrc started its engine from the 2002 NOLF2 engine, not from
a 2006 tree. The strings, the object order and the `d3d8.dll` imports all
agreed with NOLF2.

**Measure how much of the image a tree covers.** A newer tree can cover
most of an image and still have the wrong revision. Example: a 2006 engine
tree covered approximately 90% of a 2002 engine executable.

**Use a newer tree for additions only, through a three-way merge.** Keep
the dated base. Merge the changes of the newer tree into the shared code.
Use the older release as the common ancestor. Do not take a feature that
retail does not have.

Example: Contract J.A.C.K. is NOLF2 plus one year. Its merge from the 2006
tree was approximately 1,000 lines in 109 files. It did not take
`kInputSprintfFriendly`, because the retail edit control has no `%` test.

Make two lists. List what the product has and the base does not have.
List what the base has and the product removed. These lists become the
work list.

**A developer snapshot is usually older than retail.** Read the build
dates in the snapshot. Use the snapshot for the code that is specific to
the product. Use the dated base for all the shared code.

Example: the Tron snapshot says "TRON Build 20 (05/09/02)". Retail says
"Build 74", 17 months later.

## Step 2: prove the toolchain on the smallest binaries

Before the large modules, build the binaries that contain almost only
resources or one library. Their first score tests the compiler, the SDK
headers and the build system, with almost no source.

Example: the first build of the Tron `SndDrv.dll` gave 131 of 284
identical. The remaining functions were features from a newer tree, which
were recorded as known (see Step 4).

**Do not inherit the compiler of a component from related source.** Read
the Rich header of each image yourself. Also count the codegen signatures
of each compiler, for example the padding sequences.

Example: the NOLF `d3d.ren` was built with Intel C/C++. The AvP2
`d3d.ren` has 2 Intel padding sequences, where the NOLF renderer has 313.
Its Rich header shows cl 8168 objects. A rebuild with cl 8168 took it from
10 to 857 identical.

One module can mix compiler versions file by file. Example: the AvP2
`CShell.dll` has 105 sources from cl 8168 and 83 from cl 8966.
[01](01_environment.md#which-toolchain-built-a-given-retail-binary) tells
you how to read the evidence.

**Check the flags in the same way.** Example: the removal of `/GX` gave
Contract J.A.C.K. 2,710 more identical functions.

## Step 3: import as it is, then port in separate commits

**Import the tree without changes, then change it.** Make the first
commit of each imported tree an exact copy. Then each subsequent change is
a diff against known source that you can review.

**Remove the variant blocks of the related source first.** A sibling
reconstruction can contain blocks for a modern build or a debug build.
These blocks are not part of the retail source. A block that the release
build skips also moves the lines below it. Because of this, the compiler
can place out-of-line inlines differently.

Import the tree as the release build compiles it. In this repository,
`tools/releasesrc.py strip <file>` resolves the blocks and keeps the retail
reconstructions. Alternatively, rename the variant macro to the macro of
the new project. Both methods are satisfactory. A block that belongs to
the wrong product without a statement is not satisfactory.

**Rebase the files of an old API with a three-way merge.** A snapshot can
use an older API than the dated base. Make each file again with
`git merge-file`:

- ours = the file of the dated base.
- base = the file of the older API (the common ancestor).
- theirs = the file of the product.

The result is the API of the base with the intent of the product. If the
two sides changed the same lines, take the side of the product. Keep the
other side next to it as a `// MERGE:` comment. The byte matching can then
decide later.

**Port by hand only what the merge cannot join, and mark each change.**
If a file does not merge correctly, go back to the file of the product.
Port it by hand. Mark each API change with `PORT:`. Make repeated API
changes with a mechanical rewrite, for example a changed accessor.

**Write a note where a file is a stand-in.** Sometimes retail cannot have
had either version of a file. Then import the closest file with a note at
its top. Give the stubs for missing subsystems names that show that they
are stubs.

Example: the Tron snapshot multiplayer screens use WON, and retail uses
GameSpy. Thus the NOLF2 screens went in as stand-ins.

## Step 4: the first build is a gate

When an image links for the first time, score it. Record each of its
*known* differences as `UNREVIEWED`, with the date and the reason. Keep
them in a known-differences file for each check.

Example: the first Tron `Object.lto` build gave 6,963 of 15,577
identical. Its stand-in classes added RTTI that retail does not have, and
these were recorded with that reason.

After that, make the checks fail on each difference that is *not* in the
list ([14](14_progress.md#the-data-check)). This makes the first build a
fixed baseline. Then you see each new string, missing import or incorrect
slot when it first appears. When you find the cause of a difference, give
its entry a real reason or remove the entry.

## Step 5: the interfaces before the functions

An SDK header can have one slot in the wrong position. Then **each** call
after that slot goes to the wrong function. This shows as hundreds of near
matches and, at run time, as a crash. Fix the interfaces first, because
they give the most functions for each changed line.

**Function-pointer members: read the fill order of the initialiser.** An
engine can fill an interface struct with a long sequence of
`mov [reg+off], imm` stores. Align these stores one for one with the named
assignments in the reference source. The alignment gives the name of each
offset. Compare the result with the offsets that the game calls.

Example: the Tron engine has two fill sequences (127 and 46 stores), and
the game calls agreed 63 of 63. Record each offset with its evidence.

**Virtuals: find the name of each slot from its body.** Build the
reference engine from the related source. Match the body of each retail
vtable slot against it. The calls of the game are fixed points. Identical
stub bodies can make two methods ambiguous. If this occurs, use the calls
of another engine or the order of an older SDK.

Example: the Tron client and server interfaces have the older order,
with the newer additions inserted. This gave +300 identical. If a header
gives the name of a slot but not its position, see [07](07_vtables.md).

**Do not trust an order rule until calls on the two sides confirm it.**

NOTE: VC6 puts the overloads of one name together, **in the reverse of
their declaration order**. Evidence: tron20src first recorded the opposite
rule. It placed an extra `DrawPrim` overload with that rule, and put one
slot in the wrong position. The game calls to `CreateFont` and `SetText`
showed the reverse order. Two retail calls, one on each side of the
insertion, confirmed the corrected position (`CShell.dll` 0x1002948a and
0x100220db; tron20src 4e170d2).

**Compare a header that you edit by hand with the compiler output.** Take
a member pointer to each virtual. VC6 compiles it to a vcall thunk. The
`jmp [eax+N]` of the thunk gives the slot. Thus a small probe file lists
the slots that your header really makes. The probe shows what your header
does. Only the retail calls show what the header must do. You need the
two.

**A missing slot shows as a crash, not as a near match.** If the SDK does
not have a virtual, each later call is 4 bytes short.

Example: the Contract J.A.C.K. client interface has a virtual that the SDK
did not have. With the retail game DLLs, our engine crashed in its first
frames until we added the slot.

## Step 6: class layouts before the functions

When the interfaces are correct, most of the remaining near matches in a
ported tree come from **struct layout, not from codegen**. In these near
matches, only the displacements from one base are different. All of the
displacements move by the same quantity. In this repository,
`tools/layoutscan.py` finds this pattern in the near matches of a target.

**Read the displacement pairs from aligned near matches, then count.**

1. Align our function with the retail function, instruction by
   instruction.
2. Read each (old, new) displacement pair. The delta starts at the
   insertion point.
3. Count the uses of each candidate in the retail images of the two
   products to confirm it.

Example: in avp2src, three insertions in the server manager gave 335
functions. Two insertions in the object base gave 345 functions. Almost
all near matches in the engine were layout, and the group-by-group review
added 834 identical with no loss.

**Then write the class again with the offsets of the new product.** Do not
keep the layout as macros that convert old offsets to new offsets. Do not
write pads such as `0x5c4 - 0x394 + 4`. The tree belongs to the new
product. It is not the related tree with a diff on top.

Example: avp2src replaced its conversion macros with the AvP2 offsets
later. The score did not change.

**Use the constructor and the save/load functions as layout witnesses.**
A constructor touches almost all the members. Save and load functions
touch them *in member order*.

List the offsets that the retail constructor and save function touch, in
order. Put our compiled offsets next to the list. The two lists give the
layout.

Example: tron20src matched `CPlayerObj` in this way for 44 functions.

**RTTI gives the name of each vtable, so compare the slot counts first.**
A product built with `/GR` has a complete object locator for each
polymorphic class. Compare its slot counts with our slot counts. This
shows which classes have more or fewer virtuals, before you read a
function. The base-class descriptors also show incorrect hierarchies.

Example: in cjacksrc, a small number of header changes found in this way
took `Object.lto` from 5,375 to 5,705 identical. In tron20src, retail RTTI
showed that `CScanner` derives from `PropType`, not from `Prop`. This fixed
a 0x10 shift in each member.

**A constant offset delta is one blocker. Pad against it and continue.**
If a base class has the wrong size, each derived class has a near match.
Write the derived class at the retail offsets. Add a pad array of the size
of the difference. When the base is fixed, the class stops compiling. Thus
it tells you to remove the pad.

Example: in tron20src, `CButeMgr` was 0x40 bytes too large, which caused a
near match in each bute manager. `SecRezzer` was padded against a
`CDestructibleModel` of 0x738 instead of 0x728.

## Protected executables: a demo as a stand-in

A copy-protection wrapper can encrypt pages of code and redirect import
calls. Then each `call [IAT]` points to one dispatcher. Retail does not
show which import a call site calls. An unprotected demo built from the
same source solves the two problems:

- The demo supplies the code of the encrypted pages.
- The demo supplies the import behind each redirected call. Read it from
  the matching instruction in the demo.
- Before you score, write the original `ff 15 <slot>` back into the
  retail copy. Then functions with such calls can match.

Example: the NOLF2 demo gave the import of all 1,514 redirected calls.
In this repository, `tools/demoimports.py` makes the map.

**Pick the demo whose Rich header matches retail, triple for triple.** Two
demos of one product can come from different builds.

Example: for NOLF2, 94.5% of the instructions of the multiplayer demo are
the same as retail. The prerelease build gets only 26.9%. For Contract
J.A.C.K., the multiplayer demo is a `/GS` build with three more C objects.
Thus only the single-player demo matches.

CAUTION: Use the demo for code and data only, never for addresses. A demo
can link some objects in a different position.

**Look for a port that is not stripped.** A port to another platform can
keep its symbols, which give names. Its object order gives file anchors
for the stripped image. Example: the Mac NOLF2 engine has 11,485 text
symbols with full mangled names (`tools/macho.py` reads it).

## Port fixes between related projects one at a time

When you work on two related projects at the same time, fixes move between
them. Port the fixes **one at a time, and measure each one in the target
project**. A fix that is correct in one product can be wrong in the other.

Example: of a group of NOLF2 engine fixes, Contract J.A.C.K. took only
one. Another fix caused a loss of 29 functions, because that retail code
really waits on a flag.

For modern-build features, use the same discipline in a table. Put one
row for each upstream commit, with a decision and a reason (ported, nothing
new, or not applicable).

## Boot it early

The score cannot see the connections between parts. A vtable can have the
correct size and still have the wrong function in a slot. Early boots find
these problems:

- Vtable twins. Two methods have the same masked bytes and are in the
  wrong order. Example: `ILTModel` `GetNode` and `GetSocket`.
- A base stub in the position of an override. Example: one stub made the
  world render black.
- Structs declared too small, which write over the globals after them.
  Example: a renderer global declared as 0x9a8 bytes was really 0xb94.

Run the program as soon as it links, and continue to run it. See
[05](05_exe_and_engine.md#running-the-thing--nears-have-to-execute).

## Checklist

1. Before you import source, add the target release, the image table, the
   first all-unwritten baseline, the compiler of each image, and the
   checks.
2. Date the base by the literals that only one candidate has. Use newer
   trees for additions only, through a three-way merge.
3. Build the small binaries first. Read the compiler and the flags of each
   component yourself.
4. Import the tree without changes. Remove the variant blocks. Use
   `git merge-file` with the common ancestor on the old-API files. Mark
   each change `MERGE:` or `PORT:`. Mark the stand-ins.
5. At the first link of each image, record the known differences as
   `UNREVIEWED`. Let the checks hold the remaining differences.
6. Interfaces: read the initialiser stores. Match the slot bodies against
   the built reference engine. Confirm the overload order with calls on
   the two sides. Probe the header.
7. Layouts: use displacement pairs, usage counts, constructor and
   save/load witnesses, RTTI slot counts, and one pad for each blocker.
   Use the offsets of the new product.
8. For a protected executable, use an unprotected demo with a matching
   Rich header.
9. Port fixes from related projects one at a time, and measure each one.
10. Boot the program. Then start work on the functions
    ([13](13_cluster_recon.md)).
