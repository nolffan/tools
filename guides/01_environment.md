# 01 · The build environment

To reproduce Monolith's bytes you must compile with the compilers they used:
**Microsoft Visual C++ 6.0** -- several revisions of it, because Monolith did
not build every binary with the same one -- and, for the renderer `d3d.ren`,
**Intel C/C++ 4.0**. All of them are in the `toolchains/` submodule
(`git submodule update --init`), assembled from public copies of the
original media (see [`toolchains/README.md`](../../toolchains/README.md)):

| directory | compiler | used for |
|---|---|---|
| `toolchains/msvc-6.00-9782/` | cl 12.00.8804 driver, back end 12.00.9782 (VC6 SP6) | the default; game DLLs, `NOLF.exe`, `ltmsg.dll`, `sres.dll`; and the linker, librarian and resource compiler for everything |
| `toolchains/msvc-6.00-8447/` | back end 12.00.8447 | `server.dll`, `lithtech.exe`, the lithshared libraries |
| `toolchains/msvc-6.00-8168/` | back end 12.00.8168 | the headers and libraries `icl` builds against; `CL_REV=8168` experiments |
| `toolchains/icl-4.0/` | Intel C/C++ 4.0 | `d3d.ren` |

`tools/richhdr.py` reads which revision built each retail image out of the
image itself; [`toolchains/COMPILERS.md`](../../toolchains/COMPILERS.md) has the
answers and the evidence.

## Everything runs in the build container

The compilers are Win32 programs and run under Wine inside a Docker container
(Ubuntu 24.04, `docker/Dockerfile`), with the checkout mounted at `/repo` and
the container running as your user. The host needs Docker and nothing else --
no Wine, no Python.

```sh
make            # the whole build, in a throwaway container
make shell      # an interactive shell in the container, at /repo
```

Inside `make shell`, every build script and tool runs on its own (the Wine
prefix lives in `out/wineprefix`, created on first use). The rest of these
guides show commands as you type them there.

## Building parts of the tree

```sh
build/libs.sh ltguimgr          # one lithshared library (or: all)
build/build.sh cshell final     # one game DLL (cres | cshell | object | all)
build/engine.sh server          # all of one engine target's objects
build/engine.sh server verify   # ... then match every function against the retail image
build/engine.sh server-link     # link server.dll
```

`build/libs.sh` targets: `stdlith cryptmgr lith rezmgr regmgr mfcstub ztools
butemgr ltguimgr lithfontmgr gamespy all`; it writes the libraries to
`src/lithshared/out/`. `regmgr` also builds `RegMgr_Debug.lib`, the same
source with the `.dsp`'s Debug settings, which only `CShell.dll` links (the
Game of the Year `CShell.dll` has the Debug build's code). `build/engine.sh` with no arguments prints its targets;
its header lists the compiler and flags for each.

`src/engine/server/` is compiled into **both** `server.dll` (`/O1`) and
`lithtech.exe` (`/O2`). After changing a file there, rebuild both
(`build/engine.sh server` and `build/engine.sh lithtech`, or the two `*-one`
loops below), or `lithtech.exe` keeps scoring stale objects.

## Compiling one file at a time

While iterating on a single function you want a tight loop: recompile just
the one translation unit and check just its object. For the engine targets
`build/engine.sh` has that built in, with each file's own compiler and flags
(from `build/build.mk`),
in about three seconds:

```sh
build/engine.sh server-one smgr.cpp PlaySound     # server.dll
build/engine.sh lithtech-one smgr.cpp PlaySound   # lithtech.exe (a name not in
                                                  #   src/engine/lithtech is
                                                  #   taken from src/engine/server)
build/engine.sh d3d-one d3d.cpp RenderDLLSetup    # d3d.ren
```

The optional last argument narrows the report to the lines naming that symbol.

For anything else, `build/env.sh` defines `run_cl` / `run_icl` / `run_lib` /
`run_link` / `run_rc`, the compilers under Wine. Setting `CL_REV` before
sourcing it selects the cl revision (`8168` or `8447`; unset is `msvc-6.00-9782`):

```sh
cd /repo/src/lithshared/ltguimgr
CL_REV=8447 source /repo/build/env.sh
rm -f Release/ltguibitmapctrl.obj
run_cl /nologo /MT /W3 /GX /O2 /D WIN32 /D NDEBUG /D _WINDOWS /D NO_PRAGMA_LIBS \
    /D _NOMFC /D _LITHTECH2 /I ..\\..\\LT2\\lithshared\\ltguimgr \
    /I ..\\..\\LT2\\lithshared\\incs /I ..\\..\\LT2\\lithshared\\mfcstub \
    /I ..\\..\\LT2\\lithshared\\lith /I ..\\..\\LT2\\sdk\\inc /I . \
    /c /FoRelease/ ltguibitmapctrl.cpp
```

The flags come from the original `.dsp` project files: **`/MT /W3 /GX /O2`**
is the Release recipe for the libraries and game DLLs, and matching it is
mandatory -- `/O2` vs `/O1`, `/MT` vs `/MD`, a missing `/D` all change
codegen. `/D NO_PRAGMA_LIBS` suppresses the `#pragma comment(lib, ...)`
directives the LT2 headers embed (they name Monolith's own build paths and
break linking). The `build_*` function for your library in `build/libs.sh`
has its exact include paths and defines; mirror them.

A failed compile under Wine can exit 0 and leave the previous object in
place, so a broken edit measures as "no change". The `*-one` loops delete the
old object first; do the same when compiling by hand.

## What "the same bytes" requires

- **Same compiler revision** -- the one the original binary was built with
  ([`toolchains/COMPILERS.md`](../../toolchains/COMPILERS.md)); the build scripts
  pin it per target.
- **Same optimisation and runtime flags** -- per the `.dsp` files for the
  libraries and game DLLs; measured, per file, for the engine.
- **Same headers** -- the LT2-era headers in `src/LT2/`, which the include
  paths put first. Watch for local `.h` shadows that quote-include and
  override them.
- **Same source constructs** -- everything else is
  [03-reading-disassembly](03_reading_disassembly.md).

**And the same build twice.** VC6 names an anonymous namespace
`?%<source as spelled><number>`, and the number -- 8 to 10 digits -- is
drawn afresh on every compile: the same file compiled twice in a row gets
two. The name is part of every symbol declared in the namespace, so its
length moves where the linker lays things out. In avp2src, WONAPI's three
anonymous namespaces (`QueueSocket.cpp`, `CDKey.cpp`, `CRC.cpp`) decided
whether six of `ServerDir.dll`'s functions came out byte-identical, from
one clean build to the next. A scored build has to be reproducible, so the
library build runs `tools/anonns.py` over those objects: it rewrites each
number in the string table (and the RTTI names that carry it) to a fixed
one, without touching code or data. The scorer, for its part, pairs a
library member in an anonymous namespace by its name without the
`?%<path><digits>@` component, which also embeds the build machine's path
(tools, commit 180e91e). If a function flips between identical and near
across rebuilds of unchanged source, look for `?%` in its object's symbols
first.

## Which toolchain built a given retail binary

`link.exe` stamps every PE with a "Rich" header: an obfuscated record of each
tool that contributed objects, as (product, build, object count). It is the
ground truth for "which compiler do we need", and it does not agree across
NOLF's binaries:

```sh
python3 tools/richhdr.py out/reference/NOLF.exe out/reference/server.dll \
    out/reference/lithtech.exe out/reference/ltmsg.dll
```

**Run it on our own output too, and mind which file you are reading.** Both
the retail launcher and ours are called `NOLF.exe`; ours is in
`src/engine/launcher/Release/`. Reading the rebuild and calling it the retail
file is an easy mistake and it inverts the conclusion.

| binary | cl builds present | its own C++ objects |
|---|---|---|
| `ltmsg.dll` | 8168 | 8168 ×2; it is resources and the CRT, whose own default `DllMain` it uses, so its code is all CRT |
| `NOLF.exe` | 8168, 8569, 8797, 8799 | 8799 ×10 and 8797 ×10; the C rows (8797 ×138) are the CRT and 8569 ×42 is MFC |
| `server.dll` | 7291, 7299, 8168, 8447 | 8447 ×95 |
| `lithtech.exe` | 7291, 7299, 8168, 8447, 8799 | 8447 ×155 |
| `d3d.ren` | 7291, 7299, 8168, 8447 | 8168 ×8 and 8447 ×3 -- linked-in library code; the renderer itself was compiled by Intel C/C++, which leaves no Rich entry |

Our own builds with `msvc-6.00-9782` stamp 9782 -- which appears in none of the
retail images. `NOLF.exe` wants revisions nobody has (8797, 8799), yet the overwhelming majority of its functions match under the
default compiler anyway: the builds agree on almost everything, so **a near
match is far more likely to be a source shape you have not found than a
compiler difference**. Treat revision variance as the last explanation, never
the first, and claim it only with evidence -- typically, by rebuilding under
every held revision (`CL_REV=8168`, `CL_REV=8447`, unset) and showing none of
them matches.

Static libraries have an exact, per-object version of the same evidence: the
`@comp.id` symbol in every object, which `tools/compid.py` reads (see
[`toolchains/COMPILERS.md`](../../toolchains/COMPILERS.md#a-second-exact-oracle-compid)).

## Reading the flags off the image

The `.dsp` files are where the flags start, not where they end: Monolith
changed projects between the source releases and the retail builds, and
the sibling game a project was cloned from is evidence of nothing. Each
switch below leaves a mark in the retail image that can be counted, and
counting it first is cheaper than finding out from a thousand nears. Read
the flags off the image, set them, then measure: the deciding test is
always "compile each way, keep the one with more identical functions and
none lost".

**`/GR`: whose type descriptors are there.** Search the image for `.?AV`
names. If the game's own classes have them, the project was built `/GR`,
whatever the base project says: tron20src's `CShell.dll` has RTTI for
Tron's own client classes (`CClientWeaponDisc`, `CHUDHealthEnergy`, ...)
and `Object.lto` for its server ones, where NOLF2's TO2 Final
configurations, which Tron's projects started from, have none; both got
`/GR` (tron20src, commit 7d946f9). If the only descriptors are the
standard library's (`exception`, `logic_error`, `length_error`,
`out_of_range`, `type_info`), there is no `/GR`: Contract J.A.C.K.'s
engine and launcher (cjacksrc, `progress/COMPILERS.md`). The descriptors
are worth reading for more than the flag -- their base-class records are
the retail class hierarchy, which is how tron20src found that `CScanner`
derives from `PropType` and its plugin from `CPropTypePlugin`, and that
every member had been 0x10 bytes short (commit 0ef3fc3).

**`/GX`: count the `fs:0` frames.** Under `/GX` every function with a
destructible local opens an exception frame (`mov eax, fs:[0]`). Count
them in the image's own code and compare with a `/GX` build of the same
sources. If the only frames left are the STL's own explicit `try` blocks,
there is no `/GX` -- the clinching case is a destructor that destroys its
members with no frame (`CLTGUIWindow::~CLTGUIWindow`). Contract J.A.C.K.'s
`CShell.dll`, `Object.lto` and `ClientFx.fxd` have 136, 205 and 9 frames,
against 855, 1,613 and 79 built `/GX`; dropping it took `CShell.dll` from
3,603 identical functions to 4,555 and `Object.lto` from 5,848 to 7,610
(cjacksrc, `progress/COMPILERS.md`). The flag can differ between variants
of one engine: Primal Hunt's `lithtech.exe` and `server.dll` are `/GX` and
AvP2 1.0.9.6's are not, so it goes on the one variant only (avp2src,
commit 4b3cc77).

**`/GS`: the import, then the call sites.** A `/GS` object makes the image
import `__security_error_handler` and calls `__security_check_cookie`
from its epilogues. The import says *some* object was `/GS`; the call
sites say which. Contract J.A.C.K.'s `CShell.dll` imports it, but its only
two cookie checks (0x10121a92, 0x10121b3a) are in LTGUIMgr's slider, so
`/GS` goes on LTGUIMgr and nothing else; `Object.lto` has none. A lone
check inside the C runtime is the runtime's own and proves nothing
(cjacksrc, `progress/COMPILERS.md`).

**`/Gy`: are uncalled functions still there?** With `/Gy` each function is
its own COMDAT and the link's `/OPT:REF` drops the ones nothing calls;
without it an object's functions are one section and come in together.
An image that keeps functions nothing calls (Contract J.A.C.K.'s
`CD3D_RenderWorld::CastRay`, `MaybeDrawConsole`, ...) was built without
`/Gy`. On VC 7.1 (cl 13.10) that means **`/Ox /GF`**, not `/O2`: `/O2`
implies `/Gy`, and cl 13.10 has no `/Gy-` to take it back. Imports are a
cheap tell too: every image that links Contract J.A.C.K.'s RegMgr imports
`RegDeleteKeyA` and `RegDeleteValueA`, which only `CRegMgr`'s uncalled
`Delete*` members use, so the whole `regmgr.obj` was linked, so it was not
`/Gy`. Switching the engine projects to `/Ox /GF` took `Lithtech.exe`'s
unwritten functions from 39 to 28 and `server.dll`'s from 12 to 9, with no
identical function lost (cjacksrc, `progress/COMPILERS.md`, "The engine's
flags" and "The launcher and the dedicated server").

**Intel or Microsoft.** Intel C/C++ leaves no Rich-header row of its own,
so an icl image shows up as objects without a compiler stamp, and it pads
with distinctive `lea` sequences. Count both before assuming either.
NOLF's `d3d.ren` has 313 such padding sequences; AvP2 1.0.9.6's has 2, and
its Rich header's C++ 8168 ×73 are its own objects with no unstamped row
left over -- it is cl 8168, not icl, as the project had assumed from NOLF.
The correction took it from 10 identical functions to 857 (avp2src,
commit 80034dc). **Do not inherit a compiler from a sibling game**,
however close the source.

**One image, several compilers.** A Rich header can list two compilers'
C++ objects because the image genuinely mixes them. NOLF's `Processor.exe`
is Intel C/C++ 4.0 `/O1` throughout except `PreWorld.cpp`, which is VC6
SP3's cl 8447 `/O1` (unaligned code, `__EH_prolog`, the `/O1` shapes; an
8447 build of it matches 196 functions there). `tools/dsp2mk.py` takes a
per-source compiler override, `CL_<project>__<source>`, for exactly this
(lithtools, `legacy/talon/docs/PLAN.md`, commit d041780). AvP2's
`CShell.dll` is the same story across a service pack: 8168 ×142 and 8966
×114, the 8966 objects being the files rebuilt after Monolith moved to
SP5 (avp2src, `build/build.mk`, `CSHELL_8966`).

**But attribute every Rich row before concluding a mixed build.** Rows
come from statically linked libraries too. Tron 2.0's `Lithtech.exe`
carries 110 C++ objects of VC7's cl 13.00.9178 beside its 292 of cl 8168;
they are the DirectX 9 SDK's `d3dx9.lib`, linked statically as NOLF2's
engine linked `d3dx8.lib`, and `SndDrv.dll`'s single 13.00.9178 object is
`dxguid.lib` -- not a second compiler for the engine (tron20src,
`progress/COMPILERS.md`). Account for the C runtime, MFC, the SDKs and the
import libraries first; only the rows left are the game's.

**Prebuilt libraries may not be what retail linked.** A source release's
`.lib` files can be a later build than the one the shipped images linked.
AvP2 1.0.9.6's game DLLs hold cl 8168 builds of nine library objects
(`ltguieditctrl`, `butemgr`, `GameSpyMgr`, ...) where the release's
prebuilt libraries are all 8966: each matches retail only under 8168
(`CLTGUIEditCtrl::Render` is 383 bytes, retail's, under 8168 and 378 under
8966), and `AVP2Serv.exe`'s 145 "unwritten" functions were ButeMgr,
CryptMgr and StdLith built by 8168. Its engine is cl 9044 (the Processor
Pack's) and links 9044 builds of lith, RezMgr and StdLith, neither the
prebuilt nor the debug ones: `CRezItm::InitRezItm` copies its name with
VC6 `/O2`'s `strcpy` under 9044, where 8966 `/O2` inlines it as `rep movs`.
Compile each library object under every candidate revision, keep the one
with identical functions the others lack, and keep the builds in separate
directories (`Release8168/`, `Release8966/`) so the prebuilt libraries are
still scored against their own 8966 build (avp2src, commits 9d019db,
4b6eefd; `build/build.mk`, "AvP2 1.0.9.6's builds of the game DLLs'
libraries" and "AvP2 1.0.9.6's engine's builds").

**Read the objects' own command lines.** A shipped object records how it
was compiled, and that beats the project file. Primal Hunt's `server.dll`
links the release's debug RezMgr and StdLith, whose objects say
`/MTd /ZI /Od`, not the `/Zi /GZ` the `.dsp`'s Debug configuration says.
Under `/ZI` each assert carries its line relative to its function, so a
debug build pins the source's line layout as well as its code; and the
release's `Rezmgrfull.lib` (`/Z7`, with COFF line numbers) showed where
the code a `REZMGRLITE` build leaves out stood (avp2src, commit 8b90849;
`build/build.mk`, "The debug builds").

## Wine and build traps

Each of these cost real time once. None shows as a compile error; most
look like a codegen or layout difference.

**Import order: Wine's `qsort` is not Microsoft's.** `link.exe` sorts each
DLL's imports with the C runtime's `qsort`, and every key it sorts is
equal. Microsoft's `qsort` first swaps the middle element to the front;
Wine's builtin `msvcrt.dll` keeps the order. So a link under Wine starts
KERNEL32's thunks with `GetCommandLineA` where retail starts with
`EnterCriticalSection`. Where the import table must match, run a copy of
the linker (with the `mspdb60.dll` and `cvtres.exe` it loads) in its own
directory beside a native `msvcrt.dll` (icl-5.0.1 ships one), with
`WINEDLLOVERRIDES=msvcrt=n`. Under Microsoft's msvcrt two links at once
pick the same temporary file (`LNK1104`, `C:\windows\temp\lnk2`), so
serialise them with `flock`, and give the prefix `TEMP` and `TMP` in
`HKCU\Environment`. That made `CRes.dll`, `SRes.dll` and both `ltmsg.dll`
builds identical in code, data and imports (avp2src, commits e5b8a53,
0f0a35d; `build/build.mk`, "Links under Microsoft's msvcrt.dll"). An
incremental link (`Launch.dll`, a debug-toolchain build) needed a
`link.exe` copy patched so Wine allows it (commit c0f04e3).

**VC 7.1 hangs instead of failing.** With Wine's builtin `msvcp71`, VC
7.1's `c1xx` spins forever; the toolchain's `bin/` carries the native
`msvcr71.dll` and `msvcp71.dll`. Even then it spins rather than exits on a
fatal error -- a missing `#include`, `C1020` -- so compiles outside the
tree run under a watchdog (cjacksrc, `docs/PLAN.md`). A hung VC 7.1
compile means a broken source until shown otherwise. VC 7.1 also refuses
default arguments on function-pointer members (`C2383`) that VC6 took, so
LT2-era SDK headers lose them and the callers pass them explicitly
(cjacksrc, `docs/PLAN.md`, the `iltclient.h` change).

**VC6 flags that Wine dislikes, checked harmless.** `/Zm1000` fails about
half the time under Wine; `/Zm200` gives identical objects but for the
time stamp. `/FD` only writes a dependency file that parallel compiles
fight over, and can go. A rare `C1001`/`C1060` under parallel load is
Wine, not the source: retry it, up to three times, and log it (nolf2src,
`docs/SETUP_NOTES.md`, "Departures from Monolith's compile flags").

**`sg docker` breaks the container.** Running `make` under `sg docker`
passes Docker's group id into the container and fails with a misleading
"Value too large" error; run it from a shell where you are in the group
already (nolf2src, `docs/SETUP_NOTES.md`).

**Header edits that rebuild nothing.** When a project names its include
directories through a drive or a macro, dependency scanning can silently
lose them. AvP2's projects name the SDK as `$(LT2_DIR)\sdk\inc`, which the
build spells `s:\LT2\sdk\inc`; `tools/mkdeps.py` looked for that relative
to the compile's directory, found nothing, and dropped it, so no SDK
header was any object's dependency and an edited one rebuilt nothing.
`tools/dsp2mk.py --macro NAME=VALUE` expands such macros and
`--drive X=DIR` maps a drive to a tree directory; `MKDEPS_DRIVES`
(`s=src t=toolchains`) does the same for `mkdeps.py` (tools, commits
e271462, 0d83bf8). Rebuilt properly, Primal Hunt's game DLLs saw a header
slot they had been missing (avp2src, commit 5f7ec8b). After touching a
shared header, check that the objects you expected actually recompiled.

**Case-insensitive lookups need the file to exist.** `dsp2mk.py` spells
each library as the disk does, matching case-insensitively as Windows
would (the release ships `lithtrackmgr.lib`, the project names
`LithTrackMgr.lib`). In a fresh tree -- CI's, a variant's -- the copy is
not there yet, the project's spelling is kept, and make finds no rule for
it. Put the prebuilt libraries in place before generating the project
rules (avp2src, commit f89eb2e; `build/env.sh`, `avp2src_make`).
