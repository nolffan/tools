# 22 · The permuter

`permuter.py` tries many equivalent forms of the source of one function.
It compiles each form with the compiler of the build, and keeps the form
whose code is nearest to retail. Use it on a near that differs only in
register allocation, instruction order or stack layout. A person can try
ten forms by hand. The permuter tries thousands.

The permuter is in the spirit of decomp-permuter (simonlindholm), but for
VC6 (cl 12.00.x under Wine) and C++.

> **Only an identical result is a proof.** A mutation can change what
> the function does. When the code is byte-identical to retail, the
> source is correct. When it is only nearer, examine the diff before you
> keep it.

## 1. What it does

1. It reads the compile command of the object from `<obj>.cmd` (the file
   that `build.mk` writes beside each object).
2. It starts one build container for each worker. The container mounts
   the repository read-only at `/repo`. A bind mount puts the variant
   source on top of the original source file. Thus each compile has the
   same paths, flags and precompiled header as the build. The object
   goes into the scratch directory of the worker.
3. It finds the function in the source with a light tokenizer (not a
   full parser), and parses the statements of the body.
4. Each try applies one to three random mutations to the current form,
   compiles it, and scores the object.
5. A worker keeps a form if its score is equal or better. Sometimes it
   keeps a worse form (simulated annealing, `--temperature`). Sometimes
   it goes back to the best form of all workers.
6. When the mutations make only forms that it compiled before (a small
   function), a worker applies more mutations at a time. After
   `--max-dups` such mutations in sequence (default 5000), the worker
   stops.
7. It stops when a form is identical, or at `--time` or `--tries`.
8. If the best form is better than the original, a simplify step puts
   back each changed group of lines (and removes each added line) that
   the score does not need (`--no-simplify` to skip it).

The permuter does not write into the repository. It writes `best.cpp`,
`best.diff` and `log.txt` in `--out` (default: a new directory in
`/tmp`). You apply the diff by hand.

## 2. The score

The score uses the comparison of `fndiff.py`:

- 0: byte-identical, with the relocations masked.
- Otherwise: 8 × (the mnemonic diff after the best renaming of ebx, esi
  and edi) + (the mnemonic diff without renaming) + (the number of
  aligned instructions whose bytes differ) + 2 × (the difference in
  size, in bytes) + 1.

Thus a structure difference costs most, then a register difference, then
a displacement or a constant. A pure register near (the diff is 0 after
renaming) scores lower than a form with a different structure, also if
the register diff of that form is smaller. A stack layout difference
(only the frame offsets differ) has a mnemonic diff of 0 and a score of
(the number of instructions with a different offset) + 1.

## 3. The mutations

| Name | Change |
|---|---|
| `swap` | Swap two adjacent statements. Not when one writes a name that the other uses. With `--strict`, not when both call a function. |
| `decl_split` | `T x = e;` to `T x; x = e;` |
| `decl_merge` | `T x; x = e;` to `T x = e;` |
| `decl_move` | Move a declaration to the top of the function, or one statement down. A declaration with an initializer in a nested block goes to the top as `T x;`, and `x = e;` stays. |
| `return_temp` | `return e;` to `T tmp = e; return tmp;`, and the reverse. |
| `temp_inline` | Replace a local that is used one time with its initializer. |
| `split_expr` | `x = A op B;` to `x = A; x op= B;` |
| `commute` | `a op b` to `b op a` for `+ * & \| ^ == !=`; `<` to `>` and the other relations. `&&` and `\|\|` only with `--loose`. |
| `incdec` | `++i` to `i++` where the value is not used. |
| `not` | `!x` to `(x == 0)`, `x == 0` to `!x`, `x != 0` to `x`, and a condition `x` to `x != 0`. |
| `loop` | `for` to `while` (not when the body has `continue`), and `while` to `for`. |
| `if` | `if (c) A else B` to `if (!(c)) B else A`; remove the `else` after a branch that returns; put the rest of the block in an `else`; early return in a `void` function, and the reverse. |
| `cast` | Remove a C-style cast, or add one. |
| `hoist` | Put a call argument, a member or an operand with `->`, `.` or a call into a new local before its statement. The type is one of the types of the parameters, the locals, the return value and `--types`. A wrong type does not compile, or does not give the retail code. |
| `decl_order` | `int a, b;` to `int b, a;` or to `int a; int b;`; change the order of a constructor's member initializers. |

A mutation that does not compile costs one compile and is then ignored.
The permuter remembers each form that it compiled (with the white space
normalized), and does not compile it again.

## 4. Usage

Run it on the host (it starts the containers). Give the repository, the
object, the mangled symbol and the retail address:

```
ext/tools/permuter.py --repo ~/src/tron20src \
    --obj src/Game/built/Final/ObjectDll/TRON/TronTurret.obj \
    --symbol '?Fire@TronTurret@@AAE?AW4WeaponState@@XZ' \
    --addr 0x1006c4d0 --image Object --workers 6 --time 900
```

- `--image` is a target of `progress/targets.py` or an image path. The
  size comes from `--end`, or from the function table of the image
  (`out/reference/<stem>-functions.csv`), as for `fndiff.py`.
- `--func Class::Name` if the permuter cannot read the name from the
  symbol; `--line N` if the name has overloads.
- `--target-obj <obj>` compares with a function in another object, not
  with retail (the test uses it).
- `--types "HOBJECT,const WEAPON*"` gives more types for `hoist`.
- `--seed N` makes a run repeatable (with one worker).
- `--docker-image` (default `<repository name>-build`), `--root` (the
  in-container directory of the command's `cd`; default from its
  `WINEPREFIX`), `--mount HOST:CONTAINER` (more read-only mounts).
- `--verbose` writes each try to the log. `--keep` keeps the scratch
  directory (the Wine prefixes of the workers).

To stop a run, send SIGINT (Ctrl-C) or SIGTERM. The permuter then
removes its containers (`permuter-<pid>-<n>`) and writes the best form
that it found. If it is killed (SIGKILL), remove its containers with
`docker rm -f`.

Each compile of one object takes 1 to 6 seconds (Tron 2.0, with the precompiled header). Each worker uses one
processor. The first compile is the original form; the permuter stops if
it does not compile.

The object must be in the build (its `.cmd` file must exist), and the
precompiled header of its project must be current. Build the project one
time before you start.

### Tron 2.0: the release tree

Tron 2.0 compiles `out/release-tree/`, a copy of `src/` without the
`TRON20_MODERN` blocks. The `.cmd` file names this tree (its
`WINEPREFIX`), so the permuter changes the copy in the release tree. The
paths in `best.diff` are relative to that tree, and are the same as the
paths in `src/`. If the function has a variant block, apply the diff by
hand.

## 5. Limits

- The tokenizer does not know types. A temporary gets a type only from
  the return type of the function or from a declaration. `split_expr`
  can change a float expression's precision. The compiler and the score
  find most errors; you must examine the rest.
- A mutation changes only the body of the function (and the member
  initializers). It does not change headers, inline functions, other
  functions in the file, or the order of functions. A near that comes
  from the inline budget (docs of the game, "inline budget") or from a
  different statement in another function is out of its reach.
- The search is random. A form that needs several mutations at the same
  time, each of which makes the score worse, is hard to find. Use more
  time, more workers or another `--seed`.
- Macros are tokens like other names. The permuter does not expand them.

## 6. Examples (Tron 2.0, 2026-11-24)

Eleven nears of Tron 2.0 that agents classed as register or schedule
only. Each run had 2 to 4 workers for 7 to 15 minutes. Three became
identical. A check compiled each found form again, outside the
permuter, and `fndiff.py` gave "byte-identical" for each.

`CCharacter::ShouldGib` (Object 0x10091370): retail tests the two halves
of a 64-bit flag word one at a time. The `not` and `commute` mutations
found it in 134 compiles:

```
-	if( !( nGibFlags & m_nDamageFlags ) )
+	if( (0 == ( nGibFlags & m_nDamageFlags )) )
```

`AINodeExitLevelByRezOut::ProcessOnUseCmd` (Object 0x1026ea10): retail
reads `m_hObject` before the string. `hoist` found it in 3 compiles:

```
-		g_pCmdMgr->Process( m_sOnUseCmd.c_str( ), m_hObject, hUser );
+		HOBJECT permTmp0 = m_hObject;
+		g_pCmdMgr->Process( m_sOnUseCmd.c_str( ), permTmp0, hUser );
```

`CAIGoalDash::Save` (Object 0x1020bf10): the members are `double`, and
the explicit cast moved the conversion before the vtable read. `cast`
removed both casts (59 compiles; `--types "LTFLOAT,float"`):

```
-	SAVE_FLOAT( (LTFLOAT)m_fDashMinDist );
-	SAVE_FLOAT( (LTFLOAT)m_fDashMaxDist );
+	SAVE_FLOAT( m_fDashMinDist );
+	SAVE_FLOAT( m_fDashMaxDist );
```

The permuter did not find a form for these: `TronTurret::GetTurnAmount`
(the frame is 0x18 bytes bigger in retail), `TronTurret::Fire` (x87
scheduling), `CLightCycleButeMgr::GetColorShade` (eax against ecx),
`CHUDEnergyTransfer::BuildFill` (fsubr against fadd),
`CInterfaceResMgr::GetFontForHeight` and
`CTronPlayerMgr::TronUnknownLightCycleSpectate` (esi against edi in all
of the function), `CTexturedFrame::SetRect` and the `CClusterDisc`
constructor (the order of the stores). The mutations of SetRect and of
the constructor make fewer than 40 forms. The cause of these nears is
probably outside the body of the function, or in an expression that the
mutations do not make.
