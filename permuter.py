#!/usr/bin/env python3
"""Source permuter for MSVC 6 (cl 12.00.x under Wine, in a build container).

The permuter takes one function of a game repository. It makes equivalent
variants of the function's C++ source with mechanical mutations, compiles
each variant to an object, and keeps the variant whose code is nearest to
retail. Use it on a near that differs only in register allocation or
instruction order: the cases that are slow to solve by hand. It is in the
spirit of decomp-permuter (simonlindholm), but for VC6 and C++.

The permuter does not write into the game repository. It mounts the
repository read-only in the build container and puts the variant source on
top of the original file with a bind mount, so that the compile sees the
same paths, the same precompiled header and the same flags as the build.
You apply a diff that it finds by hand.

Usage:
  permuter.py --repo <repo> --obj <obj> --symbol <mangled> --addr <0xVA>
              [--image <target or image>] [--end <0xVA|+size>]
              [--target-obj <obj>] [--func <Class::Name>] [--line <n>]
              [--workers <n>] [--time <seconds>] [--tries <n>] [--seed <n>]
              [--out <dir>] [--docker-image <name>] [--loose] [--keep]

  --repo       the game repository (mounted read-only at /repo).
  --obj        our object, relative to --repo. Its compile command must be
               in <obj>.cmd, as build.mk writes it (`cd <dir> && VAR=..
               wine <cl.exe> <flags> <source>`), or give --cmd <file>.
  --symbol     the function's symbol in the object (a substring is enough,
               but give the full mangled name).
  --addr       the retail address of the function.
  --image      the retail image: a target of progress/targets.py (tgt.py)
               or a path. --end, or the image's function table, gives the
               size (as for fndiff.py).
  --target-obj compare against this object's --symbol instead of a retail
               image (for tests, and to match a known-good variant).
  --func       the qualified name in the source (default: from --symbol).
  --line       the line of the definition, if the name has overloads.
  --root       the in-container directory that <obj>.cmd's `cd` is
               relative to (default: from its WINEPREFIX, else /repo).
  --mount      HOST:CONTAINER, an extra read-only mount (more than one is
               permitted).
  --strict     do not swap two statements that both call a function (the
               order of their side effects can change).
  --types      more types for new temporaries, separated by commas
               ("HOBJECT,const WEAPON*"). The permuter also takes the
               types of the parameters, the locals and the return value.
  --loose      also commute the operands of && and ||.
               Only an identical result is a proof of equivalence.
  --keep       do not delete the scratch directory.
  --no-simplify  do not simplify the best form. (By default, when the best
               form is better than the original, the permuter puts back
               each changed group of lines that the score does not need.)

The score is 0 for code that is byte-identical (relocations masked, the
rule of fndiff.py). Otherwise it is 8 x (the mnemonic diff after the best
renaming of ebx/esi/edi) + (the mnemonic diff without renaming) + (the
number of aligned instructions whose bytes differ) + 2 x (the difference
in size, in bytes) + 1. Lower is better.

Output: <out>/best.cpp, <out>/best.diff (a unified diff of the source
against the original, with the path of the source in the tree), and
<out>/log.txt. The diff is also printed at the end.

The guide is guides/22_permuter.md.
"""
import argparse
import atexit
import difflib
import hashlib
import itertools
import math
import os
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
fndiff = None


def load_fndiff(repo=None):
    """Import fndiff.py (its listing and diff). fndiff reads the project's
    progress/targets.py at import: TOOLS_PROJECT names the project, and a
    project without one (a test) gets an empty stub."""
    global fndiff
    if fndiff is not None:
        return fndiff
    if repo:
        os.environ["TOOLS_PROJECT"] = repo
    import layout
    if not os.path.exists(os.path.join(layout.PROJECT, "progress", "targets.py")) \
            and "targets" not in sys.modules:
        import types
        stub = types.ModuleType("targets")
        stub.REFERENCE, stub.OUT, stub.DATA = "out/reference", "out/progress", "progress"
        stub.TARGETS, stub.LIBS, stub.DRIVER_OBJS, stub.SHIPPED_ENV = [], [], set(), None
        sys.modules["targets"] = stub
    import fndiff as m
    fndiff = m
    return m


# ---------------------------------------------------------------------------
# Tokenizer

_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<pp>\#(?:[^\n\\]|\\.)*)
  | (?P<str>L?"(?:[^"\\\n]|\\.)*"|L?'(?:[^'\\\n]|\\.)*')
  | (?P<num>0[xX][0-9a-fA-F]+[a-zA-Z]*|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?[a-zA-Z]*)
  | (?P<id>[A-Za-z_]\w*)
  | (?P<op>->\*|<<=|>>=|\.\.\.|::|->|\+\+|--|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%&|^]=|\.\*|.)
""", re.S | re.X)


class Tok:
    __slots__ = ("kind", "text", "start", "end")

    def __init__(self, kind, text, start, end):
        self.kind, self.text, self.start, self.end = kind, text, start, end

    def __repr__(self):
        return f"Tok({self.kind},{self.text!r})"


def tokenize(text):
    """The significant tokens of `text` (no white space, comments or
    preprocessor lines), each with its span in `text`."""
    out = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        kind = m.lastgroup
        if kind == "pp" and text[:pos].rstrip(" \t")[-1:] not in ("", "\n"):
            # a '#' that does not start a line: an operator (stringize)
            out.append(Tok("op", "#", pos, pos + 1))
            pos += 1
            continue
        if kind not in ("ws", "comment", "pp"):
            out.append(Tok(kind, m.group(), m.start(), m.end()))
        pos = m.end()
    return out


OPEN = {"(": ")", "[": "]", "{": "}"}
CLOSE = {")", "]", "}"}

KEYWORDS = {
    "if", "else", "for", "while", "do", "switch", "case", "default", "break",
    "continue", "return", "goto", "try", "catch", "throw", "new", "delete",
    "sizeof", "this", "true", "false", "operator", "typedef", "struct",
    "class", "union", "enum", "static_cast", "const_cast", "dynamic_cast",
    "reinterpret_cast", "typeid", "__asm", "_asm",
}
TYPE_WORDS = {"const", "volatile", "unsigned", "signed", "int", "char",
              "short", "long", "float", "double", "bool", "void", "static",
              "register", "struct", "class", "enum"}


def match_close(toks, i):
    """The index of the bracket that closes toks[i]."""
    want = OPEN[toks[i].text]
    stack = [want]
    j = i + 1
    while j < len(toks):
        t = toks[j].text
        if t in OPEN:
            stack.append(OPEN[t])
        elif t in CLOSE:
            if t != stack[-1]:
                raise ValueError(f"unbalanced {t!r} at offset {toks[j].start}")
            stack.pop()
            if not stack:
                return j
        j += 1
    raise ValueError("unbalanced brackets")


# ---------------------------------------------------------------------------
# Statements: a light parser over the tokens of a function body

class Stmt:
    """A statement over toks[a..b] (inclusive). kind is one of: block, if,
    for, while, do, switch, try, label, simple. Children: `body` (the
    statements of a block), `cond` (the bracket pair of if/for/while/switch),
    `then`, `els`, `sub` (the body of a loop or switch)."""

    def __init__(self, kind, a, b, **kw):
        self.kind, self.a, self.b = kind, a, b
        self.body = kw.get("body", [])
        self.cond = kw.get("cond")
        self.then = kw.get("then")
        self.els = kw.get("els")
        self.sub = kw.get("sub")

    def __repr__(self):
        return f"Stmt({self.kind},{self.a},{self.b})"


def parse_stmt(toks, i):
    t = toks[i].text
    if t == "{":
        j = match_close(toks, i)
        return Stmt("block", i, j, body=parse_seq(toks, i + 1, j))
    if t == "if" and toks[i + 1].text == "(":
        rp = match_close(toks, i + 1)
        then = parse_stmt(toks, rp + 1)
        els = None
        end = then.b
        if end + 1 < len(toks) and toks[end + 1].text == "else":
            els = parse_stmt(toks, end + 2)
            end = els.b
        return Stmt("if", i, end, cond=(i + 1, rp), then=then, els=els)
    if t in ("for", "while", "switch") and toks[i + 1].text == "(":
        rp = match_close(toks, i + 1)
        sub = parse_stmt(toks, rp + 1)
        return Stmt(t, i, sub.b, cond=(i + 1, rp), sub=sub)
    if t == "do":
        sub = parse_stmt(toks, i + 1)
        w = sub.b + 1
        if toks[w].text != "while":
            raise ValueError("do without while")
        rp = match_close(toks, w + 1)
        return Stmt("do", i, rp + 1, cond=(w + 1, rp), sub=sub)
    if t == "try":
        blk = parse_stmt(toks, i + 1)
        end = blk.b
        while end + 1 < len(toks) and toks[end + 1].text == "catch":
            rp = match_close(toks, end + 2)
            end = parse_stmt(toks, rp + 1).b
        return Stmt("try", i, end, sub=blk)
    if t in ("case", "default"):
        j = i
        depth = 0
        while True:
            x = toks[j].text
            if x in OPEN:
                depth += 1
            elif x in CLOSE:
                depth -= 1
            elif x == ":" and depth == 0:
                return Stmt("label", i, j)
            j += 1
    if toks[i].kind == "id" and i + 1 < len(toks) and toks[i + 1].text == ":":
        return Stmt("label", i, i + 1)
    if t == ";":
        return Stmt("simple", i, i)
    j = i
    while True:
        x = toks[j].text
        if x in OPEN:
            j = match_close(toks, j)
        elif x == ";":
            return Stmt("simple", i, j)
        elif x in CLOSE:
            raise ValueError(f"statement without ';' at offset {toks[i].start}")
        j += 1


def parse_seq(toks, a, b):
    """The statements of toks[a..b) (b: the closing brace)."""
    out = []
    i = a
    while i < b:
        s = parse_stmt(toks, i)
        out.append(s)
        i = s.b + 1
    return out


def walk(stmts):
    """Every statement, depth first."""
    for s in stmts:
        yield s
        for c in (s.body or []):
            yield from walk([c])
        for c in (s.then, s.els, s.sub):
            if c is not None:
                yield from walk([c])


def blocks(stmts):
    """Every block statement (the function body included)."""
    return [s for s in walk(stmts) if s.kind == "block"]


# ---------------------------------------------------------------------------
# The function in its file

class Func:
    """The function being permuted. text[hs:be+1] is its definition, from
    the first token of its qualified name to the closing brace of its body.
    toks are that range's tokens (spans relative to the file), body the
    Stmt of the body block, ret its return type (None for void, a
    constructor or a destructor)."""

    def __init__(self, text, name, line=None):
        self.text = text
        ftoks = tokenize(text)
        parts = name.split("::")
        want = []
        for k, p in enumerate(parts):
            if k:
                want.append("::")
            want.append(p)
        hits = []
        for i in range(len(ftoks) - len(want)):
            if [t.text for t in ftoks[i:i + len(want)]] != want:
                continue
            if i and ftoks[i - 1].text in ("::", ".", "->"):
                continue
            j = i + len(want)
            if j >= len(ftoks) or ftoks[j].text != "(":
                continue
            rp = match_close(ftoks, j)
            k = rp + 1
            # const / throw(...) / a constructor's member initializers
            while k < len(ftoks) and ftoks[k].text not in ("{", ";"):
                if ftoks[k].text in OPEN:
                    k = match_close(ftoks, k)
                k += 1
            if k < len(ftoks) and ftoks[k].text == "{":
                hits.append((i, j, rp, k))
        if line is not None:
            hits = [h for h in hits
                    if text.count("\n", 0, ftoks[h[0]].start) + 1 == line]
        if len(hits) != 1:
            lines = [text.count("\n", 0, ftoks[h[0]].start) + 1 for h in hits]
            raise SystemExit(f"permuter: {len(hits)} definitions of {name} "
                             f"(lines {lines}); give --line")
        i, lp, rp, lb = hits[0]
        rb = match_close(ftoks, lb)
        self.hs = ftoks[i].start
        self.be = ftoks[rb].end
        self.params = (lp - i, rp - i)
        self.mi = None
        if ftoks[rp + 1].text == ":" or (ftoks[rp + 1].text != "{" and any(
                t.text == ":" for t in ftoks[rp + 1:lb])):
            c = next(k for k in range(rp + 1, lb) if ftoks[k].text == ":")
            self.mi = (c - i, lb - i)
        # the return type: the tokens back to the previous ';', '}' or '{'
        k = i - 1
        while k >= 0 and ftoks[k].text not in (";", "}", "{") and \
                ftoks[k].kind != "str":
            k -= 1
        rt = [t.text for t in ftoks[k + 1:i]
              if t.text not in ("inline", "virtual", "static", "__forceinline",
                                "__inline", "__stdcall", "__cdecl",
                                "__fastcall", "WINAPI")]
        self.ret = " ".join(rt).replace(" :: ", "::").replace(" < ", "<") \
            .replace(" >", ">") or None
        if self.ret == "void":
            self.ret = None
        self.name = name
        # the parameter types (for temporaries): the tokens before each
        # parameter's name, without a reference's '&'
        self.param_types = []
        self.param_names = []
        k, start = lp + 1, lp + 1
        while k <= rp:
            x = ftoks[k].text
            if x in OPEN and k != lp:
                k = match_close(ftoks, k)
            elif x == "," or k == rp:
                part = [t.text for t in ftoks[start:k]]
                if "=" in part:
                    part = part[:part.index("=")]
                if len(part) >= 2 and ftoks[k - 1].kind == "id" and part != ["void"]:
                    ty = [t for t in part[:-1] if t != "&"]
                    if ty:
                        self.param_types.append(_join_type(ty))
                        self.param_names.append(part[-1])
                start = k + 1
            k += 1
        self.extra_types = []

    def source(self):
        return self.text[self.hs:self.be]

    def with_source(self, src):
        return self.text[:self.hs] + src + self.text[self.be:]


def _join_type(words):
    """A type from its tokens: `const LTVector *` -> `const LTVector*`."""
    out = ""
    for w in words:
        if w in ("*", "&", "::", "<", ">", ",") or out.endswith(("::", "<")):
            out += w
        else:
            out += (" " if out else "") + w
    return out


class View:
    """The tokens and statements of one variant of a function (its source
    text, from the qualified name to the closing brace)."""

    def __init__(self, src, func):
        self.src = src
        self.func = func
        self.toks = tokenize(src)
        lb = next(k for k in range(func.params[1], len(self.toks))
                  if self.toks[k].text == "{" and self._body_start(k))
        self.body = parse_stmt(self.toks, lb)

    def _body_start(self, k):
        # the first '{' at bracket depth 0 after the parameters
        depth = 0
        for t in self.toks[self.func.params[1] + 1:k]:
            if t.text in OPEN:
                depth += 1
            elif t.text in CLOSE:
                depth -= 1
        return depth == 0

    def text(self, a, b):
        """The source of toks[a..b] inclusive."""
        return self.src[self.toks[a].start:self.toks[b].end]

    def replace(self, edits):
        """edits: [(token a, token b, new text)], spans not overlapping.
        The token range a..b is replaced (b = a - 1: insert before a)."""
        out = self.src
        spans = []
        for a, b, new in edits:
            if b < a:
                s = e = self.toks[a].start
            else:
                s, e = self.toks[a].start, self.toks[b].end
            if new == "":
                # a statement removed: its line too, if nothing else is on it
                ls = self.src.rfind("\n", 0, s) + 1
                le = self.src.find("\n", e)
                if le >= 0 and not self.src[ls:s].strip() and not self.src[e:le].strip():
                    s, e = ls, le + 1
            spans.append((s, e, new))
        for s, e, new in sorted(spans, reverse=True):
            out = out[:s] + new + out[e:]
        return out

    def ids(self, a, b):
        return {t.text for t in self.toks[a:b + 1] if t.kind == "id"}

    def line_indent(self, a):
        """The white space at the start of the line of toks[a]."""
        s = self.toks[a].start
        ls = self.src.rfind("\n", 0, s) + 1
        m = re.match(r"[ \t]*", self.src[ls:])
        return m.group()


# ---------------------------------------------------------------------------
# Statement facts

def decl_info(v, s):
    """For a declaration statement, (the index of the first declarator name,
    [declarator names], index of '=' or None); else None. A heuristic: two
    or more type-like tokens, then a name, then = ; ( [ or ','."""
    if s.kind != "simple" or s.a == s.b:
        return None
    toks = v.toks
    if toks[s.a].kind != "id" or toks[s.a].text in KEYWORDS - {"struct", "class", "enum"}:
        return None
    k = s.a
    while k < s.b and toks[k].text not in ("=", ";", "(", "[", ","):
        t = toks[k]
        if t.text == "<":
            # a template argument list: skip to its '>'
            depth = 0
            while k < s.b:
                if toks[k].text == "<":
                    depth += 1
                elif toks[k].text == ">":
                    depth -= 1
                    if depth == 0:
                        break
                elif toks[k].text == ">>":
                    depth -= 2
                    if depth <= 0:
                        break
                k += 1
        elif not (t.kind == "id" or t.text in ("::", "*", "&")):
            return None
        k += 1
    name = k - 1
    if name <= s.a or toks[name].kind != "id" or toks[name].text in TYPE_WORDS:
        return None
    prev = toks[name - 1].text
    if not (toks[name - 1].kind == "id" or prev in ("*", "&", ">")):
        return None
    if toks[name - 1].text in KEYWORDS:
        return None
    names = [toks[name].text]
    eq = name + 1 if toks[name + 1].text == "=" else None
    # more declarators after ',' at depth 0
    j = name + 1
    while j < s.b:
        x = toks[j].text
        if x in OPEN:
            j = match_close(toks, j)
        elif x == ",":
            m = j + 1
            while m < s.b and toks[m].text in ("*", "&", "const"):
                m += 1
            if toks[m].kind == "id":
                names.append(toks[m].text)
        j += 1
    return name, names, eq


def has_call(v, s):
    toks = v.toks
    for k in range(s.a, s.b):
        if toks[k].kind == "id" and toks[k + 1].text == "(" and \
                toks[k].text not in KEYWORDS:
            return True
        if toks[k].text in ("new", "delete", "throw"):
            return True
    return False


def written(v, s):
    """The names a statement writes (as far as tokens show)."""
    out = set()
    d = decl_info(v, s)
    if d:
        out.update(d[1])
    toks = v.toks
    for k in range(s.a, s.b + 1):
        x = toks[k].text
        if x in ("=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
                 "<<=", ">>="):
            # the base name of the left side
            j = k - 1
            while j >= s.a and (toks[j].kind == "id" or
                                toks[j].text in (".", "->", "]", "[", "::")):
                j -= 1
            for m in range(j + 1, k):
                if toks[m].kind == "id":
                    out.add(toks[m].text)
                    break
        elif x in ("++", "--"):
            for m in (k - 1, k + 1):
                if s.a <= m <= s.b and toks[m].kind == "id":
                    out.add(toks[m].text)
    return out


def ends_in_return(v, s):
    if s is None:
        return False
    if s.kind == "simple":
        return v.toks[s.a].text in ("return", "throw")
    if s.kind == "block":
        return bool(s.body) and ends_in_return(v, s.body[-1])
    if s.kind == "if":
        return s.els is not None and ends_in_return(v, s.then) and \
            ends_in_return(v, s.els)
    return False


def contains(v, s, word):
    return any(t.text == word for t in v.toks[s.a:s.b + 1])


# ---------------------------------------------------------------------------
# Expression operands (for commute and the like)

PREC = {
    "*": 13, "/": 13, "%": 13, "+": 12, "-": 12, "<<": 11, ">>": 11,
    "<": 10, ">": 10, "<=": 10, ">=": 10, "==": 9, "!=": 9, "&": 8,
    "^": 7, "|": 6, "&&": 5, "||": 4,
}
STOP = {";", ",", "=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
        "<<=", ">>=", "?", ":", "return", "{", "}", "case"}


def is_binary(v, k):
    """toks[k] is a binary operator (not a unary - * & or a declarator)."""
    if v.toks[k].text not in PREC:
        return False
    p = v.toks[k - 1]
    return p.kind in ("id", "num", "str") and p.text not in KEYWORDS - {"this", "true", "false"} \
        or p.text in (")", "]")


def left_operand(v, k, lo):
    """The first token of the left operand of the binary toks[k], or None
    when an operator of the same precedence is to its left (so the
    operation is part of a left-to-right chain)."""
    p = PREC[v.toks[k].text]
    j = k - 1
    while j >= lo:
        t = v.toks[j].text
        if t in CLOSE:
            # go back to the matching open bracket
            depth = 0
            while j >= lo:
                x = v.toks[j].text
                if x in CLOSE:
                    depth += 1
                elif x in OPEN:
                    depth -= 1
                    if depth == 0:
                        break
                j -= 1
            j -= 1
            continue
        if t in OPEN or t in STOP or (t in KEYWORDS and t not in ("this", "true", "false", "sizeof")):
            return j + 1
        if t in PREC and is_binary(v, j):
            q = PREC[t]
            if q < p:
                return j + 1
            if q == p:
                return None
        j -= 1
    return lo


def right_operand(v, k, hi):
    """The last token of the right operand of the binary toks[k]."""
    p = PREC[v.toks[k].text]
    j = k + 1
    last = None
    while j <= hi:
        t = v.toks[j].text
        if t in OPEN:
            j = match_close(v.toks, j)
            last = j
            j += 1
            continue
        if t in CLOSE or t in STOP:
            break
        if t in PREC and is_binary(v, j) and PREC[t] <= p:
            break
        last = j
        j += 1
    return last


def is_primary(v, a, b):
    """toks[a..b] is a name, a member chain, a call or a bracketed group:
    no operator at depth 0 but . -> :: and brackets."""
    j = a
    while j <= b:
        t = v.toks[j]
        if t.text in OPEN:
            j = match_close(v.toks, j) + 1
            continue
        if not (t.kind in ("id", "num") or t.text in (".", "->", "::")):
            return False
        if t.kind == "id" and t.text in KEYWORDS and t.text not in ("this",):
            return False
        j += 1
    return True


# ---------------------------------------------------------------------------
# Mutations. Each takes (view, rng, opts) and returns new function source,
# or None when it finds nothing to change.

def m_swap(v, rng, opts):
    """Swap two adjacent independent statements of a block."""
    pairs = []
    for blk in blocks([v.body]):
        for x, y in zip(blk.body, blk.body[1:]):
            if x.kind == "label" or y.kind == "label":
                continue
            if any(v.toks[s.a].text in ("return", "break", "continue", "goto")
                   for s in (x, y) if s.kind == "simple"):
                continue
            wx, wy = written(v, x), written(v, y)
            ix, iy = v.ids(x.a, x.b), v.ids(y.a, y.b)
            if wx & iy or wy & ix:
                continue
            if getattr(opts, "strict", False) and has_call(v, x) and has_call(v, y):
                continue
            pairs.append((x, y))
    if not pairs:
        return None
    x, y = rng.choice(pairs)
    tx, ty = v.text(x.a, x.b), v.text(y.a, y.b)
    return v.replace([(x.a, x.b, ty), (y.a, y.b, tx)])


def m_decl_split(v, rng, opts):
    """T x = e;  ->  T x; x = e;"""
    c = []
    for s in walk([v.body]):
        d = decl_info(v, s)
        if d and d[2] is not None and len(d[1]) == 1 and \
                not any(v.toks[k].text in ("&", "const", "static") for k in range(s.a, d[0])):
            c.append((s, d))
    if not c:
        return None
    s, (name, names, eq) = rng.choice(c)
    ind = v.line_indent(s.a)
    head = v.text(s.a, name)
    rest = v.text(eq + 1, s.b)
    return v.replace([(s.a, s.b, f"{head};\n{ind}{names[0]} = {rest}")])


def m_decl_merge(v, rng, opts):
    """T x; x = e;  ->  T x = e;  (the two statements adjacent)"""
    c = []
    for blk in blocks([v.body]):
        for x, y in zip(blk.body, blk.body[1:]):
            d = decl_info(v, x)
            if not d or d[2] is not None or len(d[1]) != 1 or x.b != d[0] + 1:
                continue
            if y.kind == "simple" and y.b - y.a >= 3 and \
                    v.toks[y.a].text == d[1][0] and v.toks[y.a + 1].text == "=":
                c.append((x, y, d))
    if not c:
        return None
    x, y, d = rng.choice(c)
    return v.replace([(x.a, x.b, v.text(x.a, d[0]) + " = " + v.text(y.a + 2, y.b)),
                      (y.a, y.b, "")])


def m_decl_move(v, rng, opts):
    """Move a declaration: one without an initializer to the top of the
    function or to just before the next statement; one with an initializer
    from a nested block to the function's top (as `T x;`, with `x = e;` left
    in its place)."""
    c = []
    for blk in blocks([v.body]):
        for idx, s in enumerate(blk.body):
            d = decl_info(v, s)
            if not d:
                continue
            c.append((blk, idx, s, d))
    if not c:
        return None
    blk, idx, s, (name, names, eq) = rng.choice(c)
    if any(v.toks[k].text in ("&", "const", "static") for k in range(s.a, name)):
        return None
    ind = v.line_indent(s.a)
    if eq is None:
        # to the top of the function, or one statement down
        top = v.body.body[0]
        if rng.random() < 0.5 and top is not s:
            tind = v.line_indent(top.a)
            return v.replace([(s.a, s.b, ""), (top.a, top.a - 1,
                                              v.text(s.a, s.b) + "\n" + tind)])
        if idx + 1 < len(blk.body):
            nxt = blk.body[idx + 1]
            if nxt.kind == "label":
                return None
            return v.replace([(s.a, s.b, v.text(nxt.a, nxt.b)),
                              (nxt.a, nxt.b, v.text(s.a, s.b))])
        return None
    if blk is v.body or len(names) != 1:
        return None
    top = v.body.body[0]
    tind = v.line_indent(top.a)
    return v.replace([(top.a, top.a - 1, v.text(s.a, name) + ";\n" + tind),
                      (s.a, s.b, f"{names[0]} = " + v.text(eq + 1, s.b))])


def m_return_temp(v, rng, opts):
    """return e;  <->  T tmp = e; return tmp;"""
    rets = [s for s in walk([v.body]) if s.kind == "simple"
            and v.toks[s.a].text == "return" and s.b - s.a >= 2]
    c = []
    for s in rets:
        if s.b - s.a == 2 and v.toks[s.a + 1].kind in ("id", "num"):
            continue
        c.append(("in", s))
    # the reverse: `T x = e; return x;` with x used nowhere else
    for blk in blocks([v.body]):
        for x, y in zip(blk.body, blk.body[1:]):
            d = decl_info(v, x)
            if d and d[2] is not None and len(d[1]) == 1 and y.kind == "simple" \
                    and v.toks[y.a].text == "return" and y.b == y.a + 2 and \
                    v.toks[y.a + 1].text == d[1][0] and \
                    sum(1 for t in v.toks if t.text == d[1][0]) == 2:
                c.append(("out", (x, y, d)))
    if not c:
        return None
    kind, s = rng.choice(c)
    if kind == "in":
        if not v.func.ret:
            return None
        ind = v.line_indent(s.a)
        n = 0
        while f"permRet{n}" in v.src:
            n += 1
        e = v.text(s.a + 1, s.b - 1)
        return v.replace([(s.a, s.b, f"{v.func.ret} permRet{n} = {e};\n{ind}return permRet{n};")])
    x, y, d = s
    return v.replace([(x.a, x.b, ""), (y.a + 1, y.a + 1, v.text(d[2] + 1, x.b - 1))])


def m_temp_inline(v, rng, opts):
    """T x = e; ... use(x) ...  ->  ... use((e)) ...  (x used once, after)."""
    c = []
    for blk in blocks([v.body]):
        for idx, s in enumerate(blk.body):
            d = decl_info(v, s)
            if not d or d[2] is None or len(d[1]) != 1:
                continue
            if any(v.toks[k].text in ("&", "static") for k in range(s.a, d[0])):
                continue
            n = d[1][0]
            uses = [k for k in range(s.b + 1, len(v.toks)) if v.toks[k].text == n
                    and v.toks[k - 1].text not in (".", "->", "::")]
            if len(uses) != 1 or idx + 1 >= len(blk.body):
                continue
            if uses[0] > blk.body[-1].b:
                continue
            u = uses[0]
            if v.toks[u + 1].text in ("=", "++", "--", "+=", "-=", "*=", "|=", "&=") \
                    or v.toks[u - 1].text in ("++", "--", "&"):
                continue
            c.append((s, d, u))
    if not c:
        return None
    s, d, u = rng.choice(c)
    e = v.text(d[2] + 1, s.b - 1)
    return v.replace([(s.a, s.b, ""), (u, u, f"({e})")])


def m_split_expr(v, rng, opts):
    """x = A op B;  ->  x = A; x op= B;  (op: + - * | & ^, the last one at
    the top of the expression)"""
    c = []
    for s in walk([v.body]):
        if s.kind != "simple":
            continue
        d = decl_info(v, s)
        if d:
            if d[2] is None or len(d[1]) != 1:
                continue
            if any(v.toks[k].text in ("&", "const") for k in range(s.a, d[0])):
                continue
            lhs, eq = d[1][0], d[2]
        elif s.b - s.a >= 4 and v.toks[s.a].kind == "id" and v.toks[s.a + 1].text == "=":
            lhs, eq = v.toks[s.a].text, s.a + 1
        else:
            continue
        if lhs in v.ids(eq + 1, s.b):
            continue
        # the lowest-precedence binary operator at depth 0, the last of them
        best = None
        j = eq + 1
        while j < s.b:
            t = v.toks[j].text
            if t in OPEN:
                j = match_close(v.toks, j) + 1
                continue
            if t in ("?", ":"):
                best = None
                break
            if t in PREC and is_binary(v, j):
                if best is None or PREC[t] <= PREC[v.toks[best].text]:
                    best = j
            j += 1
        if best is not None and v.toks[best].text in ("+", "-", "*", "|", "&", "^"):
            c.append((s, eq, best, lhs))
    if not c:
        return None
    s, eq, op, lhs = rng.choice(c)
    ind = v.line_indent(s.a)
    a = v.text(eq + 1, op - 1)
    b = v.text(op + 1, s.b - 1)
    head = v.text(s.a, eq)
    return v.replace([(s.a, s.b, f"{head} {a};\n{ind}{lhs} {v.toks[op].text}= {b};")])


FLIP = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}


def _expr_ranges(v):
    """[(lo, hi)] token ranges that hold expressions: simple statements and
    the conditions of if/for/while/switch."""
    out = []
    for s in walk([v.body]):
        if s.kind == "simple":
            out.append((s.a, s.b - 1))
        elif s.cond:
            out.append((s.cond[0] + 1, s.cond[1] - 1))
    return out


def m_commute(v, rng, opts):
    """a OP b  ->  b OP a  (OP: + * & | ^ == !=; < > <= >= are flipped;
    && || only with --loose)."""
    ops = {"+", "*", "&", "|", "^", "==", "!="} | set(FLIP)
    if opts.loose:
        ops |= {"&&", "||"}
    c = []
    for lo, hi in _expr_ranges(v):
        for k in range(lo + 1, hi + 1):
            if v.toks[k].text in ops and is_binary(v, k):
                c.append((lo, hi, k))
    rng.shuffle(c)
    for lo, hi, k in c[:20]:
        # the bracket depth must be the same: find the enclosing range
        la = left_operand(v, k, lo)
        rb = right_operand(v, k, hi)
        if la is None or rb is None or la >= k:
            continue
        if v.toks[la].kind == "id" and decl_info(v, Stmt("simple", la, hi + 1)) \
                and la == lo:
            continue
        op = v.toks[k].text
        new = v.text(k + 1, rb) + " " + FLIP.get(op, op) + " " + v.text(la, k - 1)
        return v.replace([(la, rb, new)])
    return None


def m_incdec(v, rng, opts):
    """++i  <->  i++ where the value is not used (a statement, or a for's
    step)."""
    c = []
    for s in walk([v.body]):
        rngs = []
        if s.kind == "simple" and s.b - s.a == 2:
            rngs.append((s.a, s.b - 1))
        if s.kind == "for":
            semis = [k for k in range(s.cond[0], s.cond[1]) if v.toks[k].text == ";"]
            if len(semis) >= 2 and s.cond[1] - semis[-1] == 3:
                rngs.append((semis[-1] + 1, s.cond[1] - 1))
        for a, b in rngs:
            x, y = v.toks[a], v.toks[b]
            if x.text in ("++", "--") and y.kind == "id":
                c.append((a, b, y.text + x.text))
            elif y.text in ("++", "--") and x.kind == "id":
                c.append((a, b, y.text + x.text))
    if not c:
        return None
    a, b, new = rng.choice(c)
    return v.replace([(a, b, new)])


def m_not(v, rng, opts):
    """!x <-> x == 0, and in a condition x <-> x != 0."""
    c = []
    for lo, hi in _expr_ranges(v):
        for k in range(lo, hi + 1):
            t = v.toks[k].text
            if t == "!" and k + 1 <= hi:
                # !P with P primary
                j = k + 1
                e = j
                while e + 1 <= hi and (v.toks[e + 1].text in (".", "->", "::", "(", "[")
                                       or v.toks[e].text in (".", "->", "::")):
                    if v.toks[e + 1].text in OPEN:
                        e = match_close(v.toks, e + 1)
                    else:
                        e += 1
                if v.toks[j].text in OPEN:
                    e = match_close(v.toks, j)
                if is_primary(v, j, e):
                    c.append((k, e, "(" + v.text(j, e) + " == 0)"))
            elif t in ("==", "!=") and is_binary(v, k) and k + 1 <= hi and \
                    v.toks[k + 1].text in ("0", "NULL", "LTNULL", "LTFALSE", "false") and \
                    (k + 2 > hi or v.toks[k + 2].text in (")", "&&", "||", ";", ",", "?")):
                la = left_operand(v, k, lo)
                if la is None or not is_primary(v, la, k - 1):
                    continue
                if t == "==":
                    c.append((la, k + 1, "!" + v.text(la, k - 1)))
                else:
                    c.append((la, k + 1, v.text(la, k - 1)))
    for s in walk([v.body]):
        if s.kind in ("if", "while") and is_primary(v, s.cond[0] + 1, s.cond[1] - 1) \
                and s.cond[1] - s.cond[0] > 1:
            c.append((s.cond[0] + 1, s.cond[1] - 1, v.text(s.cond[0] + 1, s.cond[1] - 1) + " != 0"))
    if not c:
        return None
    a, b, new = rng.choice(c)
    return v.replace([(a, b, new)])


def m_loop(v, rng, opts):
    """for (i; c; s) b  ->  { i; while (c) { b s; } }, and while (c) b ->
    for (; c;) b."""
    c = [s for s in walk([v.body]) if s.kind in ("for", "while")]
    if not c:
        return None
    s = rng.choice(c)
    if s.kind == "while":
        return v.replace([(s.a, s.cond[1], "for (; " + v.text(s.cond[0] + 1, s.cond[1] - 1) + ";)")])
    if contains(v, s.sub, "continue"):
        return None
    semis = []
    k = s.cond[0] + 1
    while k < s.cond[1]:
        if v.toks[k].text in OPEN:
            k = match_close(v.toks, k)
        elif v.toks[k].text == ";":
            semis.append(k)
        k += 1
    if len(semis) != 2:
        return None
    s1, s2 = semis
    init = v.text(s.cond[0] + 1, s1) if s1 > s.cond[0] + 1 else ""
    cond = v.text(s1 + 1, s2 - 1) if s2 > s1 + 1 else "1"
    step = v.text(s2 + 1, s.cond[1] - 1) + ";" if s.cond[1] > s2 + 1 else ""
    ind = v.line_indent(s.a)
    body = v.text(s.sub.a, s.sub.b)
    if s.sub.kind == "block":
        inner = v.text(s.sub.a + 1, s.sub.b - 1) if s.sub.b > s.sub.a + 1 else ""
        body = "{\n" + ind + "\t" + inner + ("\n" + ind + "\t" + step if step else "") + "\n" + ind + "}"
    else:
        body = "{\n" + ind + "\t" + body + ("\n" + ind + "\t" + step if step else "") + "\n" + ind + "}"
    new = "while (" + cond + ")\n" + ind + body
    if init:
        new = "{\n" + ind + init + "\n" + ind + new + "\n" + ind + "}"
    return v.replace([(s.a, s.b, new)])


def m_if(v, rng, opts):
    """if (c) A else B -> if (!(c)) B else A; drop an else after a branch
    that returns; give the rest of a block to an else; and in a void
    function, if (c) { A } at the end -> if (!(c)) return; A."""
    c = []
    for blk in blocks([v.body]):
        for idx, s in enumerate(blk.body):
            if s.kind != "if":
                continue
            cond = v.text(s.cond[0] + 1, s.cond[1] - 1)
            if s.els is not None:
                c.append(("swap", blk, idx, s))
                if ends_in_return(v, s.then):
                    c.append(("drop-else", blk, idx, s))
            elif ends_in_return(v, s.then) and idx + 1 < len(blk.body) and \
                    not any(x.kind == "label" or decl_info(v, x) for x in blk.body[idx + 1:]):
                c.append(("add-else", blk, idx, s))
            if s.els is None and blk is v.body and idx == len(blk.body) - 1 \
                    and not v.func.ret and s.then.kind == "block":
                c.append(("early", blk, idx, s))
            if s.els is None and v.func.ret is None and s.then.kind == "simple" and \
                    s.then.b == s.then.a + 1 and v.toks[s.then.a].text == "return" and \
                    blk is v.body and idx + 1 < len(blk.body):
                c.append(("late", blk, idx, s))
            _ = cond
    if not c:
        return None
    kind, blk, idx, s = rng.choice(c)
    cond = v.text(s.cond[0] + 1, s.cond[1] - 1)
    ind = v.line_indent(s.a)
    if kind == "swap":
        return v.replace([(s.a, s.b, f"if (!({cond}))\n{ind}" + v.text(s.els.a, s.els.b)
                           + f"\n{ind}else\n{ind}" + v.text(s.then.a, s.then.b))])
    if kind == "drop-else":
        els = v.text(s.els.a, s.els.b)
        if s.els.kind == "block":
            els = v.text(s.els.a + 1, s.els.b - 1) if s.els.b > s.els.a + 1 else ""
        return v.replace([(s.a, s.b, v.text(s.a, s.then.b) + f"\n{ind}" + els)])
    if kind == "add-else":
        rest = blk.body[idx + 1:]
        r = v.text(rest[0].a, rest[-1].b)
        return v.replace([(s.a, rest[-1].b, v.text(s.a, s.b) + f"\n{ind}else\n{ind}{{\n{ind}" + r + f"\n{ind}}}")])
    if kind == "early":
        inner = v.text(s.then.a + 1, s.then.b - 1) if s.then.b > s.then.a + 1 else ""
        return v.replace([(s.a, s.b, f"if (!({cond}))\n{ind}\treturn;\n{ind}" + inner)])
    if kind == "late":
        rest = blk.body[idx + 1:]
        r = v.text(rest[0].a, rest[-1].b)
        return v.replace([(s.a, rest[-1].b, f"if (!({cond}))\n{ind}{{\n{ind}" + r + f"\n{ind}}}")])
    return None


_CAST_PREV_OK = {"(", ",", "=", "return", "+", "-", "*", "/", "<", ">", "<=",
                 ">=", "==", "!=", "&&", "||", "!", "?", ":", "+=", "-=", "*=",
                 "/=", "|=", "&=", "|", "&", "^", "["}


def _casts(v):
    """[(lp, rp, type text)] of the C-style casts in the body."""
    out = []
    toks = v.toks
    for k in range(v.body.a + 1, v.body.b):
        if toks[k].text != "(" or toks[k - 1].text not in _CAST_PREV_OK:
            continue
        rp = match_close(toks, k)
        inner = toks[k + 1:rp]
        if not inner or rp + 1 >= len(toks):
            continue
        if not all(t.kind == "id" or t.text in ("*", "&", "::") for t in inner):
            continue
        if inner[0].kind != "id" or any(t.text in KEYWORDS for t in inner):
            continue
        # one name alone is a cast only before a name, number or bracket
        nxt = toks[rp + 1]
        if not (nxt.kind in ("id", "num") or nxt.text in ("(",)):
            continue
        if nxt.kind == "id" and nxt.text in KEYWORDS - {"this", "sizeof"}:
            continue
        if len(inner) == 1 and inner[0].text[0].islower() and \
                inner[0].text not in TYPE_WORDS and not inner[0].text.startswith("uint") \
                and not inner[0].text.startswith("int"):
            continue
        out.append((k, rp, v.text(k + 1, rp - 1)))
    return out


def m_cast(v, rng, opts):
    """Remove a C-style cast, or add one (of a type the function already
    casts to) in front of a name."""
    casts = _casts(v)
    if casts and rng.random() < 0.6:
        lp, rp, _ = rng.choice(casts)
        return v.replace([(lp, rp, "")])
    types = sorted({t for _, _, t in casts} | {"float", "int", "uint32"} if casts else {"float", "int"})
    names = [k for k in range(v.body.a + 1, v.body.b)
             if v.toks[k].kind == "id" and v.toks[k].text not in KEYWORDS
             and v.toks[k - 1].text in _CAST_PREV_OK
             and v.toks[k + 1].text not in ("(", "::", "=", "++", "--")
             and v.toks[k + 1].text not in (".", "->")]
    if not names:
        return None
    k = rng.choice(names)
    return v.replace([(k, k - 1, "(" + rng.choice(types) + ")")])


def m_decl_order(v, rng, opts):
    """int a, b;  ->  int b, a;  or  int a; int b;  and the members of a
    constructor's initializer list in another order."""
    c = []
    for s in walk([v.body]):
        d = decl_info(v, s)
        if not d or len(d[1]) < 2:
            continue
        c.append(s)
    mi = v.func.mi
    if not c and not mi:
        return None
    if mi and (not c or rng.random() < 0.3):
        a, b = mi
        items = []
        k, start = a + 1, a + 1
        while k < b:
            if v.toks[k].text in OPEN:
                k = match_close(v.toks, k)
            elif v.toks[k].text == ",":
                items.append((start, k - 1))
                start = k + 1
            k += 1
        items.append((start, b - 1))
        if len(items) < 2:
            return None
        i = rng.randrange(len(items) - 1)
        x, y = items[i], items[i + 1]
        return v.replace([(x[0], x[1], v.text(*y)), (y[0], y[1], v.text(*x))])
    s = rng.choice(c)
    d = decl_info(v, s)
    # the base type: the tokens before the first declarator name, without
    # the declarator's own * and &
    base_end = d[0] - 1
    while v.toks[base_end].text in ("*", "&"):
        base_end -= 1
    parts = []
    k, start = base_end + 1, base_end + 1
    while k < s.b:
        if v.toks[k].text in OPEN:
            k = match_close(v.toks, k)
        elif v.toks[k].text == ",":
            parts.append(v.text(start, k - 1))
            start = k + 1
        k += 1
    parts.append(v.text(start, s.b - 1))
    base = v.text(s.a, base_end)
    if rng.random() < 0.5:
        i = rng.randrange(len(parts) - 1)
        parts[i], parts[i + 1] = parts[i + 1], parts[i]
        return v.replace([(s.a, s.b, base + " " + ", ".join(parts) + ";")])
    ind = v.line_indent(s.a)
    return v.replace([(s.a, s.b, f"\n{ind}".join(f"{base} {p};" for p in parts))])


def m_hoist(v, rng, opts):
    """Put a call argument, or an operand with a member access or a call,
    into a new local before its statement: `f(a->b)` -> `T t = a->b;
    f(t)`. T is one of the types that the function names (its parameters,
    its locals, its return type, --types): a wrong type does not compile,
    or does not give the retail code."""
    types = set(v.func.param_types) | set(v.func.extra_types)
    if v.func.ret:
        types.add(v.func.ret)
    for s in walk([v.body]):
        d = decl_info(v, s)
        if d:
            base = d[0] - 1
            while v.toks[base].text in ("*", "&"):
                base -= 1
            ty = [t.text for t in v.toks[s.a:base + 1] if t.text != "static"]
            stars = "".join(t.text for t in v.toks[base + 1:d[0]] if t.text == "*")
            types.add(_join_type(ty) + stars)
    types.discard("")
    if not types:
        return None
    local_names = set(v.func.param_names)
    for s in walk([v.body]):
        d = decl_info(v, s)
        if d:
            local_names.update(d[1])
    cands = []
    for blk in blocks([v.body]):
        for st in blk.body:
            if st.kind == "simple":
                lo, hi = st.a, st.b - 1
            elif st.kind in ("if", "switch"):
                lo, hi = st.cond[0] + 1, st.cond[1] - 1
            else:
                continue
            k = lo
            while k <= hi:
                t = v.toks[k]
                # the arguments of a call
                if t.text == "(" and k > lo and v.toks[k - 1].kind == "id" and \
                        v.toks[k - 1].text not in KEYWORDS:
                    rp = match_close(v.toks, k)
                    j, start = k + 1, k + 1
                    while j <= rp:
                        x = v.toks[j].text
                        if x in OPEN:
                            j = match_close(v.toks, j)
                        elif x == "," or j == rp:
                            if j > start and not (j - start == 1 and v.toks[start].kind in ("num", "str")):
                                cands.append((st, start, j - 1))
                            start = j + 1
                        j += 1
                # an operand with -> . or a call
                if t.text in PREC and is_binary(v, k):
                    la = left_operand(v, k, lo)
                    rb = right_operand(v, k, hi)
                    if la is not None and la < k and is_primary(v, la, k - 1) and \
                            any(v.toks[m].text in ("->", ".", "(") for m in range(la, k)):
                        cands.append((st, la, k - 1))
                    if rb is not None and is_primary(v, k + 1, rb) and \
                            any(v.toks[m].text in ("->", ".", "(") for m in range(k + 1, rb + 1)):
                        cands.append((st, k + 1, rb))
                k += 1
    if not cands:
        return None
    st, a, b = rng.choice(cands)
    if b - a == 0 and (v.toks[a].text in local_names or v.toks[a].text in KEYWORDS):
        return None    # already a local
    n = 0
    while f"permTmp{n}" in v.src:
        n += 1
    ind = v.line_indent(st.a)
    ty = rng.choice(sorted(types))
    return v.replace([(st.a, st.a - 1, f"{ty} permTmp{n} = {v.text(a, b)};\n{ind}"),
                      (a, b, f"permTmp{n}")])


MUTATIONS = [
    (m_swap, 4), (m_decl_split, 1), (m_decl_merge, 1), (m_decl_move, 2),
    (m_return_temp, 1), (m_temp_inline, 1), (m_split_expr, 1),
    (m_commute, 3), (m_incdec, 1), (m_not, 2), (m_loop, 1), (m_if, 2),
    (m_cast, 1), (m_decl_order, 1), (m_hoist, 2),
]


def mutate(src, func, rng, opts, tries=8):
    """One random mutation of `src` (a function's source), or None."""
    try:
        v = View(src, func)
    except (ValueError, IndexError, StopIteration):
        return None, None
    fns = [f for f, _ in MUTATIONS]
    ws = [w for _, w in MUTATIONS]
    for _ in range(tries):
        f = rng.choices(fns, ws)[0]
        try:
            new = f(v, rng, opts)
        except (ValueError, IndexError, StopIteration, KeyError, TypeError):
            new = None
        if new is not None and new != src:
            return new, f.__name__[2:]
    return None, None


# ---------------------------------------------------------------------------
# Score

def listing_of_obj(obj, sym):
    return fndiff.parse_listing(fndiff.run(["python3", os.path.join(HERE, "dumpfn.py"), obj, sym]))


def score(ship, obj, sym):
    """(score, summary) of our object's function against the retail
    listing; score 0 is byte-identical (relocations masked)."""
    ours = listing_of_obj(obj, sym)
    if not ours:
        return None, "no symbol"
    relmask = fndiff.reloc_offsets(obj, sym)
    ship_len = sum(len(b) for _, b, _, _ in ship)
    ours_len = sum(len(b) for _, b, _, _ in ours)

    def same_bytes(sb, ob, pos):
        masked = {i - pos for i in relmask if pos <= i < pos + len(ob)}
        return len(sb) == len(ob) and not any(
            x != y and y != "00" and i not in masked
            for i, (x, y) in enumerate(zip(sb, ob)))

    if ship_len == ours_len and len(ship) == len(ours):
        pos = 0
        bad = 0
        for (_, sb, _, _), (_, ob, _, _) in zip(ship, ours):
            if not same_bytes(sb, ob, pos):
                bad += 1
            pos += len(ob)
        if bad == 0:
            return 0, f"identical ({ship_len} bytes)"
    a, b = fndiff.norm(ship), fndiff.norm(ours)
    raw = sum(len(S) + len(O) for _, S, O in fndiff.opblocks(a, b))
    ren = raw
    for perm in itertools.permutations(["ebx", "esi", "edi"]):
        if ren == 0:
            break
        m = dict(zip(["ebx", "esi", "edi"], perm))
        r = sum(len(S) + len(O) for _, S, O in fndiff.opblocks(a, fndiff.norm(ours, m)))
        ren = min(ren, r)
    # byte differences in the instructions that align by mnemonic
    offs = []
    pos = 0
    for _, ob, _, _ in ours:
        offs.append(pos)
        pos += len(ob)
    bad = 0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for t, i1, i2, j1, j2 in sm.get_opcodes():
        if t != "equal":
            continue
        for i, j in zip(range(i1, i2), range(j1, j2)):
            if not same_bytes(ship[i][1], ours[j][1], offs[j]):
                bad += 1
    sc = 8 * ren + raw + bad + 2 * abs(ship_len - ours_len) + 1
    return sc, (f"ship {ship_len}/ours {ours_len} bytes, mnemonic diff {raw}, "
                f"after renaming {ren}, byte diffs {bad}")


def retail_listing(args):
    if args.target_obj:
        ship = listing_of_obj(args.target_obj, args.symbol)
        if not ship:
            sys.exit(f"permuter: {args.symbol} not in {args.target_obj}")
        return ship
    import tgt as tgt_mod  # noqa: E402  (load_fndiff set TOOLS_PROJECT)
    image = args.image
    if image and not os.path.exists(image):
        image = os.path.join(args.repo, tgt_mod.find(image)["shipped"])
    if not image:
        want = os.path.normcase(os.path.join(args.repo, args.obj))
        hits = [t for t in tgt_mod.cfg.TARGETS
                if any(os.path.normcase(os.path.join(tgt_mod.REPO, o)) == want
                       for o in tgt_mod.objs(t))]
        if len(hits) != 1:
            sys.exit("permuter: which image? give --image")
        image = os.path.join(tgt_mod.REPO, hits[0]["shipped"])
    start = int(args.addr, 16)
    if args.end:
        end = fndiff.parse_end(args.end, start)
    else:
        import csv
        stem = os.path.basename(image).split(".")[0]
        end = None
        for p in (os.path.join(args.repo, f"out/reference/{stem}-functions.csv"),
                  os.path.join(os.path.dirname(image), f"{stem}-functions.csv")):
            if os.path.exists(p):
                with open(p) as f:
                    for r in csv.DictReader(f):
                        if int(r["addr"], 16) == start:
                            end = start + int(r["size"])
                            break
            if end:
                break
        if end is None:
            sys.exit(f"permuter: no size for {args.addr}; give --end")
    end = fndiff._trim_trailing_table(image, start, end)
    ship = fndiff.parse_listing(fndiff.run(
        ["python3", os.path.join(HERE, "exedump.py"), image, args.addr, hex(end)]))
    if not ship:
        sys.exit("permuter: empty retail listing")
    return ship


# ---------------------------------------------------------------------------
# Compile: one container per worker

class Command:
    """The compile command of one object, from its .cmd file."""

    def __init__(self, text, root=None):
        text = text.strip()
        m = re.match(r"cd\s+(\S+)\s*&&\s*(.*)$", text, re.S)
        if not m:
            raise SystemExit("permuter: the .cmd does not start with `cd <dir> &&`")
        self.dir = m.group(1)
        words = shlex.split(m.group(2))
        self.env = {}
        while words and re.match(r"^[A-Za-z_]\w*=", words[0]):
            k, val = words.pop(0).split("=", 1)
            self.env[k] = val
        if not words or os.path.basename(words[0]) != "wine":
            raise SystemExit("permuter: the .cmd does not run `wine <compiler>`")
        self.exe = words[1]
        self.args = words[2:]
        srcs = [a for a in self.args if not a.startswith(("/", "-"))
                and re.search(r"\.(cpp|c|cxx|cc)$", a, re.I)]
        if len(srcs) != 1:
            raise SystemExit(f"permuter: cannot find the source in the .cmd ({srcs})")
        self.source = srcs[-1]
        if root is None:
            pfx = self.env.get("WINEPREFIX", "")
            root = pfx.split("/.wine")[0] if "/.wine" in pfx else "/repo"
        self.root = root.rstrip("/")
        self.prefix = self.env.get("WINEPREFIX")

    def container_source(self):
        """The source's path in the container."""
        p = self.source.replace("\\", "/")
        if p.startswith("./"):
            p = p[2:]
        return os.path.normpath(os.path.join(self.root, self.dir, p))

    def shell(self, out_win):
        """The command for a worker: the object to `out_win` (a Windows
        path), the worker's own prefix."""
        args = []
        for a in self.args:
            low = a.lower()
            if low.startswith(("/fo", "-fo")):
                args.append("/Fo" + out_win)
            elif low.startswith(("/fd", "-fd", "/fr", "-fr", "/fa", "-fa")):
                continue
            else:
                args.append(a)
        env = dict(self.env)
        env["WINEPREFIX"] = "/scratch/pfx"
        env.setdefault("WINEDEBUG", "-all")
        env.setdefault("WINEDLLOVERRIDES", "mscoree,mshtml=")
        return "cd {} && cd {} && env {} wine {} {}".format(
            shlex.quote(self.root), shlex.quote(self.dir),
            " ".join(shlex.quote(f"{k}={v}") for k, v in env.items()),
            shlex.quote(self.exe), " ".join(shlex.quote(a) for a in args))


CONTAINERS = set()
_CLEAN_LOCK = threading.Lock()


def cleanup_containers():
    with _CLEAN_LOCK:
        names = list(CONTAINERS)
        CONTAINERS.clear()
    if names:
        subprocess.run(["docker", "rm", "-f"] + names, capture_output=True)


def make_prefix(args, cmd, base):
    """A Wine prefix in <base>/pfx, with the drive letters of the build's
    prefix. Made once; the workers take hard-link copies of it."""
    pfx = os.path.join(base, "pfx")
    os.makedirs(os.path.join(base, "home"), exist_ok=True)
    r = subprocess.run(
        ["docker", "run", "--rm", "--init", "--name", f"permuter-{os.getpid()}-pfx",
         "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/scratch/home",
         "-v", f"{base}:/scratch", args.docker_image, "bash", "-c",
         "export WINEDEBUG=-all WINEDLLOVERRIDES='mscoree,mshtml=' WINEPREFIX=/scratch/pfx;"
         "wineboot -i >/dev/null 2>&1; wineserver -w;"
         "for v in TEMP TMP; do wine reg add 'HKCU\\Environment' /v $v /t REG_SZ "
         "/d 'C:\\windows\\temp' /f >/dev/null 2>&1; done; wineserver -w"],
        capture_output=True, text=True)
    if r.returncode or not os.path.isdir(os.path.join(pfx, "dosdevices")):
        sys.exit("permuter: cannot make a Wine prefix:\n" + r.stdout + r.stderr)
    # the drive letters of the build's prefix (s: -> /repo/..., t: -> ...)
    links = {}
    if cmd.prefix and cmd.prefix.startswith("/repo"):
        host = os.path.join(args.repo, cmd.prefix[len("/repo"):].lstrip("/"), "dosdevices")
        if os.path.isdir(host):
            for n in os.listdir(host):
                p = os.path.join(host, n)
                if os.path.islink(p) and n not in ("c:", "z:"):
                    links[n] = os.readlink(p)
    for n, target in links.items():
        p = os.path.join(pfx, "dosdevices", n)
        if os.path.lexists(p):
            os.remove(p)
        os.symlink(target, p)
    return pfx


class Worker:
    def __init__(self, idx, args, cmd, base, orig_text):
        self.idx = idx
        self.args = args
        self.cmd = cmd
        self.dir = os.path.join(base, f"w{idx}")
        os.makedirs(os.path.join(self.dir, "out"), exist_ok=True)
        os.makedirs(os.path.join(self.dir, "home"), exist_ok=True)
        subprocess.run(["cp", "-al", os.path.join(base, "pfx"), os.path.join(self.dir, "pfx")],
                       check=True)
        self.src = os.path.join(self.dir, "src", os.path.basename(cmd.container_source()))
        os.makedirs(os.path.dirname(self.src), exist_ok=True)
        with open(self.src, "w", newline="") as f:
            f.write(orig_text)
        self.name = f"permuter-{os.getpid()}-{idx}"
        vols = ["-v", f"{os.path.abspath(args.repo)}:/repo:ro",
                "-v", f"{self.src}:{cmd.container_source()}:ro",
                "-v", f"{self.dir}:/scratch"]
        for m in args.mount:
            vols += ["-v", m + ":ro"]
        CONTAINERS.add(self.name)
        r = subprocess.run(
            ["docker", "run", "-d", "--rm", "--init", "--name", self.name,
             "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/scratch/home"] + vols +
            [args.docker_image, "sleep", "infinity"], capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"permuter: docker run: {r.stderr}")
        subprocess.run(["docker", "exec", "-d", "-e", "WINEPREFIX=/scratch/pfx",
                        self.name, "wineserver", "-p"], capture_output=True)
        self.obj = os.path.join(self.dir, "out", "t.obj")
        self.shell = cmd.shell("z:\\scratch\\out\\t.obj")

    def compile(self, text):
        """Compile `text` (the whole source file); the object path, or None
        and the compiler's output."""
        with open(self.src, "w", newline="") as f:   # in place: the bind mount
            f.write(text)
        out = ""
        for _ in range(3):
            if os.path.exists(self.obj):
                os.remove(self.obj)
            try:
                r = subprocess.run(["docker", "exec", self.name, "bash", "-c", self.shell],
                                   capture_output=True, text=True, timeout=self.args.compile_timeout)
            except subprocess.TimeoutExpired:
                return None, "timeout"
            out = r.stdout + r.stderr
            if r.returncode == 0 and os.path.exists(self.obj):
                return self.obj, out
            if not re.search(r"error C10(01|60)", out):
                break
        return None, out


# ---------------------------------------------------------------------------
# Search

class Search:
    def __init__(self, args, func, ship, log):
        self.args = args
        self.func = func
        self.ship = ship
        self.log = log
        self.lock = threading.Lock()
        self.seen = {}
        self.best = (None, None, None)       # score, source, summary
        self.stop = threading.Event()
        self.tries = 0
        self.fails = 0
        self.t0 = time.time()

    def note(self, msg):
        line = f"[{time.time() - self.t0:7.1f}s] {msg}"
        with self.lock:
            print(line, flush=True)
            self.log.write(line + "\n")
            self.log.flush()

    def offer(self, sc, src, summary, how):
        with self.lock:
            better = self.best[0] is None or sc < self.best[0]
            if better:
                self.best = (sc, src, summary)
        if better:
            self.note(f"best {sc}: {summary}  ({how})")
            write_best(self.args, self.func, src)
            if sc == 0:
                self.stop.set()

    def run_worker(self, w, seed):
        rng = random.Random(seed)
        cur_sc, cur = None, None
        temp = self.args.temperature
        dups = 0
        while not self.stop.is_set():
            if dups >= self.args.max_dups:
                # a small function: the mutations make no new form
                self.note(f"w{w.idx}: no new form in {dups} mutations, stops")
                break
            with self.lock:
                if self.args.tries and self.tries >= self.args.tries:
                    break
                bsc, bsrc, _ = self.best
            if time.time() - self.t0 > self.args.time:
                break
            if cur is None or rng.random() < 0.05:
                cur_sc, cur = bsc, bsrc
            cand, hows = cur, []
            # more mutations at a time when the near forms are all tried
            for _ in range(min(8, rng.choice([1, 1, 1, 2, 2, 3]) + dups // 200)):
                new, how = mutate(cand, self.func, rng, self.args)
                if new is None:
                    continue
                cand = new
                hows.append(how)
            if cand == cur:
                dups += 1
                continue
            key = hashlib.sha1(re.sub(r"\s+", " ", cand).encode()).hexdigest()
            with self.lock:
                if key in self.seen:
                    sc = self.seen[key]
                    hit = True
                else:
                    hit = False
                    self.tries += 1
            dups = dups + 1 if hit else 0
            if not hit:
                obj, out = w.compile(self.func.with_source(cand))
                if obj is None:
                    sc = None
                    with self.lock:
                        self.fails += 1
                else:
                    sc, summary = score(self.ship, obj, self.args.symbol)
                with self.lock:
                    self.seen[key] = sc
                if self.args.verbose:
                    err = ""
                    if obj is None:
                        err = next((x.strip() for x in out.splitlines()
                                    if " error " in x or "fatal" in x), out.strip()[-200:])
                    self.note(f"w{w.idx} {'+'.join(hows)}: {sc} {err}")
                if sc is not None:
                    self.offer(sc, cand, summary, "+".join(hows))
            if sc is None:
                continue
            # many repeated forms: walk on whatever the score (explore)
            if cur_sc is None or sc <= cur_sc or dups > 1000 or \
                    rng.random() < math.exp(-(sc - cur_sc) / max(temp, 1e-9)):
                cur_sc, cur = sc, cand


def simplify(w, func, ship, args, src, sc, summary, note):
    """Make the best form as near to the original as the score permits:
    put back each changed group of lines of the original, one at a time,
    and keep the change if the score is not worse. The random walk also
    keeps changes that do not change the score; this removes them."""
    orig = func.source().splitlines(True)
    tries = 0
    changed = True
    while changed and tries < args.simplify_tries:
        changed = False
        cur = src.splitlines(True)
        ops = [o for o in difflib.SequenceMatcher(None, orig, cur, autojunk=False).get_opcodes()
               if o[0] != "equal"]
        # one group at a time; each line of a group removed; each pair of
        # neighbouring groups (a moved statement is a delete and an insert)
        trials = [[o] for o in ops]
        trials += [[("delete", 0, 0, j, j + 1)] for o in ops for j in range(o[3], o[4])
                   if o[4] - o[3] > 1 or o[0] == "replace"]
        trials += [[a, b] for a, b in zip(ops, ops[1:])]
        for group in trials:
            new = list(cur)
            for t, i1, i2, j1, j2 in sorted(group, key=lambda o: -o[3]):
                new[j1:j2] = orig[i1:i2]
            cand = "".join(new)
            if cand == src:
                continue
            tries += 1
            obj, _ = w.compile(func.with_source(cand))
            if obj is None:
                continue
            nsc, nsum = score(ship, obj, args.symbol)
            if nsc is not None and nsc <= sc:
                src, summary, changed = cand, nsum, True
                note(f"simplify: {len(group)} group(s) back as the original, score {nsc}")
                break
    write_best(args, func, src)
    return src, summary


def write_best(args, func, src):
    text = func.with_source(src)
    with open(os.path.join(args.out, "best.cpp"), "w", newline="") as f:
        f.write(text)
    with open(os.path.join(args.out, "best.diff"), "w", newline="") as f:
        f.write(make_diff(args, func.text, text))


def make_diff(args, a, b):
    rel = args.source_rel
    return "".join(difflib.unified_diff(
        a.splitlines(True), b.splitlines(True), f"a/{rel}", f"b/{rel}"))


def func_from_symbol(sym):
    """Class::Name from a mangled symbol (simple cases only)."""
    m = re.match(r"\?\?([01])(\w+)@@", sym)
    if m:
        cls = m.group(2)
        return f"{cls}::{cls}" if m.group(1) == "0" else f"{cls}::~{cls}"
    m = re.match(r"\?(\w+)@([\w@]+?)@@", sym)
    if m:
        parts = m.group(2).split("@")[::-1]
        return "::".join(parts + [m.group(1)])
    m = re.match(r"\?(\w+)@@", sym)
    if m:
        return m.group(1)
    sys.exit(f"permuter: give --func (cannot read the name of {sym})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--obj", required=True)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--addr")
    ap.add_argument("--image")
    ap.add_argument("--end")
    ap.add_argument("--target-obj")
    ap.add_argument("--cmd")
    ap.add_argument("--root")
    ap.add_argument("--func")
    ap.add_argument("--line", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--time", type=float, default=600)
    ap.add_argument("--tries", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--temperature", type=float, default=2.0)
    ap.add_argument("--out")
    ap.add_argument("--docker-image")
    ap.add_argument("--mount", action="append", default=[])
    ap.add_argument("--types", default="")
    ap.add_argument("--loose", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--status", type=float, default=60)
    ap.add_argument("--max-dups", type=int, default=5000)
    ap.add_argument("--no-simplify", action="store_true")
    ap.add_argument("--simplify-tries", type=int, default=200)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--compile-timeout", type=float, default=300)
    args = ap.parse_args(argv)
    args.repo = os.path.abspath(args.repo)
    if not args.target_obj and not args.addr:
        ap.error("give --addr (or --target-obj)")
    if args.target_obj:
        args.target_obj = os.path.abspath(args.target_obj)
    args.docker_image = args.docker_image or os.path.basename(args.repo) + "-build"
    args.func = args.func or func_from_symbol(args.symbol)
    safe = re.sub(r"[^\w]+", "_", args.func)[:60]
    args.out = os.path.abspath(args.out or os.path.join(
        tempfile.gettempdir(), f"permuter-{safe}-{os.getpid()}"))
    if os.path.commonpath([args.out, args.repo]) == args.repo:
        sys.exit("permuter: --out must not be inside the repository")
    os.makedirs(args.out, exist_ok=True)

    load_fndiff(args.repo)
    cmdfile = args.cmd or os.path.join(args.repo, args.obj + ".cmd")
    with open(cmdfile) as f:
        cmd = Command(f.read(), args.root)
    csrc = cmd.container_source()
    if os.path.commonpath([csrc, "/repo"]) != "/repo":
        sys.exit(f"permuter: the source {csrc} is not under /repo")
    host_src = os.path.join(args.repo, os.path.relpath(csrc, "/repo"))
    args.source_rel = os.path.relpath(csrc, cmd.root)
    with open(host_src, newline="") as f:
        orig = f.read()
    func = Func(orig, args.func, args.line)
    func.extra_types = [t.strip() for t in args.types.split(",") if t.strip()]

    ship = retail_listing(args)
    base = os.path.join(args.out, "scratch")
    os.makedirs(base, exist_ok=True)
    log = open(os.path.join(args.out, "log.txt"), "a")
    atexit.register(log.close)

    atexit.register(cleanup_containers)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
    # also when started in the background, where a shell ignores SIGINT
    signal.signal(signal.SIGINT, signal.default_int_handler)
    print(f"permuter: {args.func} in {args.source_rel}, {len(ship)} retail instructions, "
          f"{args.workers} worker(s), scratch {base}", flush=True)
    make_prefix(args, cmd, base)
    workers = []
    try:
        for i in range(args.workers):
            workers.append(Worker(i, args, cmd, base, orig))
        obj, out = workers[0].compile(orig)
        if obj is None:
            sys.exit("permuter: the original does not compile:\n" + out[-3000:])
        sc, summary = score(ship, obj, args.symbol)
        if sc is None:
            sys.exit(f"permuter: {args.symbol} is not in the object")
        search = Search(args, func, ship, log)
        search.note(f"original {sc}: {summary}")
        search.best = (sc, func.source(), summary)
        search.seen[hashlib.sha1(re.sub(r"\s+", " ", func.source()).encode()).hexdigest()] = sc
        orig_sc = sc
        if sc != 0:
            threads = [threading.Thread(target=search.run_worker, args=(w, args.seed * 1000 + w.idx),
                                        daemon=True) for w in workers]
            for t in threads:
                t.start()
            try:
                last = time.time()
                for t in threads:
                    while t.is_alive():
                        t.join(1)
                        if time.time() - last >= args.status:
                            last = time.time()
                            search.note(f"status: {search.tries} compiles "
                                        f"({search.fails} failed), best {search.best[0]}")
            except KeyboardInterrupt:
                search.stop.set()
                print("permuter: stopping", flush=True)
                for t in threads:
                    t.join(60)
        bsc, bsrc, bsum = search.best
        search.note(f"search done: {search.tries} compiles ({search.fails} failed); "
                    f"original {orig_sc}, best {bsc}: {bsum}")
        if bsc < orig_sc and not args.no_simplify:
            bsrc, bsum = simplify(workers[0], func, ship, args, bsrc, bsc, bsum, search.note)
            search.best = (bsc, bsrc, bsum)
        search.note(f"done: original {orig_sc}, best {bsc}: {bsum}")
        if bsrc != func.source():
            write_best(args, func, bsrc)
            print(make_diff(args, func.text, func.with_source(bsrc)), end="")
        print(f"permuter: {'IDENTICAL' if bsc == 0 else 'best score ' + str(bsc)}; "
              f"output in {args.out}", flush=True)
        return 0 if bsc == 0 else 1
    finally:
        cleanup_containers()
        if not args.keep:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
