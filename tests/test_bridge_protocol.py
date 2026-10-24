"""B2 — bridge protocol, discovery and the fake bridge (BR-01, BR-02, BR-11)."""

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from autodebug.bridge import protocol
from autodebug.bridge.client import BridgeConnection, ConnectionInfo, bridges_dir, discover, normalize_folder, select
from autodebug.errors import AutoDebugError, ErrorCode
from tests.fixtures.fake_bridge import FakeBridge

WORKSPACE = "D:\\Projects\\AutoDebug\\examples\\AutoDebugDemo"


class Protocol(unittest.TestCase):
    def test_round_trip(self):
        message = {"id": 1, "op": "stack", "args": {"levels": 5, "name": "π"}}
        self.assertEqual(protocol.decode(protocol.encode(message)), message)

    def test_rejects_bad_messages(self):
        for line in (b"{\"a\":1}", b"[1]\n", b"{\"a\":1,\"a\":2}\n", b"{\"a\":NaN}\n", b"\xff\n",
                     b"{\"a\":\"" + b"x" * protocol.MAX_MESSAGE_BYTES + b"\"}\n"):
            with self.subTest(line=line[:20]), self.assertRaises(protocol.ProtocolError):
                protocol.decode(line)
        with self.assertRaises(protocol.ProtocolError):
            protocol.encode({"a": "x" * protocol.MAX_MESSAGE_BYTES})


class Discovery(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name) / "evidence"
        self.folder = bridges_dir(self.base)

    def bridge(self, **kwargs) -> FakeBridge:
        fake = FakeBridge(self.folder, kwargs.pop("workspace", WORKSPACE), **kwargs)
        self.addCleanup(fake.close)
        return fake

    def test_missing_folder_means_no_bridges(self):
        self.assertEqual(discover(self.folder), ())

    def test_finds_a_valid_bridge_and_hides_its_token(self):
        fake = self.bridge()
        (info,) = discover(self.folder)
        self.assertEqual((info.window_id, info.ide, info.port), ("window-1", "vscode", fake.port))
        self.assertNotIn(fake.token, repr(info))

    def test_skips_malformed_files(self):
        fake = self.bridge()
        good = fake.connection_data()
        bad_values = [{"host": "0.0.0.0"}, {"port": 0}, {"token": "short"}, {"ide": "clion"}, {"protocol": 2},
                      {"workspace_folders": []}, {"window_id": "../x"}]
        for number, change in enumerate(bad_values):
            path = self.folder / f"bad-{number}.json"
            path.write_text(json.dumps({**good, **change}), encoding="utf-8")
            os.chmod(path, 0o600)
        (self.folder / "junk.json").write_text("{not json", encoding="utf-8")
        self.assertEqual([i.window_id for i in discover(self.folder)], ["window-1"])

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_refuses_a_folder_others_can_read(self):
        self.bridge()
        os.chmod(self.folder, 0o755)
        with self.assertRaises(AutoDebugError) as caught:
            discover(self.folder)
        self.assertIs(caught.exception.detail.code, ErrorCode.PERMISSION_DENIED)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_ignores_files_others_can_read(self):
        fake = self.bridge()
        os.chmod(self.folder / f"{fake.window_id}.json", 0o644)
        self.assertEqual(discover(self.folder), ())

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_ignores_linked_files(self):
        fake = self.bridge(write_file=False)
        target = self.base.parent / "elsewhere.json"
        target.write_text(json.dumps(fake.connection_data()), encoding="utf-8")
        os.chmod(target, 0o600)
        self.folder.mkdir(mode=0o700, parents=True)
        (self.folder / "linked.json").symlink_to(target)
        self.assertEqual(discover(self.folder), ())


class Selection(unittest.TestCase):
    def info(self, window_id="w1", ide="vscode", folders=(WORKSPACE,)) -> ConnectionInfo:
        return ConnectionInfo(window_id, ide, 1234, "a" * 64, folders, "0.1.0")

    def test_windows_paths_match_case_and_separator_insensitively(self):
        self.assertEqual(normalize_folder("d:/projects/autodebug/examples/autodebugdemo/"), normalize_folder(WORKSPACE))
        self.assertNotEqual(normalize_folder("/Users/Dev/demo"), normalize_folder("/users/dev/demo"))

    def test_selects_the_one_matching_window(self):
        chosen = select((self.info("w1", folders=("C:\\other",)), self.info("w2")), WORKSPACE.lower(), "vscode")
        self.assertEqual(chosen.window_id, "w2")

    def test_no_match_is_unavailable(self):
        for infos in ((), (self.info(ide="cursor"),), (self.info(folders=("C:\\other",)),)):
            with self.subTest(infos=infos), self.assertRaises(AutoDebugError) as caught:
                select(infos, WORKSPACE, "vscode")
            self.assertIs(caught.exception.detail.code, ErrorCode.BACKEND_UNAVAILABLE)

    def test_folder_open_in_the_other_ide_names_it(self):
        with self.assertRaises(AutoDebugError) as caught:
            select((self.info(ide="cursor"),), WORKSPACE, "vscode")
        self.assertIn("create the case with target ide 'cursor'", caught.exception.detail.message)

    def test_two_windows_are_ambiguous(self):
        with self.assertRaises(AutoDebugError) as caught:
            select((self.info("w1"), self.info("w2")), WORKSPACE, "vscode")
        self.assertIs(caught.exception.detail.code, ErrorCode.SESSION_AMBIGUOUS)


class Connection(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fake = FakeBridge(Path(tmp.name) / "bridges", WORKSPACE)
        self.addCleanup(self.fake.close)
        (self.info,) = discover(Path(tmp.name) / "bridges")

    def connect(self, info=None) -> BridgeConnection:
        connection = BridgeConnection(info or self.info)
        self.addCleanup(connection.close)
        return connection

    def test_authenticated_request(self):
        result = self.connect().request("describe")
        self.assertEqual(result["workspace_folders"], [WORKSPACE])
        self.assertEqual(self.fake.calls, [("describe", {})])

    def test_wrong_token_gets_no_reply(self):
        with self.assertRaises(AutoDebugError) as caught:
            self.connect(replace(self.info, token="b" * 64))
        self.assertIs(caught.exception.detail.code, ErrorCode.BACKEND_UNAVAILABLE)
        self.assertEqual(self.fake.calls, [])

    def test_wrong_window_is_refused(self):
        with self.assertRaises(AutoDebugError):
            self.connect(replace(self.info, window_id="window-2"))

    def test_bridge_errors_keep_their_code(self):
        connection = self.connect()
        with self.assertRaises(AutoDebugError) as caught:
            connection.request("step", {"approval_id": "forged", "kind": "step_over"})
        self.assertIs(caught.exception.detail.code, ErrorCode.NOT_APPROVED)
        with self.assertRaises(AutoDebugError) as caught:
            connection.request("evaluate", {"expression": "__import__('os')"})
        self.assertIs(caught.exception.detail.code, ErrorCode.CAPABILITY_UNSUPPORTED)

    def test_unreachable_port(self):
        self.fake.close()
        port_info = replace(self.info, port=self.fake.port)
        with self.assertRaises(AutoDebugError) as caught:
            BridgeConnection(port_info, connect_timeout=1)
        self.assertIs(caught.exception.detail.code, ErrorCode.BACKEND_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
