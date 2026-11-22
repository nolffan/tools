# 17 · Decompiling tools and GUI applications

Some targets are not game engines. They are desktop applications: an
editor, a level tool, a packer, a launcher. The loop is the same
([02](02_the_loop.md), [05](05_exe_and_engine.md)). The standard is also
the same: byte identity, function by function. These things are
different:

- where the source comes from;
- the application framework that the image links statically;
- the compiler-generated code and the framework tables in the image;
- the resources (dialogs, menus, icons);
- how you show that the tool *behaves* as the shipped tool does.

The examples come from lithtools. This repository decompiles the
LithTech editors and compilers (DEdit, ModelEdit, the world Processors)
and format readers for the LithTech games.

## 1. No source for this version: start from related source

Often no source of the shipped version is available. But a related
version can be available:

- a later descendant (a newer release of the same tool);
- an earlier ancestor (an older SDK);
- a sibling (a tool that shares libraries with your target).

Start from the nearest related source. Then change it back, file by
file, to the shipped version. Use this procedure:

1. **Link the related source first.** Set it up as a project in the
   **module order of the image** ([16](16_tu_mapping.md)). Make it link
   with no unresolved symbols. Measure the score before you change a
   file.
2. **Isolate the features that the shipped version does not have.** Put
   them in a **link group of their own**. Other code can still call
   them, so the project continues to link.
3. **Write a stand-in for code that nobody has written yet.** Mark each
   stand-in with a tag in the source. List each stand-in in the map
   until you replace it. The project links at all times, so you can
   measure the score at all times.
4. **Walk each file back on evidence from the image.** Each change must
   give the address that shows why it is correct.
5. **Remove the stand-ins when they lose their last callers.**
6. **Remove the link group when it is empty**, and link again.

Example: lithtools `docs/PLAN.md` §3: DEdit started from a 2006
descendant. It linked at 2,499 identical functions before we changed one
file. Lithtools 714af93 took `DEdit.cpp` back. Its evidence was the size
of an options object at 0x41653e and three callers of
`CRegionDoc::SaveRegion`.

**Commit each file when you take it. Commit each change as its own
commit.** Then the diff of a file against its original is the record of
the shipped version. You can read this record change by change.

**Use the module order as evidence.** The position of a file in the link
answers questions that strings cannot answer. If the modules follow an
alphabetical order of file name, an unknown module gets its name from
its neighbours.

Example: lithtools 7a5d6ab: an unknown DEdit module was between
`viewrender` and `WorldInfoDlg`. Its callers showed it was the world
tree. Its position gave the file name.

**Divide parallel work by image range.** Give each part the headers of
its modules, so no two agents edit the same header. The general rules
are in [13](13_cluster_recon.md).

**Use related source as a guide to shapes, not as a source of matches.**
The same source with a different compiler or different flags gives
different bytes. Trust the related source for structure. Verify its
bytes again.

Example: lithtools `progress/DEdit_map.md`: the world code of the
Processor is also in DEdit. The Processor objects (`/O2`) do not match
the DEdit objects (`/O1`).

## 2. A static framework is not your code

Many applications link an application framework statically. Examples
are MFC, OWL, VCL and wxWidgets. The framework functions are real and
are in the image. They **will match** if your objects instantiate the
same header code. This does not make them your functions.

1. **Find the limits of the application code from the link map of the
   image.** Do not stop at the first framework function. Libraries can
   start again after the framework, so the application code can be in
   more than one range.
2. **Remove framework functions from the score.** Record each removal
   with its reason.
3. **Look for framework header functions inside your range.** Your
   objects can instantiate an inline function of the framework. If it is
   byte-identical in the framework library, it is not your code.

Example: lithtools 8f752f3 removed 157 functions from the score. 150
were MFC library functions after the application code. 7 were short
bodies that matched the inside of a longer function. Lithtools 9ca3cdf
removed `CStringArray::GetAt`, which is identical in `nafxcw.lib`.

## 3. Funclets look like separate functions

A compiler can put code for a function *after* its body. Examples are
`catch` blocks and unwind handlers (funclets). Nothing calls this code
directly, so the enumeration makes it a row of its own.

Recognise a funclet by these signs:

- no caller references the row;
- it is immediately after another function;
- with VC6, a `catch` block ends with `mov eax,<continuation>; ret`, and
  the continuation points back into the row above.

Merge the row into its function. Do not write it as a function of its
own. Remove it from the function count. The other extent defects of
[13](13_cluster_recon.md) also apply: rows that start in the middle of
an instruction, and rows that are only branch targets.

Example: lithtools 9ca3cdf removed 117 interior rows of DEdit. It also
added 13 function starts that the enumeration did not find.

## 4. Framework dispatch tables

Frameworks often keep a dispatch table for each class. The table is
next to the vtable. MFC is the example: each `CCmdTarget` has a message
map in `.rdata`, and the `GetMessageMap` virtual returns it.

A dispatch table gives three types of information:

1. **It lists the handlers of the class.** For a framework class, the
   table is like the vtable of an interface ([07](07_vtables.md)). Read
   it before you write the class. It shows which members the class has
   and which it does not have.
2. **It ends a vtable.** The data after the last vtable slot is often
   the table. Use it to find where the vtable stops.
3. **It marks a module boundary.** The table and its accessor are in the
   object of the class. The next function often starts the next part of
   the file, or the next file.

Example: lithtools 7a5d6ab: the 2001 message map of `RegionView` did not
name `OnSelectionScale`, so we removed that handler. Lithtools b336b87
built the ModelEdit main dialog again against its 90-entry message map.

## 5. Resources: decompile, prove the round trip, score apart

Dialogs, menus, accelerators, string tables and icons are part of the
shipped tool. Do not type them again. Decompile them to a resource
script.

1. Decompile the resource section to a `.rc` file and binary files.
   Use the identifier names from `resource.h` where you have them.
2. Compile the `.rc` file into your build.
3. Compare the payload of each resource, by type, name and language.
   Ignore the layout of the section.
4. Score resources as **their own targets**, outside the code total.

The `tools/rsrc2rc.py` script does step 1. The `tools/rsrcdiff.py`
script does step 3.

NOTE: The proof is on the payloads. A `.rc` file can be correct but
difficult to read. Improve the readability later.

CAUTION: Do not add resource bytes to the code percentage. A resource is
not a function. Large bitmaps and dialogs can hide the code score.

Example: lithtools 8f752f3 (the `:rsrc` targets): all 224 resources of
DEdit are byte-identical. They are 289,504 bytes, which is outside the
code score.

## 6. One image, several compilers

Do not think that one image has only one compiler. The application, its
libraries and one exceptional file can each come from a different
compiler. Look for this evidence:

- Rich header entries, and objects that have no `@comp.id`;
- frame setup, padding and section names that one compiler does not
  make;
- files whose code shape does not agree with their neighbours.

Give each source file its own compiler where necessary. The
`tools/dsp2mk.py` script accepts `CL_<project>__<source base name>`,
which overrides `CL_<project>`. Record the known behaviour of each
unusual compiler in the map.

Example: lithtools `docs/PLAN.md` §2: the NOLF Processor is Intel C/C++
4.0 `/O1`. One file is VC6 SP3 `/O1`. The libraries, MFC and CRT are VC6
SP3.

## 7. Behaviour tests

Byte scoring proves the code. A behaviour test runs the shipped tool and
your tool on the same inputs and compares the output. It finds errors
that byte scoring does not find, for example in near functions.

Example: lithtools `docs/PLAN.md` §2: two near functions of a Processor
gave a different result: an edge normal and a rounding. The comparison
of the output worlds found them.

**Before you trust a comparison, run it retail against retail.** A tool
can write uninitialised data. That data can depend on the heap, and the
heap can depend on the length of the executable's path.

Example: lithtools 59a7aac: two runs of the shipped Processor, from
paths of different lengths, gave 2,637 different colour bytes. This
control also found an old comparison script that could never fail.

A behaviour test must do these four things:

1. **State exactly what it normalises.** Compare all other bytes raw.
2. **Say this in its verdict.** Write "equal but for N bytes of field
   X", not "identical".
3. **Have a control.** Two shipped runs from different paths must pass
   the same comparison.
4. **Keep the conditions of the two sides equal:**
   - the same inputs;
   - new working directories (a tool can read settings from its working
     directory);
   - paths of the same length.

## 8. File formats

When a tool reads or writes game files, the format limits come from the
binaries, not from headers. Read two things:

1. **The version check.** Find the check that prints the error. Read
   what it really tests: an exact value, a minimum or a range.
2. **The writer.** Find the constant that the writer writes.

A file can pass a check and still be read incorrectly. A minimum check
accepts newer versions that changed the layout.

Example: lithtools `FORMATS.md`, "The newer engine": two LithTech
engines check only a model version of at least 23. A later packer writes
25. Version 24 changed a structure, so these engines read v25 models
incorrectly.

**Verify each reader against every shipped file.** A unit test on one
sample proves only that the reader reads that sample. Write a verify
program for each format. Let it read every file of that type in the
game archives. If you cannot commit the archives, keep these programs
outside the unit tests and run them locally.

Make a census of the shipped versions of each format. It shows the
versions that a reader must accept.

Example: lithtools `FORMATS.md`, "Shipped assets": a census found one
v11 and two v9 models among 692 v12 models in NOLF.

## 9. Retail bugs in tools

Keep the bugs of the shipped tool in the reconstruction. Document each
bug in `RETAIL_BUGS.md` with these items:

- the address where you read the bug from the retail bytes;
- how well your function matches at that address.

Games fix their bugs in a modern build of the same source
([18](18_modern_builds.md)). Tools do not need a modern variant. A later
reimplementation applies the fixes, and the bug list is its start point.

CAUTION: Do not fix a tool bug in the reconstruction. The fix changes
the bytes, and the reconstruction then cannot prove the retail
behaviour.

See [14](14_progress.md) for how to keep the score, and
[01](01_environment.md) for the toolchains.
