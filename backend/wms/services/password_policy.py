"""Password complexity + MFA policy resolver and validator."""

import string

from sqlalchemy.orm import Session

from wms.models import PasswordPolicy, User

DEFAULT_POLICY = {
    "min_length": 4,
    "require_uppercase": False,
    "require_lowercase": False,
    "require_digit": False,
    "require_special": False,
    "require_mfa": False,
}

SPECIALS = set(string.punctuation)


def resolve_password_policy(db: Session, user: User) -> dict:
    """Resolve the effective password policy via user > role > site > global precedence."""
    rows = db.query(PasswordPolicy).all()
    by_key: dict[tuple[str, str | None], PasswordPolicy] = {
        (r.scope_type, r.scope_value): r for r in rows
    }
    for scope_type, scope_value in [
        ("user", user.employee_code),
        ("role", user.role),
        ("site", user.site_id),
        ("global", None),
    ]:
        rule = by_key.get((scope_type, scope_value))
        if rule is not None:
            return {
                "min_length": rule.min_length,
                "require_uppercase": rule.require_uppercase,
                "require_lowercase": rule.require_lowercase,
                "require_digit": rule.require_digit,
                "require_special": rule.require_special,
                "require_mfa": rule.require_mfa,
                "_source": f"{scope_type}:{scope_value or 'default'}",
            }
    return {**DEFAULT_POLICY, "_source": "default"}


def validate_password(password: str, policy: dict) -> None:
    """Raise ValueError if password violates the policy."""
    if len(password) < policy["min_length"]:
        raise ValueError(f"Password must be at least {policy['min_length']} characters")
    if policy["require_uppercase"] and not any(c.isupper() for c in password):
        raise ValueError("Password must contain an uppercase letter")
    if policy["require_lowercase"] and not any(c.islower() for c in password):
        raise ValueError("Password must contain a lowercase letter")
    if policy["require_digit"] and not any(c.isdigit() for c in password):
        raise ValueError("Password must contain a digit")
    if policy["require_special"] and not any(c in SPECIALS for c in password):
        raise ValueError("Password must contain a special character")
