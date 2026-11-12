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
them, and `toolchains/COMPILERS.md` gives the evidence.

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

**Boot early.** Not only nears: anything the scorer *placed* rather than
proved -- a vtable slot, a struct size, a link-time binding -- is only
checked by running it. Boot the game on your build as soon as it links,
under Xvfb and Wine with scripted input (`tools/playtest.sh` and its
`playtest-*.txt` input scripts; avp2src's `build/playtest.sh` adapts it
per game, `make test` runs it), and keep doing so. Getting AvP2 and Primal
Hunt from a black screen to their first levels on our engines found, among
others (avp2src f244290, 27eb79d, baebb5b):

* **Vtable twins with identical masked bytes.** `ILTModel`'s `GetNode` and
  `GetSocket` were placed each at the other's address; `ILTServer`'s
  `CreateString` slot held `LAlloc::Alloc`. Every byte matched; the calls
  went to the wrong function.
* **A base stub beating the override.** `CObjWorldModel`'s table kept
  `CObjBase`'s empty `OnFoundInBox`, so the world tree never reached the
  renderer: the world drew black, nothing crashed.
* **An undersized struct overwriting globals.** d3d.ren's `g_FormatMgr` was
  declared 0x9a8 bytes; it is 0xb94, and its constructor's scale tables
  overwrote the texture globals after it (and `d3d_drawsky.cpp`'s
  `ViewParams`, 0x4cc for 0x4f8, overwrote a sky-portal handle).

The vtable rules these taught are in [07](07_vtables.md#when-placement-votes-ties-and-twins).

**A behaviour test needs a retail-vs-retail control.** Comparing our
output with retail's is only sound where two retail runs agree.
Uninitialised data follows the heap, and the heap follows things as small
as the length of the exe's path: lithtools' Processor.exe comparison only
held with our exe named as long as the shipped one, because the physics
BSP's T-junction splits write uninitialised vertex colours (lithtools
`legacy/talon/docs/PLAN.md`, "Behaviour"). So the harness now runs the
shipped exe a second time from a longer path, and an exception to the
comparison is sound only if those two retail runs need it too: on
Sample_DM they differ in 2,637 colour bytes of 519 polies, some all 255 in
one run and garbage in the other, so "uninitialised in both" was not a
sound rule (lithtools 59a7aac). Document such a difference in
`RETAIL_BUGS.md`; don't widen the comparison until it passes.

**A `/FORCE` link does not run.** An image linked with unresolved symbols
(for the scoreboard, while the engine is incomplete) has every one of them
resolved to the image base by VC6's linker, so the first call to one jumps
to 0x00400000 and dies on the PE header's bytes: an illegal instruction at
0x0040000C, often in a static constructor before `WinMain` (avp2src's
`CConsoleView` constructor for the global `g_Console`, calling a
`CConsoleCritSec` constructor no object defined). Such an image is for
scoring only; what that means for the scorer, and how avp2src bound its
symbols to run, is [14](14_progress.md#links-with-force).

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
