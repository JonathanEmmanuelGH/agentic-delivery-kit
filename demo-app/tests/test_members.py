import unittest

from library import MemberError, MemberRegistry


class MembersTest(unittest.TestCase):
    def test_register_assigns_sequential_ids(self):
        reg = MemberRegistry()
        self.assertEqual(reg.register("Ada Example", "ada@example.org").member_id, "M-0001")
        self.assertEqual(reg.register("Ben Sample", "ben@example.org").member_id, "M-0002")

    def test_email_must_be_unique_ignoring_case(self):
        reg = MemberRegistry()
        reg.register("Ada Example", "ada@example.org")
        with self.assertRaises(MemberError):
            reg.register("Ada Again", "ADA@example.org")

    def test_invalid_input_is_refused(self):
        reg = MemberRegistry()
        with self.assertRaises(MemberError):
            reg.register("", "x@example.org")
        with self.assertRaises(MemberError):
            reg.register("No Email", "not-an-email")

    def test_deactivate(self):
        reg = MemberRegistry()
        m = reg.register("Ada Example", "ada@example.org")
        self.assertFalse(reg.deactivate(m.member_id).active)
        with self.assertRaises(MemberError):
            reg.deactivate("M-9999")


if __name__ == "__main__":
    unittest.main()
