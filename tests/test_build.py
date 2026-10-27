"""Which build a launch configuration runs (src/autodebug/build.py)."""

import tempfile
import unittest
from pathlib import Path

from autodebug.build import build_type, describe


class BuildType(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def launch(self, program, kind="cppdbg"):
        return {"type": kind, "request": "launch", "program": program}

    def test_visual_studio_uses_the_active_configuration(self):
        info = build_type({"type": "visualstudio", "configuration": "Debug|x64", "program": "x"}, str(self.root))
        self.assertEqual((info["type"], info["platform"], info["optimized"], info["debug_symbols"]),
                         ("Debug", "x64", False, True))
        self.assertEqual(info["source"], "Visual Studio's active configuration")
        self.assertNotIn("note", info)
        self.assertEqual(describe(info), "Debug x64 build (not optimized, with debug symbols)")
        relwithdebinfo = build_type({"type": "visualstudio", "configuration": "RelWithDebInfo|x64"}, str(self.root))
        self.assertIn("optimized away", relwithdebinfo["note"])
        release = build_type({"type": "visualstudio", "configuration": "Release|Win32"}, str(self.root))
        self.assertIn("breakpoints may not bind", release["note"])
        self.assertEqual(describe(release), "Release Win32 build (optimized, usually without debug symbols)")

    def test_the_programs_folder_names_the_type(self):
        for program, expected in (("${workspaceFolder}/build/RelWithDebInfo/app.exe", "RelWithDebInfo"),
                                  ("target/debug/app", "Debug"),
                                  ("${workspaceFolder}/bin/Release/net8.0/app.dll", "Release")):
            info = build_type(self.launch(program), str(self.root))
            self.assertEqual(info["type"], expected, program)
            self.assertIn("the program's folder", info["source"])

    def test_a_single_config_cmake_build_is_read_from_its_cache(self):
        build = self.root / "build"
        build.mkdir()
        (build / "CMakeCache.txt").write_text("CMAKE_BUILD_TYPE:STRING=RelWithDebInfo\n", encoding="utf-8")
        info = build_type(self.launch("${workspaceFolder}/build/bin/app"), str(self.root))
        self.assertEqual((info["type"], info["source"]), ("RelWithDebInfo", "CMAKE_BUILD_TYPE in CMakeCache.txt"))
        (build / "CMakeCache.txt").write_text("CMAKE_BUILD_TYPE:STRING=\n", encoding="utf-8")
        empty = build_type(self.launch("${workspaceFolder}/build/bin/app"), str(self.root))
        self.assertIsNone(empty["type"])
        self.assertIn("no debug symbols", empty["source"])

    def test_unknown_custom_and_interpreted(self):
        self.assertIsNone(build_type(self.launch("${command:pick}/app"), str(self.root))["type"])
        self.assertIsNone(build_type(self.launch(str(self.root / "app")), str(self.root))["type"])
        custom = build_type({"type": "visualstudio", "configuration": "Checked|x64"}, str(self.root))
        self.assertEqual((custom["type"], custom["optimized"]), ("Checked", None))
        self.assertIn("not a standard build type", custom["note"])
        python = build_type({"type": "debugpy", "request": "launch", "module": "unittest"}, str(self.root))
        self.assertEqual(describe(python), "interpreted language: no build type")


if __name__ == "__main__":
    unittest.main()
