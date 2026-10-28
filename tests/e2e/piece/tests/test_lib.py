"""Synthetic suite of the fixture piece."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib  # noqa: E402


class TestLib(unittest.TestCase):
    def test_value(self):
        self.assertEqual(lib.value(), 42)


if __name__ == "__main__":
    unittest.main()
