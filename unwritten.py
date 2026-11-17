#!/usr/bin/env python3
"""False-variable finder: our globals that no code of ours writes, but whose
shipped address the shipped code writes (or the reverse).

  unwritten.py <our dis> <our map> <ship dis> <ship-names.txt>
"""
import re
import sys

ourdis, ourmap, shipdis, shipnames = sys.argv[1:5]
WR = re.compile(r"^\s*([0-9a-f]+):\s+(?:[0-9a-f]{2} )+\s*(mov[a-z]*|fst[a-z]*|fist[a-z]*|inc[a-z]*|dec[a-z]*|add[a-z]*|sub[a-z]*|or[a-z]*|and[a-z]*|xor[a-z]*|set[a-z]+|shl|shr|sar|neg|not|xchg|lea)\s+(.*)$")


def written(dis):
    w = set()
    for line in open(dis):
        m = WR.match(line.replace("\t", " "))
        if not m:
            continue
        ops = m.group(3)
        if m.group(2) == "lea":
            mm = re.search(r"(0x[0-9a-f]{6,8})\(", ops)
            if mm:
                w.add(int(mm.group(1), 16))
            continue
        # destination is the last operand (AT&T); an absolute address
        parts = ops.split(",")
        dst = parts[-1].strip()
        if re.fullmatch(r"0x[0-9a-f]{6,8}", dst) or (len(parts) == 1 and re.fullmatch(r"0x[0-9a-f]{6,8}", dst)):
            w.add(int(dst, 16))
        mm = re.fullmatch(r"(0x[0-9a-f]{6,8})\(.*\)", dst)
        if mm:
            w.add(int(mm.group(1), 16))
        # movl $addr: an address taken (pointer stored) counts as written
        for a in re.findall(r"\$(0x[0-9a-f]{6,8})", ops):
            w.add(int(a, 16))
    for line in open(dis):
        for a in re.findall(r"push\s+\$(0x[0-9a-f]{6,8})", line):
            w.add(int(a, 16))
    return w


ours = {}
for line in open(ourmap, errors="replace"):
    m = re.match(r"\s*000([3-9]):[0-9a-f]{8}\s+(\S+)\s+([0-9a-f]{8})", line)
    if m:
        ours[m.group(2)] = int(m.group(3), 16)
ship = {}
for line in open(shipnames):
    a, n = line.split(None, 1)
    ship[n.strip()] = int(a, 16)
wo = written(ourdis)
ws = written(shipdis)


def near(ws, a):
    return any(x in ws for x in range(a - 0, a + 4))


for n, a in sorted(ours.items(), key=lambda x: x[1]):
    if n not in ship or n.startswith("??_") or n.startswith("__real"):
        continue
    so, ss = near(wo, a), near(ws, ship[n])
    if so != ss:
        print("%-60s ours %#x written=%d  ship %#x written=%d" % (n[:60], a, so, ship[n], ss))
