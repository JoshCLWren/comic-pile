"""Reading order model for grouping threads into ordered reading lists."""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ReadingOrder(Base):
    """A grouped reading list containing ordered threads."""

    __tablename__ = "reading_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    items: Mapped[list["ReadingOrderItem"]] = relationship(
        "ReadingOrderItem", back_populates="reading_order", cascade="all, delete-orphan"
    )


class ReadingOrderItem(Base):
    """A single entry in a reading order, linking a thread at a specific position."""

    __tablename__ = "reading_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reading_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reading_orders.id"), nullable=False
    )
    thread_id: Mapped[int] = mapped_column(Integer, ForeignKey("threads.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    reading_order: Mapped["ReadingOrder"] = relationship(
        "ReadingOrder", back_populates="items"
    )
