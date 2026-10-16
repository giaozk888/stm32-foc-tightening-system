"""Syntax compatibility check, not a replacement for Python 3.8 runtime tests."""
import ast
from pathlib import Path
import unittest


class CompatibilityTests(unittest.TestCase):
    def test_server_python38_syntax(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("__init__.py", "schema.py", "store.py", "server.py"):
            with self.subTest(module=name):
                ast.parse((root / name).read_text(encoding="utf-8"),
                          filename=name, feature_version=(3, 8))


if __name__ == "__main__":
    unittest.main()
