from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared SQLAlchemy declarative base.

    Kept in a dependency-free module so database engine/session setup and model
    declarations never import each other.
    """

    pass
