"""Loans: lending, returns, lost books, and the audit trail.

Rules:
  * a member holds at most MAX_ACTIVE_LOANS books at once;
  * an inactive member, or one with an overdue loan, cannot borrow;
  * a book is lent only while a copy is on the shelf;
  * the due date is LOAN_DAYS after the day of lending;
  * a lost book is written off only when a SECOND staff member, different from the
    one who reported it, confirms it (two-person rule);
  * every write appends an audit entry (who, what, when); entries are never changed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .catalog import Catalog
from .fees import late_fee
from .members import MemberRegistry

MAX_ACTIVE_LOANS = 3
LOAN_DAYS = 14


class LoanError(ValueError):
    """A lending rule was broken."""


@dataclass
class Loan:
    loan_id: str
    member_id: str
    isbn: str
    lent_on: date
    due_on: date
    lent_by: str
    returned_on: date | None = None
    fee: Decimal = Decimal("0.00")
    lost_reported_by: str | None = None
    written_off: bool = False

    @property
    def open(self) -> bool:
        return self.returned_on is None and not self.written_off


@dataclass(frozen=True)
class AuditEntry:
    action: str
    loan_id: str
    by: str
    on: date


class LoanService:
    def __init__(self, catalog: Catalog, members: MemberRegistry) -> None:
        self.catalog = catalog
        self.members = members
        self._loans: dict[str, Loan] = {}
        self._audit: list[AuditEntry] = []

    # -- reads ---------------------------------------------------------------
    @property
    def audit(self) -> tuple[AuditEntry, ...]:
        return tuple(self._audit)

    def get(self, loan_id: str) -> Loan:
        try:
            return self._loans[loan_id]
        except KeyError:
            raise LoanError(f"unknown loan: {loan_id}") from None

    def open_loans(self, member_id: str) -> list[Loan]:
        return [loan for loan in self._loans.values() if loan.member_id == member_id and loan.open]

    def on_shelf(self, isbn: str) -> int:
        book = self.catalog.get(isbn)
        out = sum(1 for loan in self._loans.values() if loan.isbn == book.isbn and loan.open)
        lost = sum(1 for loan in self._loans.values() if loan.isbn == book.isbn and loan.written_off)
        return book.copies - out - lost

    def overdue(self, today: date) -> list[Loan]:
        return [loan for loan in self._loans.values() if loan.open and loan.due_on < today]

    def outstanding_fees(self, member_id: str) -> Decimal:
        return sum((loan.fee for loan in self._loans.values() if loan.member_id == member_id), Decimal("0.00"))

    # -- writes --------------------------------------------------------------
    def _record(self, action: str, loan_id: str, by: str, on: date) -> None:
        if not by.strip():
            raise LoanError("every write names the staff member who made it")
        self._audit.append(AuditEntry(action, loan_id, by, on))

    def lend(self, member_id: str, isbn: str, staff: str, today: date) -> Loan:
        member = self.members.get(member_id)
        if not member.active:
            raise LoanError("inactive members cannot borrow")
        open_loans = self.open_loans(member_id)
        if len(open_loans) >= MAX_ACTIVE_LOANS:
            raise LoanError(f"limit of {MAX_ACTIVE_LOANS} open loans reached")
        if any(loan.due_on < today for loan in open_loans):
            raise LoanError("return the overdue book first")
        if self.on_shelf(isbn) < 1:
            raise LoanError("no copy on the shelf")
        if not staff.strip():
            raise LoanError("every write names the staff member who made it")
        loan_id = f"L-{len(self._loans) + 1:05d}"
        loan = Loan(loan_id, member_id, self.catalog.get(isbn).isbn, today, today + timedelta(days=LOAN_DAYS), staff)
        self._loans[loan_id] = loan
        self._record("lend", loan_id, staff, today)
        return loan

    def return_book(self, loan_id: str, staff: str, today: date) -> Loan:
        loan = self.get(loan_id)
        if not loan.open:
            raise LoanError("this loan is already closed")
        if today < loan.lent_on:
            raise LoanError("a return cannot predate the loan")
        self._record("return", loan_id, staff, today)
        loan.returned_on = today
        loan.fee = late_fee(max(0, (today - loan.due_on).days))
        return loan

    def report_lost(self, loan_id: str, staff: str, today: date) -> Loan:
        loan = self.get(loan_id)
        if not loan.open:
            raise LoanError("only an open loan can be reported lost")
        if loan.lost_reported_by:
            raise LoanError("already reported lost")
        self._record("report_lost", loan_id, staff, today)
        loan.lost_reported_by = staff
        return loan

    def confirm_lost(self, loan_id: str, staff: str, today: date) -> Loan:
        loan = self.get(loan_id)
        if not loan.lost_reported_by:
            raise LoanError("a loss must be reported before it is confirmed")
        if staff.strip().lower() == loan.lost_reported_by.strip().lower():
            raise LoanError("the confirmation needs a second staff member")
        if loan.written_off:
            raise LoanError("already written off")
        self._record("confirm_lost", loan_id, staff, today)
        loan.written_off = True
        return loan
