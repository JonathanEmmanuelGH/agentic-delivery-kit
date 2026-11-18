"""Fixtures with fictional data only."""
from __future__ import annotations

from datetime import date

from library import Catalog, LoanService, MemberRegistry

DAY0 = date(2026, 3, 2)


def make_isbn(n: int) -> str:
    """A checksum-valid, fictional ISBN-13 in the 978-0-00 range."""
    body = f"97800{n:07d}"
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(body))
    return body + str((10 - total % 10) % 10)


def library_with_books():
    catalog = Catalog()
    members = MemberRegistry()
    catalog.add_book(make_isbn(1), "The Quiet Orchard", "R. Fernhill", copies=2)
    catalog.add_book(make_isbn(2), "A Map of Small Rivers", "T. Okonkwo-Lind", copies=1)
    catalog.add_book(make_isbn(3), "Notes on Lighthouses", "E. Marsh", copies=5)
    catalog.add_book(make_isbn(4), "The Salt Ledger", "P. Arvo", copies=5)
    ada = members.register("Ada Example", "ada@example.org", notes="prefers large print")
    ben = members.register("Ben Sample", "ben@example.org")
    return LoanService(catalog, members), ada, ben
