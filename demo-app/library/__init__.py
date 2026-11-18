"""A toy book-lending library, used to show the gate and the work orders on real code.

Fictional data only. Standard library only. The business rules are deliberately the
kind an agent gets wrong without tests: limits, money rounding, a two-person rule,
an append-only audit trail and role-based field stripping on the server side.
"""
from .catalog import Book, Catalog, CatalogError, isbn13_is_valid
from .fees import DAILY_FEE, FEE_CAP, late_fee
from .loans import LoanError, LoanService
from .members import Member, MemberError, MemberRegistry
from .views import ROLES, member_view

__all__ = [
    "Book", "Catalog", "CatalogError", "isbn13_is_valid",
    "DAILY_FEE", "FEE_CAP", "late_fee",
    "LoanError", "LoanService",
    "Member", "MemberError", "MemberRegistry",
    "ROLES", "member_view",
]
