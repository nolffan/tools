# 05 · Reconstructing executables and engine binaries

Libraries are the easy case: they ship as `.lib` files full of COFF symbols, so
`objdiff` can match by name and mask relocations. The engine targets —
`NOLF.exe`, `lithtech.exe`, `d3d.ren`, `server.dll` — are stripped release PE
files: **no symbols, and no `.reloc` section to speak of.** That changes the
workflow.

## What's different

- **No function names.** You work by address. `.text` is carved into
  functions with synthetic names (`sub_<addr>`); `build/reference.sh` writes
  that table for every image to `out/reference/<stem>-functions.csv`, and
  `tools/progress.py` gives each row a status in `out/progress/functions.csv`.
- **No relocations to mask on the shipped side.** Whole-file diffing is
  unreliable. Instead you verify *your* objects (which *do* have relocations)
  against the image with `exematch`: it masks your object's relocation bytes
  and scans the image's `.text` for the remaining position-independent bytes.
  A hit means that function is byte-identical in the shipped image.
- **CRT/MFC noise.** A release image is mostly library code you don't
  reconstruct. Only Monolith's own functions count. For `NOLF.exe` the app
  region is `0x401000–0x409ed2`; above it is the static MFC and CRT. Each
  image's region is `APP_REGION` in `tools/progress.py`, with the evidence for
  where it ends.

## The tools

All of these run inside `make shell` (or on a host with Python 3), after
`build/reference.sh` has put the retail images in `out/reference/`.

```sh
# annotated disassembly of a range (resolves IAT calls, inlines string/section refs)
tools/exedump.py out/reference/NOLF.exe 0x404fc0 0x4054b0

# verify: does the image contain our objects' functions, byte-for-byte?
tools/exematch.py out/reference/NOLF.exe src/engine/launcher/Release/*.obj
```

`exedump` is your `dumpfn` here — read a function, identify its imports and
string literals (which name what it does), and write the source. `exematch` is
your `objdiff` — it reports `MATCH <addr>` per function, or nothing for a miss.
(`exedump` needs `objdump` from binutils, which the build image does not have;
run it on a host that does.)

## The method

1. **Enumerate and map.** `tools/enumfuncs.py` collects function starts from
   several independent sources and reports byte coverage:

   ```sh
   tools/enumfuncs.py out/reference/server.dll --csv out/reference/server-functions.csv
   ```

   (`build/reference.sh` already does this for every image.) Use all the
   sources — none is sufficient alone. In server.dll only about 60% of the
   functions are direct `call` targets; nearly a third are reachable **only
   through vtables or function tables**, and the rest through callbacks,
   initializer pairs or nothing at all. (Padding-carving works on
   lithtech.exe but *not* on server.dll or d3d.ren, which have almost no
   inter-function padding.) Check the reported coverage: well under ~99% of
   `.text` means starts are still missing.

   Then build a table of contents: for each function, the strings and imports
   it references (grep the `exedump` output). Those references tell you what
   each function is and which ones group into a source file — and in the
   engine binaries, embedded `Class::Method` strings name many outright
   (`tools/tagmap.py`; see [06](06_worked_example_engine.md)).

2. **Seed from era source where it exists.** Monolith reused code across
   titles. `NOLF.exe`'s DIB/palette code is `libs/dibmgr` in the NOLF2 source
   release; its `RezFind`/`Utils` are in the NOLF2 launcher. Back-port these —
   but **trim to the shipped era**: the shipped code predates NOLF2 by years,
   so remove later-added functions and overloads (dibmgr's post-1998 methods,
   the Win2K PSAPI path in `ExistProcess`, and so on) until the function set
   matches. A seeded file often matches 80%+ on the first compile.

3. **Disassemble-and-match the rest.** Everything with no era source is read
   straight from `exedump` output using
   [03-reading-disassembly](03_reading_disassembly.md).

4. **Resources are separate.** An exe or dll also carries dialogs, strings,
   bitmaps, icons. Reconstruct them as an `.rc` and verify with `rsrcdiff`
   (payload by payload, layout-independent) — see how `src/engine/launcher/`
   and `src/engine/ltmsg/` do it. `ltmsg.dll` is *only* resources: its `.text`
   is the bare CRT, with the CRT's own default `DllMain`.

5. **Structural tells for exes.** `NOLF.exe` is a Win32 app over *static*
   MFC — the dialogs are raw `DLGPROC`s driven by `DialogBoxParamA`, not MFC
   message maps. Recognizing the framework early saves you modelling the
   wrong thing.

## Compiling and verifying

**`server.dll` is built `/O1` (minimize size), not `/O2`** — proven by
byte-matching it; [06-worked-example-engine](06_worked_example_engine.md)
shows how that was found and what the tells look like. The other targets have
their own compilers and flags (lithtech.exe cl 8447 `/O2`, d3d.ren Intel
C/C++ 4.0 with per-file flag groups); `build/build.mk` lists
them, and `progress/COMPILERS.md` gives the evidence.

`build/engine.sh` builds each target and, with `verify`, runs `exematch` on
every object:

```sh
make shell                                # then, inside the container:
build/engine.sh launcher verify           # compile, link NOLF.exe, match
build/engine.sh server verify
```

While iterating on one function, recompile only its file and match only its
object — a few seconds per round:

```sh
build/engine.sh server-one servermsg.cpp WriteToMessageByte
build/engine.sh lithtech-one smgr.cpp PlaySound
build/engine.sh d3d-one d3d.cpp RenderDLLSetup
```

The optional last argument narrows the report to the lines naming that
symbol. `src/engine/server/*.cpp` is compiled into **both** server.dll and
lithtech.exe, so after changing one, check both.

## The whole-image link

`exematch` verifies functions individually against the shipped bytes; that
is the real proof of faithfulness. A *complete* byte-identical image
additionally needs every function reconstructed and the linker settings,
order and data matched. Until then, the per-function match rate — the table
in the top-level `README.md`, re-measured by `make progress` — is the measure
of progress.

## Running the thing — nears have to execute

A byte-identical function needs no runtime test: it *is* the shipped code. A
**near** is the opposite — instruction-equivalent but not proven, and
therefore not shown to be correct. The whole links close that gap: every
engine image is linked from our objects alone (`build/engine.sh
server-link`, `lithtech-link`, `d3d-link`), `make` assembles them into
`out/nolf-legacy-release/`, and `make test` plays levels on them. Every near we have written
runs there, beside every identical function. `server-link test` and
`d3d-link test` load a single linked image under Wine on its own.

The lesson that carried over from running nears: **a near can be the wrong
function.** Pairing by shape once matched a thiscall `AllocItems` (`ret 8`)
against a cdecl allocator (plain `ret`), and the game crashed on load; of the
functions a return-style check then flagged, two were real bugs in the
reconstruction. Compare the return instructions before believing a pairing.

**Boot early.** This rule is not only for nears. The scorer *places* some
items and does not prove them. Examples are a vtable slot, a struct size
and a link-time binding. Only a run of the game checks these items.

Boot the game on your build when it first links. Then boot it again after
each change. Use Xvfb and Wine with scripted input:

- `tools/playtest.sh` and its `playtest-*.txt` input scripts.
- avp2src's `build/playtest.sh`, which adapts the script for each game.
  `make test` runs it.

AvP2 and Primal Hunt first showed only a black screen on our engines. The
work to get them to their first levels found these problems, and others
(avp2src f244290, 27eb79d, baebb5b):

* **Vtable twins with identical masked bytes.** The scorer put `GetNode`
  of `ILTModel` at the address of `GetSocket`, and `GetSocket` at the
  address of `GetNode`. The `CreateString` slot of `ILTServer` contained
  `LAlloc::Alloc`. All the bytes matched, but the calls went to the wrong
  function.
* **A base stub beating the override.** The table of `CObjWorldModel` kept
  the empty `OnFoundInBox` of `CObjBase`. Thus the world tree did not get
  to the renderer. The world was black, but nothing crashed.
* **An undersized struct overwriting globals.** The declaration of
  `g_FormatMgr` in d3d.ren gave 0x9a8 bytes, but the correct size is
  0xb94. The scale tables of its constructor wrote over the texture
  globals after it. Also, `ViewParams` in `d3d_drawsky.cpp` was 0x4cc
  bytes, not 0x4f8, and it wrote over a sky-portal handle.

The vtable rules from these problems are in [07](07_vtables.md#when-placement-votes-ties-and-twins).

**A behaviour test needs a retail-vs-retail control.** A comparison of our
output with the retail output is correct only where two retail runs give
the same output. Uninitialised data depends on the heap. The heap depends
on very small things, for example the length of the path of the exe.

For example, the Processor.exe comparison of lithtools passed only when
the name of our exe had the same length as the name of the shipped exe.
The cause is that the T-junction splits of the physics BSP write
uninitialised vertex colours (lithtools `legacy/talon/docs/PLAN.md`,
"Behaviour"). Thus the harness now runs the shipped exe a second time
from a longer path.

An exception to the comparison is correct only if the two retail runs
also need it. On Sample_DM, the two retail runs are different in 2,637
colour bytes of 519 polies. Some of these bytes are all 255 in one run
and random values in the other run. Thus "uninitialised in both" was not
a correct rule (lithtools 59a7aac). Record such a difference in
`RETAIL_BUGS.md`. Do not make the comparison less strict until it passes.

**A `/FORCE` link does not run.** Sometimes we link an image with
unresolved symbols, for the scoreboard, while the engine is not complete.
VC6's linker then resolves each of these symbols to the image base. Thus
the first call to one of them jumps to 0x00400000 and executes the bytes
of the PE header. The result is an illegal instruction at 0x0040000C. This
often occurs in a static constructor before `WinMain`.

For example, in avp2src, the `CConsoleView` constructor for the global
`g_Console` called a `CConsoleCritSec` constructor that no object defined.
Use such an image only for the score. For the effect on the scorer, and
how avp2src bound its symbols to run the image, see
[14](14_progress.md#links-with-force).

## The engine binaries

`lithtech.exe`, `d3d.ren` and `server.dll` are the bulk of the work — about
1.4 MB of `.text` between them. How far each has got is the README's
progress table.

`server.dll` was the model for the others: it exports only
`CreateServer`/`DeleteServer`, the LT2 SDK headers give type information the
launcher work never had, and it carries embedded `Class::Method` strings that
name functions for free. Its recovered source is also lithtech.exe's: the
client engine compiles the same `src/engine/server/` files a second time, so
work there pays twice.

A caution learned there: the SDK headers in `src/LT2/sdk/inc/` are
**NOLF2-era** while these binaries are NOLF1. Signatures are mostly stable;
**vtable order is not**. Verify every slot's argument count from its `ret N`
before trusting the header's ordering.
