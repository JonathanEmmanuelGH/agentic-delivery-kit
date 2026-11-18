"""Library members."""
from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MemberError(ValueError):
    """A membership rule was broken."""


@dataclass
class Member:
    member_id: str
    name: str
    email: str
    notes: str = ""
    active: bool = True


class MemberRegistry:
    def __init__(self) -> None:
        self._members: dict[str, Member] = {}

    def register(self, name: str, email: str, notes: str = "") -> Member:
        if not name.strip():
            raise MemberError("a member needs a name")
        if not EMAIL.match(email):
            raise MemberError(f"invalid email: {email}")
        if any(m.email.lower() == email.lower() for m in self._members.values()):
            raise MemberError("email already registered")
        member_id = f"M-{len(self._members) + 1:04d}"
        member = Member(member_id, name.strip(), email, notes)
        self._members[member_id] = member
        return member

    def get(self, member_id: str) -> Member:
        try:
            return self._members[member_id]
        except KeyError:
            raise MemberError(f"unknown member: {member_id}") from None

    def deactivate(self, member_id: str) -> Member:
        member = self.get(member_id)
        member.active = False
        return member
