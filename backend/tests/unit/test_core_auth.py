"""app.core.auth unit testleri."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.application import auth_service
from app.core.auth import get_current_user
from app.core.config import Settings
from app.infrastructure.db.database import Base


@pytest.fixture
async def async_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_get_current_user_valid_token(async_db: AsyncSession) -> None:
    settings = Settings(jwt_secret="secret123")
    user = await auth_service.register_user("coreauth@example.com", "pass12345", async_db)
    token = auth_service.create_access_token(user.email, settings)

    current_user = await get_current_user(
        authorization=f"Bearer {token}",
        db=async_db,
        settings=settings,
    )
    assert current_user.email == user.email


@pytest.mark.asyncio
async def test_get_current_user_missing_header_raises_401(async_db: AsyncSession) -> None:
    settings = Settings(jwt_secret="secret123")
    with pytest.raises(HTTPException) as exc:
        await get_current_user(authorization=None, db=async_db, settings=settings)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_invalid_token_raises_401(async_db: AsyncSession) -> None:
    settings = Settings(jwt_secret="secret123")
    with pytest.raises(HTTPException) as exc:
        await get_current_user(authorization="Bearer invalidtoken", db=async_db, settings=settings)
    assert exc.value.status_code == 401
