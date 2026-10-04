"""Pages made from the framework's own files: what they promise has to be
something the framework really does."""

import sys
import tempfile
import unittest
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCS / "tools"))

from rmpdocs import generated  # noqa: E402


class BuildDefinesTest(unittest.TestCase):
    """reference.toml [build_defines] lists macros the build passes. One that
    no build passes any more would be read as 0 by every #if a reader writes."""

    def framework(self, cmake: str) -> Path:
        tmp = Path(tempfile.mkdtemp())
        (tmp / "CMakeLists.txt").write_text(cmake)
        return tmp

    def test_a_define_the_build_passes_is_documented(self):
        fw = self.framework('target_compile_definitions(rmp PUBLIC RMP_PRODUCTION_BUILD=1)\n')
        table, wrong = generated.build_defines_table(
            fw, {"build_defines": {"RMP_PRODUCTION_BUILD": {"set_in": ["CMakeLists.txt"], "doc": "1 or 0."}}})
        self.assertEqual(wrong, [])
        self.assertIn('id="RMP_PRODUCTION_BUILD"', table)

    def test_a_define_no_build_passes_is_refused(self):
        fw = self.framework('# RMP_PRODUCTION_BUILD is only mentioned here\n')
        _table, wrong = generated.build_defines_table(
            fw, {"build_defines": {"RMP_PRODUCTION_BUILD": {"set_in": ["CMakeLists.txt", "missing.yml"],
                                                            "doc": "1 or 0."}}})
        self.assertEqual(len(wrong), 2)
        self.assertIn("CMakeLists.txt does not set it", wrong[0])
        self.assertIn("missing.yml does not set it", wrong[1])

    def test_a_define_that_names_no_file_is_refused(self):
        _table, wrong = generated.build_defines_table(
            self.framework(""), {"build_defines": {"RMP_X": {"doc": "?"}}})
        self.assertEqual(wrong, ["[build_defines] RMP_X: says no file that sets it (set_in)"])

    def test_the_real_ones_hold(self):
        fw = DOCS.parent / "raylib_multiplatform"
        if not (fw / "CMakeLists.txt").is_file():
            self.skipTest("no framework next to rmp-docs")
        import tomllib
        refconf = tomllib.loads((DOCS / "reference.toml").read_text())
        _table, wrong = generated.build_defines_table(fw, refconf)
        self.assertEqual(wrong, [])
        self.assertTrue(refconf["build_defines"])


if __name__ == "__main__":
    unittest.main()
