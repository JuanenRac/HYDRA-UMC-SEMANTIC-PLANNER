# =============================================================================
# HYDRA-UMC-SEMANTIC-PLANNER - tests/test_unit_configs.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Every file the unit names inside the folder of the service is in this repository, so that the installer can copy it.

The unit points the service at /opt/hydra-umc/semantic-planner/configs/deploy-cm5.json; an installer that copies only src/ leaves the service without its configuration. The installer of
HYDRA-UMC-OS copies the folders named here and refuses to start when the file is missing from the source.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNIT = ROOT / "systemd" / "hydra-umc-semantic-planner.service"
STATE = {"data", "models", "workspace"}


class UnitConfigsTests(unittest.TestCase):
    def named(self):
        text = UNIT.read_text(encoding="utf-8")
        return [m for m in re.findall(r"/opt/hydra-umc/semantic-planner/([A-Za-z0-9_.-]+)(?:/([A-Za-z0-9_./-]+))?", text) if m[0] not in STATE and m[0] != "src"]

    def test_the_unit_names_the_configuration_file(self):
        self.assertIn(("configs", "deploy-cm5.json"), self.named())

    def test_every_file_it_names_is_in_the_repository(self):
        for folder, name in self.named():
            self.assertTrue((ROOT / folder / name).is_file() if name else (ROOT / folder).is_dir(), f"{folder}/{name}")

    def test_the_deployment_profile_is_valid_json(self):
        json.loads((ROOT / "configs" / "deploy-cm5.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
