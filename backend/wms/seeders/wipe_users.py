"""One-off: wipe every user EXCEPT MCS-ADMIN so the org tree can be rebuilt by hand.

Idempotent — safe to re-run. Leaves operational data (ASNs, lots, orders, picks,
receipts) intact, just nulls out per-user FKs and removes dependent rows.

Run: python -m wms.seeders.wipe_users
"""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from wms.db.session import SessionLocal
from wms.models import (
    AuditLog,
    LoginAttempt,
    Pick,
    ProfileChangeRequest,
    QCHold,
    Receipt,
    User,
    UserMFA,
)

KEEP_CODE = "MCS-ADMIN"


def wipe(db: Session) -> dict:
    keeper = db.query(User).filter(User.employee_code == KEEP_CODE).one_or_none()
    if keeper is None:
        raise RuntimeError(
            f"Cannot wipe: {KEEP_CODE} not found. Refusing to leave the DB without a Lvl 5."
        )
    keeper_id = keeper.id

    # IDs of users we're about to remove
    doomed_ids = [
        uid for (uid,) in db.query(User.id).filter(User.id != keeper_id).all()
    ]
    if not doomed_ids:
        return {"removed": 0, "kept": keeper.employee_code}

    # 1. Null out nullable FKs pointing at doomed users
    db.execute(update(Receipt).where(Receipt.received_by.in_(doomed_ids)).values(received_by=None))
    db.execute(update(QCHold).where(QCHold.opened_by.in_(doomed_ids)).values(opened_by=None))
    db.execute(update(Pick).where(Pick.picker_id.in_(doomed_ids)).values(picker_id=None))
    db.execute(update(User).where(User.supervisor_id.in_(doomed_ids)).values(supervisor_id=None))
    db.execute(update(AuditLog).where(AuditLog.user_id.in_(doomed_ids)).values(user_id=None))
    db.execute(update(AuditLog).where(AuditLog.actor_id.in_(doomed_ids)).values(actor_id=None))

    # 2. Delete rows that have NOT NULL FKs to users
    db.query(UserMFA).filter(UserMFA.user_id.in_(doomed_ids)).delete(synchronize_session=False)
    db.query(ProfileChangeRequest).filter(
        ProfileChangeRequest.user_id.in_(doomed_ids)
    ).delete(synchronize_session=False)

    # 3. Login-attempt rows are FK-less (employee_code is just a string), but
    #    keep history clean too
    db.query(LoginAttempt).filter(
        LoginAttempt.employee_code.notin_([KEEP_CODE])
    ).delete(synchronize_session=False)

    # 4. Finally, delete the users themselves
    removed = (
        db.query(User)
        .filter(User.id.in_(doomed_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"removed": int(removed), "kept": keeper.employee_code}


def run() -> None:
    db = SessionLocal()
    try:
        result = wipe(db)
        remaining = db.query(User).count()
        print(
            f"✓ Wiped {result['removed']} users · "
            f"kept {result['kept']} · {remaining} user(s) remain"
        )
    finally:
        db.close()


if __name__ == "__main__":
    run()
