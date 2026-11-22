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

`vtabcheck.py --targets` is now a gate of `make progress`
([14](14_progress.md#what-a-run-rests-on)). Thus, if the check reads a
table as too long, the build fails. No marker in `.rdata` shows the end of
a vtable. In each of these cases, the check read past the end of a table
into the data after it:

* **An MFC message map.** MFC puts the `AFX_MSGMAP` of a class immediately
  after its vtable. The first word of the map points at `GetThisMessageMap`
  (`_GetBaseMessageMap` before MFC 7). This is code, so the check reads it
  as one more slot. In Contract J.A.C.K., the shipped `CMoveDialog` table
  read as 89 slots and our table had 88 slots. All 88 slots agreed
  (cjacksrc 6937926). Now, if such a pointer is past the end of our table,
  it also ends the shipped table (tools 568aedf, in the slot comparison of
  `vtabcheck.py`).

  The same macro is also a landmark in code. `BEGIN_MESSAGE_MAP` emits a
  message-map accessor at the position of the macro in its `.cpp` file.
  Thus the accessor shows the module of the functions near it, and their
  position in that module. In DEdit, `InitTracker` at 0x452bb7 is
  immediately after the `GetMessageMap` of `CRegionView` at 0x452bb1. This
  evidence moved `InitTracker` from its own file back into `RegionView.cpp`
  (lithtools 7a5d6ab).
* **Folded template tables in sequence.** In DEdit, the compiler folded the
  code of the `CMoArray<T*>` instantiations into one set of functions. Thus
  three 12-slot vtables (0x4da860, 0x4da890, 0x4da8c0) are identical, and
  no symbol or reference separates them. The check read them as one
  36-slot table. Our table matches the first 12 slots. `vtab-known.txt`
  records the table as a read-on (lithtools d0118e2).
* **No reference range.** The check also cuts a shipped table at an
  address where the image refers into the table. For this, the check must
  know the range of tables to examine. Without a range, the check cuts
  nothing, and an abstract table with no placed neighbour continues into
  the next table. Example: in Object.lto, `CAIPoodleState` continued into
  `CAIPoodleStateDischarge`. Now, if a target has no audited tables, the
  check uses the `.rdata` of the shipped image as its range (tools
  e3a10a3).
* **A statically linked `_purecall`.** Abstract slots hold `_purecall`. The
  check finds it as the `jmp [IAT]` thunk of `MSVCRT!_purecall`. An image
  that links the CRT statically has no such thunk. Thus the check could not
  verify the last slot of each abstract table. For such a target, give the
  address as `purecall` in `progress/targets.py` (example: nolfsrc
  f91c788).

## When placement votes: ties and twins

The scorer places the functions of a class by vtable slot. Our table and
the shipped table vote on which retail row each of our virtuals is. These
votes can go wrong in a small number of known ways.

* **A tie places nothing.** Some sibling classes inherit the virtuals of a
  base without change. These classes have the same functions in those
  slots. When the virtuals of the base are identical, the table of each
  sibling gets the same votes. Before the fix, the first table won. In
  Primal Hunt, the virtuals of `CProxGrenade` went to the retail rows of
  `CPredDisk`. Now the scorer does not place a table that ties with another
  table (`progress.py`, tools c83182e).

You can also build vtables from the placements of the scorer, for
example to link the interface tables of an engine that is not complete
(`tools/mkvtabobj.py` links such tables; avp2src builds its engine
interfaces this way). Then a wrong placement is a wrong call at run time.
Three more rules apply to all tables that are built or checked this way:

* **Twins with the same masked bytes.** Two functions can have the same
  bytes when the relocations are masked. To tell twins apart, examine what
  their operands reach. If a call in a candidate reaches a different
  function of ours than the call in retail, the scorer rejects the
  candidate. The scorer also compares twins outside the union of the two
  masks. Example: in `ILTServer`, slot 46 (`CreateString`) held
  `LAlloc::Alloc` (avp2src 27eb79d). In `ILTModel`, `GetNode` and
  `GetSocket` each went to the address of the other (baebb5b).
* **A placement that its own calls refute gets no vote.** Example: the
  swapped `GetNode` and `GetSocket` then voted for the wrong string
  addresses (baebb5b).
* **A function of the class wins over a stub of the base.** A placed
  function of the class itself wins over the stub of its base, near-paired
  or not. The scorer reads the hierarchy from the sources. Example: the
  table of `CObjWorldModel` kept the empty inherited virtuals of `CObjBase`
  in eight slots, `WantsTree` (27eb79d) and `OnFoundInBox` (baebb5b)
  among them. The world tree never got to the renderer, and the world
  rendered black.

The scorer showed no problem with any of these cases. We found them when we
ran the game
([05](05_exe_and_engine.md#running-the-thing--nears-have-to-execute)).

## Classes with RTTI

If a game was built with `/GR`, both images carry RTTI for each polymorphic
class. RTTI pairs tables without a header. A pointer to the complete object
locator comes immediately before each vtable. The locator names the type
descriptor (`.?AV<class>@@`). Through the class hierarchy descriptor, the
locator also names the bases and their offsets.

Pair each of our vtables with the retail vtable that has the same type
descriptor. To check a hand-edited header, use a probe. The probe is a
member pointer to each virtual. The compiled vcall thunk of that pointer
names the slot that the compiler gives the virtual. Compare these slots
with the retail table.

Example: with this probe, tron20src found that VC6 puts the virtual
overloads of a name in the **reverse** of their declaration order
(tron20src b4717cd, 4e170d2). [15](15_related_source.md) gives more detail
about the method.
