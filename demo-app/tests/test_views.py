import unittest
from decimal import Decimal

from library import ROLES, Member, member_view


class MemberViewTest(unittest.TestCase):
    def setUp(self):
        self.member = Member("M-0001", "Ada Example", "ada@example.org", notes="prefers large print")

    def test_admin_sees_everything(self):
        view = member_view(self.member, "admin", Decimal("1.50"))
        self.assertEqual(view["notes"], "prefers large print")
        self.assertEqual(view["outstanding_fees"], "1.50")

    def test_internal_notes_are_absent_for_everyone_else(self):
        for role in ROLES:
            if role != "admin":
                self.assertNotIn("notes", member_view(self.member, role), role)

    def test_email_and_fees_only_for_librarian_and_admin(self):
        for role, visible in (("member", False), ("volunteer", False), ("librarian", True), ("admin", True)):
            view = member_view(self.member, role)
            self.assertEqual("email" in view, visible, role)
            self.assertEqual("outstanding_fees" in view, visible, role)

    def test_stripped_fields_are_absent_not_blank(self):
        view = member_view(self.member, "member")
        self.assertEqual(set(view), {"member_id", "name"})
        self.assertNotIn("ada@example.org", repr(view))

    def test_unknown_role_is_refused(self):
        with self.assertRaises(PermissionError):
            member_view(self.member, "guest")


if __name__ == "__main__":
    unittest.main()
