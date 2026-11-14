import unittest

from limit import choose_limit


class LimitTests(unittest.TestCase):
    def test_uses_default_when_unspecified(self):
        self.assertEqual(choose_limit(), 100)

    def test_accepts_positive_integer_and_integer_text(self):
        self.assertEqual(choose_limit(25), 25)
        self.assertEqual(choose_limit("25"), 25)

    def test_rejects_values_outside_range(self):
        for value in (0, -1, 10001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                choose_limit(value)


if __name__ == "__main__":
    unittest.main()
