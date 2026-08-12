"""Shopping endpoint — shopping list items."""

from __future__ import annotations

from fastapi import APIRouter

from services import ShoppingService

router = APIRouter()

_service = ShoppingService()


@router.get("/shopping")
async def list_shopping() -> list[dict]:
    return await _service.list_items()
