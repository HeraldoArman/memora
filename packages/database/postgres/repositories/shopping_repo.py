"""Shopping list + item repository.

Single implicit device → one default list. get_or_create_default() ensures it exists.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from postgres.models import ShoppingItem, ShoppingList


class ShoppingRepo:
    """CRUD for shopping lists + items."""

    async def get_or_create_default(self, db: AsyncSession) -> ShoppingList:
        result = await db.execute(select(ShoppingList).limit(1))
        lst = result.scalars().first()
        if lst is not None:
            return lst
        lst = ShoppingList(title="Shopping")
        db.add(lst)
        await db.commit()
        await db.refresh(lst)
        return lst

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
        result = await db.execute(
            select(ShoppingItem).where(
                ShoppingItem.list_id == list_id, ShoppingItem.name.ilike(name)
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
