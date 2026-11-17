#!/usr/bin/env python3
"""Check that our absolute data references go where the shipped ones go.

Like ext/tools/callcheck.py, but for DIR32 relocations (globals, tables,
vtables, string literals). For each function that exematch places at one
shipped address, read the shipped dword behind each DIR32 relocation, take
away our addend, and group:

  SPLIT   one of our symbols reaches several shipped addresses
  MERGED  several of our symbols reach one shipped address

Usage: datarefcheck.py <image> <obj>...
"""
import collections
import glob
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exematch import find  # noqa: E402
from exedump import Pe  # noqa: E402

DIR32 = 0x06


def parse(data):
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
        _vs, _va, rawsz, rawp, relp, _lnp, nrel, _nln = struct.unpack_from("<IIIIIIHH", data, s + 8)
        flags = struct.unpack_from("<I", data, s + 36)[0]
        secs.append((rawsz, rawp, relp, nrel, flags))
    entries = [None] * nsyms
    i = 0
    while i < nsyms:
        e = symoff + i * 18
        raw = data[e:e + 18]
        name = symname(raw[:8])
        value, secnum, typ, storage, naux = struct.unpack_from("<IhHBB", raw, 8)
        entries[i] = (name, value, secnum, typ, storage)
        i += 1 + naux
    out = {}
    for si, (rawsz, rawp, relp, nrel, flags) in enumerate(secs, 1):
        if not flags & 0x20 or rawsz == 0 or rawp == 0:
            continue
        code = data[rawp:rawp + rawsz]
        masks = set()
        rels = []
        for r in range(nrel):
            va, idx, typ = struct.unpack_from("<IIH", data, relp + r * 10)
            masks.update(range(va, min(va + 4, rawsz)))
            if typ == DIR32:
                ent = entries[idx] if idx < nsyms else None
                if ent:
                    name = ent[0]
                    # a static/section symbol: name it by section and value
                    if ent[4] == 3 and ent[1] == 0 and ent[2] > 0:
                        name = "%s<sec%d>" % (name, ent[2])
                    addend = struct.unpack_from("<i", code, va)[0]
                    rels.append((va, name, addend))
        fsyms = sorted((v, n) for e in entries if e for n, v, sn, typ, st in [e]
                       if sn == si and st in (2, 3) and typ == 0x20)
        for j, (v, n) in enumerate(fsyms):
            end = fsyms[j + 1][0] if j + 1 < len(fsyms) else rawsz
            fcode = code[v:end]
            while fcode and fcode[-1] in (0x90, 0xCC):
                fcode = fcode[:-1]
            fmask = {m - v for m in masks if v <= m < v + len(fcode)}
            frels = [(o - v, s, a) for o, s, a in rels if v <= o < v + len(fcode)]
            out[n] = (fcode, fmask, frels)
    return out


def main():
    image, objs = sys.argv[1], sys.argv[2:]
    expanded = []
    for o in objs:
        expanded.extend(sorted(glob.glob(o)) if "*" in o else [o])
    pe = Pe(image)
    tva, tvs, trp = pe.secs[".text"]
    text = pe.d[trp:trp + tvs]
    placed, ambiguous, parsed = {}, set(), {}
    for obj in expanded:
        try:
            fns = parse(open(obj, "rb").read())
        except Exception as exc:
            print("skipped", obj, exc, file=sys.stderr)
            continue
        parsed[obj] = fns
        for name, (code, mask, _r) in fns.items():
            if len(code) - len(mask) < 8:
                continue
            hits = list(find(text, tva, code, mask))
            if len(hits) == 1:
                if name in placed and placed[name] != hits[0]:
                    ambiguous.add(name)
                placed[name] = hits[0]
            elif len(hits) > 1:
                ambiguous.add(name)
    for n in ambiguous:
        placed.pop(n, None)
    by_sym = collections.defaultdict(lambda: collections.defaultdict(list))
    by_addr = collections.defaultdict(set)
    nsites = 0
    for obj, fns in parsed.items():
        tu = os.path.basename(obj)
        for name, (code, mask, rels) in fns.items():
            if name not in placed:
                continue
            base = placed[name]
            for off, sym, addend in rels:
                i = base - tva + off
                ship = struct.unpack_from("<I", text, i)[0]
                tgt = (ship - addend) & 0xffffffff
                key = sym if "<sec" not in sym else tu + ":" + sym
                by_sym[key][tgt].append("%s %s+%d" % (tu, name[:50], off))
                by_addr[tgt].add(key)
                nsites += 1
    print("%d placed, %d DIR32 sites" % (len(placed), nsites))
    if os.environ.get("SITES"):
        for sym, tg in by_sym.items():
            if os.environ["SITES"] in sym:
                for t, where in tg.items():
                    for w in where:
                        print("SITE %s 0x%08x %s" % (sym, t, w))
    if os.environ.get("NAMES"):
        with open(os.environ["NAMES"], "w") as fh:
            for sym, tg in sorted(by_sym.items()):
                if len(tg) == 1:
                    fh.write("%08x %s\n" % (list(tg)[0], sym))
            for n, a in sorted(placed.items()):
                fh.write("%08x %s\n" % (a, n))
    for sym, tg in sorted(by_sym.items()):
        if len(tg) > 1:
            print("SPLIT  %s:" % sym)
            for t, where in sorted(tg.items()):
                print("    0x%08x  x%d  e.g. %s" % (t, len(where), where[0]))
    for t, syms in sorted(by_addr.items()):
        if len(syms) > 1:
            print("MERGED 0x%08x <- %s" % (t, "; ".join(sorted(syms))))


if __name__ == "__main__":
    main()
