# 07 · Naming anonymous functions from vtables

The check-literal trick ([06](06_worked_example_engine.md)) names a function
only if it validates its arguments. Most functions don't, so most of a
stripped engine binary stays `sub_1000xxxx`. This guide is the second naming
source, and it is bigger than the first: **a vtable is a class's method list
in the SDK header's declaration order**, sitting in `.rdata` in plain sight.
One anchored vtable names every method of that interface at once, argument
checks or not.

## The method

1. **Find the vtables.** They are runs of consecutive pointers into `.text`
   in the data sections:

   ```sh
   tools/vtabmap.py out/reference/server.dll --at 0x1001260b \
       --names out/reference/server-functions.csv
   ```

   `--at` takes any address you already know (a matched function, a tagged
   one) and prints the run whose slots contain it. `--names` labels slots
   from the function table's name column (error-tag names and exports, as
   `build/reference.sh` writes it) so the anchors are visible.

2. **Anchor the run against an SDK header.** Count virtuals in the header
   (`src/LT2/sdk/inc/`), in declaration order, starting from the class's
   first virtual — `tools/sdkvtab.py` reads that order off a header for you.
   When the labelled slots land on the right names in the right order, the
   vtable is identified — and every *unlabelled* slot between them is now
   named by whatever the header declares at that position.

3. **Mind where one vtable ends and the next begins.** `vtabmap.py` merges
   back-to-back vtables into one run, because nothing separates them in
   `.rdata`. The seam shows as a discontinuity: the slot sequence stops
   following one header and starts following another. Anchors on both sides
   pin it exactly. `tools/vtabaudit.py` enumerates tables one per row from
   the evidence (the constructors that store each vptr), which is the
   reliable way to split a run.

4. **Reconstruct the newly named slots as usual**
   ([03](03_reading_disassembly.md)): they are ordinary functions that now
   have a signature — the SDK gives parameter types, return type, and often
   a doc comment.

Remember the era caveat from [05](05_exe_and_engine.md): the SDK headers are
NOLF2-era, and vtable order is the thing that drifted. Check each slot's
argument count against its `ret N` before trusting a long stretch of header
order.

## What this found in server.dll

One 407-slot run at `0x1004e24c` is two vtables back to back:

* **`0x1004e24c`, 31 slots — MyServerInterface.** Exactly
  `server_interface.h`'s declaration order, confirmed by `GetClientPing` (a
  matched function) sitting at slot 19 where the header puts it. Twenty
  previously anonymous functions got names from this one vtable:
  AddResources, LoadBinaries, GetFileList, OpenFile, CopyFile, Update,
  InitNetworking, HostGame, and the rest of the interface.

* **`0x1004e2c8`, 376 slots — CLTServer's ILTServer vtable.** The interface
  aggregates everything, and the known blocks confirm the mapping: the
  ILTCSBase message methods at slots 72–101 in header order, the math
  helpers at 127–141, the physics accessors from 197. Runs of `0x1003ea24`
  are a shared not-implemented stub — those slots exist in the header but
  were never filled in, which is information too.

## The demonstration

`iltphysics.h` ends with GetGlobalForce, SetGlobalForce, GetStairHeight,
SetStairHeight. The physics block of CLTServer's vtable had four anonymous
targets after IsWorldObject — `0x1002d6e9`, `0x1002d702`, `0x1002d719`,
`0x1002d727` — tiny functions no literal names and nothing else references.
Read off the header, all four reconstructed byte-identical on the first
compile, and pinned two new facts: `SPhysicsLT::m_StairHeight` lives at +0x08,
and the world's global-force state is an embedded object at +0x668 whose
current value sits at +0x67c. They are in `src/engine/server/commonphysics.cpp`
(`SPhysicsLT::GetGlobalForce` and its neighbours).

They also settled a misattribution. The image has **two** Get/SetGlobalForce
pairs. `iltserver.h` declares them taking `LTVector*` — so that pair
null-checks and forwards through the world's vtable; `iltphysics.h` declares
them taking `LTVector&` — so that pair cannot check and reads the fields
directly. The parameter type in the header dictates the whole shape of the
compiled function, and the vtable says which is which. The pointer pair had
been filed under SPhysicsLT before the vtable was mapped; it is CLTServer's
(`CLTServer::GetGlobalForce` in `src/engine/server/servermessage.cpp`).

## Why this scales

The check literals name a couple of hundred functions. The two vtables above
cover ~400 slots, and every engine interface with an SDK header (ILTServer,
ILTCommon, ILTModel, ILTPhysics, ILTLightAnim, ILTSpriteControl, ILTSoundMgr,
ILTVideoMgr…) has its implementation's vtable somewhere in `.rdata`. Each one
is a batch of named, typed, documented functions — the same thing the
literals give, but denser, and with signatures attached.

Once a target links, `tools/vtabcheck.py` closes the loop the other way: it
compares our linked image's vtables with the shipped ones slot by slot, which
catches a constructor that is byte-identical (the vptr store is a masked
relocation) while installing a stand-in table that is too short.

## Where a table ends: what vtabcheck learned

`vtabcheck.py --targets` is a gate of `make progress` now
([14](14_progress.md#what-a-run-rests-on)), so a table it reads too long
fails the build. Nothing in `.rdata` marks a vtable's end, and each of
these read one on into whatever followed it:

* **An MFC message map.** MFC puts a class's `AFX_MSGMAP` right after its
  vtable, and the map's first word points at `GetThisMessageMap`
  (`_GetBaseMessageMap` before MFC 7): code, so it reads as one more slot.
  Contract J.A.C.K.'s `CMoveDialog` read as 89 slots against our 88, all
  88 agreeing (cjacksrc 6937926). Past our table's end, such a pointer
  now ends the shipped one too (tools 568aedf, in `vtabcheck.py`'s slot
  comparison). The same macro is a landmark in code: the message-map
  accessor `BEGIN_MESSAGE_MAP` emits sits at the macro's place in its
  `.cpp`, so it says which module, and where in it, the functions beside
  it belong to. DEdit's `InitTracker` at 0x452bb7, just after
  `CRegionView`'s `GetMessageMap` at 0x452bb1, put it back in
  `RegionView.cpp` from a file of its own (lithtools 7a5d6ab).
* **Folded template tables back to back.** DEdit's `CMoArray<T*>`
  instantiations have their code folded into one, so three 12-slot
  vtables (0x4da860, 0x4da890, 0x4da8c0) are identical with no symbol or
  reference between them, and the check read one 36-slot table. Ours
  matches the first 12; it is recorded in `vtab-known.txt` as a read-on
  (lithtools d0118e2).
* **No reference range.** A shipped table is also cut where the image
  refers into it, which needs the range of tables to look in. Only NOLF's
  engine images have a `vtabaudit` table; elsewhere the range was
  0..0x10000, nothing cut, and an abstract table with no placed neighbour
  ran on into the next (Object.lto's `CAIPoodleState` into
  `CAIPoodleStateDischarge`). A target with no audited tables now takes
  the shipped image's `.rdata` as its range (tools e3a10a3).
* **A statically linked `_purecall`.** Abstract slots hold `_purecall`,
  which the check finds as the `jmp [IAT]` thunk of `MSVCRT!_purecall`.
  An image that links the CRT statically has no such thunk, so the last
  slot of every abstract table was unverifiable. Give the target its
  address as `purecall` in `progress/targets.py` (nolfsrc f91c788:
  `CShell.dll` and `Object.lto`, as `lithtech.exe` already had it).

## When placement votes: ties and twins

The scorer places the functions of a class by vtable slot: our table and
the shipped one vote on which retail row each of our virtuals is. Votes go
wrong in recognisable ways.

* **A tie places nothing.** Sibling classes that inherit a base's virtuals
  unchanged have the same functions in those slots, so once the base's
  virtuals are identical every sibling's table gets the same votes, and
  the first table won: Primal Hunt's `CProxGrenade` virtuals landed on
  `CPredDisk`'s retail rows. A table another table ties is now left
  unplaced (`progress.py`, tools c83182e).

avp2src builds its engines' full interface vtables from the scoreboard's
placements (its `build/vtables/mkvtables.py`, linked through
`tools/mkvtabobj.py`), and booting them found three more rules for any
table built or checked that way:

* **Twins with the same masked bytes.** `ILTServer`'s slot 46,
  `CreateString`, held `LAlloc::Alloc` -- the same bytes once relocations
  are masked (avp2src 27eb79d); `ILTModel`'s `GetNode` and `GetSocket`
  were placed each at the other's address (baebb5b). Tell twins apart by
  what their operands reach: a candidate whose call reaches a different
  function of ours than retail's call does is rejected, and twins are
  compared outside the union of both masks.
* **A placement its own calls refute gets no vote.** The swapped
  `GetNode`/`GetSocket` voted for the wrong string addresses in turn
  (baebb5b).
* **A class's own function beats a base stub.** `CObjWorldModel`'s table
  kept `CObjBase`'s inherited empty virtuals in eight slots -- `WantsTree`
  (27eb79d), and slot 7, `OnFoundInBox`, which the world tree's frustum
  walk calls on every world model (baebb5b) -- and the world rendered
  black. A class's own placed function, near-paired or not, now wins
  over its base's stub, the hierarchy read from the sources.

Every one of these looked fine to the scorer; they were found by running
the game ([05](05_exe_and_engine.md#running-the-thing--nears-have-to-execute)).

## Classes with RTTI

A game built `/GR` carries RTTI for every polymorphic class in both images,
and that pairs tables without any header: each vtable is preceded by a
pointer to its complete object locator, which names the type descriptor
(`.?AV<class>@@`) and, through the class hierarchy descriptor, the bases
and their offsets. tron20src pairs its game's vtables with retail's this
way and checks hand-edited headers with a probe -- a member pointer to each
virtual, whose compiled vcall thunk names the slot VC6 gives it -- which is
how it found that VC6 lays out a name's virtual overloads in the
**reverse** of their declaration order (tron20src b4717cd, 4e170d2). Those
helpers are tron20src-local scratch scripts (its gitignored `out/work/`),
not tools here; [15](15_sibling_games.md) covers the method in depth.
