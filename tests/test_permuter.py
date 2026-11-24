"""Tests for permuter.py.

    python3 -m unittest tests.test_permuter          (from tools/)

The first tests need no compiler: they parse a small C++ function, apply
each mutation and examine the result. The last test (End2End) runs the
permuter on a tiny example with the real compiler. It needs Docker and a
game repository with its build image and ext/toolchains/msvc-6.00-8168:
set PERMUTER_TEST_REPO to that repository (for example ~/src/tron20src).
Without it, the test is skipped. The test does not write into that
repository: it mounts its toolchains read-only.
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import permuter  # noqa: E402

SAMPLE = """\
#include "x.h"

// a comment with GetFoo::Bar in it
int Other::Bar(int a) { return a; }

float CThing::Update(const int *p, int n)
{
	int i;
	float fSum = 0.0f, fMax = 1.0f;
	m_nCount = n * 2;
	DoA(p);
	DoB(n);
	for (i = 0; i < n; i++)
	{
		fSum += p[i] + m_fBias;
	}
	if (!m_pOwner)
	{
		return fSum;
	}
	else
	{
		fMax = (float)n;
	}
	return fSum * fMax;
}
"""

OPTS = types.SimpleNamespace(loose=False, strict=False)


def balanced(src):
    stack = []
    for t in permuter.tokenize(src):
        if t.text in "([{":
            stack.append(t.text)
        elif t.text in ")]}":
            if not stack or "([{"[")]}".index(t.text)] != stack.pop():
                return False
    return not stack


class Parse(unittest.TestCase):
    def setUp(self):
        self.f = permuter.Func(SAMPLE, "CThing::Update")

    def test_finds_definition(self):
        src = self.f.source()
        self.assertTrue(src.startswith("CThing::Update("))
        self.assertTrue(src.endswith("}"))
        self.assertEqual(self.f.ret, "float")
        self.assertEqual(self.f.with_source(src), SAMPLE)

    def test_statements(self):
        v = permuter.View(self.f.source(), self.f)
        kinds = [s.kind for s in v.body.body]
        self.assertEqual(kinds, ["simple"] * 5 + ["for", "if", "simple"])
        d = permuter.decl_info(v, v.body.body[1])
        self.assertEqual(d[1], ["fSum", "fMax"])
        self.assertIsNone(permuter.decl_info(v, v.body.body[2]))

    def test_overloads_need_line(self):
        text = SAMPLE + "\nfloat CThing::Update(int n)\n{\n\treturn 0;\n}\n"
        with self.assertRaises(SystemExit):
            permuter.Func(text, "CThing::Update")
        f = permuter.Func(text, "CThing::Update", line=text.count("\n", 0, text.rindex("float CThing")) + 1)
        self.assertIn("int n)", f.source())

    def test_symbol_names(self):
        self.assertEqual(permuter.func_from_symbol("?Fire@TronTurret@@AAE?AW4WeaponState@@XZ"),
                         "TronTurret::Fire")
        self.assertEqual(permuter.func_from_symbol("??0CFoo@@QAE@XZ"), "CFoo::CFoo")
        self.assertEqual(permuter.func_from_symbol("?Get@Inner@Outer@@QAEHXZ"), "Outer::Inner::Get")


class Mutations(unittest.TestCase):
    def setUp(self):
        self.f = permuter.Func(SAMPLE, "CThing::Update")
        self.src = self.f.source()

    def apply(self, m, seed=1, n=40):
        rng = random.Random(seed)
        outs = set()
        for _ in range(n):
            r = m(permuter.View(self.src, self.f), rng, OPTS)
            if r is not None:
                outs.add(r)
        return outs

    def test_every_mutation_keeps_brackets(self):
        for m, _ in permuter.MUTATIONS:
            for r in self.apply(m):
                self.assertNotEqual(r, self.src, m.__name__)
                self.assertTrue(balanced(r), m.__name__ + ":\n" + r)
                permuter.View(r, self.f)          # still parses

    def test_swap(self):
        outs = self.apply(permuter.m_swap)
        self.assertTrue(any("DoB(n);\n\tDoA(p);" in r for r in outs))

    def test_strict_swap(self):
        strict = types.SimpleNamespace(loose=False, strict=True)
        rng = random.Random(1)
        for _ in range(40):
            r = permuter.m_swap(permuter.View(self.src, self.f), rng, strict)
            self.assertFalse(r and "DoB(n);\n\tDoA(p);" in r)

    def test_commute(self):
        outs = self.apply(permuter.m_commute, n=200)
        self.assertTrue(any("2 * n" in r for r in outs))
        self.assertTrue(any("n > i" in r for r in outs))
        self.assertTrue(any("fMax * fSum" in r for r in outs))

    def test_incdec(self):
        outs = self.apply(permuter.m_incdec)
        self.assertEqual(outs, {self.src.replace("i++)", "++i)")})

    def test_not(self):
        outs = self.apply(permuter.m_not)
        self.assertIn(self.src.replace("!m_pOwner", "(m_pOwner == 0)"), outs)

    def test_loop(self):
        outs = self.apply(permuter.m_loop)
        self.assertEqual(len(outs), 1)
        r = outs.pop()
        self.assertIn("while (i < n)", r)
        self.assertIn("i++;", r)
        self.assertNotIn("for", r)

    def test_if(self):
        outs = self.apply(permuter.m_if)
        self.assertTrue(any("if (!(!m_pOwner))" in r for r in outs))
        # the else after a return goes
        self.assertTrue(any("else" not in r for r in outs))

    def test_cast(self):
        outs = self.apply(permuter.m_cast, n=80)
        self.assertIn(self.src.replace("(float)n", "n"), outs)

    def test_return_temp(self):
        outs = self.apply(permuter.m_return_temp)
        self.assertTrue(any("float permRet0 = fSum * fMax;\n\treturn permRet0;" in r for r in outs))

    def test_decl_order(self):
        outs = self.apply(permuter.m_decl_order)
        self.assertTrue(any("float fMax = 1.0f, fSum = 0.0f;" in r for r in outs))
        self.assertTrue(any("float fSum = 0.0f;\n\tfloat fMax = 1.0f;" in r for r in outs))

    def test_split_expr(self):
        outs = self.apply(permuter.m_split_expr)
        self.assertIn(self.src.replace("m_nCount = n * 2;", "m_nCount = n;\n\tm_nCount *= 2;"), outs)


class CommandLine(unittest.TestCase):
    CMD = ("cd src/Game/ObjectDLL/TRON && WINEPREFIX=/repo/out/release-tree/.wine/drives "
           "INCLUDE='t:\\msvc\\INCLUDE;s:\\x' wine /repo/out/release-tree/ext/toolchains/"
           "msvc-6.00-8168/BIN/cl.exe '/nologo' '/O2' '/Yustdafx.h' "
           "'/Fp..\\..\\Built\\Final\\ObjectDLL\\TRON\\Object.pch' "
           "'/Fo..\\..\\Built\\Final\\ObjectDLL\\TRON\\' '/c' '.\\TronTurret.cpp'")

    def test_parse(self):
        c = permuter.Command(self.CMD)
        self.assertEqual(c.root, "/repo/out/release-tree")
        self.assertEqual(c.container_source(),
                         "/repo/out/release-tree/src/Game/ObjectDLL/TRON/TronTurret.cpp")
        sh = c.shell("z:\\scratch\\out\\t.obj")
        self.assertIn("/Foz:\\scratch\\out\\t.obj", sh)
        self.assertIn("WINEPREFIX=/scratch/pfx", sh)
        self.assertIn("/Fp..", sh)
        self.assertNotIn("/Fo..", sh)


TINY = """\
int g_a, g_b;
int DoA(int);
int DoB(int);

int Tiny(int n)
{
	int x = DoA(n);
	int y = DoB(n + 1);
	g_a = x;
	g_b = y;
	return x + y;
}
"""
TINY_TARGET = TINY.replace("\tint x = DoA(n);\n\tint y = DoB(n + 1);\n",
                           "\tint y = DoB(n + 1);\n\tint x = DoA(n);\n")


@unittest.skipUnless(os.environ.get("PERMUTER_TEST_REPO"), "set PERMUTER_TEST_REPO to a game repository")
class End2End(unittest.TestCase):
    def test_tiny(self):
        game = os.path.abspath(os.path.expanduser(os.environ["PERMUTER_TEST_REPO"]))
        tc = os.path.join(game, "ext", "toolchains")
        image = os.path.basename(game) + "-build"
        tmp = tempfile.mkdtemp(prefix="permuter-test-")
        try:
            repo = os.path.join(tmp, "repo")
            os.makedirs(os.path.join(repo, "src"))
            with open(os.path.join(repo, "src", "tiny.cpp"), "w") as f:
                f.write(TINY)
            cmd = ("cd src && INCLUDE='z:\\tc\\msvc-6.00-8168\\INCLUDE' "
                   "wine /tc/msvc-6.00-8168/BIN/cl.exe /nologo /O2 /c /Fotiny.obj tiny.cpp")
            with open(os.path.join(repo, "src", "tiny.obj.cmd"), "w") as f:
                f.write(cmd + "\n")
            # the target: the same command on the target source, in a
            # worker of the permuter's own
            args = types.SimpleNamespace(repo=repo, docker_image=image,
                                         mount=[f"{tc}:/tc"], compile_timeout=120)
            c = permuter.Command(cmd)
            base = os.path.join(tmp, "target")
            os.makedirs(base)
            try:
                permuter.make_prefix(args, c, base)
                w = permuter.Worker(0, args, c, base, TINY)
                obj, out = w.compile(TINY_TARGET)
                self.assertIsNotNone(obj, out)
                target = os.path.join(tmp, "target.obj")
                shutil.copy(obj, target)
            finally:
                permuter.cleanup_containers()
            subprocess.run(["rm", "-rf", base])
            out = os.path.join(tmp, "out")
            rc = permuter.main(["--repo", repo, "--obj", "src/tiny.obj", "--symbol", "?Tiny@@YAHH@Z",
                                "--func", "Tiny", "--target-obj", target, "--mount", f"{tc}:/tc",
                                "--docker-image", image, "--workers", "2", "--time", "300",
                                "--seed", "1", "--out", out])
            self.assertEqual(rc, 0)
            with open(os.path.join(out, "best.cpp")) as f:
                best = f.read()
            # DoB is called first, as in the target; the simplify step puts
            # back what the score does not need
            body = best[best.index("int Tiny("):]
            self.assertLess(body.index("DoB("), body.index("DoA("))
            self.assertIn("return x + y;", best)
            with open(os.path.join(out, "best.diff")) as f:
                self.assertTrue(f.read().startswith("--- a/src/tiny.cpp"))
        finally:
            permuter.cleanup_containers()
            subprocess.run(["rm", "-rf", tmp])


if __name__ == "__main__":
    unittest.main()
