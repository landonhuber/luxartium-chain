"""Windows operator recipe exercised with all Docker/task/Python calls mocked."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class WelcomeUpgradeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows operator recipe")
    def test_fresh_backup_activation_order_and_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="luxartium-welcome-recipe-") as directory:
            environment = {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}
            result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(Path(__file__).with_name("test_welcome_upgrade_recipe.ps1")), "-TestDirectory", directory],
                capture_output=True, text=True, timeout=30, env=environment)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS synthetic", result.stdout)


if __name__ == "__main__":
    unittest.main()
