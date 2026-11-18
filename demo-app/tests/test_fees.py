import unittest
from decimal import Decimal

from library import FEE_CAP, late_fee


class FeesTest(unittest.TestCase):
    def test_on_time_is_free(self):
        self.assertEqual(late_fee(0), Decimal("0.00"))

    def test_daily_fee(self):
        self.assertEqual(late_fee(1), Decimal("0.25"))
        self.assertEqual(late_fee(7), Decimal("1.75"))

    def test_cap(self):
        # Pin the business value, not only the constant: a test written against
        # FEE_CAP alone keeps passing when someone edits the cap.
        self.assertEqual(FEE_CAP, Decimal("10.00"))
        self.assertEqual(late_fee(40), Decimal("10.00"))
        self.assertEqual(late_fee(10_000), Decimal("10.00"))
        self.assertEqual(late_fee(39), Decimal("9.75"))

    def test_half_cents_round_up(self):
        self.assertEqual(late_fee(1, daily_fee=Decimal("0.125")), Decimal("0.13"))
        self.assertEqual(late_fee(3, daily_fee=Decimal("0.115")), Decimal("0.35"))

    def test_result_is_whole_cents(self):
        self.assertEqual(late_fee(3).as_tuple().exponent, -2)

    def test_negative_days_are_refused(self):
        with self.assertRaises(ValueError):
            late_fee(-1)


if __name__ == "__main__":
    unittest.main()
