#!/usr/bin/env python3
"""Prove enumeration errors next to the unwritten and near rows, and propose
the progress/ rows that fix them.

enumcheck.py and extentcheck.py REPORT suspects; every one still has to be
read by hand before it becomes a row of <stem>-screen-exclude.csv or
extent-splits.csv. This does the reading for the shapes whose proof is
mechanical, on the enumeration the scorer actually uses (progress.py's
_enum_with_sizes: the enumerator, plus extent-splits.csv, minus the rows
already excluded), and only next to rows that are unwritten (todo,
attempted) or near -- the rows an enumeration error can be keeping from
pairing.

Each row P is decoded by RECURSIVE DESCENT from its start (both arms of a
conditional branch, a jmp's target, a `jmp [reg*4+table]`'s table entries;
stopping at ret/jmp/int3), so bytes that are never executed (padding, jump
tables) are not taken for instructions. For the row N after it:

  (a) jumped-to  a conditional branch reached from P's start targets N's
                 start (an unconditional jmp may be a tail call, so it counts
                 only when N's own code branches back into P's interior)
  (b) mid-insn   an instruction reached from P's start straddles N's start,
                 so N's start is an operand byte
  (c/d) falls in the instruction reached from P's start that ends exactly at
                 N's start is not ret/jmp/int3/call: P runs straight into N
                 with no padding and no return (a call is excluded because
                 the callee may not return)

In each case N is not a function but P's interior block, provided N's start
is referenced by nothing else: no 4-byte copy of its address anywhere in the
file, and no call/jmp to it from the decode of any other row. N is then
proposed as `NOT A FUNCTION: interior block of 0xP: ...`, which (through
_names_container) also gives N's bytes back to P. P itself must be trusted:
a call in the decode of some row reaches it, a copy of its address is in
the file, or it is a proven start (extent-splits.csv), and it decodes
without an opcode this decoder does not know. Chains are followed: once N is P's, the
row after N is tested against P's whole extent, and is named P too.

  (s) split      a row X whose descent ends (ret/jmp), followed by padding,
                 followed by code at Y < X's end that nothing reached from
                 X's start branches to, and X does not touch fs:[0] (SEH or
                 C++ EH, whose handler blocks are reached only from tables):
                 Y is proposed as a start for extent-splits.csv.

Usage:
  enumproof.py [--csv out/progress/functions.csv] [--target LABEL]...
               [--write]

--csv   statuses (default out/progress/functions.csv, from build/progress.sh)
--write append the proposals to progress/<stem>-screen-exclude.csv and
        progress/extent-splits.csv (otherwise they are only printed)
"""
import csv
import os
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import progress  # noqa: E402
from enumfuncs import enumerate_functions  # noqa: E402
from x86len import decode  # noqa: E402

UNWRITTEN = {"todo", "attempted"}
CHECK = UNWRITTEN | {"near"}
TRUSTED_SRC = {"init", "export"}


def is_jcc(op):
    return 0x70 <= op <= 0x7F or 0x0F80 <= op <= 0x0F8F or 0xE0 <= op <= 0xE3


def rel_target(code, ins, base):
    """The target of a relative branch/call, or None."""
    op = ins.op
    if not (is_jcc(op) or op in (0xE8, 0xE9, 0xEB)):
        return None
    if ins.imm_len == 1:
        d = struct.unpack_from("<b", code, ins.imm_off)[0]
    elif ins.imm_len == 4:
        d = struct.unpack_from("<i", code, ins.imm_off)[0]
    else:
        return None
    return base + ins.off + ins.length + d


class Descent:
    """Recursive descent from `entry`, never leaving [lo, hi)."""

    def __init__(self, img, entry, lo, hi):
        self.insns = {}       # addr -> (length, op, reg, how): how it was reached
        self.branches = []    # (from, to, kind)  kind: jcc / jmp / call
        self.unknown = False  # an opcode decode() does not know was reached
        self.indirect = False  # an indirect jmp that is not a jump table
        self.tables = []      # (lo, hi) of jump tables read
        self.fs = False       # touches fs: (SEH / C++ EH frames)
        text, tlo = img.text, img.tlo
        work = [(entry, "entry")]
        while work:
            a, how = work.pop()
            while lo <= a < hi and a not in self.insns:
                ins = decode(text, a - tlo)
                if ins is None:
                    self.unknown = True
                    break
                self.insns[a] = (ins.length, ins.op, ins.reg, how)
                if 0x64 in ins.prefixes:
                    self.fs = True
                op = ins.op
                t = rel_target(text, ins, tlo)
                if op in (0xC3, 0xC2, 0xCC, 0xCB, 0xCA, 0xCF, 0xF4):
                    break
                if is_jcc(op):
                    self.branches.append((a, t, "jcc"))
                    work.append((t, "jcc"))
                elif op in (0xE9, 0xEB):
                    self.branches.append((a, t, "jmp"))
                    work.append((t, "jmp"))
                    break
                elif op == 0xE8:
                    self.branches.append((a, t, "call"))
                elif op == 0xFF and ins.reg in (4, 5):
                    # jmp dword ptr [reg*4 + table]: ff 24 x5 disp32 with a
                    # scale of 4 and no base
                    o = a - tlo
                    if ins.reg == 4 and ins.mod == 0 and ins.rm == 4 and \
                            (text[o + 2 + len(ins.prefixes)] & 0xC7) == 0x85:
                        tab = struct.unpack_from("<I", text, ins.disp_off)[0]
                        k = tab
                        while lo <= k < hi and k + 4 <= tlo + len(text):
                            e = struct.unpack_from("<I", text, k - tlo)[0]
                            if not (lo <= e < hi):
                                break
                            work.append((e, "table"))
                            k += 4
                        if k > tab:
                            self.tables.append((tab, k))
                        else:
                            self.indirect = True
                    else:
                        self.indirect = True
                    break
                a += ins.length
                how = "call-fall" if op == 0xE8 else "fall"

    def straddle(self, x):
        for a, (n, _op, _r, how) in self.insns.items():
            if a < x < a + n:
                return a, how
        return None

    def ending_at(self, x):
        for a, (n, op, reg, how) in self.insns.items():
            if a + n == x:
                return a, op, reg, how
        return None

    def end(self):
        return max((a + v[0] for a, v in self.insns.items()), default=0)


_DIS = {}


def intel(img, a):
    """One instruction at `a`, Intel syntax, as the existing rows quote it."""
    key = (img.path, a)
    if key in _DIS:
        return _DIS[key]
    b = img.text[a - img.tlo:a - img.tlo + 16]
    with tempfile.NamedTemporaryFile(suffix=".bin") as f:
        f.write(b)
        f.flush()
        out = subprocess.run(
            ["objdump", "-D", "-b", "binary", "-mi386", "-M", "intel",
             f"--adjust-vma={a:#x}", f.name], capture_output=True,
            text=True).stdout
    s = "?"
    for line in out.splitlines():
        p = line.split("\t")
        if len(p) >= 3 and p[0].strip().rstrip(":") == f"{a:x}":
            s = " ".join(p[2].split())
            s = s.replace(" PTR ", " ptr ").replace("DWORD", "dword") \
                 .replace("WORD", "word").replace("BYTE", "byte")
            hexb = p[1].strip()
            s = f"{s}` ({hexb})"
            break
    s = "`" + s if s != "?" else "?"
    _DIS[key] = s
    return s


PADB = (0x90, 0xCC)
LEANOPS = (b"\x8d\xa4\x24\x00\x00\x00\x00", b"\x8d\x9b\x00\x00\x00\x00",
           b"\x8d\x64\x24\x00", b"\x8d\x49\x00", b"\x8b\xff", b"\x8b\xc0",
           b"\x8d\xa4\x20\x00\x00\x00\x00", b"\x8d\x76\x00", b"\x8d\x7f\x00",
           b"\x8d\xb6\x00\x00\x00\x00", b"\x8d\xbf\x00\x00\x00\x00",
           b"\x8d\x74\x26\x00", b"\x89\xf6")


def skip_pad(img, a, hi):
    t, tlo = img.text, img.tlo
    while a < hi:
        if t[a - tlo] in PADB:
            a += 1
            continue
        for p in LEANOPS:
            if t[a - tlo:a - tlo + len(p)] == p:
                a += len(p)
                break
        else:
            return a
    return a


def statuses(path):
    out = {}
    for r in csv.DictReader(open(path)):
        f = r["function"]
        if f.startswith("sub_"):
            try:
                out.setdefault(r["target"], {})[int(f[4:], 16)] = r["status"]
            except ValueError:
                pass
    return out


def check_target(t, st):
    label = t["label"]
    img, starts, sizes = progress._enum_with_sizes(t["shipped"], label)
    _s, src = enumerate_functions(img)
    splits = progress._extent_splits().get(label, set())
    rem = progress._REMAINDER_STARTS.get(label, set())
    phantom = progress._phantom_index(label)
    data = img.d
    tlo, thi = img.tlo, img.thi
    idx = {a: i for i, a in enumerate(starts)}

    def ext(i):
        return starts[i + 1] if i + 1 < len(starts) else thi

    # Every call/jmp in the decode of every row (each from its own start,
    # within its own extent): the "real" references, as against an e8 byte
    # that merely happens to sit in an operand.
    desc = {}
    refs = {}
    for i, a in enumerate(starts):
        d = Descent(img, a, a, ext(i))
        desc[a] = d
        for f, to, k in d.branches:
            refs.setdefault(to, []).append((f, k))
    abs_cache = {}

    def nabs(x):
        if x not in abs_cache:
            abs_cache[x] = data.count(struct.pack("<I", x))
        return abs_cache[x]

    def trusted(a):
        if a in splits or a in rem:
            return True
        if nabs(a) or any(k == "call" for _f, k in refs.get(a, ())):
            return True
        return src.get(a) in TRUSTED_SRC

    want = {a for a, s in st.items() if s in CHECK}
    props = []          # (kind, file-row tuple)
    taken = set()
    for i, p in enumerate(starts):
        if i + 1 >= len(starts) or p in taken:
            continue
        n = starts[i + 1]
        if p not in want and n not in want:
            continue
        if not trusted(p):
            continue
        j = i + 1
        hi = ext(j)
        while j < len(starts):
            n = starts[j]
            if n in phantom:
                break
            if not (p in want or n in want or j > i + 1):
                break
            d = Descent(img, p, p, hi)
            if d.unknown:
                break
            # references from N's own descent back to N (a loop to its own
            # head) are not references from outside either
            outside = [f for f, k in refs.get(n, ())
                       if not (p <= f < n) and not (n <= f < hi)]
            if outside:
                break
            why = None
            jcc = [f for f, to, k in d.branches if to == n and k == "jcc"]
            jmp = [f for f, to, k in d.branches if to == n and k == "jmp"]
            sd = d.straddle(n)
            if sd and sd[1] not in ("call-fall",):
                # An instruction reached from P's start overlaps N's start:
                # no compiler emits overlapping code, so this holds even if
                # a dword somewhere happens to equal N's address.
                a0, _h = sd
                why = (f"decoded from that start, 0x{a0:08x} is "
                       f"{intel(img, a0)}, so 0x{n:08x} is inside it")
                if nabs(n):
                    why += (f" (the {nabs(n)} dword(s) in the file equal to "
                            f"0x{n:08x} cannot be pointers to it)")
            elif nabs(n):
                break
            elif jcc:
                why = (f"0x{jcc[0]:08x} {intel(img, jcc[0])} in that "
                       f"function branches to it")
            elif jmp:
                back = [f for f, to, k in desc[n].branches
                        if k in ("jcc", "jmp") and p < to < n]
                if back:
                    to = [to for f, to, k in desc[n].branches if f == back[0]][0]
                    why = (f"0x{jmp[0]:08x} {intel(img, jmp[0])} in that "
                           f"function jumps to it, and its own 0x{back[0]:08x} "
                           f"{intel(img, back[0])} branches back to 0x{to:08x} "
                           f"inside that function")
            if why is None:
                e = d.ending_at(n)
                if e and e[3] != "call-fall":
                    a0, op, reg, _h = e
                    stop = op in (0xC3, 0xC2, 0xCC, 0xCB, 0xCA, 0xCF, 0xF4,
                                  0xE9, 0xEB, 0xE8) or \
                        (op == 0xFF and reg in (2, 3, 4, 5))
                    if not stop:
                        why = (f"0x{a0:08x} {intel(img, a0)} falls through "
                               f"into 0x{n:08x}")
            if why is None:
                break
            tail = ("" if nabs(n) else " and no copy of the address is in "
                    "the file")
            why = (f"NOT A FUNCTION: interior block of 0x{p:08x}: {why}; "
                   f"nothing calls or jumps to 0x{n:08x} from outside "
                   f"it{tail}")
            props.append(("x", (f"0x{n:08x}", why), p, n,
                          st.get(p, "?"), st.get(n, "?")))
            taken.add(n)
            j += 1
            hi = ext(j) if j < len(starts) else thi

    # (s) merged rows
    for i, x in enumerate(starts):
        if st.get(x) not in CHECK or x in taken:
            continue
        hi = ext(i)
        d = desc[x]
        if d.unknown or d.indirect or d.fs or not d.insns:
            continue
        e = d.end()
        for lo_t, hi_t in d.tables:
            if lo_t <= e:
                e = max(e, hi_t)
        last = max(d.insns)
        if d.insns[last][1] not in (0xC3, 0xC2, 0xE9, 0xEB):
            continue
        y = skip_pad(img, e, hi)
        if y >= hi or y == e:
            continue
        if any(lo_t <= y < hi_t for lo_t, hi_t in d.tables):
            continue
        if any(to == y for _f, to, _k in d.branches):
            continue
        dy = Descent(img, y, y, hi)
        if dy.unknown or not dy.insns:
            continue
        r = refs.get(y, [])
        ref = (f"{len([1 for f, k in r if k == 'call'])} call(s) and "
               f"{nabs(y)} copy(ies) of the address elsewhere")
        why = (f"a function start the enumeration merged into 0x{x:08x}: "
               f"decoded from that start, its code ends at 0x{e:08x} "
               f"(0x{last:08x} {intel(img, last)}), then padding to "
               f"0x{y:08x}, which nothing in that function branches to; "
               f"{ref}")
        props.append(("s", (label, f"0x{y:08x}", why), x, y,
                      st.get(x, "?"), "-"))
    return props


def main():
    args = sys.argv[1:]
    csvp = os.path.join(progress.OUT, "functions.csv")
    only = []
    write = False
    while args:
        a = args.pop(0)
        if a == "--csv":
            csvp = args.pop(0)
        elif a == "--target":
            only.append(args.pop(0))
        elif a == "--write":
            write = True
        else:
            sys.exit(__doc__)
    st = statuses(csvp)
    for t in progress.TARGETS:
        if t.get("kind") != "image" or not os.path.exists(t["shipped"]):
            continue
        if only and t["label"] not in only and t["stem"] not in only:
            continue
        props = check_target(t, st.get(t["label"], {}))
        print(f"== {t['label']}: {len(props)} proposal(s)")
        for kind, row, p, n, sp, sn in props:
            print(f"  [{kind}] 0x{p:08x}({sp}) <- 0x{n:08x}({sn})\n"
                  f"      {row[-1]}")
        if write and props:
            ex = [r for k, r, *_ in props if k == "x"]
            sp = [r for k, r, *_ in props if k == "s"]
            if ex:
                f = os.path.join(progress.DATA,
                                 f"{t['stem']}-screen-exclude.csv")
                new = not os.path.exists(f)
                with open(f, "a", newline="") as fh:
                    w = csv.writer(fh)
                    if new:
                        w.writerow(["addr", "reason"])
                    w.writerows(ex)
            if sp:
                with open(os.path.join(progress.DATA, "extent-splits.csv"),
                          "a", newline="") as fh:
                    csv.writer(fh).writerows(sp)


if __name__ == "__main__":
    main()
