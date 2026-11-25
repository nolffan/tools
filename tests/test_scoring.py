"""Adversarial fixtures for the scoring tools: small synthetic objects and
images, each built to catch one way the oracle has been, or could be,
fooled.

    python3 -m unittest discover -s tools/tests     (from a project), or
    python3 -m unittest discover -s tests           (from tools/ itself)

Covered: a wrong float literal behind a masked relocation (fpconst.py); the
literal a relocation names (progress.py's _verify_literals); a
relocated `mov reg, imm32` after an `fstp st(0)` not taken for an x87
operand (fpconst.py, x86len.py); instruction lengths (x86len.py); an
interior match, a shared tail and a non-start hit (progress.py's
_resolve_overlaps); split tails merged into a near row only on proof
(progress.py's _merge_split_tails); whole-image identity through the time stamps but not
through a changed byte (progress.py, buildcmp.py); known and new data
differences (datacheck.py); a switch's jump table matched by the case
labels its entries name, not by its masked bytes (exematch.py), and a
start inside a near function's switch tables merged into it
(_merge_split_tails); end to end through _rows_for_image: a function
our link leaves out pairs only where nothing of our link does, long
look-alikes chosen by what they call and by their vtables' slots, or
identical nowhere, and a second run that starts from nothing; and
enumfuncs' rule 4h (a start reached only by a tail jump or a loaded
address). Not covered here, by their nature: vtabcheck.py
and the region rules need a linked image and a map (tested against the
games' builds: see tools/README.md).
"""
import os
import struct
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

# progress.py reads a project's progress/targets.py at import: a stub
stub = types.ModuleType("targets")
stub.REFERENCE, stub.OUT, stub.DATA = "out/reference", "out/progress", "progress"
stub.TARGETS, stub.LIBS, stub.DRIVER_OBJS, stub.SHIPPED_ENV = [], [], set(), None
sys.modules.setdefault("targets", stub)

import fpconst  # noqa: E402
import progress  # noqa: E402
import x86len  # noqa: E402
import datacheck  # noqa: E402

DIR32 = 6


def coff(code, relocs, rdata):
    """A COFF object: .text holding one function `_f` (code), .rdata holding
    `_lit` (rdata), and DIR32 relocations at the given .text offsets, all to
    `_lit`."""
    nsec = 2
    hdr = 20
    sh = hdr + 40 * nsec
    text_p = sh
    rel_p = text_p + len(code)
    rdata_p = rel_p + 10 * len(relocs)
    sym_p = rdata_p + len(rdata)
    syms = [(b"_f", 0, 1, 0x20, 2), (b"_lit", 0, 2, 0, 2)]
    out = bytearray(struct.pack("<HHIIIHH", 0x14C, nsec, 0, sym_p, len(syms), 0, 0))
    out += struct.pack("<8sIIIIIIHHI", b".text", 0, 0, len(code), text_p, rel_p, 0,
                       len(relocs), 0, 0x60000020)
    out += struct.pack("<8sIIIIIIHHI", b".rdata", 0, 0, len(rdata), rdata_p, 0, 0,
                       0, 0, 0x40000040)
    out += code
    for off in relocs:
        out += struct.pack("<IIH", off, 1, DIR32)
    out += rdata
    for name, val, sec, typ, st in syms:
        out += struct.pack("<8sIhHBB", name, val, sec, typ, st, 0)
    out += struct.pack("<I", 4)          # an empty string table
    return bytes(out)


def pe(text, rdata, base=0x400000, stamp=0):
    """A minimal PE image: .text at base+0x1000, .rdata at base+0x2000."""
    out = bytearray(0x200)
    out[0:2] = b"MZ"
    struct.pack_into("<I", out, 0x3C, 0x40)
    out[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", out, 0x44, 0x14C, 2, stamp, 0, 0, 0xE0, 0x102)
    o = 0x58
    struct.pack_into("<H", out, o, 0x10B)
    struct.pack_into("<I", out, o + 16, 0x1000)
    struct.pack_into("<I", out, o + 28, base)
    struct.pack_into("<II", out, o + 32, 0x1000, 0x200)
    struct.pack_into("<I", out, o + 56, 0x3000)
    struct.pack_into("<I", out, o + 60, 0x200)
    struct.pack_into("<I", out, o + 92, 16)
    s = o + 0xE0
    tsz = (len(text) + 0x1FF) & ~0x1FF
    rsz = (len(rdata) + 0x1FF) & ~0x1FF
    struct.pack_into("<8sIIIIIIHHI", out, s, b".text", len(text), 0x1000, tsz,
                     0x200, 0, 0, 0, 0, 0x60000020)
    struct.pack_into("<8sIIIIIIHHI", out, s + 40, b".rdata", len(rdata), 0x2000,
                     rsz, 0x200 + tsz, 0, 0, 0, 0, 0x40000040)
    out += text.ljust(tsz, b"\xcc") + rdata.ljust(rsz, b"\0")
    return bytes(out)


class Tmp:
    def __init__(self):
        self.d = tempfile.mkdtemp()

    def write(self, name, data):
        p = os.path.join(self.d, name)
        with open(p, "wb") as f:
            f.write(data)
        return p


FILLER = bytes.fromhex("d9c0d9c0d9c0d9c0ddd8ddd8ddd8ddd8") + b"\xc3"


class FloatConstants(unittest.TestCase):
    def run_case(self, obj_lit, img_lit, prefix=b"\xd9\x05"):
        # fld dword [lit] ; filler ; ret
        code = prefix + b"\0\0\0\0" + FILLER
        t = Tmp()
        o = t.write("f.obj", coff(code, [len(prefix)], struct.pack("<f", obj_lit)))
        img_code = prefix + struct.pack("<I", 0x402000) + FILLER
        p = t.write("img.exe", pe(img_code, struct.pack("<f", img_lit)))
        import io
        return fpconst.check(p, [o], out=io.StringIO())

    def test_wrong_literal_is_caught(self):
        checked, bad, _u = self.run_case(1.0, 0.001)
        self.assertEqual((checked, bad), (1, 1))

    def test_right_literal_passes(self):
        checked, bad, _u = self.run_case(0.001, 0.001)
        self.assertEqual((checked, bad), (1, 0))

    def test_mov_after_fstp_is_not_an_x87_operand(self):
        # `fstp st(0)` (dd d8) then `mov esi, imm32`: the byte before the
        # field is d8, which the old checker took for an x87 opcode
        checked, bad, _u = self.run_case(1.0, 0.001, prefix=b"\xdd\xd8\xbe")
        self.assertEqual((checked, bad), (0, 0))


class Literals(unittest.TestCase):
    """What _verify_literals reads: the length of the literal a symbol
    names, and the symbol and addend of each relocation."""

    def test_literal_sizes(self):
        size = progress._literal_size
        self.assertEqual(size("??_C@_0L@KLLA@CPlayerObj?$AA@"), 11)
        self.assertEqual(size("??_C@_04JFPK@Body?$AA@"), 5)
        self.assertEqual(size("??_C@_0BI@BCAA@AISpatialRepresentation?$AA@"),
                         24)
        self.assertEqual(size("__real@4@3ff9a3d70a0000000000"), 4)
        self.assertEqual(size("__real@8@3fffc90fdb0000000000"), 8)
        self.assertEqual(size("__real@3f800000"), 4)
        self.assertEqual(size("__real@3ff0000000000000"), 8)
        self.assertIsNone(size("?_M_list@?$_Stl_prime@_N@_STL@@2QBKB"))

    def test_relocation_targets(self):
        # push lit ; push lit+4 ; ret: the second is not the literal
        code = b"\x68\0\0\0\0\x68\x04\0\0\0\xc3"
        from exematch import parse_obj_masked
        targets = {}
        parse_obj_masked(coff(code, [1, 6], b"Body\0\0\0\0"), {}, targets)
        self.assertEqual(targets["_f"], {1: ("_lit", 0), 6: ("_lit", 4)})


class Lengths(unittest.TestCase):
    def test_lengths(self):
        cases = [
            ("d905" + "00" * 4, 6, 2),        # fld dword [abs32]
            ("ddd8", 2, None),                # fstp st(0)
            ("be" + "00" * 4, 5, None),       # mov esi, imm32
            ("8b442404", 4, 3),               # mov eax, [esp+4] (disp8)
            ("c7058c000000" + "00" * 4, 10, 2),  # mov dword [abs], imm32
            ("0fb6c0", 3, None),              # movzx eax, al
            ("66c7050000000001 00".replace(" ", ""), 9, 3),  # mov word [abs], imm16
            ("e8" + "00" * 4, 5, None),       # call rel32
            ("0f84" + "00" * 4, 6, None),     # je rel32
        ]
        for hexs, n, disp in cases:
            ins = x86len.decode(bytes.fromhex(hexs), 0)
            self.assertIsNotNone(ins, hexs)
            self.assertEqual(ins.length, n, hexs)
            self.assertEqual(ins.disp_off, disp, hexs)


class Overlaps(unittest.TestCase):
    def resolve(self, matched, starts, names=None, placed=()):
        progress.PLACED_SYMS.clear()
        for a, n in (names or {}).items():
            progress.PLACED_SYMS[("T", a)] = n
        progress._resolve_overlaps("T", matched, set(placed), set(starts), {},
                                   {}, {}, lambda *a: iter(()), b"", 0)
        return matched

    def test_interior_match_is_dropped(self):
        m = self.resolve({0x1000: 91, 0x1014: 71, 0x101e: 61}, starts={0x1000})
        self.assertEqual(m, {0x1000: 91})

    def test_shared_tail_is_clipped_not_dropped(self):
        m = self.resolve({0x1000: 21, 0x100c: 247}, starts={0x1000, 0x100c})
        self.assertEqual(m, {0x1000: 12, 0x100c: 247})

    def test_start_beats_a_longer_non_start(self):
        m = self.resolve({0x0ff8: 40, 0x1000: 16}, starts={0x1000})
        self.assertEqual(m, {0x1000: 16})

    def test_no_byte_counted_twice(self):
        m = self.resolve({0x1000: 30, 0x1008: 8, 0x1010: 40, 0x1030: 4},
                         starts={0x1000, 0x1010, 0x1030})
        spans = sorted((a, a + n) for a, n in m.items())
        for (a0, e0), (a1, _e1) in zip(spans, spans[1:]):
            self.assertLessEqual(e0, a1)


class SplitTails(unittest.TestCase):
    """progress.py's _merge_split_tails: a start the flow from the row in
    front of it reaches is merged only into a near row whose function of
    ours is long enough to reach it."""
    TVA = 0x1000
    TGT = {"label": "T", "app": [(0x1000, 0x2000)]}

    def merge(self, text, starts, sizes, paired, funcs):
        progress.SPLIT_TAILS.clear()
        sizes = dict(sizes)
        out = progress._merge_split_tails(self.TGT, "T", text, self.TVA,
                                          list(starts), sizes, {}, paired,
                                          set(), funcs, False)
        return out, sizes

    def test_conditional_jump_target_is_a_tail(self):
        # 0: test eax,eax; jne +3; xor eax,eax; ret | 7: mov eax,1; ret
        text = bytes.fromhex("85c0750331c0c3" "b801000000c3")
        out, sizes = self.merge(text, [0x1000, 0x1007], {0x1000: 7,
                                0x1007: 6}, {0x1000: "f"},
                                {"f": (text, set())})
        self.assertEqual(out, [0x1000])
        self.assertEqual(sizes[0x1000], 13)

    def test_inside_an_instruction_is_a_tail(self):
        # 0: mov eax,0x0000c3c3 (b8 c3 c3 00 00): a start at 2 is inside it
        text = bytes.fromhex("b8c3c30000c3")
        out, _s = self.merge(text, [0x1000, 0x1002], {0x1000: 2, 0x1002: 4},
                             {0x1000: "f"}, {"f": (text, set())})
        self.assertEqual(out, [0x1000])

    def test_unconditional_jump_is_no_proof(self):
        # 0: jmp +0 (a tail call to the next function) | 2: ret
        text = bytes.fromhex("eb00c3")
        out, _s = self.merge(text, [0x1000, 0x1002], {0x1000: 2, 0x1002: 1},
                             {0x1000: "f"}, {"f": (text, set())})
        self.assertEqual(out, [0x1000, 0x1002])

    def test_after_a_call_is_no_proof(self):
        # 0: call (may not return) | 5: ret
        text = bytes.fromhex("e800000000c3")
        out, _s = self.merge(text, [0x1000, 0x1005], {0x1000: 5, 0x1005: 1},
                             {0x1000: "f"}, {"f": (text, set())})
        self.assertEqual(out, [0x1000, 0x1005])

    def test_ours_too_short_keeps_the_tail(self):
        text = bytes.fromhex("85c0750331c0c3" "b801000000c3")
        out, _s = self.merge(text, [0x1000, 0x1007], {0x1000: 7, 0x1007: 6},
                             {0x1000: "f"}, {"f": (text[:7], set())})
        self.assertEqual(out, [0x1000, 0x1007])

    def test_not_near_keeps_the_tail(self):
        text = bytes.fromhex("85c0750331c0c3" "b801000000c3")
        out, _s = self.merge(text, [0x1000, 0x1007], {0x1000: 7, 0x1007: 6},
                             {}, {"f": (text, set())})
        self.assertEqual(out, [0x1000, 0x1007])


    def switch(self):
        """A switch whose byte index table the enumeration cut: 0: the
        code, 0x24: the jump table (cases 0x18, 0x1e), 0x2c: its byte
        index table (6 bytes), 0x32: the next function."""
        tva = self.TVA
        code = bytes.fromhex("8b442404" "83f805" "7715" "33c9" "8a88") + \
            struct.pack("<I", tva + 0x2C) + bytes.fromhex("ff248d") + \
            struct.pack("<I", tva + 0x24) + \
            bytes.fromhex("b801000000c3" "33c0c3" "909090") + \
            struct.pack("<II", tva + 0x18, tva + 0x1E) + \
            bytes.fromhex("000101000100")
        return code, code + bytes.fromhex("33c0c3")

    def test_inside_the_switch_tables_is_a_tail(self):
        code, text = self.switch()
        out, sizes = self.merge(text, [0x1000, 0x102f, 0x1032],
                                {0x1000: 0x2f, 0x102f: 3, 0x1032: 3},
                                {0x1000: "f"}, {"f": (code, set())})
        self.assertEqual(out, [0x1000, 0x1032])
        self.assertEqual(sizes[0x1000], 0x32)
        self.assertEqual(progress.SPLIT_TAILS[-1][4], "table")

    def test_a_row_past_the_switch_tables_keeps_the_tail(self):
        # the row runs on into the next function: not only the tables
        code, text = self.switch()
        out, _s = self.merge(text, [0x1000, 0x102f],
                             {0x1000: 0x2f, 0x102f: 6},
                             {0x1000: "f"}, {"f": (code, set())})
        self.assertEqual(out, [0x1000, 0x102f])


class JumpTables(unittest.TestCase):
    """exematch's self-references: a switch's jump table matches where
    each entry names the matching case label of the function at that
    address, not by its masked bytes."""
    BASE = 0x401000

    def obj(self):
        # 0: mov eax,[esp+4]; cmp eax,1; ja 0x16; jmp [eax*4+$Ltab]
        # 0x10: case 0: mov eax,1; ret   0x16: case 1: xor eax,eax; ret
        # 0x1c: $Ltab: dd $L0, $L1
        code = bytes.fromhex("8b442404" "83f801" "770d" "ff2485") + \
            b"\0" * 4 + bytes.fromhex("b801000000c3" "33c0c3" "909090") + \
            b"\0" * 8
        syms = [(b"_f", 0, 0x20, 2), (b"$Ltab", 0x1C, 0, 6),
                (b"$L0", 0x10, 0, 6), (b"$L1", 0x16, 0, 6)]
        relocs = [(0x0C, 1), (0x1C, 2), (0x20, 3)]
        sym_p = 20 + 40 + len(code) + 10 * len(relocs)
        out = bytearray(struct.pack("<HHIIIHH", 0x14C, 1, 0, sym_p, len(syms),
                                    0, 0))
        out += struct.pack("<8sIIIIIIHHI", b".text", 0, 0, len(code), 60,
                           60 + len(code), 0, len(relocs), 0, 0x60000020)
        out += code
        for off, sym in relocs:
            out += struct.pack("<IIH", off, sym, DIR32)
        for name, val, typ, st in syms:
            out += struct.pack("<8sIhHBB", name, val, 1, typ, st, 0)
        out += struct.pack("<I", 4)
        from exematch import parse_obj_masked
        return parse_obj_masked(bytes(out))["_f"]

    def linked(self, at, tab, cases):
        code = bytearray(bytes.fromhex("8b442404" "83f801" "770d" "ff2485") +
                         struct.pack("<I", tab) +
                         bytes.fromhex("b801000000c3" "33c0c3" "909090") +
                         struct.pack("<II", *cases))
        return bytes(code)

    def hits(self, text):
        from exematch import find
        code, mask = self.obj()
        return list(find(text, self.BASE, code, mask))

    def test_self_references(self):
        _code, mask = self.obj()
        self.assertEqual(mask.selfrefs, {0x0C: (True, 0x1C),
                                         0x1C: (True, 0x10),
                                         0x20: (True, 0x16)})

    def test_another_builds_copy_is_off_by_one_amount(self):
        # a target's `readable` pages: another build's bytes copied to the
        # shipped address; its table names its cases at that build's
        # address, all of them 0x30 lower
        b = self.BASE
        text = self.linked(b, b - 0x30 + 0x1C, (b - 0x30 + 0x10,
                                                b - 0x30 + 0x16))
        from exematch import find
        code, mask = self.obj()
        self.assertEqual(self.hits(text), [])
        self.assertEqual(list(find(text, b, code, mask, lambda a: True)), [b])
        text = self.linked(b, b - 0x30 + 0x1C, (b - 0x30 + 0x16,
                                                b - 0x30 + 0x10))
        self.assertEqual(list(find(text, b, code, mask, lambda a: True)), [])

    def test_recursive_call_through_a_thunk(self):
        # an incremental link's recursive call: to the function's own
        # `jmp rel32` thunk, which is the same place; to another, it is not
        from exematch import Mask, find
        b = self.BASE
        # 0: a thunk, jmp 0x10 | 0x10: f: call f; xor eax,eax; ret ...
        code = bytes.fromhex("e8fbffffff") + bytes.fromhex("33c0c3d9c0d9c0d9c0c3")
        mask = Mask(range(1, 5), {1: (False, 0)})
        thunk = bytes.fromhex("e90b000000") + b"\xcc" * 11      # jmp +0x0b -> 0x10
        direct = bytes.fromhex("e8fbffffff") + code[5:]
        via = bytes.fromhex("e8ebffffff") + code[5:]           # call 0x0
        self.assertEqual(list(find(thunk + direct, b, code, mask)), [b + 0x10])
        self.assertEqual(list(find(thunk + via, b, code, mask)), [b + 0x10])
        other = bytes.fromhex("e90b010000") + b"\xcc" * 11      # elsewhere
        self.assertEqual(list(find(other + via, b, code, mask)), [])

    def test_entries_naming_its_cases_match(self):
        b = self.BASE
        text = self.linked(b, b + 0x1C, (b + 0x10, b + 0x16))
        self.assertEqual(self.hits(text), [b])

    def test_entries_naming_other_cases_do_not(self):
        b = self.BASE
        text = self.linked(b, b + 0x1C, (b + 0x16, b + 0x10))
        self.assertEqual(self.hits(text), [])

    def test_a_copy_naming_another_function_does_not(self):
        # the same bytes at 0x40, so its table names the first copy's cases
        b = self.BASE
        one = self.linked(b, b + 0x1C, (b + 0x10, b + 0x16))
        text = one.ljust(0x40, b"\xcc") + one
        self.assertEqual(self.hits(text), [b])


class WholeImage(unittest.TestCase):
    def test_time_stamps_only(self):
        t = Tmp()
        text = b"\x55\x8b\xec\x5d\xc3"
        a = t.write("a.exe", pe(text, b"x" * 8, stamp=1))
        b = t.write("b.exe", pe(text, b"x" * 8, stamp=2))
        c = t.write("c.exe", pe(text, b"y" * 8, stamp=1))
        old = progress.REPO
        progress.REPO = "/"
        try:
            self.assertTrue(progress.whole_image_identical({"shipped": a}, b))
            self.assertFalse(progress.whole_image_identical({"shipped": a}, c))
        finally:
            progress.REPO = old


class DataCheck(unittest.TestCase):
    def test_known_and_new(self):
        import collections
        diff = {("x.dll", "retail"): collections.Counter({"a": 1, "b": 2}),
                ("x.dll", "ours"): collections.Counter()}
        known = [("x.dll", "retail", "a", "#"), ("x.dll", "retail", "b", "#"),
                 ("x.dll", "retail", "gone", "#")]
        new, fixed = datacheck.compare(diff, known)
        self.assertEqual(dict(new), {("x.dll", "retail", "b"): 1})
        self.assertEqual(dict(fixed), {("x.dll", "retail", "gone"): 1})

    def test_wildcard(self):
        import collections
        diff = {("x.dll", "retail"): collections.Counter({"a": 3})}
        new, _f = datacheck.compare(diff, [("x.dll", "retail", "*", "#")])
        self.assertFalse(new)


if __name__ == "__main__":
    unittest.main()


REL32 = 0x14


def coff_funcs(funcs):
    """A COFF object: one .text section that holds each function of
    `funcs`, [(name, code, [(offset, symbol, relocation type)])], at a
    16-aligned offset (0xCC between them). A symbol a relocation names
    that no function defines is an external."""
    text, at = bytearray(), {}
    for name, code, _r in funcs:
        text += b"\xcc" * (-len(text) % 16)
        at[name] = len(text)
        text += code
    names = [n for n, _c, _r in funcs]
    for _n, _c, rel in funcs:
        for _o, s, _k in rel:
            if s not in names:
                names.append(s)
    strtab = bytearray(b"\0\0\0\0")
    syms = bytearray()
    for n in names:
        b = n.encode()
        if len(b) <= 8:
            raw = b.ljust(8, b"\0")
        else:
            raw = struct.pack("<II", 0, len(strtab))
            strtab += b + b"\0"
        sec = 1 if n in at else 0
        syms += raw + struct.pack("<IhHBB", at.get(n, 0), sec, 0x20, 2, 0)
    struct.pack_into("<I", strtab, 0, len(strtab))
    relocs = bytearray()
    nrel = 0
    for n, _c, rel in funcs:
        for o, s, k in rel:
            relocs += struct.pack("<IIH", at[n] + o, names.index(s), k)
            nrel += 1
    text_p = 20 + 40
    rel_p = text_p + len(text)
    sym_p = rel_p + len(relocs)
    out = bytearray(struct.pack("<HHIIIHH", 0x14C, 1, 0, sym_p, len(names),
                                0, 0))
    out += struct.pack("<8sIIIIIIHHI", b".text", 0, 0, len(text), text_p,
                       rel_p, 0, nrel, 0, 0x60000020)
    out += text + relocs + syms + strtab
    return bytes(out)


def body(seed, n=40):
    """`n` bytes of straight-line code, different for each seed (x87
    register moves and `mov eax, imm32`), ending in `ret`."""
    out = bytearray()
    while len(out) < n - 6:
        out += bytes([0xB8]) + struct.pack("<I", (seed * 2654435761 +
                                                  len(out)) & 0x7FFFFFFF)
    return bytes(out[:n - 1]).ljust(n - 1, b"\x90").replace(
        b"\x90", b"\xd9") + b"\xc3"


class Image:
    """A shipped image or our link of one: functions placed at fixed
    offsets in .text (base 0x400000, .text at 0x401000), each call a
    `call rel32` to another of them."""
    BASE = 0x401000

    def __init__(self, layout, size=0x400):
        # layout: [(offset, name, code, [(offset in code, callee)])]
        self.at = {n: self.BASE + o for o, n, _c, _r in layout}
        text = bytearray(b"\xcc" * size)
        for o, n, code, calls in layout:
            text[o:o + len(code)] = code
            for co, callee in calls:
                struct.pack_into("<i", text, o + co,
                                 self.at[callee] - (self.BASE + o + co + 4))
        self.text = bytes(text)
        self.rdata = b"\0" * 16
        self.data_syms = {}          # name -> address, for the map


class Rows(unittest.TestCase):
    """_rows_for_image end to end: a shipped image, our objects, our
    linked image and its map."""

    def score(self, shipped, ours, objs):
        """shipped, ours: Image. objs: {file name: coff bytes}. The map
        lists what `ours` places, under the object that defines it."""
        t = Tmp()
        sp = t.write("ship.exe", pe(shipped.text, shipped.rdata))
        op = t.write("ours.exe", pe(ours.text, ours.rdata))
        paths = [t.write(n, d) for n, d in objs.items()]
        owner = {}
        from exematch import parse_obj_masked
        for n, d in objs.items():
            for f in parse_obj_masked(d):
                owner.setdefault(f, n)
        mp = t.write("ours.map", "".join(
            " 0001:%08x       %s %08x f   %s\n" % (a - Image.BASE, n, a,
                                                   owner[n])
            for n, a in sorted(ours.at.items(), key=lambda kv: kv[1])
            if n in owner).encode() + "".join(
            " 0002:%08x       %s %08x     x.obj\n" % (a - 0x402000, n, a)
            for n, a in sorted(ours.data_syms.items())).encode())
        tgt = dict(label="T.exe", kind="image", shipped=sp, built=op,
                   stem="T", app=[(0x401000, 0x402000)])
        progress.BY_LABEL["T.exe"] = tgt
        for d in (progress.PLACED_SYMS, progress.SMALL_SYMS):
            for k in [k for k in d if k[0] == "T.exe"]:
                del d[k]
        progress.NEAR_PAIRS[:] = [r for r in progress.NEAR_PAIRS
                                  if r[0] != "T.exe"]
        self.last = (paths, mp, None)
        rows = progress._rows_for_image(tgt, paths, mp, None)
        status = {int(n[4:], 16): st for _l, n, _s, st in rows
                  if n.startswith("sub_")}
        near = {r[1]: r[3].split(":", 1)[1] for r in progress.NEAR_PAIRS
                if r[0] == "T.exe"}
        ident = {a: n.split(":", 1)[1]
                 for (l, a), n in progress.PLACED_SYMS.items()
                 if l == "T.exe" and status.get(a) == "identical"}
        return status, near, ident, rows

    @staticmethod
    def caller(names):
        """A function that calls each of `names` (so each is a start)."""
        code = bytearray()
        for i, _n in enumerate(names):
            code += b"\xe8\0\0\0\0"
        code += b"\xc3"
        return bytes(code), [(1 + 5 * i, n) for i, n in enumerate(names)]

    def test_unlinked_code_takes_no_address_from_linked_code(self):
        # A, B: identical in both images (the anchors). P: the shipped
        # function between them. L: ours of it, in our link between A and
        # B, too different to pair by content. U: a function our link
        # leaves out, whose bytes agree with P's on more than half: by
        # content it would take P, and L would stay unplaced.
        a, b = body(1), body(2)
        p = body(3, 64)
        u = bytearray(p)
        for i in range(0, 64, 7):
            u[i] ^= 0x01             # agrees on most bytes, matches nowhere
        u[-1] = 0xC3
        l = body(4, 56)
        root, calls = self.caller(["_a", "_p", "_b"])
        shipped = Image([(0x000, "_a", a, []), (0x040, "_p", p, []),
                         (0x080, "_b", b, []), (0x100, "_root", root, calls)])
        ours = Image([(0x000, "_a", a, []), (0x040, "_l", l, []),
                      (0x080, "_b", b, [])])
        objs = {"x.obj": coff_funcs([("_a", a, []), ("_l", l, []),
                                     ("_b", b, [])]),
                "y.obj": coff_funcs([("_u", bytes(u), [])])}
        status, near, ident, rows = self.score(shipped, ours, objs)
        p_at = shipped.at["_p"]
        self.assertEqual(ident.get(shipped.at["_a"]), "_a")
        self.assertEqual(status.get(p_at), "near")
        self.assertEqual(near.get(p_at), "_l")
        self.assertNotIn(("T.exe", "y.obj:_u", len(u), "near"), rows)
        self.assertFalse(any(n.endswith(":_l") and st == "unplaced"
                             for _l, n, _s, st in rows))

    def test_unlinked_code_pairs_where_nothing_linked_does(self):
        # the same U, with nothing of our link for P: it pairs there
        a, b = body(1), body(2)
        p = body(3, 64)
        u = bytearray(p)
        for i in range(0, 64, 7):
            u[i] ^= 0x01
        u[-1] = 0xC3
        root, calls = self.caller(["_a", "_p", "_b"])
        shipped = Image([(0x000, "_a", a, []), (0x040, "_p", p, []),
                         (0x080, "_b", b, []), (0x100, "_root", root, calls)])
        ours = Image([(0x000, "_a", a, []), (0x080, "_b", b, [])])
        objs = {"x.obj": coff_funcs([("_a", a, []), ("_b", b, [])]),
                "y.obj": coff_funcs([("_u", bytes(u), [])])}
        status, near, _ident, _rows = self.score(shipped, ours, objs)
        self.assertEqual(near.get(shipped.at["_p"]), "_u")

    def look_alikes(self, ours_calls):
        """Two shipped copies of one shape, F1 calling X and F2 calling Y
        (X and Y unique). Ours: X, Y and one copy calling `ours_calls`."""
        x, y = body(5), body(6)
        f = b"\xe8\0\0\0\0" + body(7, 48)
        root, calls = self.caller(["_f1", "_f2"])
        shipped = Image([(0x000, "_x", x, []), (0x040, "_y", y, []),
                         (0x080, "_f1", f, [(1, "_x")]),
                         (0x0c0, "_f2", f, [(1, "_y")]),
                         (0x100, "_root", root, calls)])
        ours = Image([(0x000, "_x", x, []), (0x040, "_y", y, []),
                      (0x080, "_f", f, [(1, ours_calls)])])
        objs = {"x.obj": coff_funcs([("_x", x, []), ("_y", y, []),
                                     ("_f", f, [(1, ours_calls, REL32)])])}
        return shipped, self.score(shipped, ours, objs)

    def test_look_alikes_are_chosen_by_what_they_call(self):
        # name order and the object's anchors put ours at F1, which
        # calls X; ours calls Y, so it is F2
        shipped, (status, _near, ident, _rows) = self.look_alikes("_y")
        self.assertEqual(ident.get(shipped.at["_f2"]), "_f")
        self.assertNotEqual(status.get(shipped.at["_f1"]), "identical")
        shipped, (status, _near, ident, _rows) = self.look_alikes("_x")
        self.assertEqual(ident.get(shipped.at["_f1"]), "_f")
        self.assertNotEqual(status.get(shipped.at["_f2"]), "identical")

    def test_a_second_run_starts_from_nothing(self):
        # three shipped copies (calling X, Y and Z), two of ours (calling Y
        # and X), scored twice as an image with remainders is: the second
        # run must not keep the first run's names at the addresses
        x, y, z = body(5), body(6), body(8)
        f = b"\xe8\0\0\0\0" + body(7, 48)
        root, calls = self.caller(["_h1", "_h2", "_h3", "_z"])
        shipped = Image([(0x000, "_x", x, []), (0x040, "_y", y, []),
                         (0x080, "_h1", f, [(1, "_y")]),
                         (0x0c0, "_h2", f, [(1, "_x")]),
                         (0x100, "_h3", f, [(1, "_z")]),
                         (0x140, "_root", root, calls),
                         (0x180, "_z", z, [])])
        ours = Image([(0x000, "_x", x, []), (0x040, "_y", y, []),
                      (0x080, "_g1", f, [(1, "_x")]),
                      (0x0c0, "_g2", f, [(1, "_y")]),
                      (0x100, "_z", z, [])])
        objs = {"x.obj": coff_funcs([("_x", x, []), ("_y", y, []),
                                     ("_g1", f, [(1, "_x", REL32)]),
                                     ("_g2", f, [(1, "_y", REL32)]),
                                     ("_z", z, [])])}
        first = self.score(shipped, ours, objs)
        tgt = progress.BY_LABEL["T.exe"]
        rows = progress._rows_for_image(tgt, *self.last)
        self.assertEqual(sorted(rows), sorted(first[3]))
        self.assertEqual(first[2].get(shipped.at["_h1"]), "_g2")
        self.assertEqual(first[2].get(shipped.at["_h2"]), "_g1")
        self.assertNotEqual(first[0].get(shipped.at["_h3"]), "identical")

    def test_look_alikes_are_chosen_by_their_vtables(self):
        # two shipped copies of a constructor shape, each storing its own
        # class's vtable; the vtables are different in one slot, `mov
        # eax, 4; ret` against `mov eax, 8; ret` (a GetType). Ours stores
        # the vtable whose slot is ours of the second: it is the second
        # copy, though nothing maps either vtable
        g4, g8 = bytes.fromhex("b804000000c3"), bytes.fromhex("b808000000c3")
        f = bytes.fromhex("c701") + b"\0" * 4 + body(7, 48)
        root, calls = self.caller(["_c1", "_c2"])
        shipped = Image([(0x000, "_g4", g4, []), (0x010, "_g8", g8, []),
                         (0x080, "_c1", f, []), (0x0c0, "_c2", f, []),
                         (0x100, "_root", root, calls)])
        text = bytearray(shipped.text)
        struct.pack_into("<I", text, 0x082, 0x402000)
        struct.pack_into("<I", text, 0x0c2, 0x402010)
        shipped.text = bytes(text)
        shipped.rdata = struct.pack("<IIII", shipped.at["_g4"], 0, 0, 0) + \
            struct.pack("<IIII", shipped.at["_g8"], 0, 0, 0)
        ours = Image([(0x010, "_g8", g8, []), (0x080, "_c", f, [])])
        text = bytearray(ours.text)
        struct.pack_into("<I", text, 0x082, 0x402000)
        ours.text = bytes(text)
        ours.rdata = struct.pack("<IIII", ours.at["_g8"], 0, 0, 0)
        ours.data_syms = {"??_7B@@6B@": 0x402000}
        objs = {"x.obj": coff_funcs([("_g8", g8, []),
                                     ("_c", f, [(2, "??_7B@@6B@", DIR32)])])}
        status, _near, ident, _rows = self.score(shipped, ours, objs)
        self.assertEqual(ident.get(shipped.at["_c2"]), "_c")
        self.assertNotEqual(status.get(shipped.at["_c1"]), "identical")

    def test_functions_the_shipped_link_folds_are_one(self):
        # two functions of ours with the same bytes, both calling X: the
        # shipped link's /OPT:ICF keeps one copy (F1). F2 calls Y. One of
        # ours is identical at F1, the other is the same function (not
        # unplaced, nor paired near at F2, which is a function we lack)
        x, y = body(5), body(6)
        f = b"\xe8\0\0\0\0" + body(7, 48)
        root, calls = self.caller(["_f1", "_f2"])
        shipped = Image([(0x000, "_x", x, []), (0x040, "_y", y, []),
                         (0x080, "_f1", f, [(1, "_x")]),
                         (0x0c0, "_f2", f, [(1, "_y")]),
                         (0x100, "_root", root, calls)])
        ours = Image([(0x000, "_x", x, []), (0x040, "_y", y, []),
                      (0x080, "_a", f, [(1, "_x")]),
                      (0x0c0, "_b", f, [(1, "_x")])])
        objs = {"x.obj": coff_funcs([("_x", x, []), ("_y", y, []),
                                     ("_a", f, [(1, "_x", REL32)]),
                                     ("_b", f, [(1, "_x", REL32)])])}
        status, _near, ident, rows = self.score(shipped, ours, objs)
        self.assertIn(ident.get(shipped.at["_f1"]), ("_a", "_b"))
        self.assertEqual(status.get(shipped.at["_f2"]), "todo")
        self.assertFalse([r for r in rows if r[3] == "unplaced"])

    def test_chosen_hits_do_not_overlap(self):
        # A (0x50 bytes) ends with B's bytes. Shipped: A1 at 0x080 calls
        # X and Y, so B's shape is also at 0x0b0, an enumerated start
        # (something calls it) inside A1; A2 at 0x100 calls Z and W; B
        # alone at 0x180 (no start: nothing calls it) calls Y. Ours: A
        # calls X and Y, B calls Y. B's operands agree at 0x0b0 and at
        # 0x180, and 0x0b0 is a start, but A has it: B keeps 0x180
        x, y = body(5), body(6)
        z, w, v = body(10), body(11), body(12)
        b = b"\xe8\0\0\0\0" + body(7, 0x1b)
        a = b"\xe8\0\0\0\0" + body(8, 0x2b) + b
        root, calls = self.caller(["_a1", "_b0", "_a2"])
        shipped = Image([(0x000, "_x", x, []), (0x040, "_y", y, []),
                         (0x080, "_a1", a, [(1, "_x"), (0x31, "_y")]),
                         (0x0b0, "_b0", b"", []),
                         (0x100, "_a2", a, [(1, "_z"), (0x31, "_w")]),
                         (0x180, "_b2", b, [(1, "_y")]),
                         (0x1c0, "_root", root, calls),
                         (0x200, "_z", z, []), (0x240, "_w", w, []),
                         (0x280, "_v", v, [])], size=0x300)
        ours = Image([(0x000, "_x", x, []), (0x040, "_y", y, []),
                      (0x080, "_a", a, [(1, "_x"), (0x31, "_y")]),
                      (0x100, "_b", b, [(1, "_y")])])
        objs = {"x.obj": coff_funcs([
            ("_x", x, []), ("_y", y, []),
            ("_a", a, [(1, "_x", REL32), (0x31, "_y", REL32)]),
            ("_b", b, [(1, "_y", REL32)])])}
        status, _near, ident, _rows = self.score(shipped, ours, objs)
        self.assertEqual(ident.get(shipped.at["_a1"]), "_a")
        self.assertEqual(ident.get(shipped.at["_b2"]), "_b")

    def test_look_alikes_that_name_other_things_are_identical_nowhere(self):
        # ours calls Z, which is placed (identical) at neither callee
        x, y, z = body(5), body(6), body(8)
        f = b"\xe8\0\0\0\0" + body(7, 48)
        root, calls = self.caller(["_f1", "_f2", "_z"])
        shipped = Image([(0x000, "_x", x, []), (0x040, "_y", y, []),
                         (0x080, "_f1", f, [(1, "_x")]),
                         (0x0c0, "_f2", f, [(1, "_y")]),
                         (0x100, "_root", root, calls),
                         (0x140, "_z", z, [])])
        ours = Image([(0x000, "_x", x, []), (0x040, "_y", y, []),
                      (0x080, "_f", f, [(1, "_z")]), (0x0c0, "_z", z, [])])
        objs = {"x.obj": coff_funcs([("_x", x, []), ("_y", y, []),
                                     ("_f", f, [(1, "_z", REL32)]),
                                     ("_z", z, [])])}
        status, _near, ident, _rows = self.score(shipped, ours, objs)
        self.assertEqual(ident.get(shipped.at["_z"]), "_z")
        self.assertNotEqual(status.get(shipped.at["_f1"]), "identical")
        self.assertNotEqual(status.get(shipped.at["_f2"]), "identical")


class TailJumpStarts(unittest.TestCase):
    """enumfuncs rule 4h: a function after padding that only a `jmp
    rel32` or a `mov r32, imm32` reaches is a start; a jump to a label
    inside a function is not."""

    def starts(self, text):
        from enumfuncs import Image as EImage, enumerate_functions
        t = Tmp()
        p = t.write("t.exe", pe(text, b"\0" * 16))
        return set(enumerate_functions(EImage(p))[0])

    def test_tail_jump_and_loaded_address(self):
        b = 0x401000
        text = bytearray(b"\xcc" * 0x100)
        # 0x00: called; mov ecx,[ecx+0x54]; test ecx,ecx; je +5; jmp 0x30;
        #       xor eax,eax; ret
        text[0x00:0x0c] = bytes.fromhex("8b495485c97405e9") + \
            struct.pack("<i", 0x30 - 0x0c)
        text[0x0c:0x0f] = bytes.fromhex("33c0c3")
        # 0x20: ... ret 4; then padding; 0x30: mov eax,[ecx+0x14]; ret
        text[0x20:0x23] = bytes.fromhex("c20400")
        text[0x30:0x34] = bytes.fromhex("8b4114c3")
        # 0x40: mov eax, 0x401060; ret | 0x60: mov eax,[ecx]; jmp [eax+0x64]
        text[0x3f] = 0xC3
        text[0x40:0x46] = b"\xb8" + struct.pack("<I", b + 0x60) + b"\xc3"
        text[0x60:0x65] = bytes.fromhex("8b01ff6064")
        # 0x80: called: xor eax,eax; jmp 0x88 (a label inside it)
        text[0x80:0x87] = b"\x33\xc0\xe9" + struct.pack("<i", 0x88 - 0x87)
        text[0x87:0x8b] = bytes.fromhex("40" "40" "40" "c3")
        # the calls that make 0x00, 0x20, 0x40 and 0x80 starts
        calls = bytearray()
        for i, t0 in enumerate((0x00, 0x20, 0x40, 0x80)):
            calls += b"\xe8" + struct.pack("<i", t0 - (0xc0 + 5 * i + 5))
        text[0xc0:0xc0 + len(calls)] = calls
        text[0x1f] = 0xC3
        s = self.starts(bytes(text))
        self.assertIn(b + 0x30, s)
        self.assertIn(b + 0x60, s)
        self.assertNotIn(b + 0x88, s)

    def test_no_start_without_padding_after_a_ret(self):
        # the same jump to a 16-aligned address that runs on from the code
        # in front (no ret, no padding): a label, not a start
        b = 0x401000
        text = bytearray(b"\xcc" * 0x100)
        text[0x00:0x07] = b"\x33\xc0\xe9" + struct.pack("<i", 0x30 - 0x07)
        text[0x07:0x30] = b"\x40" * 0x29
        text[0x30:0x32] = bytes.fromhex("33c0")
        text[0x32] = 0xC3
        text[0xc0:0xc5] = b"\xe8" + struct.pack("<i", 0x00 - 0xc5)
        s = self.starts(bytes(text))
        self.assertNotIn(b + 0x30, s)
