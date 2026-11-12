"""SQLAlchemy models. Import every model here so Alembic autogenerate sees it."""

from app.models.base import Base

__all__ = ["Base"]
