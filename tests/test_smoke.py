"""Package import and `TEXT_ENCODING` contract."""

import unittest


class TestPackage(unittest.TestCase):
    def test_text_encoding_is_utf8(self) -> None:
        from agsuperbrain import terminal

        self.assertEqual(terminal.TEXT_ENCODING, "utf-8")
