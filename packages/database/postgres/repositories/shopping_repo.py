"""Shopping list + item repository.

Single implicit device → one default list. get_or_create_default() ensures it exists.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from postgres.models import ShoppingItem, ShoppingList


class ShoppingRepo:
    """CRUD for shopping lists + items."""

    async def get_or_create_default(self, db: AsyncSession) -> ShoppingList:
        # Atomic single-list guarantee: INSERT ... ON CONFLICT DO NOTHING, then fetch.
        # The old select→add→commit path raced → two default lists under concurrency.
        await db.execute(
            insert(ShoppingList)
            .values(title="Shopping")
            .on_conflict_do_nothing(index_elements=["title"])
        )
        await db.commit()
        result = await db.execute(
            select(ShoppingList).where(ShoppingList.title == "Shopping").limit(1)
        )
        return result.scalars().one()

    async def add_item(
        self, db: AsyncSession, *, list_id: UUID, name: str, quantity: str | None = None
    ) -> ShoppingItem:
        item = ShoppingItem(list_id=list_id, name=name, quantity=quantity)
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item

    async def list_items(self, db: AsyncSession, list_id: UUID) -> list[ShoppingItem]:
        result = await db.execute(
            select(ShoppingItem)
            .where(ShoppingItem.list_id == list_id)
            .order_by(ShoppingItem.created_at)
        )
        return list(result.scalars().all())

    async def find_item(self, db: AsyncSession, *, list_id: UUID, name: str) -> ShoppingItem | None:
        # Exact case-insensitive match (func.lower), not an ilike substring scan on
        # raw user input — ilike(name) let a caller's %/_ wildcards pattern-match rows.
        result = await db.execute(
            select(ShoppingItem).where(
                ShoppingItem.list_id == list_id,
                func.lower(ShoppingItem.name) == name.lower(),
            )
        )
        return result.scalars().first()

    async def set_checked(
        self, db: AsyncSession, item_id: UUID, checked: bool
    ) -> ShoppingItem | None:
        item = await db.get(ShoppingItem, item_id)
        if item is None:
            return None
        item.checked = checked
        await db.commit()
        await db.refresh(item)
        return item

    async def delete_item(self, db: AsyncSession, item_id: UUID) -> bool:
        item = await db.get(ShoppingItem, item_id)
        if item is None:
            return False
        await db.delete(item)
        await db.commit()
        return True
