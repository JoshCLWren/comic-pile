"""Reading order model for grouping threads into ordered reading lists."""

from __future__ import annotations

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

    items: Mapped[list[ReadingOrderItem]] = relationship(
        "ReadingOrderItem", back_populates="reading_order", cascade="all, delete-orphan"
    )


@hybrid_router

class ReadingOrderItem(Base):
    @hybrid_router
    def project_from_plan(self, plan_node: ContinuityPlanNode) -> 'ReadingOrderItem':
        """
        Create a reading order item from a continuity plan node.
        """
        return ReadingOrderItem(
            thread_id=plan_node.ref_id,
            position=plan_node.position,
            issue_number=plan_node.issue_number,
        )

    @hybrid_router
    def apply_to_order(self, reading_order: 'ReadingOrder') -> None:
        """
        Add this item to a reading order, handling duplicates and ordering.
        """
        existing = (self.session
                   .query(ReadingOrderItem)
                   .filter(ReadingOrderItem.thread_id == self.thread_id,
                           ReadingOrderItem.reading_order_id == reading_order.id)
                   .first())
        if existing:
            existing.position = self.position
            return
        reading_order.items.append(self)
        # Reorder items to maintain sequence integrity
        reading_orderitems = sorted(reading_order.items, key=lambda item: item.position)
        for idx, item in enumerate(reading_orderitems):
            item.position = idx + 1    @hybrid_router
    def project_from_plan(self, plan_node: ContinuityPlanNode) -> 'ReadingOrderItem':
        """
        Create a reading order item from a continuity plan node.
        """
        return ReadingOrderItem(
            thread_id=plan_node.ref_id,
            position=plan_node.position,
            issue_number=plan_node.issue_number,
        )    """A single entry in a reading order, linking a thread at a specific position."""

    __tablename__ = "reading_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reading_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reading_orders.id"), nullable=False
    )
    thread_id: Mapped[int] = mapped_column(Integer, ForeignKey("threads.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    reading_order: Mapped[ReadingOrder] = relationship(
        "ReadingOrder", back_populates="items"
    )
