import unittest
from datetime import timedelta
from decimal import Decimal

from library import LoanError

from .helpers import DAY0, library_with_books, make_isbn


class LendingTest(unittest.TestCase):
    def setUp(self):
        self.svc, self.ada, self.ben = library_with_books()

    def test_lend_sets_due_date_and_audits(self):
        loan = self.svc.lend(self.ada.member_id, make_isbn(1), "desk-1", DAY0)
        self.assertEqual(loan.due_on, DAY0 + timedelta(days=14))
        self.assertEqual([(e.action, e.by) for e in self.svc.audit], [("lend", "desk-1")])

    def test_limit_of_three_open_loans(self):
        for n in (1, 3, 4):
            self.svc.lend(self.ada.member_id, make_isbn(n), "desk-1", DAY0)
        with self.assertRaisesRegex(LoanError, "limit"):
            self.svc.lend(self.ada.member_id, make_isbn(1), "desk-1", DAY0)

    def test_returning_frees_a_slot(self):
        loans = [self.svc.lend(self.ada.member_id, make_isbn(n), "desk-1", DAY0) for n in (1, 3, 4)]
        self.svc.return_book(loans[0].loan_id, "desk-1", DAY0 + timedelta(days=2))
        self.svc.lend(self.ada.member_id, make_isbn(2), "desk-1", DAY0 + timedelta(days=2))

    def test_no_copy_on_the_shelf(self):
        self.svc.lend(self.ada.member_id, make_isbn(2), "desk-1", DAY0)
        with self.assertRaisesRegex(LoanError, "no copy"):
            self.svc.lend(self.ben.member_id, make_isbn(2), "desk-1", DAY0)

    def test_overdue_loan_blocks_new_loans(self):
        self.svc.lend(self.ada.member_id, make_isbn(1), "desk-1", DAY0)
        late = DAY0 + timedelta(days=15)
        self.assertEqual(len(self.svc.overdue(late)), 1)
        with self.assertRaisesRegex(LoanError, "overdue"):
            self.svc.lend(self.ada.member_id, make_isbn(3), "desk-1", late)

    def test_inactive_member_cannot_borrow(self):
        self.svc.members.deactivate(self.ben.member_id)
        with self.assertRaisesRegex(LoanError, "inactive"):
            self.svc.lend(self.ben.member_id, make_isbn(1), "desk-1", DAY0)

    def test_every_write_names_its_author(self):
        with self.assertRaises(LoanError):
            self.svc.lend(self.ada.member_id, make_isbn(1), " ", DAY0)
        self.assertEqual(self.svc.audit, ())


class ReturnTest(unittest.TestCase):
    def setUp(self):
        self.svc, self.ada, _ = library_with_books()
        self.loan = self.svc.lend(self.ada.member_id, make_isbn(1), "desk-1", DAY0)

    def test_on_time_return_has_no_fee(self):
        loan = self.svc.return_book(self.loan.loan_id, "desk-2", self.loan.due_on)
        self.assertEqual(loan.fee, Decimal("0.00"))

    def test_late_return_charges_the_fee(self):
        loan = self.svc.return_book(self.loan.loan_id, "desk-2", self.loan.due_on + timedelta(days=6))
        self.assertEqual(loan.fee, Decimal("1.50"))
        self.assertEqual(self.svc.outstanding_fees(self.ada.member_id), Decimal("1.50"))

    def test_double_return_is_refused(self):
        self.svc.return_book(self.loan.loan_id, "desk-2", DAY0)
        with self.assertRaises(LoanError):
            self.svc.return_book(self.loan.loan_id, "desk-2", DAY0)

    def test_return_cannot_predate_the_loan(self):
        with self.assertRaises(LoanError):
            self.svc.return_book(self.loan.loan_id, "desk-2", DAY0 - timedelta(days=1))


class LostBookTest(unittest.TestCase):
    def setUp(self):
        self.svc, self.ada, _ = library_with_books()
        self.loan = self.svc.lend(self.ada.member_id, make_isbn(2), "desk-1", DAY0)

    def test_two_people_write_off_a_lost_book(self):
        self.svc.report_lost(self.loan.loan_id, "desk-1", DAY0)
        loan = self.svc.confirm_lost(self.loan.loan_id, "desk-2", DAY0)
        self.assertTrue(loan.written_off)
        self.assertEqual(self.svc.on_shelf(make_isbn(2)), 0)
        self.assertEqual([e.action for e in self.svc.audit], ["lend", "report_lost", "confirm_lost"])

    def test_the_reporter_cannot_confirm(self):
        self.svc.report_lost(self.loan.loan_id, "desk-1", DAY0)
        with self.assertRaisesRegex(LoanError, "second staff member"):
            self.svc.confirm_lost(self.loan.loan_id, "DESK-1 ", DAY0)
        self.assertFalse(self.svc.get(self.loan.loan_id).written_off)

    def test_confirm_needs_a_report(self):
        with self.assertRaises(LoanError):
            self.svc.confirm_lost(self.loan.loan_id, "desk-2", DAY0)

    def test_report_twice_is_refused(self):
        self.svc.report_lost(self.loan.loan_id, "desk-1", DAY0)
        with self.assertRaises(LoanError):
            self.svc.report_lost(self.loan.loan_id, "desk-3", DAY0)

    def test_audit_is_append_only(self):
        self.svc.report_lost(self.loan.loan_id, "desk-1", DAY0)
        trail = self.svc.audit
        self.assertIsInstance(trail, tuple)
        with self.assertRaises(AttributeError):
            trail[0].by = "someone else"


if __name__ == "__main__":
    unittest.main()
