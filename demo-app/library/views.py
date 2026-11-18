"""Serializers: what each role may see about a member.

Fields are stripped HERE, on the server side, never left to a screen to hide:
a field a role must not see is absent from the dictionary, not blanked.
"""
from __future__ import annotations

from decimal import Decimal

from .members import Member

ROLES = ("member", "volunteer", "librarian", "admin")
VISIBLE = {
    "member": {"member_id", "name"},
    "volunteer": {"member_id", "name", "active"},
    "librarian": {"member_id", "name", "active", "email", "outstanding_fees"},
    "admin": {"member_id", "name", "active", "email", "outstanding_fees", "notes"},
}


def member_view(member: Member, role: str, outstanding_fees: Decimal = Decimal("0.00")) -> dict:
    if role not in VISIBLE:
        raise PermissionError(f"unknown role: {role}")
    full = {
        "member_id": member.member_id,
        "name": member.name,
        "active": member.active,
        "email": member.email,
        "outstanding_fees": str(outstanding_fees),
        "notes": member.notes,
    }
    return {key: value for key, value in full.items() if key in VISIBLE[role]}
