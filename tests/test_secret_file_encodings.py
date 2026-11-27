# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_secret_file_encodings.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""A secret file saved by an editor of Windows with a byte order mark holds the same secret; a file in another encoding is refused, never guessed."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hydra_umc_semantic_planner.docs_qa import DocsQaConfigError, DocsQaClient, DocsQaPolicy
from hydra_umc_semantic_planner.plan_trajectory import TrajectoryConfigError, ReplicaClient, TrajectoryPolicy
from hydra_umc_semantic_planner.recovery_export import ExportConfigError, RecoveryExporter, ExportPolicy
from hydra_umc_semantic_planner.safety_gate import SafetyGate, SafetyGateConfigError, SafetyGatePolicy

SECRET = "s3cret-0123456789-abcdefghij-0123456789"


class SecretFileEncodingTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.bom = Path(folder.name, "bom.token")
        self.bom.write_bytes(b"\xef\xbb\xbf" + SECRET.encode("ascii") + b"\r\n")  # what Notepad calls "UTF-8 with BOM"
        self.utf16 = Path(folder.name, "utf16.token")
        self.utf16.write_bytes((SECRET + "\r\n").encode("utf-16"))  # what `>` of Windows PowerShell writes

    def test_the_token_of_docs_qa_ignores_a_byte_order_mark(self) -> None:
        self.assertEqual(DocsQaClient.from_policy(DocsQaPolicy(enabled=True, token_file=str(self.bom)))._token, SECRET)

    def test_the_token_of_docs_qa_refuses_another_encoding(self) -> None:
        with self.assertRaises(DocsQaConfigError):
            DocsQaClient.from_policy(DocsQaPolicy(enabled=True, token_file=str(self.utf16)))

    def test_the_token_of_plan_trajectory_ignores_a_byte_order_mark(self) -> None:
        self.assertEqual(ReplicaClient.from_policy(TrajectoryPolicy(enabled=True, robot="arm", token_file=str(self.bom)))._token, SECRET)

    def test_the_token_of_plan_trajectory_refuses_another_encoding(self) -> None:
        with self.assertRaises(TrajectoryConfigError):
            ReplicaClient.from_policy(TrajectoryPolicy(enabled=True, robot="arm", token_file=str(self.utf16)))

    def test_the_token_of_recovery_export_ignores_a_byte_order_mark(self) -> None:
        self.assertEqual(RecoveryExporter.from_policy(ExportPolicy(enabled=True, token_file=str(self.bom)))._token, SECRET)

    def test_the_token_of_recovery_export_refuses_another_encoding(self) -> None:
        with self.assertRaises(ExportConfigError):
            RecoveryExporter.from_policy(ExportPolicy(enabled=True, token_file=str(self.utf16)))

    def test_the_safety_token_ignores_a_byte_order_mark(self) -> None:
        self.assertEqual(SafetyGate.from_policy(SafetyGatePolicy(enabled=True, require_signature=False, token_file=str(self.bom)))._token, SECRET)

    def test_the_safety_token_refuses_another_encoding(self) -> None:
        with self.assertRaises(SafetyGateConfigError):
            SafetyGate.from_policy(SafetyGatePolicy(enabled=True, require_signature=False, token_file=str(self.utf16)))


if __name__ == "__main__":
    unittest.main()
