"""Shopping service — wraps ShoppingRepo over Postgres.

Single implicit device → one default list (get_or_create_default). Tools call add/list/
check/remove via the `action` arg the tool declaration exposes.
"""

from __future__ import annotations

from uuid import UUID

from postgres.repositories import ShoppingRepo
from postgres.session import get_sessionmaker


class ShoppingService:
    def __init__(self, repo: ShoppingRepo | None = None) -> None:
        self.repo = repo or ShoppingRepo()

    async def _list_id(self) -> UUID:
        sm = get_sessionmaker()
        async with sm() as db:
            lst = await self.repo.get_or_create_default(db)
            return lst.id

    async def add(self, name: str, *, quantity: str | None = None) -> dict:
        list_id = await self._list_id()
        sm = get_sessionmaker()
        async with sm() as db:
            item = await self.repo.add_item(db, list_id=list_id, name=name, quantity=quantity)
            return _to_dict(item)

    async def list_items(self) -> list[dict]:
        list_id = await self._list_id()
        sm = get_sessionmaker()
        async with sm() as db:
            items = await self.repo.list_items(db, list_id)
            return [_to_dict(i) for i in items]

    async def check(self, name: str, *, checked: bool = True) -> dict | None:
        list_id = await self._list_id()
        sm = get_sessionmaker()
        async with sm() as db:
            item = await self.repo.find_item(db, list_id=list_id, name=name)
            if item is None:
                return None
            updated = await self.repo.set_checked(db, item.id, checked)
            return _to_dict(updated) if updated else None

    async def remove(self, name: str) -> bool:
        list_id = await self._list_id()
        sm = get_sessionmaker()
        async with sm() as db:
            item = await self.repo.find_item(db, list_id=list_id, name=name)
            if item is None:
                return False
            return await self.repo.delete_item(db, item.id)


def _to_dict(i) -> dict:
    return {
        "item_id": str(i.id),
        "name": i.name,
        "quantity": i.quantity,
        "checked": i.checked,
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }
