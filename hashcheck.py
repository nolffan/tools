#!/usr/bin/env python3
"""The byte check without the retail binaries: our build against hashes.

`make progress` (tools/progress.py, tools/ratchet.py) needs the retail
binaries, and so the retail game. A machine without them (a CI runner)
cannot run it. This check needs only our build and a file the project
commits: progress/hashes/identical.tsv. tools/progress.py --hashes writes
that file, from the full scoring, for every row it scores identical:

  C <target> <shipped address> <length> <locator> <mask> <SHA-256>
      A function of a linked image. <locator> is where the function is in
      our link: `module:symbol` from our .map, with `+0x<n>` when the
      function starts n bytes after that symbol, or `@0x<address>` when
      our image is the shipped one byte for byte (the same address). <mask>
      is the offsets that the comparison leaves out, as `<offset>+<count>`
      runs (`-`: none): the bytes the linker writes an address into. The
      SHA-256 is that of the <length> shipped bytes at the address, with
      the masked bytes set to zero.
  R <target> <resource> <length> <SHA-256>
      A resource (`rsrc:<type>/<name>/<language>`): the SHA-256 of the
      shipped resource's data.
  L <target> <symbol> <length> <SHA-256>
      A function of a library scored symbol by symbol: the SHA-256 of the
      shipped function's code with its relocations set to zero, as
      tools/objdiff.py reads it.

The fields are separated by one TAB. The file holds no retail bytes: only
addresses, lengths, offsets, symbols of ours and hashes.

  hashcheck.py check [--no-art]
      For each row, find the function in our build (our .map gives the
      address of the locator in our image), hash its bytes with the same
      mask, and compare. Every function in progress/identical.txt must have
      a row. Exit status 1 if a hash differs, a function cannot be found,
      or a function has no row. --no-art: the resources that a target's
      `art` key names (regular expressions on the resource) are not
      checked; a build made without the retail game compiles placeholder
      art in their place.

The check builds nothing and discovers nothing. It cannot see a function
that becomes identical: only the full `make progress-update` records that.
A function or symbol that is renamed also needs `make progress-update`.
"""
import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from layout import PROJECT as REPO  # noqa: E402

FILE = "identical.tsv"
HEADER = """\
## The rows that tools/progress.py scores identical, as hashes, for the check
## that runs without the retail binaries (tools/hashcheck.py; written by
## `tools/progress.py --hashes`). No retail bytes: addresses, lengths,
## offsets, our symbols and SHA-256 hashes.
## C <target> <shipped address> <length> <locator> <mask> <SHA-256>
## R <target> <resource> <length> <SHA-256>
## L <target> <symbol> <length> <SHA-256>
"""


def fmt_mask(offs):
    """Sorted offsets as `<offset>+<count>` runs, or `-`."""
    offs = sorted(set(offs))
    runs = []
    for o in offs:
        if runs and runs[-1][0] + runs[-1][1] == o:
            runs[-1][1] += 1
        else:
            runs.append([o, 1])
    return ",".join("%d+%d" % (o, n) for o, n in runs) or "-"


def parse_mask(s):
    out = set()
    if s == "-":
        return out
    for part in s.split(","):
        o, n = part.split("+")
        out.update(range(int(o), int(o) + int(n)))
    return out


def masked_sha(b, mask):
    b = bytearray(b)
    for i in mask:
        if i < len(b):
            b[i] = 0
    return hashlib.sha256(bytes(b)).hexdigest()


def sha(b):
    return hashlib.sha256(bytes(b)).hexdigest()


ANON = re.compile(r"\?%[^@]*@|\?A0x[0-9a-f]+@")


ANON_NUMBER = re.compile(r"(\?%[^@]*?)[0-9]+@")


def anon_path(sym):
    """A VC6 anonymous-namespace symbol with only the namespace's number left
    out: `?%<source path>@`. The source path stays, so the copies that two
    source files make of one helper stay apart."""
    return ANON_NUMBER.sub(r"\1@", sym)


def anon(sym):
    """A symbol with its anonymous namespace's name left out: VC6 names it
    `?%<source path><number>@`, VC7.1 `?A0x<hash>@`, and the number or hash
    differs from one checkout
    or build of the same source to the next."""
    return ANON.sub("?%@", sym)


class Layout:
    """Our link's .map: (module, symbol) -> address, and back."""

    def __init__(self, layout):
        import bisect
        self.by_key = layout or {}
        self.by_sym = {}
        self.by_anon = {}
        self.by_anon_sym = {}
        self.by_path_sym = {}
        for (mod, s), a in self.by_key.items():
            self.by_sym.setdefault(s, set()).add(a)
            self.by_anon.setdefault((mod, anon(s)), set()).add(a)
            self.by_anon_sym.setdefault(anon(s), set()).add(a)
            self.by_path_sym.setdefault(anon_path(s), set()).add(a)
        self.starts = sorted({a for a in self.by_key.values()})
        self.at = {}
        for k, a in sorted(self.by_key.items()):
            self.at.setdefault(a, []).append(k)
        self._bisect = bisect

    def locator(self, va, prefer=None):
        """`module:symbol[+0x<n>]` for our address va: the symbol `prefer`
        (module:symbol) if the map has it there, else a symbol at va, else
        the nearest symbol before it."""
        if prefer and ":" in prefer:
            mod, s = prefer.split(":", 1)
            if self.by_key.get((mod.lower(), s)) == va:
                return "%s:%s" % (mod.lower(), s)
            keys = self.at.get(va, [])
            same = [k for k in keys if k[1] == s]
            if same:
                return "%s:%s" % same[0]
        keys = self.at.get(va)
        if keys:
            return "%s:%s" % keys[0]
        i = self._bisect.bisect_right(self.starts, va) - 1
        if i < 0:
            return None
        a = self.starts[i]
        return "%s:%s+0x%x" % (self.at[a][0] + (va - a,))

    def resolve(self, loc):
        """Our address for a locator, or None."""
        if loc.startswith("@"):
            return int(loc[1:], 16)
        m = re.match(r"(.*?):(.*?)(?:\+0x([0-9a-f]+))?$", loc)
        mod, s, d = m.group(1), m.group(2), int(m.group(3) or "0", 16)
        a = self.by_key.get((mod, s))
        if a is None and len(self.by_anon.get((mod, anon(s)), ())) == 1:
            a = next(iter(self.by_anon[(mod, anon(s))]))   # another build's name
        if a is None and len(self.by_sym.get(s, ())) == 1:
            a = next(iter(self.by_sym[s]))       # the map names another module
        if a is None and len(self.by_anon_sym.get(anon(s), ())) == 1:
            # another build's name, and the map names another module: an
            # identical-code fold can give the folded function the module
            # of the function it is folded into
            a = next(iter(self.by_anon_sym[anon(s)]))
        if a is None and len(self.by_path_sym.get(anon_path(s), ())) == 1:
            # the same, when other source files have their own copy of the
            # helper: the source path in the namespace's name tells the
            # copies apart, and an identical-code fold puts this file's copy
            # at one address whatever module the map gives it
            a = next(iter(self.by_path_sym[anon_path(s)]))
        return None if a is None else a + d


def write(path, rows):
    """rows: tuples of fields (strings or ints), sorted here."""
    def key(r):
        return (r[1], r[0], r[2] if r[0] != "C" else "%08x" % int(r[2], 16))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="\n") as f:
        f.write(HEADER)
        for r in sorted(rows, key=key):
            f.write("\t".join(str(x) for x in r) + "\n")


def read(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        rows.append(line.rstrip("\n").split("\t"))
    return rows


# --- the check ----------------------------------------------------------------

def check(no_art=False):
    import progress
    os.chdir(REPO)
    cfg = progress.cfg
    path = os.path.join(progress.DATA, "hashes", FILE)
    if not os.path.exists(path):
        print(f"FAIL: no {path}: run `make progress-update` with the retail game")
        return 1
    rows = read(path)
    by_label = {}
    for r in rows:
        by_label.setdefault(r[1], []).append(r)
    targets = {t["label"]: t for t in cfg.TARGETS}
    libs = dict(cfg.LIBS)
    art = {t["label"]: [re.compile(x) for x in t.get("art", ())] for t in cfg.TARGETS}

    bad, skipped, counts = [], {}, {}
    images = {}

    def image(label):
        if label not in images:
            t = targets[label]
            ours = progress.built_image(t)
            if not ours:
                images[label] = None
            else:
                from exedump import Pe
                mp = progress.our_map(ours)
                images[label] = (Pe(os.path.join(REPO, ours)),
                                 Layout(progress._our_layout(mp) if mp else None),
                                 ours)
        return images[label]

    objs = {}

    def obj_code(label, n):
        """(code, mask) of our function `module:symbol` from the link's
        inputs, as tools/progress.py reads them."""
        import glob
        import tempfile
        from exematch import parse_obj_masked
        from libextract import extract
        if label not in objs:
            index = {}
            for o in progress.image_objs(targets[label], image(label)[2]):
                if o.lower().endswith(".lib"):
                    stem = os.path.splitext(os.path.basename(o))[0]
                    index[stem.lower()] = ("lib", o)
                else:
                    index[os.path.basename(o).lower()] = ("obj", o)
            objs[label] = (index, {})
        index, cache = objs[label]
        mod, sym = n.split(":", 1)
        m = re.match(r"(.*)\((.*)\)$", mod)
        key = (m.group(1) if m else mod).lower()
        if mod not in cache:
            kind, path = index.get(key, (None, None))
            data = None
            if kind == "obj":
                data = open(os.path.join(REPO, path), "rb").read()
            elif kind == "lib" and m:
                with tempfile.TemporaryDirectory() as td:
                    extract(os.path.join(REPO, path), td)
                    for f in glob.glob(td + "/*"):
                        if os.path.basename(f).lower() == m.group(2).lower():
                            data = open(f, "rb").read()
            cache[mod] = parse_obj_masked(data) if data else {}
        got = cache[mod].get(sym)
        if got is None:
            same = [v for k, v in cache[mod].items() if anon(k) == anon(sym)]
            got = same[0] if len(same) == 1 else None
        return got

    lib_code = {}

    def lib(label):
        if label not in lib_code:
            p = os.path.join(REPO, libs[label])
            lib_code[label] = progress.load_lib(p) if os.path.exists(p) else None
        return lib_code[label]

    resources = {}
    for label in sorted(by_label):
        ok = n = 0
        for r in by_label[label]:
            kind = r[0]
            n += 1
            if kind == "C":
                _k, _l, addr, length, loc, mask, want = r
                img = image(label) if label in targets else None
                if not img:
                    bad.append((label, "sub_%x" % int(addr, 16), "no build of ours"))
                    continue
                pe, lay, _ours = img
                if loc.startswith("obj:"):
                    code = obj_code(label, loc[4:])
                    if code is None:
                        bad.append((label, "sub_%x" % int(addr, 16),
                                    f"{loc[4:]} is in none of our link's inputs"))
                        continue
                    c = code[0]
                    if len(c) != int(length):
                        c = progress.strip_pad(c)
                    if masked_sha(c, parse_mask(mask)) != want:
                        bad.append((label, "sub_%x" % int(addr, 16),
                                    f"our code of {loc[4:]} differs"))
                        continue
                    ok += 1
                    continue
                va = lay.resolve(loc)
                o = pe.va2off(va) if va is not None else None
                if o is None:
                    bad.append((label, "sub_%x" % int(addr, 16),
                                f"{loc} is not in our map"))
                    continue
                got = masked_sha(pe.d[o:o + int(length)], parse_mask(mask))
                if got != want:
                    bad.append((label, "sub_%x" % int(addr, 16),
                                f"our bytes at 0x{va:08x} ({loc}) differ"))
                    continue
                ok += 1
            elif kind == "R":
                _k, _l, key, length, want = r
                if no_art and any(x.search(key) for x in art.get(label, ())):
                    skipped[label] = skipped.get(label, 0) + 1
                    n -= 1
                    continue
                if label not in resources:
                    ours = progress.built_image(targets[label])
                    resources[label] = progress._resources(os.path.join(REPO, ours)) \
                        if ours else None
                res = resources[label]
                mine = None
                if res is not None:
                    for k, data in res.items():
                        if "rsrc:" + "/".join(str(x) for x in k) == key:
                            mine = data
                            break
                if mine is None:
                    bad.append((label, key, "no such resource in our image"))
                elif sha(mine) != want:
                    bad.append((label, key, "our resource differs"))
                else:
                    ok += 1
            elif kind == "L":
                _k, _l, sym, length, want = r
                code = lib(label) if label in libs else None
                if code is None:
                    bad.append((label, sym, "no build of ours"))
                    continue
                mine = code.get(sym)
                if mine is None and ANON.search(sym):
                    key = anon(sym)
                    mine = next((c for s, c in code.items() if anon(s) == key), None)
                if mine is None:
                    bad.append((label, sym, "not in our library"))
                elif sha(mine) != want:
                    bad.append((label, sym, "our code differs"))
                else:
                    ok += 1
        counts[label] = (ok, n)

    # every function recorded identical has a row
    recorded = set()
    for r in rows:
        if r[0] == "C":
            recorded.add((r[1], "sub_%x" % int(r[2], 16)))
        else:
            recorded.add((r[1], r[2]))
    missing = []
    ident = os.path.join(progress.DATA, "identical.txt")
    for line in open(ident, encoding="utf-8"):
        if line.startswith("#") or "\t" not in line:
            continue
        t, fn = line.rstrip("\n").split("\t", 1)
        if (t, fn) not in recorded:
            missing.append((t, fn))

    print(f"{'target':<18} {'recorded':>9} {'identical':>10}")
    for label in sorted(counts):
        ok, n = counts[label]
        note = f"  ({skipped[label]} art resources not checked)" if label in skipped else ""
        print(f"{label:<18} {n:>9} {ok:>10}{note}")
    print()
    for label, fn, why in bad:
        print(f"  {label}\t{fn}\t{why}")
    if missing:
        print(f"FAIL: {len(missing)} function(s) in {ident} have no row in {path}: "
              f"run `make progress-update`")
        for t, fn in missing[:20]:
            print(f"  {t}\t{fn}")
    if bad:
        print(f"FAIL: {len(bad)} function(s) recorded as byte-identical no longer are "
              f"(by their hashes)")
    if bad or missing:
        return 1
    print("PASS: every function recorded as byte-identical still is (by its hash)")
    return 0


def main():
    args = sys.argv[1:]
    if args[:1] == ["check"]:
        return check("--no-art" in args)
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
