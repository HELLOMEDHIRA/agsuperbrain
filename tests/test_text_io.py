"""Path read/write should use the same encoding as the rest of the package."""

import tempfile
import unittest
from pathlib import Path

from agsuperbrain.terminal import TEXT_ENCODING


class TestTextIO(unittest.TestCase):
    def test_roundtrip_non_ascii(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.txt"
            s = "Résumé 测试"
            p.write_text(s, encoding=TEXT_ENCODING)
            self.assertEqual(p.read_text(encoding=TEXT_ENCODING), s)
