# 01 · The build environment

To reproduce Monolith's bytes you must compile with the compilers they used:
**Microsoft Visual C++ 6.0** -- several revisions of it, because Monolith did
not build every binary with the same one -- and, for the renderer `d3d.ren`,
**Intel C/C++ 4.0**. All of them are in the `ext/toolchains/` submodule
(`git submodule update --init`), assembled from public copies of the
original media (see [`toolchains/README.md`](../../toolchains/README.md)):

| directory | compiler | used for |
|---|---|---|
| `toolchains/msvc-6.00-9782/` | cl 12.00.8804 driver, back end 12.00.9782 (VC6 SP6) | the default; game DLLs, `NOLF.exe`, `ltmsg.dll`, `sres.dll`; and the linker, librarian and resource compiler for everything |
| `toolchains/msvc-6.00-8447/` | back end 12.00.8447 | `server.dll`, `lithtech.exe`, the lithshared libraries |
| `toolchains/msvc-6.00-8168/` | back end 12.00.8168 | the headers and libraries `icl` builds against; `CL_REV=8168` experiments |
| `toolchains/icl-4.0/` | Intel C/C++ 4.0 | `d3d.ren` |

`tools/richhdr.py` reads which revision built each retail image out of the
image itself; [`progress/COMPILERS.md`](../../../progress/COMPILERS.md) has the
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
  ([`progress/COMPILERS.md`](../../../progress/COMPILERS.md)); the build scripts
  pin it per target.
- **Same optimisation and runtime flags** -- per the `.dsp` files for the
  libraries and game DLLs; measured, per file, for the engine.
- **Same headers** -- the LT2-era headers in `src/LT2/`, which the include
  paths put first. Watch for local `.h` shadows that quote-include and
  override them.
- **Same source constructs** -- everything else is
  [03-reading-disassembly](03_reading_disassembly.md).

**The same build twice.** VC6 gives each anonymous namespace the name
`?%<source as spelled><number>`. The number has 8 to 10 digits. The
compiler makes a new number on each compile. Thus, if you compile the same
file two times, you get two different names. The name is part of each
symbol that the namespace declares, so its length changes where the linker
puts code and data.

In avp2src, WONAPI has three anonymous namespaces (`QueueSocket.cpp`,
`CDKey.cpp`, `CRC.cpp`). From one clean build to the next, they changed
whether six functions of `ServerDir.dll` were byte-identical. A scored
build must be reproducible. Thus the library build runs `tools/anonns.py`
on those objects. The script changes each number in the string table, and
in the RTTI names that contain it, to a fixed number. It does not change
code or data.

The scorer pairs a library member in an anonymous namespace by its name
without the `?%<path><digits>@` component. This component also contains
the path on the build machine (tools, commit 180e91e).

NOTE: If a function changes between identical and near when you rebuild
unchanged source, look for `?%` in the symbols of its object first.

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
[`progress/COMPILERS.md`](../../../progress/COMPILERS.md#a-second-exact-oracle-compid)).

## Reading the flags off the image

The flags start in the `.dsp` files, but the `.dsp` files do not give the
final flags. Monolith changed the projects between the source releases and
the retail builds. The sibling game that a project came from is not
evidence for its flags. Each switch below leaves a mark in the retail
image, and you can count that mark. It is faster to count the mark first
than to find the flag later from a thousand nears.

Use this procedure:

1. Read the flags from the image.
2. Set the flags.
3. Measure the result.

The deciding test is always the same. Compile each way. Keep the build
that has more identical functions and that loses no identical function.

**`/GR`: whose type descriptors are there.** Search the image for `.?AV`
names. If the classes of the game have these names, the project used
`/GR`. This is true also when the base project does not use `/GR`. For
example, tron20src's `CShell.dll` has RTTI for Tron's own client classes
(`CClientWeaponDisc`, `CHUDHealthEnergy`, ...). Its `Object.lto` has RTTI
for Tron's server classes. Tron's projects started from the TO2 Final
configurations of NOLF2, and these have no RTTI. Both Tron images got
`/GR` (tron20src, commit 7d946f9).

If the only descriptors are those of the standard library (`exception`,
`logic_error`, `length_error`, `out_of_range`, `type_info`), the project
did not use `/GR`. Contract J.A.C.K.'s engine and launcher are examples
(cjacksrc, `progress/COMPILERS.md`).

The descriptors give more than the flag. Their base-class records show
the retail class hierarchy. From these records, tron20src found that
`CScanner` derives from `PropType`. It also found that the plugin of
`CScanner` derives from `CPropTypePlugin`. Before this change, the offset
of each member was 0x10 bytes too small (commit 0ef3fc3).

**`/GX`: count the `fs:0` frames.** Under `/GX`, each function with a
destructible local opens an exception frame (`mov eax, fs:[0]`). Count
these frames in the code of the image. Compare the count with a `/GX`
build of the same sources. If the only frames are the explicit `try`
blocks of the STL, the project did not use `/GX`. The best proof is a
destructor that destroys its members without a frame
(`CLTGUIWindow::~CLTGUIWindow`).

Contract J.A.C.K.'s `CShell.dll`, `Object.lto` and `ClientFx.fxd` have
136, 205 and 9 frames. A `/GX` build of each has 855, 1,613 and 79 frames.
Without `/GX`, `CShell.dll` went from 3,603 identical functions to 4,555.
`Object.lto` went from 5,848 to 7,610 (cjacksrc, `progress/COMPILERS.md`).

The flag can be different between variants of one engine. Primal Hunt's
`lithtech.exe` and `server.dll` use `/GX`, but those of AvP2 1.0.9.6 do
not. Thus `/GX` goes on the Primal Hunt variant only (avp2src, commit
4b3cc77).

**`/GS`: the import, then the call sites.** A `/GS` object makes the image
import `__security_error_handler`. Its epilogues call
`__security_check_cookie`. The import shows that *some* object used `/GS`.
The call sites show which objects used it. For example, Contract
J.A.C.K.'s `CShell.dll` has the import. Its only two cookie checks
(0x10121a92, 0x10121b3a) are in the slider of LTGUIMgr. Thus `/GS` goes on
LTGUIMgr and on no other library. `Object.lto` has no cookie checks.

NOTE: A single check in the C runtime belongs to the runtime. It is not
evidence for `/GS` (cjacksrc, `progress/COMPILERS.md`).

**`/Gy`: are uncalled functions still there?** With `/Gy`, each function
is its own COMDAT, and the `/OPT:REF` link option removes the functions
that no code calls. Without `/Gy`, the functions of an object are in one
section, and the linker includes all of them together. Thus, if an image
keeps functions that no code calls, the build did not use `/Gy`. Contract
J.A.C.K.'s `CD3D_RenderWorld::CastRay` and `MaybeDrawConsole` are
examples.

On VC 7.1 (cl 13.10), a build without `/Gy` uses **`/Ox /GF`**, not
`/O2`. The reason is that `/O2` includes `/Gy`, and cl 13.10 has no `/Gy-`
option to remove it.

The imports are also a fast sign. Each image that links Contract
J.A.C.K.'s RegMgr imports `RegDeleteKeyA` and `RegDeleteValueA`. Only the
uncalled `Delete*` members of `CRegMgr` use these functions. Thus the
linker included all of `regmgr.obj`, and the build did not use `/Gy`.

We changed the engine projects to `/Ox /GF`. No identical function was
lost, and the number of unwritten functions went down:

- `Lithtech.exe`: from 39 to 28.
- `server.dll`: from 12 to 9.

The source is cjacksrc, `progress/COMPILERS.md`, "The engine's flags" and
"The launcher and the dedicated server".

**Intel or Microsoft.** Intel C/C++ does not put a row of its own in the
Rich header. Thus an icl image shows objects without a compiler stamp.
Also, icl puts distinctive `lea` sequences in the padding. Count both
signs before you decide which compiler built the image. NOLF's `d3d.ren`
has 313 of these padding sequences. AvP2 1.0.9.6's `d3d.ren` has 2.

The Rich header of AvP2 1.0.9.6's `d3d.ren` has C++ 8168 ×73 for its own
objects, and no row without a stamp remains. Thus the compiler is cl 8168,
not icl. The project assumed icl because NOLF uses icl. After the
correction, the count went from 10 identical functions to 857 (avp2src,
commit 80034dc).

CAUTION: **Do not inherit a compiler from a sibling game**, also when the
source is very similar.

**One image, several compilers.** A Rich header can list the C++ objects
of two compilers, because the image really contains both. NOLF's
`Processor.exe` uses Intel C/C++ 4.0 `/O1` for all files except
`PreWorld.cpp`. That file uses cl 8447 `/O1` of VC6 SP3. The signs are
unaligned code, `__EH_prolog` and the `/O1` shapes. An 8447 build of the
file matches 196 functions there.

`tools/dsp2mk.py` accepts a per-source compiler override,
`CL_<project>__<source>`, for this case (lithtools,
`legacy/talon/docs/PLAN.md`, commit d041780).

AvP2's `CShell.dll` shows the same thing across a service pack. Its Rich
header has 8168 ×142 and 8966 ×114. The 8966 objects are the files that
Monolith rebuilt after it moved to SP5 (avp2src, `build/build.mk`,
`CSHELL_8966`).

**But attribute every Rich row before concluding a mixed build.** Rows
also come from statically linked libraries. Tron 2.0's `Lithtech.exe`
has 110 C++ objects of VC7's cl 13.00.9178 and 292 of cl 8168. The 9178
objects are the static `d3dx9.lib` of the DirectX 9 SDK. NOLF2's engine
linked `d3dx8.lib` in the same way. The single 13.00.9178 object of
`SndDrv.dll` is `dxguid.lib`. These rows do not show a second compiler
for the engine (tron20src, `progress/COMPILERS.md`).

Do these steps:

1. Find the rows of the C runtime, MFC, the SDKs and the import libraries.
2. Use only the remaining rows as the rows of the game.

**Prebuilt libraries may not be what retail linked.** The `.lib` files of
a source release can be a later build than the build that the shipped
images linked. AvP2 1.0.9.6's game DLLs contain cl 8168 builds of nine
library objects (`ltguieditctrl`, `butemgr`, `GameSpyMgr`, ...). The
prebuilt libraries of the release are all 8966. Each of these objects
matches retail only under 8168. For example, `CLTGUIEditCtrl::Render` is
383 bytes under 8168, as in retail, and 378 bytes under 8966.

Also, `AVP2Serv.exe` had 145 "unwritten" functions. They were ButeMgr,
CryptMgr and StdLith, built by 8168.

The AvP2 engine is cl 9044, from the Processor Pack. It links 9044 builds
of lith, RezMgr and StdLith. These are not the prebuilt libraries and not
the debug libraries. For example, under 9044, `CRezItm::InitRezItm`
copies its name with the `strcpy` of VC6 `/O2`. Under 8966 `/O2`, the
compiler inlines that copy as `rep movs`.

Use this procedure for the libraries:

1. Compile each library object under each candidate revision.
2. Keep the revision that gives identical functions that the other
   revisions do not give.
3. Keep the builds in separate directories (`Release8168/`,
   `Release8966/`). Then the scorer can still compare the prebuilt
   libraries with their own 8966 build.

The sources are avp2src, commits 9d019db and 4b6eefd, and
`build/build.mk`, "AvP2 1.0.9.6's builds of the game DLLs' libraries" and
"AvP2 1.0.9.6's engine's builds".

**Read the objects' own command lines.** A shipped object records how it
was compiled. This record is better evidence than the project file. Primal
Hunt's `server.dll` links the debug RezMgr and StdLith of the release.
Their objects show `/MTd /ZI /Od`. The Debug configuration of the `.dsp`
shows `/Zi /GZ`, which is not correct.

Under `/ZI`, each assert contains its line number relative to its
function. Thus a debug build fixes the line layout of the source, and
also its code. The release's `Rezmgrfull.lib` (`/Z7`, with COFF line
numbers) showed the location of the code that a `REZMGRLITE` build does
not include (avp2src, commit 8b90849; `build/build.mk`, "The debug
builds").

## Wine and build traps

Each of these traps caused a large loss of time in the past. None of them
shows as a compile error. Most of them look like a difference in codegen
or layout.

**Import order: Wine's `qsort` is not Microsoft's.** `link.exe` sorts the
imports of each DLL with the `qsort` of the C runtime, and all the keys
that it sorts are equal. Microsoft's `qsort` first moves the middle
element to the front. The builtin `msvcrt.dll` of Wine keeps the order.
Thus, under Wine, the KERNEL32 thunks of a link start with
`GetCommandLineA`. In retail, they start with `EnterCriticalSection`.

If the import table must match, do these steps:

1. Copy the linker to its own directory. Include the `mspdb60.dll` and
   `cvtres.exe` that it loads.
2. Put a native `msvcrt.dll` in the same directory. icl-5.0.1 has one.
3. Run the linker with `WINEDLLOVERRIDES=msvcrt=n`.
4. Run only one link at a time with `flock`. Under Microsoft's msvcrt,
   two links at the same time use the same temporary file (`LNK1104`,
   `C:\windows\temp\lnk2`).
5. Set `TEMP` and `TMP` for the prefix in `HKCU\Environment`.

With these steps, `CRes.dll`, `SRes.dll` and the two `ltmsg.dll` builds
became identical in code, data and imports (avp2src, commits e5b8a53 and
0f0a35d; `build/build.mk`, "Links under Microsoft's msvcrt.dll"). An
incremental link (`Launch.dll`, a build with the debug toolchain) needed a
patched copy of `link.exe` that Wine accepts (commit c0f04e3).

**VC 7.1 hangs instead of failing.** With the builtin `msvcp71` of Wine,
the `c1xx` of VC 7.1 does not stop. Thus the `bin/` directory of the
toolchain contains the native `msvcr71.dll` and `msvcp71.dll`. But also
with these DLLs, a fatal error makes the compiler hang, and it does not
exit. Examples are a missing `#include` and `C1020`. Thus compiles outside
the tree run under a watchdog (cjacksrc, `docs/PLAN.md`).

NOTE: If a VC 7.1 compile hangs, think first that the source is broken.

VC 7.1 also does not accept default arguments on function-pointer members
(`C2383`). VC6 accepted them. Thus the LT2-era SDK headers do not have
these default arguments, and the callers give the arguments explicitly
(cjacksrc, `docs/PLAN.md`, the `iltclient.h` change).

**VC6 flags that Wine dislikes, checked harmless.** We examined these
flags. The changes below have no effect on the objects:

- `/Zm1000` fails approximately half of the time under Wine. `/Zm200`
  gives identical objects, except for the time stamp.
- `/FD` only writes a dependency file. Parallel compiles conflict on this
  file. You can remove `/FD`.
- A rare `C1001` or `C1060` under parallel load comes from Wine, not from
  the source. Try the compile again, a maximum of three times, and record
  the error in the log.

The source is nolf2src, `docs/SETUP_NOTES.md`, "Departures from
Monolith's compile flags".

**`sg docker` breaks the container.** If you run `make` under
`sg docker`, Docker's group id goes into the container. The build then
fails with an incorrect "Value too large" error. Run `make` from a shell
that already has the group (nolf2src, `docs/SETUP_NOTES.md`).

**Header edits that rebuild nothing.** If a project names its include
directories through a drive or a macro, the dependency scan can lose them
without a warning. AvP2's projects name the SDK as `$(LT2_DIR)\sdk\inc`,
and the build changes this to `s:\LT2\sdk\inc`. `tools/mkdeps.py` looked
for that path relative to the directory of the compile. It did not find
the path, and it removed it. Thus no SDK header was a dependency of an
object, and a changed SDK header rebuilt nothing.

The fix has these parts (tools, commits e271462 and 0d83bf8):

- `tools/dsp2mk.py --macro NAME=VALUE` expands such macros.
- `tools/dsp2mk.py --drive X=DIR` maps a drive to a directory of the tree.
- `MKDEPS_DRIVES` (`s=src t=toolchains`) does the same for `mkdeps.py`.

After a correct rebuild, Primal Hunt's game DLLs got a header slot that
they did not have before (avp2src, commit 5f7ec8b). After you change a
shared header, make sure that the expected objects compiled again.

**Case-insensitive lookups need the file to exist.** `dsp2mk.py` spells
each library as the disk spells it. It compares names without case, as
Windows does. For example, the release has `lithtrackmgr.lib`, and the
project names `LithTrackMgr.lib`. In a new tree, for example in CI or for
a variant, the copy is not there yet. Then `dsp2mk.py` keeps the spelling
of the project, and make finds no rule for it. Put the prebuilt libraries
in position before you generate the project rules (avp2src, commit
f89eb2e; `build/env.sh`, `avp2src_make`).
