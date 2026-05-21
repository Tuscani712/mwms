"""SQLAlchemy ORM models. Importing this package registers all tables on Base.metadata."""

from wms.models.core import (
    AuditLog,
    LoginAttempt,
    PasswordPolicy,
    ProfileChangeRequest,
    Site,
    User,
    UserMFA,
    UserProfileField,
)
from wms.models.inventory import SKU, Location, Lot, LotGenealogy
from wms.models.ops import (
    ASN,
    ASNLine,
    Order,
    OrderLine,
    Pick,
    QCHold,
    Receipt,
    ReceiptLine,
    Shipment,
)
from wms.models.orgmeta import Department, Role, Shift, Title

__all__ = [
    "ASN",
    "ASNLine",
    "AuditLog",
    "Department",
    "Location",
    "LoginAttempt",
    "Lot",
    "LotGenealogy",
    "Order",
    "OrderLine",
    "PasswordPolicy",
    "Pick",
    "ProfileChangeRequest",
    "QCHold",
    "Receipt",
    "ReceiptLine",
    "Role",
    "SKU",
    "Shift",
    "Shipment",
    "Site",
    "Title",
    "User",
    "UserMFA",
    "UserProfileField",
]
