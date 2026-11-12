# 14 · The scoreboard: building and using `progress/`

Every other guide is about one function. This one is about all of them at
once: how the project measures how much of the retail game it rebuilds
exactly, how that measure is held so it can only go up, and how you use it
to pick work and to hand work in.

The reference for every status, file and rule is the host project's
[`progress/README.md`](../../progress/README.md). This guide is the
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
                                    README.md's table      ◀───┘
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
   retail game (from `rez/`), and the first `make progress` extracts the
   binaries it scores into `out/reference/` (`build/reference.sh`), with a
   function and vtable table per image. That happens once.
3. **Optionally, the source release's libraries.** The seven lithshared
   libraries are scored against the prebuilt `.lib`s from Monolith's *NOLF
   Source Code v1.003* release, which is not in the repository. Point
   `NOLF_SOURCE` at your extracted copy (the directory holding `LT2/`). They
   are checked against `progress/shipped-libs.sha256`, and a mismatch is an
   error, not a skip: a different library would be the wrong ground truth.
   Without `NOLF_SOURCE` everything else is still scored and checked.

## Checking: `make progress`

```sh
make                                   # build what you changed
make progress                          # score it, hold it to the baseline
make progress NOLF_SOURCE=~/nolfsrc    # the same, with the libraries
```

`make progress` runs `build/progress.sh check` in the build container:
`progress.py`, then `ratchet.py check`. It prints a line per target as it
places functions, then the score of the run, then the run against the
baseline and the verdict (trimmed; a run without `NOLF_SOURCE`):

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
* `README.md`'s table is not the one `progress/summary.json` renders (someone
  edited one without the other), or
* the data check finds text that differs from the retail images and is not
  in `progress/data-known.txt` (below, "The data check"), or
* `fpconst.py` or `vtabcheck.py` finds a float constant or a vtable that
  differs and is not known (below, "What a run rests on").

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
make progress-update NOLF_SOURCE=~/nolfsrc
git add progress/identical.txt progress/summary.json progress/data-known.txt README.md
```

It rewrites `progress/identical.txt`, `progress/summary.json` and the README
table, so from then on the new functions are held like the old ones, and
drops from `progress/data-known.txt` the text differences that are gone. Commit
the three files with the source change that earned them, so the history
shows which change made which function identical.

It refuses two kinds of run:

* **A run without the libraries.** The baseline covers every target, so it
  needs `NOLF_SOURCE`.
* **A run that lost a recorded function.** Fix the loss, or -- when the change
  rightly gives the function up (it was identical by coincidence, say, and
  the right source compiles differently) -- record it with
  `make progress-update ACCEPT_LOSSES=1` and say why in the commit message.

## Reading a run

`out/progress/functions.csv` has one row per shipped function: target,
name, size, status. `progress.py` has views onto it, inside `make shell` (it
needs Python 3 only):

```sh
python3 tools/progress.py --nears=server.dll     # near matches, closest first
python3 tools/progress.py --todo=lithtech.exe    # untouched, largest first
python3 tools/progress.py --attempted=d3d.ren    # worked on, not matched
python3 tools/progress.py --unplaced=d3d.ren     # ours, with no shipped home
python3 tools/progress.py --unreferenced=d3d.ren # ours, that /OPT:REF would drop
python3 tools/progress.py --refuted=d3d.ren      # short ones whose operands disagree
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

Not every unplaced function is a miss. The scoreboard links are
`/OPT:NOREF` (they have to keep going with unresolved references), so they
keep every COMDAT an object carries -- a template member an explicit
instantiation emits and nothing calls, say -- where retail's `/OPT:REF`
threw it away. Since tools 892868a each image's objects get an `/OPT:REF`
walk of the scorer's own: a reference graph by section from the COFF
relocations (externals by name, so a missing callee breaks no chain),
rooted at every non-COMDAT section, every NODUPLICATES COMDAT (an ordinary
out-of-line function is always kept), the entry points, the exports and
`/INCLUDE`s, and every placed function of ours. An unplaced function the
walk never reaches is `unreferenced`, not `unplaced`, and is not held
against coverage.

Two refinements followed, each from a wrong count:

* **A shape-only placement keeps nothing alive** (5d44dcd). Primal Hunt's
  server.dll had 13 explicitly instantiated stand-in `~CMoArray`
  destructors that nothing calls; placed by their 19-byte shape, they took
  13 of retail's 32 slots, and the referenced ones they displaced went
  unplaced. What only a shape-placed function reaches is no longer
  counted as live, so the stand-ins are `unreferenced` and retail's 32
  (all called from unwind funclets) pair with ours parent by parent.
* **A target's `discarded` regex** (on `module:symbol`) names out-of-line
  definitions the retail object had but `/OPT:REF` dropped: set aside
  before placement, not roots of the walk, listed `unreferenced` (AvP2
  d3d.ren's `d3d_TermTranslucentStates`). `no_reach` turns the walk off
  for a target, leaving all such rows `unplaced`.

On a project whose links already use `/OPT:REF` -- VC6's default --
`unreferenced` is 0 everywhere, because the link discarded those
functions itself (tron20src f964bf9). That is expected, not a sign the
walk is broken.

## How the scorer proves a short function

A function long enough is proven by its bytes: `exematch` masks the
relocations and what is left is unique in the image. A short one is not.
A one-call forwarder (`push arg; call X; pop ecx; ret`), a `GenAppend`
stub, a `ret`, a one-line getter folded across a dozen classes, all match
at many addresses, and "matched somewhere" says nothing about *which*
function it is. Every rule below came from a run that credited such a
function at the wrong address; together they took back several hundred
recorded identicals across the projects. When one of these rules lowers
your score, the lost functions were never shown to be what was credited:
record the loss with `ACCEPT_LOSSES=1` and say so in the commit.

**The operand map.** Once the long functions are placed, their relocations
give a mapping from our addresses to retail's: our `con_Term` is retail's
`0x0047xxxx` because an identical caller calls each. A short function's
operands are then checked through that map.

* **A stub placed by shape proves its operands** (tools 34a4a8e). A
  function of fewer than 16 unmasked bytes placed by shape alone used to
  take its first look-alike in name order, and the false placement then
  fed the map. avp2src's `cc_TermState` (`push arg; call con_Term; pop;
  ret`) sat at lithtech.exe 0x479ee0, retail's `operator delete` (which
  calls `dfree`), so `con_Term` mapped to two addresses and every caller's
  operand went ambiguous; its real address is 0x47a660. Now, where our
  image is linked, each such stub's call and address operands are compared
  against a map built only from **unambiguous** placements (one hit, or
  pinned) and imports. A stub whose operand maps to a different retail
  address is refuted: it moves to a hit where every operand agrees, or
  stays put if there is none, and the stub whose address it takes moves on
  in turn. avp2src gave up 40 recorded identicals of this kind (a45dd79),
  cjacksrc 20 (6937926), while placing 399 more.
* **A stub crowded off every look-alike takes a freed one** (0a08bdd). A
  stub that the first pass gave no address at all was never reconsidered,
  so the address a refuted stub vacated stayed empty (nolf2src's
  `FindObjectServer`, its row counted unwritten). Such a stub now takes a
  free hit where every operand maps, displacing nothing: 22 newly
  identical in nolf2src.
* **A string operand is compared by content** (180e91e): the same string
  counts as mapped, a different one refutes.

`PROGRESS_SHAPE_LOG=1` in the environment prints every such move to
stderr (`refuted <name> <from> ... -> <to>`, or from `-` for a crowded-off
stub); `--refuted` lists the short functions left with a contradicted
operand -- real differences, or a placement still wrong.

**A relocation-free function verifies only at its own address** (tools
1b61dca). With no relocations there is nothing for the map to check, so a
bare `ret` used to verify at whichever address of its shape placement
chose. It now counts only where its own address is mapped: identical code
calls or jumps to it there, or a paired vtable holds it in that slot. The
proof is the identical caller; an operand of the function that nothing has
paired yet ("unmapped") does not block it, one that maps elsewhere
("refuted") does (8e8a48f: every avp2src target gained, lithtech.exe +105,
none lost). The cost, the first time: cjacksrc withdrew 303 credits, all
1-7 byte shapes (2a2e387), tron20src 557 (f964bf9), avp2src's game DLLs
79 (f5f12c7).

When the right address is known but the scorer cannot prove it -- the
look-alikes differ only in a string or a callee it cannot see -- pin it:
the target's `own_symbols` in `progress/targets.py` maps a symbol to its
shipped address, with the evidence in a comment or a CSV it loads
(cjacksrc 8fe6925 pins CLayoutMgr's 193 attribute getters at the copies
passing the same strings, `progress/CShell-layout-pins.csv`). A
`sub_<addr>` name does the same, and `own_names` takes a substring of the
leaf name. A pin is a preference, not a credit -- the bytes must still
agree there -- and a pinned placement counts as unambiguous for the
operand map.

**`linked_oracle="same-address"`** (5660aba) is a stronger form for a
target whose own link lays the image out as retail's does: its
relocation-free functions are compared with our linked image at their own
address only, where every rel32 in the body then names the same target as
retail's. avp2src's cdaudio.dll proves its ten short functions this way
(c8193b2, 80 of 81 identical). `linked_oracle=True` takes the bytes
anywhere in our link, which is not proof for a body that recurs.

**One function, however many copies.** A template member or an inline is a
COMDAT that every object using it carries, and the linker keeps one. So:

* a copy that came out differently in one object is not near-paired when
  another copy is identical (98c44da): AvP2's `CSoundButeMgr` destructor
  had its slot held by an STL copy from another object; the copies our
  link kept pair first;
* a placement another function overwrites moves to its next free hit
  rather than vanishing (9a56003: AvP2's `CGameSpyServer::GetAddress` was
  lost to `GetPing`, which fitted only there);
* a displaced function pairs again only if our link has it (61deff4: Tron
  2.0's ClientFx.fxd paired an unlinked `CPlayRandomSoundFX::Term` at
  another class's address).

### Links with `/FORCE`

An engine that is not finished links with `/FORCE`, and VC6's linker
(6.00.8447) resolves **every** unresolved symbol to the image base. In
such an image all unresolved calls name one address: one identical
function's call to any of them mapped the base to its shipped callee, and
every short function calling any other unresolved symbol then "verified".
An operand of our image that falls outside its own sections is therefore
unknown: never noted in the map, never proof (tools 1b61dca, met in
avp2src f5f12c7's engine links, 1,440 and 320 symbols unresolved).

The way out is fewer unresolved symbols, not a looser scorer. avp2src
5301b0b took each engine link from over a thousand to a handful with a
per-image alias file (weak externals built by `tools/mkaliasobj.py`), each
binding checked against retail: every placed site that references the
symbol, read back out of the retail image, must reach where its target is
placed, and a binding no placed site confirms is kept apart as unproven
(avp2src docs/PLAN.md, "9. boot"). Such an image also cannot run: see
[05](05_exe_and_engine.md#running-the-thing--nears-have-to-execute).

### Libraries through the `.lib` the link reads

Score a library's functions through the library the link actually reads,
not loose copies of its objects. nolfsrc's engine targets listed copies of
RezMgr's objects for the per-object checks; the `.map` names those
functions by library member (`RezMgr:rezmgr2.obj`), a module the copies'
names never match, so none of RezMgr's short functions could be checked
by what they call. Listing `RezMgr.lib` in the target's `objs` made 13
identical, among them the hash tables' `jmp CBaseHash::~CBaseHash` that
only unwind funclets reach (nolfsrc 0b3ef3a).

## What a run rests on

A score is only worth what it compared, so the scorer guards its own
counting (tools adfdafa, from an audit with counterexamples in three
games):

* **No byte counted twice.** A short body's masked shape could match
  inside a longer function already matched in full, and both counted:
  nolfsrc had 41 such identicals, among them an 8-byte HostSession
  wrapper inside `CClassMgr::Init` (removed in nolfsrc dc82b03, each with
  its reason in `progress/corrections.txt`). Matches are taken longest and
  best-evidenced first; one that overlaps a better one is dropped and its
  function tries its other hits.
* **A scoring driver's own initializers are never placed.** sdkforce.obj's
  `_$E46` had been credited with 71 bytes inside
  `sm_ResetProfileCounters`, and its jmp thunks as four "small".
* **The region decides before the match**: outside `app` a row is `crt`
  whatever matched there, except in a target's `compiler_output` ranges.
* **Exports compare with their ordinals** in the data check (2515c05):
  `export <name> @<ordinal>`, since a module importing by ordinal binds to
  the number.

And every run records what it rested on (ca4369a): `out/progress/
evidence.json` holds the source and submodule revisions, each retail
image's SHA-256, the hashes of `progress/targets.py` and every exclusion
file, our images, maps and link commands, and the toolchain trees with
their digests checked against `toolchains/fetch.sh`'s pins.
`make progress-update` keeps a copy as `progress/evidence.json` beside the
baseline. Before scoring, `build/progress.sh` checks `out/reference/`
against `progress/reference.sha256` and extracts again if it differs
(nolfsrc dc82b03): a baseline recorded against other retail images is not
a baseline. After the data check it runs two more gates, `fpconst.py
--targets` (a float constant behind a masked relocation that differs from
retail's) and `vtabcheck.py --targets` (vtables and call wiring against
`progress/vtab-known.txt`, [07](07_vtables.md)); either failing fails
`make progress`.

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

Some of that evidence is mechanical, and `tools/enumproof.py` (892868a)
gathers it next to the unwritten and near rows: a row the row before
branches into, a start that is an operand byte of an instruction
straddling it, code that runs straight into it, or code after padding the
row's own trace never reaches. It proposes the screen-exclude row
(`NOT A FUNCTION: interior block of 0x...`) or extent split with that
evidence in the reason, and only when the later row is referenced nowhere
else:

```sh
python3 tools/enumproof.py --target server.dll           # print the proposals
python3 tools/enumproof.py --target server.dll --write   # append them
```

It reads the run's `out/progress/functions.csv` (`--csv` for another), so
score first. How it fits with the rest of the TU-mapping work is
[16](16_tu_mapping.md).

## A session, start to finish

```sh
make                                          # 1. a clean baseline build
make progress                                 # 2. passes: you start from green
python3 tools/progress.py --nears=server.dll  # 3. pick work (in make shell)
#    ... write source; build/engine.sh server-one <file> <symbol>; fndiff ...
make                                          # 4. rebuild everything
make progress                                 # 5. no regressions, new functions reported
make progress-update NOLF_SOURCE=~/nolfsrc    # 6. record them
git add -A src progress README.md && git commit
```

If step 2 fails on a fresh checkout, the tree and the baseline disagree
before you have touched anything: the build is not the one the baseline was
recorded from (another compiler, a stale object). Fix that first -- every
later result depends on it.

## Adapting it to another project

`progress.py`, `ratchet.py`, `datacheck.py` and `vtabcheck.py` know no
project by name. Everything about one -- which binaries, where each one's
code and ours is -- is in the project's own `progress/targets.py`, the one
file they read about it; `progress.py`'s header documents every key. At
module level:

* `REFERENCE`, `OUT`, `DATA`: where the retail images, each run's output
  and the recorded baseline are.
* `TARGETS`: one `dict` per scored image or resource set -- `label`,
  `what` (the README row's text), `kind` (`"image"` or `"resources"`),
  `shipped` (the retail image), `stem`, `built` (our image) and `objs`
  (our objects and libraries, where the link writes no response file).
* `LIBS`, `SHIPPED_LIB`, `SHIPPED_AS`, `SHIPPED_ENV`: libraries scored
  symbol by symbol against shipped `.lib`s (NOLF's lithshared, from the
  directory `NOLF_SOURCE` names); empty for a project without them.
* `DRIVER_OBJS` (scoring drivers, never placed) and `CITED_SRC` (where a
  comment citing an address marks a row `attempted`).

Per target, the keys that decide the denominator and the evidence: `app`
(the address ranges of the developer's own code; the rest is the
statically linked runtime, `crt`, not counted), `middleware` and
`third_party` (others' code inside it), `compiler_output`, `encrypted` /
`readable` / `unreadable` (copy-protected pages), `own_symbols` and
`own_names` (pins), `linked_oracle`, `discarded` and `no_reach` (above),
and `purecall` (the CRT's `_purecall` where it has no import thunk to be
found by, [07](07_vtables.md)). The README table's rows come from
`TARGETS`; `ratchet.py` keeps only where the table goes (`README`,
`BEGIN`, `END`).

Get `app` right first, with evidence: it decides what the denominator is,
and counting the runtime would understate progress as badly as counting
only what has been attempted would overstate it. Then record a first
baseline with `ratchet.py update`, and from then on the ratchet holds it.

**The first build's differences.** A newly built target differs from
retail in its data and its vtables in ways nobody has reviewed yet, and the
gates fail on every one. Record them, marked as such, so the gates hold
everything added from then on:

```sh
python3 tools/datacheck.py baseline --image=Object.lto "UNREVIEWED, recorded at Object.lto's first build (<date>): <why>"
python3 tools/vtabcheck.py --targets --baseline="UNREVIEWED, recorded at Object.lto's first build (<date>): <why>"
```

They go to `progress/data-known.txt` and `progress/vtab-known.txt` under
that reason (tron20src 789512a for Object.lto, 5aa07a9 for CShell.dll;
avp2src f5f12c7 for the engine links), and are worked down from there: an
`UNREVIEWED` line is a debt, not an explanation.
