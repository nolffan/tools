# 15 · Starting a game from a sibling

How to bootstrap a new LithTech game from one that is already well along.
Every game after NOLF was started this way: AvP2 from nolfsrc's engine,
NOLF2's engine from the Jupiter tree, Contract J.A.C.K. from nolf2src, and
Tron 2.0 from nolf2src with Monolith's own dev snapshot. The sibling gives
you tens of thousands of lines that are nearly right. Most of the early work
is finding *where* they are wrong, and the cheapest place to find that is the
interfaces and the struct layouts, not the functions.

The steps below are in the order they paid off: choose the base, prove the
toolchain, import the code, take the first build as a gate, fix layouts and
interfaces, and only after that work on functions.

## Day 1: the scoreboard before any source

All four repos started the same way: an empty commit, then a plan and a
scoreboard, before any source was imported (tron20src 27b3b66, avp2src
4f8f24f, cjacksrc b9ca749):

- `rez` installs the target release, `make reference` extracts every
  binary with its function and vtable tables, and `progress/targets.py` says
  where each image's own code is (provisional boundaries are fine, see
  [14-progress](14_progress.md#adapting-it-to-another-project)). The tools
  know no binary by name. They read `targets.py` through `tools/tgt.py`
  (nolf2src `docs/SETUP_NOTES.md`, "A shared `decomp` submodule?").
- `make progress` records the first baseline with every function
  unwritten (Tron: 39,790). From then on, every import and port is measured
  against that baseline.
- `progress/COMPILERS.md` gets the Rich-header reading for every image
  ([01](01_environment.md#which-toolchain-built-a-given-retail-binary)), and
  `RETAIL_BUGS.md` / `MODERN.md` are created empty.
- The data, float-constant and vtable checks go in while nothing is built
  (tron20src 47fc194). That way they are already running when the first
  image appears.

**Choose the target release before choosing a base.** Pick the last release
that contains everything (the GOTY/EU rule). Avp2src chose Primal Hunt
1.0.2.2, which has every AvP2 patch and newer engine binaries, and kept
AvP2 1.0.9.6's game DLLs as separate targets because Primal Hunt plays only
its own campaigns. 1.0.9.6's engine was then used as a second witness
(avp2src 469525b). Tron has no GOTY or EU release held, so it is the USA
v1.030 (27b3b66).

## Step 1: date the base, don't assume it

A sibling tree is the right base only if the game shipped *that revision* of
the shared code. Measure this before importing:

- **Count literals unique to one candidate, then look for them in retail.**
  Tron's two candidates for the shared server code were Build 51's
  `ObjectDLL` (March 2002) and NOLF2 1.3's `ObjectShared` (late 2002). 417 of
  the string literals that only NOLF2 1.3 has are in retail `Object.lto`.
  What it lacks is mostly NOLF2's last multiplayer additions. So the base is
  NOLF2 1.3, even though Tron's own Build 69 snapshot is a May 2002 tree on
  Build 51's API (tron20src `docs/PLAN.md` §4, 789512a).
- **For an engine, compare strings, object order and imports.** Contract
  J.A.C.K.'s engine was started from nolf2src's (2002 engine, D3D8) and not
  from the newer 2006 Jupiter tree. Three things decided it: the
  single-player demo engine's strings are NOLF2's almost throughout, its
  object order (string anchors, interface registrations) is NOLF2's module
  for module, and it imports `d3d8.dll`/`dinput8.dll` and links D3DX8
  (cjacksrc `docs/PLAN.md` §6).
- **Quantify how much of the image a tree covers.** nolf2src's study of the
  2006 Jupiter tree (`docs/engine/fear_mapping.md`) found it covered about
  90% of `Lithtech.exe` and 95% of `server.dll` before anyone committed to
  trimming it back to 2002.

**Use the newer tree for additions only, by three-way merge.** Contract
J.A.C.K. is NOLF2 plus a year. It took the 2006 tree's changes to the shared
game code as a three-way merge with NOLF2's release as the base: about
1,000 lines in 109 files (cjacksrc `docs/PLAN.md`, "Port"). It did not
switch bases. Some features were not taken, because retail lacks them
(`kInputSprintfFriendly`: CJ's edit control has no `%` test). List what the
game has that the base lacks, and what the base has that the game dropped.
cjacksrc §6 keeps both lists, and they become the work list.

A game's own dev snapshot is usually *older* than retail. Build 69's TRON
directories say "TRON Build 20 (05/09/02)", while retail is "Build 74",
17 months later. Use the snapshot for the game-specific code and the dated
sibling for everything shared.

## Step 2: prove the toolchain on the smallest binaries

Before the game DLLs, build the binaries that are almost only
resources or one library: `ltmsg.dll`, `SndDrv.dll` (tron20src 379af4a,
cjacksrc 463917f). A first score here tests the compiler, the SDK headers and
the build plumbing with almost no source in play. Tron's `SndDrv.dll` gave
131 of 284 identical as first built. The rest were features from the 2006
tree, recorded as known (see Step 4).

**Don't inherit a component's compiler from the sibling.** Read each
image's Rich header yourself. AvP2's `d3d.ren` was assumed to be Intel C/C++
like NOLF's. It is cl 8168: it has 2 of Intel's lea-padding sequences where
NOLF's has 313, and its Rich header's C++ 8168 ×73 rows are its own objects.
Rebuilt that way it went from 10 to 857 identical (avp2src 80034dc,
`progress/COMPILERS.md`). The same repo also found that its game DLLs mix
cl 8168 and 8966 file by file (CShell.dll: 105 and 83 sources). How to
read the evidence is in
[01](01_environment.md#which-toolchain-built-a-given-retail-binary). Flags
are the same story: dropping `/GX` from Contract J.A.C.K.'s game projects
gained 950 functions in CShell.dll and 1,760 in Object.lto (cjacksrc
`docs/PLAN.md`, "Flags").

## Step 3: import, then port in separate commits

- **Import "as it is", change afterwards.** The first commit of each
  imported tree is unmodified: tron20src 5eea8c5 ("Import Build 69's Tron
  2.0 game code, as it is"), cjacksrc 833c707 ("Import nolf2src's engine
  source, as it is"). Every later change is then a reviewable diff against
  known source.
- **Strip the sibling's variant blocks first.** A sibling's
  `*_MODERN`/`*_DEBUG` blocks are not part of the retail source. Even a
  block the release build skips moves the lines below it, and VC6 can place
  out-of-line inlines differently because of that. Import the tree as the
  release build compiles it: `tools/releasesrc.py strip <file>` (tron20src
  cf7ebf1 and 379af4a: nolf2src 48c2506 with its blocks resolved out, its
  `RETAIL` reconstructions kept). Avp2src took the other route and renamed
  nolfsrc's `NOLFSRC_MODERN` to `AVP2_MODERN` (bef5102). Either is fine. A
  block that silently belongs to the wrong game is not.
- **Rebase old-API files with a three-way merge.** Most of Tron's screens in
  Build 69 are Build 51's TO2 screens with Tron's changes. Each was rebuilt
  as `git merge-file`, with ours = NOLF2 1.3's file, base = Build 51's (the
  common ancestor) and theirs = Tron's. The result is NOLF2's API with
  Tron's intent. 26 of 45 merged cleanly (tron20src df50fb5). Where both
  sides changed the same lines, take the game's side and keep the sibling's
  next to it as a `// MERGE:` comment, so the byte matching can decide later.
- **Port by hand only what the merge can't join, and mark every change.**
  Files that merged badly went back to Tron's own Build 69 version and were
  ported by hand (ScreenSingle, HUDCrosshair: 8342ae1). Every API change is
  marked `PORT:`, some done by mechanical rewrite (the message accessors,
  the message id moved into the message: 789512a).
- **Say so where the sibling's file stands in.** Where retail cannot have
  had either version (Tron's multiplayer screens: TO2's are on WON, retail
  uses GameSpy), NOLF2's file goes in with a note at its top (8342ae1).
  Stubs for missing subsystems are named as stubs: WON's server-directory
  factory returns no directory until the GameSpy code is written.

## Step 4: the first build is a gate

When an image first links, score it and record each of its *known*
differences as `UNREVIEWED`, with the date and the reason, in
`progress/data-known.txt` and `progress/vtab-known.txt`:

- Object.lto as first built: 6,963 of 15,577 identical, 1,912 unwritten
  (tron20src 789512a). CShell.dll: 2,732 of 9,549 (5aa07a9).
- Turning on `/GR` to match retail's RTTI added RTTI for classes retail
  does not have (stand-in screens, May 2002 classes Tron dropped). Those
  were recorded with that reason as well (7d946f9).

After that, `datacheck.py` and `vtabcheck.py` fail the run on any
difference that is *not* in the list ([14](14_progress.md#the-data-check)).
That turns the first build into a fixed baseline: from then on, every new
string, missing import or wrong slot is noticed when it first appears. As
each difference is explained, its entry gets a real reason or goes.

## Step 5: the interfaces before anything else

A sibling's SDK header with one slot in the wrong place makes **every** call
after it go to the wrong function. That shows up as hundreds of nears and,
at run time, as a crash. Fix the engine interfaces first, because they gain
the most functions per line changed.

**Function-pointer members: read the engine's fill order.** `ILTClient`
and `ILTServer` are structs of function pointers. The retail engine fills
them in long runs of `mov [reg+off], imm` stores. Those runs line up one
for one with the reference engine's named assignments
(`CLTClient::InitFunctionPointers`, `winclientde_impl.cpp`,
`serverde_impl.cpp`), so the alignment names each offset. Cross-check
against the offsets the game's own near functions call. For Tron,
Lithtech.exe has two runs (127 and 46 stores) and the near calls agreed
63 of 63. Tron kept Build 51's order where NOLF2 had reordered it
(`GetConsoleVar` at +0x18c, not NOLF2's +0xf8). One header change gained
CShell.dll +166 identical (tron20src 21b556b). `ILTServer`: one run of 107
stores, 55 of 55 (8d627cf). Record every offset with its evidence
(`progress/engine/*-offsets.csv`).

**Virtuals: name each slot by its body.** Build the reference engine (the
sibling's), and match each retail vtable slot's body against it. The
game's calls are fixed points. Where identical stub bodies leave two
methods ambiguous, the other engine's calls or an older SDK's order decide.
Tron's `CLTClient` (94 slots) and `CLTServer` (76) came out as Build 51's
order with NOLF2's additions inserted, for +300 identical (0377246). The
server shell's 17 `IServerShell` virtuals are in an order of Tron's own
(4695d20). Record them in `progress/engine/*-vtable.csv`. Where the slot's
name is in a header but not its position, [07](07_vtables.md) has the
method.

**Don't trust an order rule until calls on both sides confirm it.** VC6
lays a name's overloads out together, **in the reverse of their declaration
order**. Tron first recorded the opposite (8d627cf: "in declaration
order"), placed Tron's extra `DrawPrim` overload by that rule, and put
`LT_POLYFT4`'s slot in the wrong place. The game's calls to `CreateFont`
and `SetText` showed the reverse order (b4717cd). The `DrawPrim` placement
was corrected against two retail calls on either side of the insertion
(CShell.dll 0x1002948a, 0x100220db: 4e170d2). The stale wording is still in
tron20src `docs/PLAN.md` §4a's first bullet, the `ILTDrawPrim`/`ILTCommon`/
`ILTModel` vtable CSV headers, and `tools/sdkvtab.py`'s docstring ("in
declaration order"). Read those as wrong for overloads.

**Check a hand-edited header against what the compiler makes of it.** Take a
member pointer to each virtual. VC6 compiles it to a vcall thunk whose
`jmp [eax+N]` names the slot, so a small probe file lists the slots your
header actually produces (tron20src `docs/PLAN.md` §4a; its `out/work/`
probe is local and untracked). The probe tells you what your header does.
Only retail's calls tell you what it should do. You need both.

**A missing slot looks like a crash, not a near.** Contract J.A.C.K.'s
`CLTClient` has a virtual between `AddParticle` and `StartQuery` that the
SDK lacked (`GetUDPSocket`, our name). Every `ILTClient` call after it in
the game was 4 bytes short (retail CShell.dll calls `SetLightGroupColor`
through +0x150), and the built engine crashed in its first frames under
retail's game DLLs until the slot went in (cjacksrc `docs/PLAN.md`,
"Round 4", and §8).

## Step 6: layouts, which are most of a port's nears

Once the interfaces are right, most of the remaining nears in a ported tree
are **struct layout, not codegen**. The bytes differ only in displacements
off one base, all shifted by the same amount. `tools/layoutscan.py` finds
that signature across a target's nears.

- **Read the displacement pairs from aligned nears, then count.** Align
  our near with retail's instruction by instruction and read off the
  (old, new) displacements. Then confirm each candidate by counting its uses
  in *both* games' retail images. Avp2src found three insertions in
  `CServerMgr` over NOLF's (+4 before the object lists, +0x408 after
  `m_hWorldFile`, +4 after `m_NetMgr`) for 335 functions (ddded5c), and two
  in the object base for 345 (cd16e26). Working through lithtech.exe's
  near list group by group ("nearly every near was layout rather than
  codegen") added 834 identical, none lost (453a4a9).
- **Then rewrite the views in the new game's own offsets.** Avp2src first
  wrote its layout fixes as macros mapping a NOLF offset to AvP2's
  (`AVP2_MGR`, `AVP2_OBJ`). Pads read like `0x5c4 - 0x394 + 4` and member
  comments named NOLF's offsets. e3eaba7 replaced all of it with AvP2's own
  offsets and deleted the macros, with no score change. Do it that way from
  the start: the tree is the new game's, not the sibling's with a diff on
  top.
- **Constructors and `Save` are the best layout witnesses.** A constructor
  touches nearly every member, and `Save`/`Load` touch them *in member
  order*. Listing the offsets retail's `Save` and constructor touch, in
  order, next to our compiled offsets gives the layout. Tron's
  `CGameServerShell` was done from its constructor and `Save` (4250b3a), and
  `CPlayerObj` was matched through `m_hPlayerLure` (0x2e58) for 44 functions
  once `CPlayerScore` had retail's size (02d62c4). tron20src's helpers for
  this (`offprobe.sh` for our offsets, `savemap.py` for the alignment) are
  in its untracked `out/work/`. They are worth promoting to `tools/` when
  the next game needs them.
- **RTTI names every vtable, so diff slot counts first.** A game built `/GR`
  has a complete object locator for every polymorphic class. Comparing slot
  counts with ours shows which classes gained or lost virtuals, before any
  function is read. In cjacksrc, a handful of header changes found that way
  took Object.lto from 5,375 to 5,705 (`docs/PLAN.md`, "Method that pays").
  The base-class descriptors catch wrong hierarchies too: retail RTTI shows
  Tron's `CScanner` deriving from `PropType`, not `Prop`, which fixed a 0x10
  shift in every member (tron20src 0ef3fc3).
- **One constant delta is one blocker, so pad against it and move on.**
  Tron's `CButeMgr` is 0x40 bytes larger in our library than in retail's,
  and that one fact explains a near in every bute manager (635d3b5). Write
  the dependent class at retail's offsets with a pad array sized by the
  difference. Then it stops compiling, and so asks to be removed, when the
  base is fixed (`SecRezzer` against `CDestructibleModel`'s 0x738 vs 0x728:
  f707b07).

## Protected executables: the demo as a stand-in

A SecuROM-wrapped engine has encrypted pages and redirected import calls.
Every `call [IAT]` points at one dispatcher, so retail no longer says which
import a site calls. A demo built from the same source fixes both:

- The unprotected demo supplies the encrypted pages' code (NOLF2: five
  pages, ≈146 UI, ≈60 CRT/thunk and ≈35 D3DX functions) and the import
  behind every redirected call (NOLF2: all 1,514), read from the matching
  instruction (nolf2src `docs/engine/anatomy.md` §2). `tools/demoimports.py`
  builds the map, and the scorer writes the original `ff 15 <slot>` back
  before scoring, so functions with such calls can match (cjacksrc 82507cc,
  for SecuROM's 91 direct-call variants).
- **Pick the demo whose Rich header matches retail triple for triple.**
  For NOLF2 the multiplayer demo matches (94.5% of the exe's app
  instructions verbatim; the prerelease build reaches only 26.9%). For
  Contract J.A.C.K. it is the *single-player* demo. The multiplayer demo's
  engine is a `/GS` build with three more C objects (the cookie's), so it
  is a different build (cjacksrc `progress/COMPILERS.md`, "No `/GS`").
- **Use it for code and data, never for addresses.** The demo links some
  objects in a different place (anatomy.md: "Object order differs in
  places").
- **Look for an unstripped port.** The Mac NOLF2 engine has 11,485 text
  symbols with full Itanium-mangled names and real source paths in its
  strings. Its `define_holder` interface registrations, which sit at the
  start of each object's code, are file anchors in the Windows image too
  (anatomy.md §3, `tools/macho.py`, `tools/macinventory.py`).

## Porting fixes between sibling repos

Once two siblings are both being worked on, fixes flow between them. Port
them **one at a time and measure each in the target repo**. A fix proven in
one game can be wrong in the other. Of nolf2src's recent engine fixes,
cjacksrc took one (+1, cfd2625). Its server interface entries lost 29
server.dll functions, because Contract J.A.C.K.'s retail really does wait
on `m_bUpdating`. Others changed nothing or relied on STLport, which CJ
doesn't link. For modern-build features the same discipline is a table:
one row per upstream commit with a verdict (ported / nothing new / not
applicable, and why). nolf2src's `nolfsync` table (`docs/engine/PLAN.md`
§17) is the model.

## Boot it early

Scoring can't see wiring. A vtable can be the right size and still hold the
wrong function in a slot. Avp2src's first boots found vtable twins
(`ILTModel`'s `GetNode`/`GetSocket` swapped, same masked bytes), a base
stub placed instead of an override (`CObjWorldModel`'s `OnFoundInBox` →
the world rendered black), and structs declared too small that overwrote
the globals after them (`d3d.ren`'s `g_FormatMgr` declared 0x9a8, really
0xb94) (avp2src f244290, 27eb79d, baebb5b). Run the game as soon as it
links, and keep running it: see
[05](05_exe_and_engine.md#running-the-thing--nears-have-to-execute).

## Checklist

1. Empty repo → target release, `targets.py`, first all-unwritten baseline,
   `COMPILERS.md` from Rich headers, checks wired in.
2. Date the base by literals unique to each candidate; newer trees supply
   additions by three-way merge only.
3. Build the small binaries first; read every component's compiler yourself.
4. Import unchanged; strip sibling variant blocks; `git merge-file` the
   old-API files; `MERGE:`/`PORT:` every change; mark stand-ins.
5. First link of each image: record known diffs `UNREVIEWED`, let the
   checks hold the rest.
6. Interfaces: function-pointer fill order, slot bodies against the built
   sibling engine, overload order confirmed by calls, probe the header.
7. Layouts: displacement pairs, usage counts, ctor/Save witnesses, RTTI
   slot counts, one pad per blocker; the new game's own offsets.
8. Boot it. Then start on functions ([13](13_cluster_recon.md)).
