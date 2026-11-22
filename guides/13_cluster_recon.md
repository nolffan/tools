# 13 · Reconstructing an untouched cluster

The procedure for taking a run of functions nobody has written yet, typically
a contiguous block of a retail image belonging to one module, from raw bytes
to source. [09](09_codegen_patterns.md) is the codegen catalogue; this is the
procedure. It is written so that it can be handed as-is to a contributor or an
agent working one cluster.

## Ground rules

1. **Ground truth is the retail image in `out/reference/`**
   (`build/reference.sh`). Never read a function out of one of our own builds
   (`src/engine/lithtech/Release/lithtech.exe`, `out/nolf-legacy-release/`): that hands you
   your own bytes back as the oracle, and the function looks solved when it is
   not.
2. **NEVER GUESS.** Every field name, offset, constant and control-flow
   decision must be read off shipped bytes and cited by address in a comment.
   Name unknowns by address (`sub_451720`, `m_Unknown54`).
3. **Write your output INCREMENTALLY**, appending each function as you finish
   it. An interrupted session loses everything not yet on disk.
4. **When several people or agents work clusters at once, keep them apart.**
   Either give each its own worktree (`tools/agentwt.sh`, which makes a
   branch `wt/<name>`), so each can build and measure its own work and
   commit it there for merging, or have workers write one new source file each
   and leave building and measuring to one person. Two builds in one tree
   overwrite each other's objects.
5. If your file will be linked alongside others written in parallel, give
   every new symbol a unique suffix, so the objects cannot collide at link
   time.
6. Build only through the build container (`make shell`, or the
   `build/engine.sh` targets inside it); the compilers run under its Wine.

## Choosing the rows

`tools/uncovered.py` lists the shipped functions that nothing of ours accounts
for. It marks EVERY address one of our COMDATs matches, not one per symbol,
and reads the hand-curated exclusions in `progress/`:

```sh
python3 tools/uncovered.py out/reference/lithtech.exe src/engine/lithtech/Release \
    out/reference/lithtech-functions.csv --csv=rows.csv
```

Read its four counts, not just the list. Rows below exematch's 8-byte floor
that one of our symbols already covers by shape, rows already written up, and
rows matched by name are not work; only the UNTOUCHED count is. Cross-check
the status of each row in `out/progress/functions.csv` (`tools/progress.py`),
so that nothing already written up as a near elsewhere is redone.

**You still must check extents.** That screen says nothing about whether a
row is a real function.

## Step 1: identify the module before decoding anything

In order of reliability:

0. **The console-variable table, whenever the module has one.** This is the
   best instrument found so far and it outranks everything below it. In
   `.data` there is an array of 20-byte records shaped
   `{char* name, float* pFloatVal, int32* pIntVal, ...}`. A record ties a NAME
   to **the address of the storage the module actually uses**, so it
   identifies the module that OWNS THE CODE. One read of three records
   (`"Prediction"`, `"PredictionLines"`, `"MaxExtrapolateTime" -> 0.5f`) named
   the whole run 0x00460d30..0x00461ccf as client dead-reckoning after the
   string pool had pointed at the renderer.
1. **A dispatch table or vtable.** `tools/vtabmap.py`, `tools/vtabaudit.py`,
   `tools/dataref.py`. One table at 0x00477fe0 typed nineteen handlers at
   once. A run of adjacent vtables lined up column by column gives you the
   class shape for free.
2. **The `.data` string pool read in ADDRESS ORDER.** Literal order follows
   function address order in these images.
3. **The call graph.** `wm_PushWorldModel` was identified by a single edge:
   the only caller in the image, sitting exactly where the source returns it.
   `tools/tagmap.py` names functions from the `Class::Method` error-tag
   literals they push.

**A string pool identifies the MODULE, not the function that references it.**
One cluster's indented `"  Models"` / `"  Music"` tree turned out to be
referenced by a single function that prints nothing and fills a table.

**Distrust the string pool: it has named the wrong module repeatedly.** In
each case the literals were real, and every one of them belonged to a row that
was *not* on the worklist, usually in an already-written file. Worse, a 0x4000
block routinely holds several unrelated modules: 0x00488000 turned out to be
three (a GDI font module, video-manager plumbing, and a PVS traversal), and
its four naming literals described none of the rows that needed writing.

The contrast is the rule. A string literal is evidence about **where the
literal lives**; a cvar record and a vtable are evidence about **where the
code lives**. Prefer instruments of the second kind, and when the two
disagree, the second kind wins.

## Step 2: verify every extent

`python3 tools/extentcheck.py <image> <start> <size|end>`, and
`tools/enumcheck.py` for a whole table. Wrong extents are common: clusters
have come back with half their rows defective. Catalogued defect shapes:

* the success arm of the function above;
* a shared `fail:` block or loop tail;
* the fall-through of an entry test: N sequential `if (!p) return ERR;`
  guards manufacture N-1 bogus starts;
* a row that CUTS AN INSTRUCTION IN HALF because the previous row was short;
* an INTERIOR BLOCK: branch targets leaving it, or other sites jumping INTO
  it;
* a row that is really TWO OR MORE functions. **Above about 1 KB this is the
  likeliest defect**: one row said 2,593 bytes against a real 4,613;
* DATA, not code;
* an **ASCII ACCIDENT**. PE import names do it (`"GetStartupInfoA\0"`
  contains the dword 0x00416f66, `"LoadCursorA\0"` contains 0x0041726f), and
  **ordinary `.data` string literals do it just as often**:
  `"SYNTHSAMPLERATE\0"` yields 0x00455441 and `"WSAEMSGSIZE\0"` yields
  0x00455a49, and both were on a worklist. The productive window is **the last
  three characters of any string plus its NUL**, because the NUL supplies the
  high zero byte a 0x004xxxxx address needs. Signature: a `ptr` row,
  unaligned, with no caller. **Test it in four bytes**: read the address back
  as little-endian text and see whether it spells the tail of a string that
  exists in the image. That retires the row before you disassemble anything.

  **It is necessary but not sufficient.** 0x00477d20 reads back as
  `" }G\0"`, fully printable, and is a real function: slot 0 of type 9 in a
  dispatch table. It was cleared by showing `.data` 0x004ae380..0x004ae387 is
  all zero, so no string exists whose tail those bytes could be. Printability
  RAISES the question; only finding the actual string answers it;
* an **INTERIOR BLOCK FIVE BYTES PAST AN INTRA-FUNCTION `jne`**, with a
  TRUNCATED HEAD ROW that tiles it exactly. A whole family, not a one-off:
  0x00442947 and 0x00442ab7 are each five bytes past a `jne` inside their own
  function, each has a 23-byte head row (0x00442930, 0x00442aa0) that tiles
  the rest exactly, and the same shape hits 0x004429ed and 0x00442bed in the
  same module. **Signature: a row whose only in-image reference is a
  conditional branch a few bytes earlier, sitting immediately after a
  suspiciously short row.** Add the two together and check whether the sum is
  a whole function;
* a **FALSE CALL TARGET INSIDE A MEMORY DISPLACEMENT**. 0x004478fd is
  `mov DWORD PTR [ecx+0xe8],0x0`, and the `0xe8` of the displacement was read
  as a call opcode, manufacturing a start at 0x00447904 in the middle of a
  183-byte function;
* a **FALSE CALL TARGET INSIDE AN IMMEDIATE**. Row 0x004619a0 was cut at
  0x00461c77, mid-instruction, because the bytes `e8 40 4b 00` occur inside
  `movl $0x0,0x4b40e8` at 0x0045d132 and were read as a call. The real
  function is 815 bytes, not the 727 the row claimed, and the neighbouring
  "0x00461c77 / 88 / call" row is not a function at all. Signature: a `call`
  row whose start is mid-instruction, and whose apparent caller is a `mov`
  with a `.data` address as its immediate. Nasty precisely because `call`
  provenance is otherwise the trustworthy kind.

How far to trust a row's `source` column
(`out/reference/<image>-functions.csv`):

* `gap` and `ptr` rows are the unreliable ones. A cluster of clean `call`
  rows had all eight extents sound.
* **`setup` provenance is usually sound but not reliable.** All four
  `setup`-sourced rows in cluster 0x00488000 were whole interface-slot bodies
  reached by a `movl $addr` installing them in a function-pointer table, and
  all four came out byte-identical. The counter-example is a defect shape of
  its own: 0x0042e856 has no call, no jump and no stored address anywhere in
  the image. Its one "reference" is the dword at 0x00473fb8, which is not data
  at all: it is the bytes `56 e8 42 00` of `push esi ; call 0x00474000` at
  0x00473fa5. **The `setup` scan reads address-shaped dwords out of `.text`**,
  and an accidental `push reg ; call rel32` pair spells a plausible code
  address. The row truncated its real function (0x0042e830, 112 bytes) at a
  phantom boundary. So a `setup` row is evidence only once you have confirmed
  the referencing dword lives in a DATA section.
* **`call` provenance is not unconditionally safe** either, per the
  false-call-target shapes above. Check that the start is on an instruction
  boundary.

To prove a large row is ONE function, sweep every `e8`/`e9` in `.text` for
displacements landing inside it: if the only one is its own jump to its
cleanup, it is one function.

A row proven not to be a function goes into
`progress/<image>-screen-exclude.csv` with a reason starting
`NOT A FUNCTION:` and the evidence; a start the enumeration missed goes into
`progress/extent-splits.csv`. Both change what the scoreboard counts, so the
evidence must be in the row (see `progress/README.md`).

## Step 3: write it

lithtech.exe's code is MSVC 6 `cl` rev 8447 at `/O2`, which implies `/Oy`:
**every function is frameless and `%esp`-relative**.
(`progress/COMPILERS.md` and `build/build.mk` give each
binary's compiler and the per-file exceptions.)

**ORDERING is source-reachable**: statement order; which arm falls through;
member-store order; comparison operand order; cast placement; an expression
repeated rather than cached; declaration order when one local has a
constructor and another does not.

**ALLOCATION is NOT**: register choice, `lea` base-vs-index, stack-slot
assignment, frame size, loop rotation and peeling.

The rules that pay most, in order:

1. **Positive guards, and they NEST.** If the shipped conditional jump goes
   FORWARD to a block sitting past every other return, that block is a
   TRAILING STATEMENT and the guard above it is positive. The shared answer
   need not be one instruction; a 25-instruction `RETURN_ERROR` expansion
   counts. After fixing the outer guard, look inside the body again.
2. **One instruction differing only in an IMMEDIATE is a struct offset or
   size.** Read a class's size straight off its `operator new` argument.
3. `new char[strlen(s)+1]` is followed by `strcpy`, never `memcpy`.
4. **VC6 does not CSE two written-out `strlen()` calls**: two `repnz scasb`
   scans mean the source wrote it twice. Same reading for repeated field
   loads: four reloads of one member means it is written out at each use.
5. **Count epilogue copies to find `if` nesting**: one shared exit with
   several producers means nested positive guards plus one trailing return;
   several duplicated exits mean separate early returns.
6. Of two identical sites, VC6 keeps the SECOND inline and jumps the first
   into it.
7. A constructor's statement order comes from the argument PRELOADS, not the
   store order: VC6 loads three values into ecx/edx/eax, then alternates
   store-then-reload, so stores 3 and 4 come out transposed.
8. **An unmatched destructor short by exactly one vptr store** means a member
   class has a destructor you have not written. The constant names the class,
   and it goes on the MOST-DERIVED one.

[12](12_o2_shape.md) covers the `/O2`-specific rules in more depth.

## Things that will waste your time if you do not know them

* **objdump x87 hazard**: DE-form mnemonics are SWAPPED in AT&T syntax, as in
  GNU `as`. Use `objdump -M intel` for x87 code. Many wrong decodes have come
  from this.
* **`/O2` canonicalises commutative FP sums**: do not read operand order off
  a float add.
* `progress/lithtech-decoded-map.csv` rows whose evidence column says
  `bridged-callsite` are inferred from a call site, and **the name may be
  wrong**.
* A `+` suffix on an exematch address means those bytes occur more than once;
  when two functions differ only inside a masked relocation it will name the
  wrong one.
* `tools/callseq.py` needs a compiled object. Until you have one, say
  NOT RUN rather than claiming a pass.
* The client half of shared code may legitimately DROP a scoped profiling
  timer the server keeps (`build/engine.sh` passes `/D LT_SERVER_TIMERS` to
  the server only), and shared server source sometimes CALLS INTO THE CLIENT
  under `LT_SERVER_BUILD`. If a client function is exactly a counter's worth
  smaller, or has one extra call into client code, that is why.

## `jmp` over padding into a zero-initialiser is `??__E`, not a mystery

A shape that is easy to give up on: a five-byte `jmp` landing a few bytes
ahead, over what looks like alignment padding, onto a body that stores zeroes
into three consecutive floats.

That is VC6's **dynamic initialiser for a file-scope object**. The thunk and
the body are two COMDATs; the linker 16-byte-aligns the second, which is the
whole of the "padding". The two images prove it outright:

    lithtech.exe 0x0042f630   e9 0b 00 00 00   jmp 0x0042f640
    server.dll   0x1000e4df   e9 00 00 00 00   jmp 0x1000e4e4   <- displacement ZERO

Same construct, same body, and the displacement is zero in the image whose
linker did not need to pad. The bodies differ in size for a reason that
cross-checks exactly: `/Os` picks `fldz ; fstps` (8 bytes × 3 + ret = 25,
server's size) and `/Ot` picks `movl $0,<abs>` (10 × 3 + ret = 31,
lithtech's). **One source, both sizes exact.**

The source is a file-scope object with a constructor,
`CVectorZeroInit g_Name(0,0,0);`, and `src/engine/server/svlast.cpp` already
reconstructs the server side that way. Find the object's name in the CRT
`__xc` table (here 0x004a7000..0x004a70fc): the table's slot ORDER is
declaration order.

## Running parallel waves

Ground rule 4 prevents two workers from overwriting the objects of each
other. A wave is a group of many agents that work at the same time. Each
agent takes a share of the unwritten functions of a DLL. A wave needs more
than ground rule 4. It also needs:

- a partition that nobody can dispute,
- a rule that tells who owns the shared files,
- one person who merges.

The model is the unwritten-functions wave of tron20src. Ten band agents
worked, each in its own worktree. After the merge, the net gain was +721
identical functions: 758 new functions, and 37 small stubs re-paired among
twins (tron20src 6a0b3f0). The working files of this wave are in the
`out/work/` of tron20src, which is gitignored. They are local to that
checkout. They are not in its history and not part of `tools/`. Thus, for
a new wave, make these files again. Do not look for them in git.

**Partition by retail address band.** Cut the code of each DLL into a small
number of contiguous address ranges. Give one or more ranges to each agent.
For each band, filter the unwritten rows of the scoreboard
(`out/progress/functions.csv`, status `todo`) into a `todo-<band>.txt` file.
Each line of this file is `address size`. A header line names the range.
For example:

    # Object.lto 0x10001000..0x1001a000: 110 unwritten functions
    0x10001250 35
    0x10001290 745

Retail translation units are contiguous, and their functions are in source
order. Thus ownership follows from this rule: **an agent owns a TU if the
FIRST function of the TU is in its band**. The rule applies also when the
TU continues past the end of the band. The rule settles every boundary
case, and the agents do not have to discuss them.

**Rules for the shared files.** Write these rules into the brief:

- Shared headers are ADD-only. You can add constants or a declaration. You
  can add a member at the end only where the retail layout shows it. Do not
  reorder or remove items in a class that another agent owns. List your
  additions in your report.
- Use the `out/work/dspadd.py` of tron20src to add new files to the
  project. This script is a local helper, not part of `tools/`. It keeps
  the group in alphabetical order. Thus the `.dsp` additions cause as few
  conflicts as possible.
- Workers do not run `make progress`, and they do not merge. Only the
  coordinator merges the branches. The coordinator resolves the `.dsp`
  conflicts and runs `make progress` one time for the wave.

**A brief that each agent reads first.** The brief of tron20src was
`out/work/AGENT_BRIEF.md`. The brief contains:

- The project and its targets.
- The origin of the source.
- The fast loop: one object, then the function diff.
- The rules above.
- The **known compiler facts**. Without them, each agent must find them
  again. For Tron, these facts were:
  - VC6 puts the virtual overloads of a name in reverse declaration order.
  - Identical code folds.
  - A member function that is defined in the class is inline.
- The **known blockers**. Agents leave these functions near and do not try
  to fix them. Examples are a vtable that is known to be short, a class
  with the wrong size, and enums that are different.
- **"already solved -- grep master first"**: the classes and libraries
  that earlier workers wrote, and where they are.

### What went wrong, and what to do about it

Two problems used most of the merge time of the tron20src wave.

- **Workers duplicated shared dependencies.** If two bands need the same
  class, two workers write it. In Tron, two workers added
  `CLIENTFXUSERCREATESTRUCT` for two different users (e18c7f2). The GameSpy
  files `md5c.c` and `nonport.c` came two times, in two directories
  (4d3f4c2). `CSubroutineDataMgr` came one time as the full class. It came
  a second time as a partial header with a second global (eff0766). Each
  case needed a dedup commit after the merge. Also, we had to move the user
  of the partial copy onto the full class.
- **Almost every merge had a conflict in `docs/RETAIL_BUGS.md`.** Each
  worker that found a retail bug appended to the same section of the same
  file. Four merges of the wave had a conflict in that file and in no other
  file (ccc5235, 8df0099, d07c0be, 8f64ca5). Two more merges had a
  conflict in a `.dsp` file. After the merges, the entries needed a
  separate commit to separate them (ba62c68).

**Remedies.** We did only the second remedy, after that wave and for the
next wave. We recommend the other remedies, but we did **not yet try**
them:

- *(Not yet tried.)* Assign the shared classes before the wave. Find the
  shared classes that the TUs of the bands call. Their RTTI and the calls
  that the retail dumps name show these classes. Give each class to one
  band, or write the classes first.
- Add to the "already solved" list between waves. It is better to add to
  it between merges. Then a late worker can grep for the code of an early
  worker. The list in the Tron brief now names the three duplicated cases
  above.
- *(Not yet tried.)* Make `RETAIL_BUGS.md` append-only. Mark it
  `docs/RETAIL_BUGS.md merge=union` in `.gitattributes`. Then concurrent
  appends merge without a conflict.

  CAUTION: A union merge can interleave or duplicate lines. Thus the
  coordinator must still read the merged file.
- *(Not yet tried.)* As an alternative, each worker writes its bugs to its
  own file (`docs/retail-bugs/<band>.md`). The coordinator then folds these
  files into `RETAIL_BUGS.md` in the merge commit.

The same partition also worked for a tool. lithtools restored the AvP2
DEdit to its 2001 source in nine parts, by image range. Each part owned the
headers of its modules. One round of nine agents did the work. The count of
identical functions went from 2,499 to 3,855 (lithtools
`legacy/talon/docs/PLAN.md`, section 3).

## Tools

    python3 tools/exedump.py out/reference/lithtech.exe <start_va> <end_va>
    python3 tools/extentcheck.py out/reference/lithtech.exe <start> <size|end>
    python3 tools/vtabmap.py | dataref.py | enumcheck.py | nearpos.py | tagmap.py
    build/engine.sh lithtech-one <file.cpp> [symbol]     # once you can build

## Reporting back

When the cluster is done, report a table: address | what it is | signature |
what you VERIFIED | honest byte-identity confidence. Then which rows were not
functions and why, which were already written, and anything unpinned, with the
alternatives weighed.

**Calibration: people and agents predict call agreement well and byte
identity badly, and the error is almost always pessimistic.** Report what you
verified, not what you expect. A well-evidenced "this row cannot be won, and
here is why" is a good outcome: such findings have retired more work than the
edits they replaced.
