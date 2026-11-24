#!/usr/bin/env python3
"""Match functions from COFF objects against a PE32 image's .text.

For every function symbol in the given .obj/.lib files, masks the bytes
covered by the object's relocations and scans the executable's .text for
a byte-match of the remaining (position-independent) bytes. Because the
mask positions come from our object, a match means the shipped code is
byte-identical up to addresses — the exe-level equivalent of objdiff.

Usage: exematch.py <exe> <obj|lib>... [--verbose]
"""
import struct
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from objdiff import parse_obj  # noqa: E402
from exedump import Pe  # noqa: E402
import tempfile, glob, os  # noqa: E402
from libextract import extract  # noqa: E402


class Mask(set):
    """The masked offsets of a function (a set), and its SELF-REFERENCES:
    the relocated operands that name a place inside the function itself,
    as {offset: (absolute, place)}, `place` the offset of that place in
    the function. A switch's jump table is one entry per case, each a
    DIR32 to the case label; the `jmp [reg*4+table]` that indexes it, and
    the `mov r8, [reg+table]` that reads its byte index table, are DIR32s
    to the tables; a recursive call is a REL32 to the function itself.
    Masked like every relocation, they would match any address at all,
    so a table would match when its entries name other cases, or another
    function's code. Their value is known once the function's address is.
    find() admits a hit only where each one holds (selfrefs_hold): a table
    matches when each entry names the matching case label, not by its raw
    bytes."""
    __slots__ = ("selfrefs",)

    def __init__(self, it=(), selfrefs=None):
        super().__init__(it)
        self.selfrefs = dict(selfrefs or {})


def selfrefs_hold(text, tbase, fstart, mask, length=None, rebased=False):
    """True when every self-reference of `mask` (Mask.selfrefs) below
    `length` holds for the function at text[fstart:], at address
    tbase + fstart:

      absolute (a DIR32): the operand is that address plus the place;
      relative (a REL32): the operand reaches the place, directly or
        through a `jmp rel32` thunk (an incremental link's: a recursive
        call goes through the function's own thunk).

    rebased: the bytes are another build's, copied to this address (a
    target's `readable` pages), so every absolute operand is that build's
    address of its place: all of them must be off by the same amount."""
    delta = None
    n = len(text)
    for off, (absolute, place) in getattr(mask, "selfrefs", {}).items():
        if length is not None and off + 4 > length:
            continue
        o = fstart + off
        if o < 0 or o + 4 > n:
            return False
        got = struct.unpack_from("<I", text, o)[0]
        if absolute:
            d = (got - (tbase + fstart + place)) & 0xFFFFFFFF
            if d and not rebased:
                return False
            if delta is None:
                delta = d
            elif d != delta:
                return False
            continue
        dest = (o + 4 + got) & 0xFFFFFFFF      # an offset into text
        if dest == fstart + place:
            continue
        if dest + 5 <= n and text[dest] == 0xE9 and \
                (dest + 5 + struct.unpack_from("<i", text, dest + 1)[0]) \
                == fstart + place:
            continue
        return False
    return True


def parse_obj_masked(data, kinds=None, targets=None):
    """Like objdiff.parse_obj but returns (code, maskset) per function.

    kinds, a dict, is filled with each function's relocations as
    {name: {offset: COFF relocation type}} (6 DIR32, 7 DIR32NB, 0x14
    REL32, ...), for a caller that has to know what each masked dword is.
    targets, a dict, is filled with what each relocation names, as
    {name: {offset: (symbol, the dword in the code)}}: for a DIR32 the
    dword is the addend, so (`??_C@_05...`, 0) is the start of that
    string literal and not an address in another symbol that only
    happens to be the same.

    Each mask is a Mask: it also holds the function's self-references
    (Mask.selfrefs), the DIR32 and REL32 relocations that name a place
    inside the function's own extent (its jump tables' entries, the
    operands that index the tables)."""
    if len(data) < 20:
        return {}
    machine, nsec, _ts, symoff, nsyms, optsz, _ch = struct.unpack_from("<HHIIIHH", data, 0)
    if machine != 0x14C:
        return {}
    strtab = data[symoff + nsyms * 18:]

    def symname(raw):
        if raw[:4] == b"\0\0\0\0":
            off = struct.unpack_from("<I", raw, 4)[0]
            return strtab[off:strtab.find(b"\0", off)].decode("latin-1")
        return raw.rstrip(b"\0").decode("latin-1")

    secs = []
    for i in range(nsec):
        s = 20 + optsz + i * 40
        vsize, _va, rawsz, rawp, relp, _lnp, nrel, _nln = struct.unpack_from(
            "<IIIIIIHH", data, s + 8)
        flags = struct.unpack_from("<I", data, s + 36)[0]
        secs.append((rawsz, rawp, relp, nrel, flags))

    syms = []
    by_index = {}
    sym_at = {}     # symbol index -> (value, section number)
    i = 0
    while i < nsyms:
        e = symoff + i * 18
        raw = data[e : e + 18]
        name = symname(raw[:8])
        value, secnum, typ, storage, naux = struct.unpack_from("<IhHBB", raw, 8)
        syms.append((name, value, secnum, typ, storage))
        by_index[i] = name
        sym_at[i] = (value, secnum)
        i += 1 + naux

    out = {}
    for si, (rawsz, rawp, relp, nrel, flags) in enumerate(secs, 1):
        if not flags & 0x20 or rawsz == 0 or rawp == 0:
            continue
        code = data[rawp : rawp + rawsz]
        masks = set()
        rtype = {}
        rsym = {}
        local = {}      # offset -> (absolute, the place in this section)
        for r in range(nrel):
            va, si2 = struct.unpack_from("<II", data, relp + r * 10)
            masks.update(range(va, min(va + 4, rawsz)))
            rtype[va] = struct.unpack_from("<H", data, relp + r * 10 + 8)[0]
            if targets is not None and va + 4 <= rawsz:
                rsym[va] = (by_index.get(si2),
                            struct.unpack_from("<I", code, va)[0])
            # a relocation to a symbol of this same section (a label, the
            # section's own symbol): the place it names, in the section
            sv, ssec = sym_at.get(si2, (None, None))
            if ssec == si and va + 4 <= rawsz and rtype[va] in (0x06, 0x14):
                add = struct.unpack_from("<I", code, va)[0]
                # (a REL32's field holds S + A - (P + 4): the place is S + A)
                local[va] = (rtype[va] == 0x06, (sv + add) & 0xFFFFFFFF)
        fsyms = sorted(
            (v, n) for n, v, sn, typ, st in syms
            if sn == si and st in (2, 3) and typ == 0x20)
        for j, (v, n) in enumerate(fsyms):
            end = fsyms[j + 1][0] if j + 1 < len(fsyms) else rawsz
            fcode = code[v:end]
            while fcode and fcode[-1] in (0x90, 0xCC):
                fcode = fcode[:-1]
            # the self-references: a place inside this function's extent
            # (v up to the next function or the section's end), named
            # from inside its kept bytes
            selfrefs = {}
            for o, (absolute, place) in local.items():
                if v <= o and o + 4 <= v + len(fcode) and v <= place < end:
                    selfrefs[o - v] = (absolute, place - v)
            fmask = Mask((m - v for m in masks if v <= m < v + len(fcode)),
                         selfrefs)
            out[n] = (fcode, fmask)
            if kinds is not None:
                kinds[n] = {o - v: t for o, t in rtype.items()
                            if v <= o < v + len(fcode)}
            if targets is not None:
                targets[n] = {o - v: t for o, t in rsym.items()
                              if v <= o < v + len(fcode)}
    return out


def find(text, tbase, code, mask, rebased=None):
    """Scan text for code with masked positions ignored; yield offsets.
    A hit must also keep the function's self-references (a Mask's
    selfrefs: its jump tables name its own case labels there). rebased, a
    function of the address: True where the bytes are another build's
    (selfrefs_hold)."""
    if not code:
        return
    # anchor: longest unmasked run
    runs = []
    start = None
    for i in range(len(code) + 1):
        if i < len(code) and i not in mask:
            if start is None:
                start = i
        else:
            if start is not None:
                runs.append((i - start, start))
                start = None
    if not runs:
        return
    alen, aoff = max(runs)
    anchor = code[aoff : aoff + alen]
    pos = -1
    while True:
        pos = text.find(anchor, pos + 1)
        if pos < 0:
            return
        fstart = pos - aoff
        if fstart < 0 or fstart + len(code) > len(text):
            continue
        if all(text[fstart + i] == code[i] for i in range(len(code)) if i not in mask) \
                and selfrefs_hold(text, tbase, fstart, mask, None,
                                  bool(rebased and rebased(tbase + fstart))):
            yield tbase + fstart


def main():
    verbose = "--verbose" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pe = Pe(args[0])
    tva, tvs, trp = pe.secs[".text"]
    text = pe.d[trp : trp + tvs]

    funcs = {}
    for path in args[1:]:
        if path.lower().endswith(".lib"):
            with tempfile.TemporaryDirectory() as td:
                extract(path, td)
                for m in sorted(glob.glob(td + "/*")):
                    funcs.update(parse_obj_masked(open(m, "rb").read()))
        else:
            funcs.update(parse_obj_masked(open(path, "rb").read()))

    matched = missing = tiny = 0
    for n, (code, mask) in sorted(funcs.items()):
        if len(code) - len(mask) < 8:
            tiny += 1
            if verbose:
                print(f"  ?tiny    {n} ({len(code)} bytes)")
            continue
        hits = list(find(text, tva, code, mask))
        if hits:
            matched += 1
            print(f"  MATCH 0x{hits[0]:x}{'+' if len(hits) > 1 else ' '}  {n} ({len(code)})")
        else:
            missing += 1
            print(f"  ----     {n} ({len(code)} bytes)")
    print(f"matched {matched}, unmatched {missing}, too-small-to-match {tiny}")


if __name__ == "__main__":
    main()
