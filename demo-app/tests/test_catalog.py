import unittest

from library import Catalog, CatalogError, isbn13_is_valid

from .helpers import make_isbn


class CatalogTest(unittest.TestCase):
    def test_valid_isbn_is_accepted(self):
        self.assertTrue(isbn13_is_valid(make_isbn(7)))
        self.assertTrue(isbn13_is_valid("978-0-00-000000-2"))

    def test_bad_checksum_is_refused(self):
        isbn = make_isbn(7)
        wrong = isbn[:-1] + str((int(isbn[-1]) + 1) % 10)
        self.assertFalse(isbn13_is_valid(wrong))
        with self.assertRaises(CatalogError):
            Catalog().add_book(wrong, "Title", "Author")

    def test_shape_is_checked(self):
        for value in ("", "123", "97800000000AB", "97800000000021"):
            self.assertFalse(isbn13_is_valid(value), value)

    def test_adding_the_same_isbn_adds_copies(self):
        catalog = Catalog()
        catalog.add_book(make_isbn(1), "A", "B", copies=1)
        book = catalog.add_book(make_isbn(1), "A", "B", copies=2)
        self.assertEqual(book.copies, 3)
        self.assertEqual(len(catalog), 1)

    def test_title_author_and_copies_are_required(self):
        catalog = Catalog()
        with self.assertRaises(CatalogError):
            catalog.add_book(make_isbn(1), " ", "B")
        with self.assertRaises(CatalogError):
            catalog.add_book(make_isbn(1), "A", "")
        with self.assertRaises(CatalogError):
            catalog.add_book(make_isbn(1), "A", "B", copies=0)

    def test_unknown_book(self):
        with self.assertRaises(CatalogError):
            Catalog().get(make_isbn(99))


if __name__ == "__main__":
    unittest.main()
