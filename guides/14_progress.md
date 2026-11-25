# 14 · The scoreboard: building and using `progress/`

Every other guide is about one function. This one is about all of them at
once: how the project measures how much of the retail game it rebuilds
exactly, how that measure is held so it can only go up, and how you use it
to pick work and to hand work in.

The reference for every status, file and rule is the host project's
[`progress/README.md`](../../../progress/README.md). This guide is the
walk-through: what to run, in what order, what the output means, and what to
do when it fails.

## The pieces

```
  the retail images ──┐
  (out/reference/)    │
                      ├─▶ tools/progress.py ─▶ out/progress/  ─┐
  our build output ───┤    (score this run)    functions.csv   │
  (src/*/Release/,    │                        summary.json    │
   src/lithshared/out)│                                        ▼
                      │                        tools/ratchet.py check|update
  progress/*.csv ─────┘                                        │
  (hand-curated                     progress/identical.txt ◀───┤ (the baseline)
   evidence)                        progress/summary.json  ◀───┤
                           progress/README.md's table      ◀───┘
```

* **`tools/progress.py`** scores one run. It enumerates every function of
  every retail binary from the binary itself, searches our objects for each
  one, and gives every shipped function one status (`identical`, `near`,
  `small`, `attempted`, `todo`, ...). It writes `out/progress/`, which is a
  scratch result: nothing there is committed.
* **`tools/ratchet.py`** compares that run with the **baseline** committed in
  `progress/`: `identical.txt` (every function ever verified identical) and
  `summary.json` (the figures they add up to, from which the README table is
  rendered). `check` fails on any regression; `update` records the run as the
  new baseline.
* **`progress/*.csv`** are evidence a human gathered: addresses the
  enumeration gets wrong, function starts it misses, extents it misjudges.
  They change the denominator, so they are reviewed like code.
* **`build/progress.sh`** is the glue, `make progress` and `make
  progress-update` its entry points.

The scoring compiles nothing. It reads whatever the last build left in the
tree, so the order is always: build, then score.

## Before the first run

You need three things.

1. **The build**: `make`. The scorer reads `src/engine/*/Release/*.obj`,
   `src/game/*/Final_Release/*.obj`, the `.map` files of our own links and
   `src/lithshared/out/*.lib`. Only the release build is scored; the variant
   builds live under `out/build-<variant>/`, where the scorer never looks.
2. **The retail images**, the ground truth. `make retail` installs the
   retail game (from your own disc images in `isos/`), and the first
   `make progress` extracts the binaries it scores into `out/reference/`
   (`build/reference.sh`), with a function and vtable table per image.
   That happens once.
3. **Optionally, the source release's libraries.** The seven lithshared
   libraries are scored against the prebuilt `.lib`s from Monolith's *NOLF
   Source Code v1.003* release, which is not in the repository. Point
   `NOLFSRC_SOURCE` at your extracted copy (the directory holding `LT2/`). They
   are checked against `progress/shipped-libs.sha256`, and a mismatch is an
   error, not a skip: a different library would be the wrong ground truth.
   Without `NOLFSRC_SOURCE` everything else is still scored and checked.

## Checking: `make progress`

```sh
make                                   # build what you changed
make progress                          # score it, hold it to the baseline
make progress NOLFSRC_SOURCE=~/nolfsrc    # the same, with the libraries
```

`make progress` runs `build/progress.sh check` in the build container:
`progress.py`, then `ratchet.py check`. It prints a line per target as it
places functions, then the score of the run, then the run against the
baseline and the verdict (trimmed; a run without `NOLFSRC_SOURCE`):

```
target              ident  near  small  attem  todo  funcs  unwr  unpl   bytes id  bytes tot      %
---------------------------------------------------------------------------------------------------------
NOLF.exe              172     1     48      0     0    221     0     0      34056      35033  97.2%
server.dll           2031    47    194      0     0   2272     0     4     212941     249622  85.3%
...
wrote out/progress/functions.csv, out/progress/summary.json

target                identical (recorded -> now)    identical bytes (recorded -> now)      unwritten       unplaced
NOLF.exe                    172 ->    172                  34056 ->    34056                0 -> 0         0 -> 0
server.dll                 2031 ->   2031                 212941 ->   212941                0 -> 0         4 -> 4
...
PASS: every function recorded as byte-identical still is
```

The first table is this run; the second is this run against the baseline,
and the one to read after a change. Resources are rows too: `CRes.dll`, and
each engine image's as a target of its own (`lithtech.exe:rsrc`, ...), one
row per resource, held like functions and kept out of the total, which
counts code. It fails (non-zero exit) when:

* a function listed in `progress/identical.txt` is no longer identical,
* a target's identical byte count went down,
* a target's count of **unwritten** or **unplaced** functions went up,
* `progress/README.md`'s table is not the one `progress/summary.json` renders (someone
  edited one without the other), or
* the data check finds text that differs from the retail images and is not
  in `progress/data-known.txt` (below, "The data check"), or
* `fpconst.py` or `vtabcheck.py` finds a float constant or a vtable that
  is different and that is not in its list of known differences (below,
  "What a run rests on").

New identical functions **pass**, with a reminder that they are not recorded
yet. Run it before you hand anything in; CI runs it on every push and pull
request (`.github/workflows/public-archives.yml`, without the libraries).

Two stricter forms exist for later: `make progress COVERED=1` also fails
unless nothing is unwritten or unplaced anywhere (every shipped function has
a written, placed counterpart), and `make progress COMPLETE=1` unless every
function is identical -- the finish line.

## Recording: `make progress-update`

When a run is better than the baseline, lock it in:

```sh
make progress-update NOLFSRC_SOURCE=~/nolfsrc
git add progress/identical.txt progress/summary.json progress/data-known.txt progress/README.md
```

It rewrites `progress/identical.txt`, `progress/summary.json` and the README
table, so from then on the new functions are held like the old ones, and
drops from `progress/data-known.txt` the text differences that are gone. Commit
the three files with the source change that earned them, so the history
shows which change made which function identical.

It refuses two kinds of run:

* **A run without the libraries.** The baseline covers every target, so it
  needs `NOLFSRC_SOURCE`.
* **A run that lost a recorded function.** Fix the loss, or -- when the change
  rightly gives the function up (it was identical by coincidence, say, and
  the right source compiles differently) -- record it with
  `make progress-update ACCEPT_LOSSES=1` and say why in the commit message.

## Checking without the retail binaries: hashes

`make progress` needs the retail binaries. A machine that does not have
the retail game (for example a CI runner) cannot run it. For such a
machine, a project can record the full check as hashes, and check its
build against these hashes. This is opt-in: a project that does not use
`--hashes` sees no change.

To record, give `--hashes` to each check in the project's
`progress-update`:

```sh
python3 tools/progress.py --hashes          # out/progress/hashes/identical.tsv
python3 tools/datacheck.py update --hashes  # out/progress/hashes/data.tsv
python3 tools/fpconst.py --targets --hashes # out/progress/hashes/fpconst.tsv
python3 tools/vtabcheck.py --targets --hashes   # out/progress/hashes/vtab.tsv
```

When all the checks pass, copy `out/progress/hashes/` to `progress/hashes/`
and commit it with `progress/identical.txt`. The files hold no retail
bytes:

* `identical.tsv`: for each identical function, its shipped address and
  length, where it is in our link (a symbol of our `.map`), the offsets the
  comparison masks (the relocations), and the SHA-256 of the shipped bytes
  with those offsets set to zero. For each identical resource and library
  function, the SHA-256 of the shipped data.
* `data.tsv`: the SHA-256 of each string in the retail images' data, with
  its count.
* `fpconst.tsv`: the SHA-256 of each float constant behind a masked
  relocation.
* `vtab.tsv`: for each vtable that `vtabcheck.py` compared, its shipped
  length and a hash of the symbols in our slots; for each function whose
  calls and addresses it compared, the offsets and a hash of the symbols
  they reach.

To check, without the retail binaries:

```sh
python3 tools/hashcheck.py check [--no-art]
python3 tools/datacheck.py ci
python3 tools/fpconst.py --targets --ci
python3 tools/vtabcheck.py --targets --ci
```

Each one reads only our build and `progress/hashes/`. `hashcheck.py` finds
each recorded function in our image through our `.map`, hashes it with the
recorded mask and compares. It fails if a hash differs, if a function is
not in our map, or if `progress/identical.txt` has a function with no
hash. `--no-art` does not check the resources that a target's `art` key
names (regular expressions on `rsrc:<type>/<name>/<language>`): a build
without the retail game compiles placeholder art in their place.

Know these limits:

* The check finds no new match. Only the full `make progress-update` with
  the retail binaries records one.
* A renamed function or symbol is not in the recorded data. After a rename,
  run `make progress-update` again.
* `vtab.tsv` records our symbols as the full check verified them. If a slot
  or a call reaches another symbol of ours, the check fails, also where the
  full check would only report the slot as unverified.

### Another checkout of the same source

Some names change from one checkout or build to the next. The checks find a
recorded function also in these two conditions.

**A link with no `.map`.** An incremental Debug link writes no `.map`
(avp2src's `Launch.dll`). For such an image, `progress.py --hashes` records
each row with an `obj:` locator: the code of the function in its own
object (tools e2865d3). This is the same locator as for a function that our
link removed. Before this change, the image had no rows, and `hashcheck.py`
failed on its functions with "no row". The scores do not change.

**Anonymous namespaces.** VC6 names an anonymous namespace
`?%<source path><number>@`, and VC7.1 names it `?A0x<hash>@`. The number or
the hash changes from one checkout to the next. Thus a CI clone gets
symbol names that are different from the names in the checkout that
recorded the hashes. [01](01_environment.md#what-the-same-bytes-requires)
tells how this name changes the layout of a link, and how `anonns.py` makes
the number the same for a library build. If our build does not have a
recorded symbol by its exact name, the checks look for it in this sequence:

1. `vtabcheck.py` and `fpconst.py` remove only the number, and keep the
   source path (tools 133b1ee, b00d90a). Two source files can each have a
   function of the same name in their anonymous namespace (nolf2src
   `CShell.dll`: `CreateCallBack` in `ScreenHostMission.cpp` and in
   `ScreenProfile.cpp`). The path keeps them apart.
2. `hashcheck.py`, `vtabcheck.py` and `fpconst.py` remove the full name of
   the namespace (`hashcheck.anon`). They use the result only if one symbol
   has that name (tools 44f478e, 9508881). `fpconst.py` looks only in the
   object that the constant is recorded for.
3. The VC7.1 hash has no source path. Thus `vtabcheck.py --ci` maps each
   recorded hash to our hash of the same object file (tools 9e5ef0e).
   `progress/hashes/identical.tsv` names the object of each recorded
   symbol, and our `.map` names the object of each of our symbols. If this
   gives no result, it uses the one hash of ours whose namespace holds all
   the recorded names.

`vtabcheck.py --hashes` hashes the symbols without the name of the
namespace. Thus the recorded `vtab.tsv` files stay valid. These changes
came from CI clones that failed:

* nolf2src `CShell.dll`: 21 callbacks "not in our map" for `vtabcheck.py
  --ci`,
* cjacksrc `CShell.dll`: 20 callbacks "not in our map", and
  `ConvertToGamma` of `ScreenDisplay.cpp` "gone" for `fpconst.py --ci`,
* avp2src `Object.lto` and `PHObject.lto`: 38 constants "gone" for
  `fpconst.py --ci`.

## Reading a run

`out/progress/functions.csv` has one row per shipped function: target,
name, size, status. `progress.py` has views onto it, inside `make shell` (it
needs Python 3 only):

```sh
python3 tools/progress.py --nears=server.dll     # near matches, closest first
python3 tools/progress.py --todo=lithtech.exe    # untouched, largest first
python3 tools/progress.py --attempted=d3d.ren    # worked on, not matched
python3 tools/progress.py --unplaced=d3d.ren     # ours, with no shipped home
python3 tools/progress.py --unreferenced=d3d.ren # ours, /OPT:REF would remove them
python3 tools/progress.py --refuted=d3d.ren      # short ones, an operand does not agree
```

Which list to work from depends on the kind of work:

| You want to | Start from | Guide |
|---|---|---|
| close functions that are almost right | `--nears`, smallest delta first | [10-upgrading-nears](10_upgrading_nears.md) |
| write something new | `--todo`, a small function that opens a cluster | [README](README.md#picking-a-target), [13-cluster-recon](13_cluster_recon.md) |
| fix coverage | `--unplaced` and `--todo` of the same target, side by side | below |

The two coverage counts, per target in the README:

* **Unwritten**: shipped functions with nothing of ours placed at them
  (`todo` + `attempted`).
* **Unplaced**: functions of ours, in our own link of the image, that no
  shipped function is placed for.

A function written right but compiled differently -- other registers, another
block order -- is placed by similarity, or joined to its shipped twin by
name (`sub_<addr>`), by object (the linker keeps an object's functions
together) or by link order. When all of that misses it, it is counted twice:
once unwritten, once unplaced. So an unplaced function is usually a near
match the scorer could not see. Naming it for the address it reconstructs
(`sub_<addr>`, `d3d.ren`'s convention) joins the two; a comment in `src/`
citing the address only marks the shipped row `attempted`.

### Unreferenced: what retail's linker would have dropped

Not every unplaced function is a miss. The scoreboard links use
`/OPT:NOREF`, because they must continue when a reference is not resolved.
Thus they keep every COMDAT that an object carries. An example is a
template member that an explicit instantiation emits and that nothing
calls. Retail's `/OPT:REF` removed such a COMDAT.

Since tools 892868a, the scorer does its own `/OPT:REF` walk over the
objects of each image. The walk uses a reference graph by section, which it
makes from the COFF relocations. It finds externals by name, so a missing
callee does not break a chain. The roots of the walk are:

* each section that is not a COMDAT,
* each NODUPLICATES COMDAT (the linker always keeps an ordinary
  out-of-line function),
* the entry points, the exports and the `/INCLUDE`s,
* each placed function of ours.

If the walk does not reach an unplaced function, the status of the function
is `unreferenced`, not `unplaced`. An `unreferenced` function does not
decrease the coverage.

Two refinements followed. Each one came from a wrong count:

* **A shape-only placement keeps nothing alive** (5d44dcd). Primal Hunt's
  server.dll had 13 explicitly instantiated stand-in `~CMoArray`
  destructors. Nothing calls them. The scorer placed them by their 19-byte
  shape, so they took 13 of retail's 32 slots. The referenced destructors
  that they displaced stayed unplaced. Now, a function that only a
  shape-placed function reaches is not live. Thus the stand-ins are
  `unreferenced`, and retail's 32 destructors pair with ours, parent by
  parent. Unwind funclets call all 32 of them.
* **A target's `discarded` regex** (on `module:symbol`) names out-of-line
  definitions that the retail object had and that `/OPT:REF` removed. An
  example is AvP2 d3d.ren's `d3d_TermTranslucentStates`. The scorer sets
  these functions aside before the placement. They are not roots of the
  walk, and the scorer lists them as `unreferenced`. `no_reach` stops the
  walk for a target. All such rows then stay `unplaced`.

NOTE: A project can link with `/OPT:REF`, which is the VC6 default. Then
`unreferenced` is 0 for all targets, because the link itself removed those
functions (tron20src f964bf9). This is the expected result. It does not
show that the walk is broken.

## How the scorer proves a short function

The bytes of a long function prove it. `exematch` masks the relocations,
and the remaining bytes are unique in the image. The bytes of a short
function do not prove it. These short functions match at many addresses:

* a forwarder with one call (`push arg; call X; pop ecx; ret`),
* a `GenAppend` stub,
* a `ret`,
* a getter of one line that the linker folded across approximately 12
  classes.

Thus a match at some address does not tell *which* function it is. Each
rule below came from a run that credited such a function at the wrong
address. Together, the rules removed several hundred recorded identical
functions across the projects. If one of these rules decreases your score,
nothing proved that the lost functions were what the scorer credited.
Record the loss with `ACCEPT_LOSSES=1`, and write this in the commit
message.

**The operand map.** First, the scorer places the long functions. Their
relocations then give a map from our addresses to retail's addresses. For
example, our `con_Term` is retail's `0x0047xxxx`, because an identical
caller calls each of them. The scorer then checks the operands of a short
function through that map.

* **A stub that the scorer places by shape must prove its operands**
  (tools 34a4a8e). Before this rule, a function of fewer than 16 unmasked
  bytes, placed by shape only, took its first look-alike in name order.
  That false placement then went into the map. avp2src's `cc_TermState`
  (`push arg; call con_Term; pop; ret`) was at lithtech.exe 0x479ee0. That
  address is retail's `operator delete`, which calls `dfree`. Thus
  `con_Term` mapped to two addresses, and the operand of each caller
  became ambiguous. The real address of `cc_TermState` is 0x47a660.

  Now, where our image is linked, the scorer compares the call operands
  and the address operands of each such stub with a map. This map contains
  only **unambiguous** placements (one hit, or pinned) and imports. If an
  operand of a stub maps to a different retail address, the placement is
  refuted. The stub then moves to a hit where all its operands agree. If
  there is no such hit, the stub stays where it is. The stub whose address
  it takes then moves to a different hit. avp2src lost 40 recorded
  identical functions of this kind (a45dd79), and cjacksrc lost 20
  (6937926). The same change placed 399 more.
* **A stub that other stubs push off all its look-alikes takes an address
  that becomes free** (0a08bdd). Before this rule, the scorer did not
  examine again a stub that the first pass gave no address. Thus an
  address that a refuted stub left stayed empty. An example is nolf2src's
  `FindObjectServer`, whose row counted as unwritten. Now such a stub
  takes a free hit where all its operands map, and it displaces nothing.
  nolf2src got 22 new identical functions.
* **The scorer compares a string operand by its content** (180e91e). The
  same string counts as mapped. A different string refutes the placement.

If you set `PROGRESS_SHAPE_LOG=1` in the environment, the scorer writes
each such move to stderr: `refuted <name> <from> ... -> <to>`. For a stub
that had no address, `<from>` is `-`. `--refuted` lists the short
functions that still have an operand that does not agree. Each one is a
real difference, or a placement that is still wrong.

**A jump table matches by the case labels that it names.** A switch
statement can compile to a jump table after the code of the function. Each
entry is a DIR32 relocation to a case label. The `jmp [reg*4+table]` that
reads the table, and the `mov r8, [reg+table]` that reads its byte index
table, are DIR32 relocations to the tables. The masked match masked these
operands as it masks all relocations. Thus a table matched when its
entries named other cases, or the code of a different function. Now
`exematch` keeps each relocation that names a place in the extent of the
function itself (a self-reference, `Mask.selfrefs`). At a hit, each such
operand must name the same place in the function at that address:

* For a DIR32, the operand must be the hit address plus the offset of the
  place.
* For a REL32 (a recursive call), the operand must reach the place. It can
  also reach a `jmp rel32` thunk to the place: an incremental link calls a
  function through its thunk (NOLF2.exe's `_Rb_tree::_M_erase` at
  0x405020 calls itself through 0x401585).
* In the pages that a target's `readable` fills in, the bytes are the code
  of a different build at the shipped addresses. Thus each DIR32 operand
  there is the address of its place in that build. All of them must be
  different from the shipped address of the place by the same quantity.

If one operand does not agree, the hit is not a hit. The function then
goes to the near pairing, as other functions whose bytes are different do.
This rule makes nothing identical. A table is equal when each entry names
the matching case label, not when its raw bytes are equal. The rows of the
byte index table are not relocations. The scorer compares them byte for
byte, as before.

**The literals that a function names** (tools 80606ba). The masked match
masks every relocated operand. Thus functions that are different only in
the string that they pass have one shape, and name order chose among them.
Object.lto's `IsBody`, `IsGameBase`, `IsWorldModel`, `IsPlayer` and `IsAI`
all call `GetClass("<name>")` and then the same calls. Tron 2.0's
`IsWorldModel` was identical at Object.lto 0x100ccbd0, but the function
at that address passes "CPlayerObj". Now, where our image is linked, the
scorer checks these literals (`_verify_literals`):

1. It finds each DIR32 relocation of ours that names a string literal
   (`??_C@_...`) or a floating-point constant (`__real@...`), with no
   addend.
2. It reads the content of our literal from our linked image.
3. It compares that content with the bytes that the shipped operand at the
   same offset points to, in the initialized data of the shipped image.

Different content refutes the placement. The function then goes to a hit
where all its literals agree, or it is not placed. If two unplaced
functions both agree at one hit, neither one takes it in this pass. Other
operands (a global, a function) give no evidence here. This rule makes
nothing identical that the masked bytes do not match. It only chooses
among those addresses, or removes one.

On Tron 2.0, the count went from 30,481 to 30,436 identical functions.
Each loss was a placement that a literal refuted, or a short function that
only such a placement proved. `IsPlayer` is now at 0x100ccbd0, and
`IsWorldModel` is at 0x100cce80. NOLF2 went from 29,461 to 29,465. For
each target, the scorer writes how many placements the literals moved,
placed nowhere, or placed where there was none. With
`PROGRESS_SHAPE_LOG=1`, it also writes each move, with our literal and the
shipped bytes.

**A relocation-free function verifies only at its own address** (tools
1b61dca). A function with no relocations gives the map nothing to check.
Before this rule, a bare `ret` verified at the address that the shape
placement chose for it. Now it counts only where its own address is
mapped. That is, identical code calls it or jumps to it at that address,
or a paired vtable holds it in that slot. The identical caller is the
proof. An operand of the function that nothing paired yet ("unmapped")
does not stop it. An operand that maps to a different address ("refuted")
stops it (8e8a48f: all avp2src targets increased, lithtech.exe by 105, and
no target decreased). The first time, this rule had a cost:

* cjacksrc removed 303 credits, all of them shapes of 1 to 7 bytes
  (2a2e387),
* tron20src removed 557 (f964bf9),
* the game DLLs of avp2src removed 79 (f5f12c7).

Sometimes you know the correct address, but the scorer cannot prove it.
For example, the look-alikes are different only in a string or in a callee
that the scorer cannot see. Then pin the function. The target's
`own_symbols` in `progress/targets.py` maps a symbol to its shipped
address. Put the evidence in a comment, or in a CSV that `targets.py`
loads. For example, cjacksrc 8fe6925 pins the 193 attribute getters of
CLayoutMgr at the copies that pass the same strings
(`progress/CShell-layout-pins.csv`). A `sub_<addr>` name does the same
thing. `own_names` takes a substring of the leaf name. A pin is a
preference, not a credit: the bytes at that address must still agree. The
operand map counts a pinned placement as unambiguous.

**`linked_oracle="same-address"`** (5660aba) is a stronger form of this
check. Use it for a target whose own link puts the image in the same
layout as retail's. The scorer compares the relocation-free functions of
that target with our linked image only at their own address. At that
address, each rel32 in the body names the same target as in retail's
image. avp2src's cdaudio.dll proves its ten short functions this way
(c8193b2, 80 of 81 identical). `linked_oracle=True` accepts the bytes at
any address in our link. That is not proof for a body that occurs more
than one time.

**One function, any number of copies.** A template member or an inline
function is a COMDAT. Each object that uses it carries a copy, and the
linker keeps one copy. Thus:

* If a copy in one object compiled differently, the scorer does not
  near-pair it when another copy is identical (98c44da). In AvP2, an STL
  copy from another object held the slot of the `CSoundButeMgr`
  destructor. The copies that our link kept now pair first.
* If another function overwrites a placement, the placement moves to its
  next free hit. It does not disappear (9a56003: AvP2's
  `CGameSpyServer::GetAddress` was lost to `GetPing`, which fitted only at
  that address).
* A displaced function pairs again only if our link has it (61deff4: Tron
  2.0's ClientFx.fxd paired a `CPlayRandomSoundFX::Term` that our link did
  not have, at the address of another class).

**A function that our link does not have pairs last.** Our link can
leave out a function of an object that it links. `/OPT:REF` removes it
when nothing of ours calls it yet, or another object supplies the COMDAT.
Such a function has no address in our image. Thus no reference, no
position and no relocation can confirm where it ships. Only its bytes
can. Before this rule, it paired by content in the same pass as the
functions of our link. Thus it took addresses that the functions of our
link get by reference or by position, and those functions stayed
unplaced. On Tron 2.0's Object.lto:

* `CLightCycleGameData::Load` (1,165 bytes, not in our link) paired with
  0x10039c30. `CDisc::HandleDeadlyDeflect` (937 bytes) is there by
  position, and it was unplaced.
* CircuitButeMgr.obj's `vector<CircuitWave>` copy constructor (not in our
  link) paired with 0x1012a4c0. `CSubroutineDataMgr::GetNameId` is
  there by position, and it was unplaced.

Now such a function pairs after the join, by content, and only with an
address that nothing of our link took. It does not pair when another copy
of the same function is placed.

**Long look-alikes: the relocations choose.** Some long functions have
the same masked bytes at several addresses, and are different only in
their relocated operands. Object.lto has seven 371-byte
`_Rb_tree::insert_unique` copies, one for each map type. Each one calls
the `_M_create_node` of its own type. It has 24 79-byte
`Default<Class>Constructor` thunks. Each one calls the constructor of its
base and stores the vtables of its own class. Before this rule, name
order and the anchors of the object chose the address. Tron 2.0's
`DefaultAIVolumeStairsConstructor` was identical at 0x101553d0. That
function calls the constructor of `ClientLightFX`, not of `AIVolume`.

Now, where our image is linked, the scorer does for these functions what
the operand map does for the stubs (`_verify_long_hits`):

1. It makes a map from our addresses to the shipped addresses. The map
   comes only from the functions placed without a choice (one hit, the
   address that their name gives, or a stub whose operands agree).
2. At each hit, it compares each relocated operand through that map. An
   operand that maps to a different shipped address refutes the hit. A
   string with different content refutes it. A vtable of ours refutes it
   when a slot maps to a function different from the one in the same
   slot of the shipped table. A slot that nothing maps refutes it too,
   when our function there is a short body with no relocation and the
   shipped slot's function has other bytes. (Object.lto's
   `AIVolume::GetVolumeType` returns 4 for `AIVolumeStairs`, 8 for
   `AIVolumeLedge` and 0x100 for `AIVolumeAmbientLife`. Thus the three
   constructor thunks that call `AIVolume`'s constructor go to the three
   shipped addresses whose vtables return the same values.)
3. An address of ours that our own link's `/OPT:ICF` gave to several
   functions is unknown, not evidence. (Our Object.lto link gives
   `~LTObjRefNotifier` the address of `~LineSystem::SystemEntry`. The
   shipped image keeps them apart.)
4. It gives each function one hit where nothing refutes it, and each hit
   to one function (a matching). A hit where operands agree goes first.
   The copies of one COMDAT are one function. A function of ours that
   gets no hit, and whose bytes and relocation targets in our image are
   those of a function that got one, is folded onto it: the shipped
   link's `/OPT:ICF` made them one function (NOLF2's
   `CLTClient::GetOccluderID` and `CLTServer::GetOccluderID` at
   Lithtech.exe 0x472c70). Where the shipped image keeps such functions
   apart, each one gets its own hit (each object's `_$E13` in Tron 2.0's
   SndDrv.dll).
5. A function that has only one such hit is proven there. It joins the
   map, and the pass repeats.
6. Two chosen hits must not overlap. A hit can be a byte run inside
   another function, or a function can be longer than its row. The
   longer function keeps its hit, the hit of the other is banned for it,
   and the matching runs again. (Before, the second function was then
   placed nowhere, although it had a free hit.)

A function that all its hits refute is identical nowhere: its bytes
match, but its operands name other things. It goes to the near pairing,
at one of its own hits first. A hit that no function took is left to the
position join: the content pairing does not put a function of other bytes
there. This rule makes nothing identical that the masked bytes do not
match. It only chooses among those addresses, or removes one.

Before this rule, each copy of a COMDAT took a hit of its own. Tron 2.0's
CShell.dll has the `vector<CLTGUICtrl*>::_M_insert_overflow` of 10
objects. Thus one function was identical at several addresses, and the
other functions there (other instantiations, other classes' deleting
destructors) were counted as identical too. Now one copy stands for the
function. An address that only such a copy held becomes near or todo.
Expect losses when this rule first runs on a project: each lost row was
credited to a copy of a function that is placed elsewhere, or to a
function whose operands name other things there.

With `PROGRESS_SHAPE_LOG=1`, the scorer writes each move, each copy that
leaves an address and, for each function identical nowhere, the operand
that refutes it at each hit. `PROGRESS_LONG_WHY=<address>[,<address>]`
writes, for each function of ours whose masked bytes match there, its
state there and the operand that refutes it.

An image with remainders is scored two times (`rows_for_image`). The
second run now starts with no placements. Before, a name that the first
run left at an address displaced the function that the second run put
there, and the function of that name then took a second address.

### Split tails and folded code

Some places in the shipped image are not one function for each row. The
scorer pairs these places only on proof (tools edfba3d).

**Split tails.** Sometimes the enumeration takes a place inside a function
for a function start. Examples are the case label of a switch (its jump
table points at it), and a byte in the middle of an instruction. Such a
start cuts the function into two rows. If our function is identical, the
second row is inside the matched bytes and drops out. If our function is
near, the second row stayed unwritten, although our function covers it.
Its status then changed from build to build. Now a start joins the near
row in front of it when these two conditions are true:

1. In the shipped code, control flow from the near row reaches the start.
   The flow must be a conditional jump, a jump table, or a fall-through
   from an instruction that is not a call. Alternatively, the start is
   inside an instruction that this flow reaches. Alternatively, the start
   is inside a switch table that an instruction of this flow reads: the
   jump table of a `jmp [reg*4+table]` (its entries, while each one points
   into the near row), or the byte index table that a `mov r8,
   [reg+table]` reads before that jump (its bytes, while each one is the
   number of an entry). After the tables, the row of the start must
   contain only padding. An unconditional jump is
   not proof, because a tail call to the next function is also one. A call
   is not proof, because a call does not always return.
2. Our function that is placed near at that row is long enough to reach the
   start. If our function is shorter, the shipped tail can be code that we
   did not write yet. Then the tail stays a row of its own.

The merged row keeps the status of the row in front, which is near. The
scorer claims nothing for its bytes. For each target, it writes the number
of split tails that it merged.

**Folded code.** The shipped links fold functions whose code is the same
(`/OPT:ICF`). For example, the trivial destructors of approximately 12
`CSpecialFX` classes are one function at CShell.dll 0x10111590. Our
scoring links do not fold. Thus one shipped address stands for several
functions of ours, and the address map saw this as a contradiction. Now
the scorer counts these functions of ours as one function, for the address
map and for the count of short shapes. It does this only when all of these
are the same:

* the bytes,
* the relocations, at the same offsets,
* the target of each relocation in our image.

A relocation whose target is not in the sections of our image does not
prove that the functions are the same.

### Links with `/FORCE`

An engine that is not complete links with `/FORCE`. VC6's linker
(6.00.8447) then resolves **every** unresolved symbol to the image base.
Thus, in such an image, all unresolved calls name one address. One call of
an identical function to one of these symbols mapped the base to its
shipped callee. After that, each short function that called any other
unresolved symbol "verified". Thus the scorer now treats an operand of our
image outside its own sections as unknown. It does not put the operand in
the map, and it does not use it as proof (tools 1b61dca). We found this
problem in the engine links of avp2src f5f12c7, which had 1,440 and 320
unresolved symbols.

To correct this, decrease the number of unresolved symbols. Do not make
the scorer less strict. avp2src 5301b0b decreased each engine link from
more than a thousand unresolved symbols to a small number. It used an
alias file for each image (weak externals that `tools/mkaliasobj.py`
builds). Each binding is checked against retail:

1. The scorer reads each placed site that references the symbol back out
   of the retail image.
2. That site must reach the address where the target of the binding is
   placed.
3. A binding that no placed site confirms stays apart as unproven (avp2src
   docs/PLAN.md, "9. boot").

Such an image also cannot run: see
[05](05_exe_and_engine.md#running-the-thing--nears-have-to-execute).

### Libraries through the `.lib` the link reads

Score the functions of a library through the library that the link reads.
Do not score loose copies of its objects. nolfsrc's engine targets listed
copies of RezMgr's objects, for the checks of each object. The `.map` names
those functions by library member (`RezMgr:rezmgr2.obj`). The names of the
copies never match that module. Thus the scorer could not check any short
function of RezMgr by what it calls. When we listed `RezMgr.lib` in the
`objs` of the target, 13 functions became identical (nolfsrc 0b3ef3a).
Among them are the `jmp CBaseHash::~CBaseHash` functions of the hash
tables, which only unwind funclets reach.

## What a run rests on

A score has value only for what it compared. Thus the scorer guards its
own count (tools adfdafa). These guards came from an audit with
counterexamples in three games:

* **No byte counts two times.** The masked shape of a short body could
  match inside a longer function that already matched in full, and both
  counted. nolfsrc had 41 such identical functions. One of them was an
  8-byte HostSession wrapper inside `CClassMgr::Init`. nolfsrc dc82b03
  removed them, each with its reason in `progress/corrections.txt`. Now
  the scorer takes the longest matches with the best evidence first. If a
  match overlaps a better one, the scorer drops it. Its function then
  tries its other hits.
* **The scorer never places the initializers of a scoring driver.** The
  scorer credited `_$E46` of sdkforce.obj with 71 bytes inside
  `sm_ResetProfileCounters`, and its jmp thunks as four "small".
* **The region decides before the match.** Outside `app`, a row is `crt`,
  whatever matched there. The exception is the `compiler_output` ranges of
  a target.
* **Exports compare with their ordinals** in the data check (2515c05):
  `export <name> @<ordinal>`. A module that imports by ordinal binds to
  the number.

Each run also records what it rests on (ca4369a).
`out/progress/evidence.json` holds:

* the revisions of the source and of the submodules,
* the SHA-256 of each retail image,
* the hashes of `progress/targets.py` and of each exclusion file,
* our images, maps and link commands,
* the toolchain trees, with their digests checked against the pins in
  `ext/toolchains/fetch.sh`.

`make progress-update` keeps a copy as `progress/evidence.json`, next to
the baseline. Before the scoring, `build/progress.sh` checks
`out/reference/` against `progress/reference.sha256`. If they are
different, it extracts the images again (nolfsrc dc82b03). A baseline that
we recorded against different retail images is not a valid baseline.
After the data check, `build/progress.sh` runs two more gates:

1. `fpconst.py --targets` finds a float constant behind a masked
   relocation that is different from retail's constant.
2. `vtabcheck.py --targets` checks the vtables and the call wiring against
   `progress/vtab-known.txt` ([07](07_vtables.md)).

If one of the two gates fails, `make progress` fails.

### False variables the scorer cannot see

The masked comparison masks every relocation. Thus a function can be
byte-identical and still read or write the wrong global. Two tools find
these false variables (tools a760122):

* `datarefcheck.py <image> <obj>...` does for DIR32 data references what
  `callcheck.py` does for calls. For each function that `exematch` places
  at one shipped address, it reads the shipped dword behind each DIR32
  relocation. It removes our addend, and it reports two groups:
  * `SPLIT`: one of our symbols reaches several shipped addresses.
  * `MERGED`: several of our symbols reach one shipped address.

  With `NAMES=<file>` in the environment, it also writes a names file: the
  shipped address of each symbol that reaches only one address, and of
  each placed function. With `SITES=<text>`, it prints each site of the
  symbols whose name contains that text.
* `unwritten.py <our dis> <our map> <ship dis> <ship-names.txt>` lists our
  globals that no code of ours writes, but whose shipped address the
  shipped code writes. It also lists the reverse. The two disassemblies
  are objdump output (AT&T syntax). The names file can be the `NAMES`
  output of `datarefcheck.py`.

Both tools found faults in avp2src's d3d.ren that the byte-identical score
does not show:

* a lightmap flag that no code set, so the world got no dynamic light,
* a Rage 128 flag,
* a filter flag.

Use these tools when an image with many identical functions does not
operate as retail does.

## The data check

After the scoring, `make progress` runs `tools/datacheck.py`, which compares
what the scoring cannot see: the text in each image's data (every section
but code, `.reloc` and `.rsrc`, with the import and export tables read as
names). It prints a line per image -- how many strings only the retail image
has, how many only ours -- and fails on any difference that
`progress/data-known.txt` does not list:

```
data check (text outside code and resources; progress/data-known.txt):
  lithtech.exe      3 only in retail,    0 only in ours
  ...
  d3d.ren          11 only in retail,    0 only in ours, 1 NEW
NEW: d3d.ren: only in the retail image: VisRadius
FAIL: 1 new text difference(s) from the retail images; ...
```

A NEW line is text your change added or lost: a literal spelled
differently, a string now in twice (a file built without string pooling,
`/Gf`), a C runtime's tables, an import. Fix it, or -- when it is meant --
add it to `data-known.txt` under a `# ` line saying why.
`python3 tools/datacheck.py show [image]` lists every difference, known or
not. When a change makes a listed difference go away, the check says so
("no longer differs"), and `make progress-update` drops the entry, so it is
held from then on. The reference for what is read and how is
`progress/README.md`, "The data check".

## When the enumeration is wrong: the CSVs

The retail images have no symbols. Their functions are found from the code
(call targets, vtables, exports, callbacks), and that occasionally finds
something that is not a function -- an operand byte that looked like a call
target, a jump into the middle of another function, padding -- or misses one
hidden behind a thunk. Since the denominator comes from this enumeration, a
wrong row is a wrong score. The fixes are rows in `progress/`:

| File | Add a row when |
|---|---|
| `<image>-screen-exclude.csv` | an enumerated address is not a function (reason starting `NOT A FUNCTION` or `NOT GAME CODE`: removed from the count), or you examined it by hand (any other reason: marked `attempted`) |
| `extent-splits.csv` | a function start the enumeration misses |
| `<image>-enum-suspect.csv` | a row looks wrong but you have not proved it: kept in the count, left off the worklists of `uncovered.py`, `decoded.py` and `d3dwork.py` |
| `decoded-extents.csv` | a large function whose enumerated extent is wrong |

Every row carries its evidence in the reason column -- the bytes, the
instruction that jumps there, the function it belongs to -- as the existing
rows do. A reviewer has to be able to check it without redoing your work.
Changing the denominator without evidence is the one way to make the
scoreboard lie.

Before you add a row, make sure that no rule of `enumfuncs.py` finds the
start. Rule 4h finds a function that only a tail jump (`jmp rel32`) or a
loaded address (`mov r32, imm32`) reaches. A wrapper `if (p) return
p->Get(); return 0;` ends in `jmp Get`. A member-function pointer to a
virtual function is the address of its vcall thunk (`mov eax,[ecx]; jmp
[eax+d]`), loaded into a register. Before rule 4h, each such function
merged into the row in front of it. Examples are Tron 2.0 Object.lto
0x101daab0 (`CAISenseRecorderAbstract::GetDoneProcessingStimuli`),
0x101daca0 (`IncrementIntersectSegmentCount`) and the vcall thunk at
0x1002e5b0. The rule takes the target only where the code in front of it
ended: the target is 16-aligned, and padding (0x90 or 0xCC) separates it
from a `ret` or a `ret imm16`. VC6 puts padding only between functions.
Thus a label inside a function is never such a target.

Some of that evidence is mechanical. `tools/enumproof.py` (892868a)
collects it next to the unwritten and near rows. It decodes each row by
recursive descent from its start. Then it examines the row after it. The
next row is an interior block of the row in front of it when one of these
is true:

* a branch of the row in front goes to its start,
* its start is an operand byte of an instruction that crosses it,
* the code in front runs directly into it, with no padding and no return.

For such a row, it proposes a screen-exclude row (`NOT A FUNCTION: interior
block of 0x...`), with that evidence in the reason. It does this only when
nothing else references the later row. It also proposes an extent split for
code after padding that the trace of the row in front never reaches:

```sh
python3 tools/enumproof.py --target server.dll           # print the proposals
python3 tools/enumproof.py --target server.dll --write   # append them
```

It reads the `out/progress/functions.csv` of the run (`--csv` gives a
different file). Thus, score first. [16](16_tu_mapping.md) tells how it
fits with the rest of the TU-mapping work.

## A session, start to finish

```sh
make                                          # 1. a clean baseline build
make progress                                 # 2. passes: you start from green
python3 tools/progress.py --nears=server.dll  # 3. pick work (in make shell)
#    ... write source; build/engine.sh server-one <file> <symbol>; fndiff ...
make                                          # 4. rebuild everything
make progress                                 # 5. no regressions, new functions reported
make progress-update NOLFSRC_SOURCE=~/nolfsrc    # 6. record them
git add -A src progress && git commit
```

If step 2 fails on a fresh checkout, the tree and the baseline disagree
before you have touched anything: the build is not the one the baseline was
recorded from (another compiler, a stale object). Fix that first -- every
later result depends on it.

## Adapting it to another project

`progress.py`, `ratchet.py`, `datacheck.py` and `vtabcheck.py` do not know
a project by name. All the data about a project is in its own
`progress/targets.py`: which binaries to score, and where the code of each
binary is and where our code is. It is the one file that these tools read
about the project. The header of `progress.py` documents each key. The keys
at module level are:

* `REFERENCE`, `OUT`, `DATA`: where the retail images, the output of each
  run and the recorded baseline are.
* `TARGETS`: one `dict` for each scored image or resource set. Its keys are
  `label`, `what` (the text of the README row), `kind` (`"image"` or
  `"resources"`), `shipped` (the retail image), `stem`, `built` (our image)
  and `objs` (our objects and libraries, where the link writes no response
  file).
* `LIBS`, `SHIPPED_LIB`, `SHIPPED_AS`, `SHIPPED_ENV`: the libraries that
  the scorer scores symbol by symbol against shipped `.lib`s. An example is
  NOLF's lithshared, from the directory that `NOLFSRC_SOURCE` names. These
  keys are empty for a project that has no such libraries.
* `DRIVER_OBJS`: the scoring drivers, which the scorer never places.
* `CITED_SRC`: where a comment that cites an address marks a row
  `attempted`.
* `README`: the file that holds the progress table, for example
  `progress/README.md` (tools baf6354). If the key is not there,
  `ratchet.py` uses the `README.md` of the project.

For each target, these keys decide the denominator and the evidence:

* `app`: the address ranges of the developer's own code. The rest is the
  statically linked runtime, `crt`, which the scorer does not count.
* `middleware` and `third_party`: code from other developers inside `app`.
* `compiler_output`: ranges outside `app` where our own compiler-made
  funclets, initializers and terminators count.
* `encrypted`, `readable` and `unreadable`: the pages that the copy
  protection encrypts.
* `own_symbols` and `own_names`: pins (above).
* `linked_oracle`, `discarded` and `no_reach`: see above.
* `purecall`: the address of the CRT's `_purecall`, where no import thunk
  shows it ([07](07_vtables.md)).

The rows of the README table come from `TARGETS`. `ratchet.py` itself keeps
only the markers of the table (`BEGIN`, `END`) and the default file
(`README`).

First, set `app` correctly, with evidence, because it decides the
denominator. If you count the runtime, the score shows much less progress
than the real progress. If you count only what you attempted, the score
shows much more. Then record a first baseline with `ratchet.py update`.
After that, the ratchet holds it.

**The differences of the first build.** A target that you build for the
first time is different from retail in its data and in its vtables. Nobody
reviewed these differences yet, and the gates fail on each one. Record
them, and mark them as unreviewed. Then the gates hold all the differences
that come after that:

```sh
python3 tools/datacheck.py baseline --image=Object.lto "UNREVIEWED, recorded at Object.lto's first build (<date>): <why>"
python3 tools/vtabcheck.py --targets --baseline="UNREVIEWED, recorded at Object.lto's first build (<date>): <why>"
```

The lines go into `progress/data-known.txt` and `progress/vtab-known.txt`
with that reason (tron20src 789512a for Object.lto, 5aa07a9 for CShell.dll;
avp2src f5f12c7 for the engine links). Then remove them, one by one. An
`UNREVIEWED` line is work that you must do. It is not an explanation.
