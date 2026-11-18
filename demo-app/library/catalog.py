"""Books and copies."""
from __future__ import annotations

from dataclasses import dataclass


class CatalogError(ValueError):
    """A catalog rule was broken."""


def isbn13_is_valid(isbn: str) -> bool:
    """ISBN-13 checksum: weights 1 and 3 alternate; the total is a multiple of 10."""
    digits = isbn.replace("-", "")
    if len(digits) != 13 or not digits.isdigit():
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits))
    return total % 10 == 0


@dataclass
class Book:
    isbn: str
    title: str
    author: str
    copies: int


class Catalog:
    def __init__(self) -> None:
        self._books: dict[str, Book] = {}

    def add_book(self, isbn: str, title: str, author: str, copies: int = 1) -> Book:
        isbn = isbn.replace("-", "")
        if not isbn13_is_valid(isbn):
            raise CatalogError(f"invalid ISBN-13: {isbn}")
        if not title.strip() or not author.strip():
            raise CatalogError("title and author are required")
        if copies < 1:
            raise CatalogError("a book needs at least one copy")
        if isbn in self._books:
            self._books[isbn].copies += copies
            return self._books[isbn]
        book = Book(isbn, title.strip(), author.strip(), copies)
        self._books[isbn] = book
        return book

    def get(self, isbn: str) -> Book:
        try:
            return self._books[isbn.replace("-", "")]
        except KeyError:
            raise CatalogError(f"unknown book: {isbn}") from None

    def __len__(self) -> int:
        return len(self._books)
