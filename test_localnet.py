"""Focused operator checks; no Docker or network access."""
import unittest

from localnet import Network, native_amount


class AmountTests(unittest.TestCase):
    def test_exact_integer_conversion(self):
        self.assertEqual(native_amount("0.000001"), 1)
        self.assertEqual(native_amount("12.500001"), 12_500_001)
        self.assertEqual(native_amount("999999999.999999"), 999_999_999_999_999)

    def test_rejects_rounding_and_ambiguous_amounts(self):
        for value in ("0", "-1", "1e3", "NaN", "Infinity", "0.0000001", "01", "1,000", "1000000001", "1uluxar"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                native_amount(value)

    def test_resource_namespace_is_bounded(self):
        for name in ("postgres", "luxartium-local-1-data", "luxartium-check-../", "luxartium-check-", "production"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                Network(name)


if __name__ == "__main__":
    unittest.main()
