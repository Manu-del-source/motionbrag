# MotionBrag Unit Tests

import unittest
from pathlib import Path
import sys

# Add scripts directory to python path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

class TestMotionBragSetup(unittest.TestCase):
    def test_scripts_exist(self):
        root = Path(__file__).parent.parent
        self.assertTrue((root / "scripts" / "render_website.py").is_file())
        self.assertTrue((root / "scripts" / "capture_site.py").is_file())
        self.assertTrue((root / "scripts" / "validate_video.py").is_file())

if __name__ == "__main__":
    unittest.main()
