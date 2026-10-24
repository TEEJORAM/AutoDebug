"""B1 — plan schema 0.3 and the extended digest (BR-03)."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from autodebug.adapters import VSCodeAdapter
from autodebug.approvals import ApprovalBroker
from autodebug.facade import AutoDebugFacade
from autodebug.models import (
    BRIDGE_SCHEMA_VERSION, Breakpoint, CasePlan, CasePolicy, IntakeSource, ReproductionPlan, TargetRef,
)
from autodebug.plans import bind_resolved_inputs, compute_plan_digest, resolve_inputs, stage_plan, validate_case_plan
from autodebug.sessions import SessionRegistry

WORKSPACE = "D:\\Projects\\AutoDebug\\examples\\AutoDebugDemo"
TARGET = TargetRef(host_id="local-windows", ide="vscode", debug_session_id=None, pid=None)
LAUNCH = {"name": "Debug tests", "type": "debugpy", "request": "launch", "module": "unittest", "args": ["-v"]}
TASK = {"label": "cmake build", "type": "shell", "command": "cmake --build build"}
SOURCE = b"def polygon_area(points):\n    total = 0.0\n"


def bridge_plan(**overrides) -> CasePlan:
    values = dict(
        schema_version=BRIDGE_SCHEMA_VERSION, case_id="DEMO-AREA-MOVE", source_revision="working-tree",
        target=TARGET, breakpoints=(Breakpoint(file="geometry.py", line=15),),
        reproduction=ReproductionPlan(mode="manual", steps=("Run the tests under the debugger",)),
        policy=CasePolicy(max_steps=20, max_inspection_seconds=600),
        workspace_folder=WORKSPACE, launch_configuration_name="Debug tests",
    )
    values.update(overrides)
    return CasePlan(**values)


def resolved(plan: CasePlan, launch=LAUNCH, task=None, files=None):
    files = {"geometry.py": SOURCE} if files is None else files
    return resolve_inputs(plan, launch=launch, task=task, files=files)


class ValidBridgePlans(unittest.TestCase):
    def test_minimal_plan_is_valid(self):
        validate_case_plan(bridge_plan())

    def test_cursor_posix_workspace_build_task_and_nested_file_are_valid(self):
        validate_case_plan(bridge_plan(
            target=replace(TARGET, ide="cursor", host_id="local-mac"), workspace_folder="/Users/dev/demo",
            build_task="cmake build", breakpoints=(Breakpoint(file="cpp/geometry.cpp", line=16),),
            policy=CasePolicy(max_steps=5, max_inspection_seconds=60, max_build_seconds=900),
        ))

    def test_report_to_workspace_defaults_to_true(self):
        self.assertIs(bridge_plan().report_to_workspace, True)


class InvalidBridgePlans(unittest.TestCase):
    def assertInvalid(self, **overrides):
        with self.assertRaises(ValueError):
            validate_case_plan(bridge_plan(**overrides))

    def test_other_ides_are_refused(self):
        self.assertInvalid(target=replace(TARGET, ide="clion"))

    def test_workspace_folder_must_be_absolute(self):
        for folder in (None, "", "examples/AutoDebugDemo", "C:relative", "a" * 2001, "C:\\x\x00y"):
            with self.subTest(folder=folder):
                self.assertInvalid(workspace_folder=folder)

    def test_launch_configuration_name_is_required_and_bounded(self):
        for name in (None, "", "   ", "x" * 201, "Debug\ntests"):
            with self.subTest(name=name):
                self.assertInvalid(launch_configuration_name=name)

    def test_build_task_is_bounded(self):
        for task in ("", "x" * 201, "build\r"):
            with self.subTest(task=task):
                self.assertInvalid(build_task=task)

    def test_launch_only(self):
        self.assertInvalid(process_running=True)
        self.assertInvalid(launch_configuration=(("program", "report.py"),))

    def test_breakpoints_must_stay_inside_the_workspace(self):
        for file in ("/etc/passwd", "C:\\Windows\\x.py", "C:x.py", "\\\\server\\share\\x.py",
                     "../outside.py", "src\\..\\..\\x.py", "./", "a\x00.py", ""):
            with self.subTest(file=file):
                self.assertInvalid(breakpoints=(Breakpoint(file=file, line=1),))

    def test_max_build_seconds_bounds(self):
        for seconds in (0, 901, True, 1.5):
            with self.subTest(seconds=seconds):
                self.assertInvalid(policy=CasePolicy(max_steps=1, max_inspection_seconds=60, max_build_seconds=seconds))

    def test_report_to_workspace_must_be_bool(self):
        self.assertInvalid(report_to_workspace="yes")

    def test_legacy_schemas_cannot_use_bridge_fields(self):
        legacy = dict(schema_version="0.2-draft", target=replace(TARGET, ide="clion"))
        for extra in ({"workspace_folder": WORKSPACE}, {"launch_configuration_name": "x"}, {"build_task": "b"},
                      {"report_to_workspace": False}, {"resolved_inputs": (("launch", "a" * 64),)},
                      {"policy": CasePolicy(max_steps=1, max_inspection_seconds=60, max_build_seconds=60)}):
            with self.subTest(extra=extra):
                fields = {"workspace_folder": None, "launch_configuration_name": None, **legacy, **extra}
                with self.assertRaises(ValueError):
                    validate_case_plan(bridge_plan(**fields))


class LegacyDigestIsStable(unittest.TestCase):
    def test_new_fields_do_not_change_legacy_digests(self):
        plan = CasePlan(
            schema_version="0.1-draft", case_id="C", source_revision="r",
            target=TargetRef(host_id="local-mac", ide="clion", debug_session_id=None, pid=None),
            breakpoints=(Breakpoint(file="/repo/a.cpp", line=1),),
            reproduction=ReproductionPlan(mode="manual", steps=("s",)),
            policy=CasePolicy(max_steps=1, max_inspection_seconds=60),
        )
        # Digest computed before schema 0.3 existed, for exactly this plan.
        self.assertEqual(compute_plan_digest(plan), "34d4bf60a938c00f4e03835fc83df4631c129d8f1adcc5a8508faf125bcdbd97")


class ResolvedInputs(unittest.TestCase):
    def test_hashes_cover_launch_task_and_each_breakpoint_file(self):
        plan = bridge_plan(build_task="cmake build",
                           breakpoints=(Breakpoint("geometry.py", 15), Breakpoint("geometry.py", 9)))
        inputs = dict(resolved(plan, task=TASK))
        self.assertEqual(sorted(inputs), ["file:geometry.py", "launch", "task"])
        self.assertTrue(all(len(v) == 64 for v in inputs.values()))

    def test_each_input_changes_the_digest(self):
        plan = bridge_plan(build_task="cmake build")
        base = bind_resolved_inputs(stage_plan(plan), resolved(plan, task=TASK)).digest_sha256
        for kwargs in ({"launch": {**LAUNCH, "args": ["-q"]}}, {"task": {**TASK, "command": "rm -rf ."}},
                       {"files": {"geometry.py": SOURCE + b"# edited\n"}}):
            with self.subTest(changed=list(kwargs)):
                args = {"task": TASK, **kwargs}
                other = bind_resolved_inputs(stage_plan(plan), resolved(plan, **args)).digest_sha256
                self.assertNotEqual(base, other)

    def test_key_order_does_not_change_the_hash(self):
        reordered = dict(reversed(list(LAUNCH.items())))
        self.assertEqual(resolved(bridge_plan()), resolved(bridge_plan(), launch=reordered))

    def test_attach_configurations_are_refused(self):
        with self.assertRaises(ValueError):
            resolved(bridge_plan(), launch={**LAUNCH, "request": "attach"})

    def test_launch_name_must_match_the_plan(self):
        with self.assertRaises(ValueError):
            resolved(bridge_plan(), launch={**LAUNCH, "name": "Debug report.py"})

    def test_task_presence_must_match_the_plan(self):
        with self.assertRaises(ValueError):
            resolved(bridge_plan(), task=TASK)
        with self.assertRaises(ValueError):
            resolved(bridge_plan(build_task="cmake build"), task=None)
        with self.assertRaises(ValueError):
            resolved(bridge_plan(build_task="other"), task=TASK)

    def test_every_breakpoint_file_is_required_and_nothing_else(self):
        with self.assertRaises(ValueError):
            resolved(bridge_plan(), files={})
        with self.assertRaises(ValueError):
            resolved(bridge_plan(), files={"geometry.py": SOURCE, "other.py": b""})

    def test_binding_validates_and_restages(self):
        plan = stage_plan(bridge_plan())
        bound = bind_resolved_inputs(plan, resolved(plan))
        self.assertNotEqual(bound.digest_sha256, plan.digest_sha256)
        self.assertEqual(bound.digest_sha256, compute_plan_digest(bound))
        with self.assertRaises(ValueError):
            bind_resolved_inputs(plan, (("launch", "not-a-digest"),))
        with self.assertRaises(ValueError):
            bind_resolved_inputs(plan, (("launch", "a" * 64),))  # missing file:geometry.py
        with self.assertRaises(ValueError):
            bind_resolved_inputs(bound, resolved(plan))  # already bound


class AgentCannotSupplyResolvedInputs(unittest.TestCase):
    def test_stage_plan_refuses_caller_supplied_hashes(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        broker = ApprovalBroker(now=lambda: 0.0, make_token=lambda: "t")
        facade = AutoDebugFacade(registry=SessionRegistry(), broker=broker, evidence_base_dir=Path(tmp.name))
        facade.autodebug_create_case(case_id="DEMO-AREA-MOVE", intake_source=IntakeSource.DEVELOPER_TEXT,
                                     intake_description="area changes when moved", adapter=VSCodeAdapter(),
                                     target=TARGET)
        plan = bridge_plan()
        forged = replace(plan, resolved_inputs=resolved(plan))
        result = facade.autodebug_stage_plan(case_id="DEMO-AREA-MOVE", plan=forged)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")
        self.assertTrue(facade.autodebug_stage_plan(case_id="DEMO-AREA-MOVE", plan=plan)["ok"])


class McpDecoding(unittest.TestCase):
    def test_a_json_plan_decodes_to_schema_0_3(self):
        from autodebug.server import TOOLS, _decode
        raw = {
            "schema_version": "0.3", "case_id": "DEMO-AREA-MOVE", "source_revision": "working-tree",
            "target": {"host_id": "local-windows", "ide": "vscode", "debug_session_id": None, "pid": None},
            "workspace_folder": WORKSPACE, "launch_configuration_name": "Debug tests",
            "breakpoints": [{"file": "geometry.py", "line": 15}],
            "reproduction": {"mode": "manual", "steps": ["Run the tests under the debugger"]},
            "policy": {"max_steps": 20, "max_inspection_seconds": 600, "max_build_seconds": 120},
        }
        plan = _decode(raw, TOOLS["autodebug_stage_plan"].parameters["plan"])
        self.assertEqual(plan, bridge_plan(policy=CasePolicy(max_steps=20, max_inspection_seconds=600,
                                                              max_build_seconds=120)))
        self.assertEqual(len(stage_plan(plan).digest_sha256), 64)


if __name__ == "__main__":
    unittest.main()
