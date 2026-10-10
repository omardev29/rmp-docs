"""The installers the site serves: the framework's bytes at FRAMEWORK_REF, with
the line endings git gives them on checkout -- which is not what `git show`
gives, and that difference is the whole reason this file exists."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs import checks, served, truth  # noqa: E402

FRAMEWORK = Path(os.environ.get("RMP_FRAMEWORK", DOCS.parent / "raylib_multiplatform"))

# The framework's own .gitattributes, as it is.
ATTRIBUTES = """thirdparty/** linguist-vendored=true
* text=auto eol=native
*.bat text eol=crlf
*.cmd text eol=crlf
*.ps1 text eol=crlf
*.sh  text eol=lf

.clangd filter=gitignore
rmp   text eol=lf
"""


class EolTest(unittest.TestCase):
    def test_the_last_matching_line_decides(self):
        self.assertEqual(served.eol_rule(ATTRIBUTES, "tools/install.ps1"), "crlf")
        self.assertEqual(served.eol_rule(ATTRIBUTES, "tools/install.sh"), "lf")
        self.assertEqual(served.eol_rule(ATTRIBUTES, "rmp"), "lf")
        self.assertEqual(served.eol_rule(ATTRIBUTES, "rmp.cmd"), "crlf")

    def test_native_and_no_rule_change_nothing(self):
        self.assertEqual(served.eol_rule(ATTRIBUTES, "README.md"), "")
        self.assertEqual(served.eol_rule("", "tools/install.ps1"), "")
        self.assertEqual(served.eol_rule(ATTRIBUTES + "*.ps1 -text\n", "tools/install.ps1"), "")

    def test_a_pattern_with_a_slash_is_a_path(self):
        self.assertEqual(served.eol_rule("tools/*.ps1 eol=crlf\n", "tools/install.ps1"), "crlf")
        self.assertEqual(served.eol_rule("tools/*.ps1 eol=crlf\n", "other/install.ps1"), "")

    def test_normalise_both_ways_and_twice(self):
        self.assertEqual(served.normalise(b"a\nb\n", "crlf"), b"a\r\nb\r\n")
        self.assertEqual(served.normalise(b"a\r\nb\r\n", "crlf"), b"a\r\nb\r\n")
        self.assertEqual(served.normalise(b"a\r\nb\n", "lf"), b"a\nb\n")
        self.assertEqual(served.normalise(b"a\r\nb\n", ""), b"a\r\nb\n")

    def test_the_first_difference(self):
        self.assertEqual(served.first_difference(b"abc", b"abd"), 2)
        self.assertEqual(served.first_difference(b"ab", b"abc"), 2)


@unittest.skipIf(shutil.which("git") is None, "needs git")
class AtRefTest(unittest.TestCase):
    """A real repository: the blob at a commit, not the file on disk."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)

        def git(*argv):
            return subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=t",
                                   "-c", "user.email=t@t", *argv], check=True,
                                  capture_output=True, text=True).stdout.strip()
        self.git = git
        git("init", "-q")
        (self.repo / ".gitattributes").write_text(ATTRIBUTES)
        (self.repo / "tools").mkdir()
        (self.repo / "tools" / "install.ps1").write_bytes(b"Write-Host 'one'\r\nWrite-Host 'two'\r\n")
        git("add", "-A")
        git("commit", "-q", "-m", "one")
        self.ref = git("rev-parse", "HEAD")

    def test_git_stores_lf_and_the_site_serves_crlf(self):
        self.assertEqual(served.at_ref(self.repo, self.ref, "tools/install.ps1"),
                         b"Write-Host 'one'\nWrite-Host 'two'\n")
        want, eol = served.expected(self.repo, self.ref, "tools/install.ps1")
        self.assertEqual(eol, "crlf")
        self.assertEqual(want, b"Write-Host 'one'\r\nWrite-Host 'two'\r\n")
        self.assertEqual(served.from_checkout(self.repo, "tools/install.ps1"), want)

    def test_a_checkout_that_moved_on_is_not_the_ref(self):
        (self.repo / "tools" / "install.ps1").write_bytes(b"Write-Host 'one'\r\nWrite-Host 'TWO'\r\n")
        want, _eol = served.expected(self.repo, self.ref, "tools/install.ps1")
        self.assertNotEqual(served.from_checkout(self.repo, "tools/install.ps1"), want)

    def test_a_file_the_ref_does_not_have_says_so(self):
        with self.assertRaises(LookupError) as e:
            served.at_ref(self.repo, self.ref, "tools/install.sh")
        self.assertIn("at FRAMEWORK_REF", str(e.exception))


class GateTest(unittest.TestCase):
    """The gate on a framework that is a real repository: one byte planted in
    what the site serves is red, and naming the right line."""

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_one_byte_is_red(self):
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, repo, True)
        run = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t",  # noqa: E731
                                         "-c", "user.email=t@t", *a], check=True, capture_output=True)
        run("init", "-q")
        (repo / ".gitattributes").write_text(ATTRIBUTES)
        (repo / "tools").mkdir()
        (repo / "tools" / "install.sh").write_bytes(b"#!/bin/sh\necho one\necho two\n")
        run("add", "-A")
        run("commit", "-q", "-m", "one")
        ref = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                             text=True).stdout.strip()
        config = {"served": {"install.sh": "tools/install.sh"}}
        good = served.from_checkout(repo, "tools/install.sh")
        ctx = checks.Context(docs=repo, config=config, framework=repo, ref=ref,
                             served={"install.sh": good})
        self.assertEqual(truth.check_installer(ctx), [])
        ctx.served["install.sh"] = good.replace(b"two", b"twO")
        got = [str(p) for p in truth.check_installer(ctx)]
        self.assertEqual(len(got), 1)
        self.assertIn("install.sh:3: is not tools/install.sh as it is at FRAMEWORK_REF", got[0])


class RealSiteTest(unittest.TestCase):
    """The site serves what FRAMEWORK_REF has, when the framework has it."""

    def test_the_served_files_are_the_frameworks(self):
        import tomllib
        if not (FRAMEWORK / ".git").exists():
            self.skipTest("no framework checkout next to rmp-docs")
        ref = (DOCS / "FRAMEWORK_REF").read_text().strip()
        config = tomllib.loads((DOCS / "site.toml").read_text())
        self.assertEqual(sorted(config["served"]), ["install.ps1", "install.sh"])
        for name, path in config["served"].items():
            try:
                want, eol = served.expected(FRAMEWORK, ref, path)
            except LookupError as e:
                self.skipTest(str(e))
            self.assertEqual(eol, "crlf" if name.endswith(".ps1") else "lf")
            if b"\r\n" in want:
                self.assertNotIn(b"\n", want.replace(b"\r\n", b""))


if __name__ == "__main__":
    unittest.main()
