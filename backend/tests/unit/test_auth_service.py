"""auth_service unit testleri."""

from __future__ import annotations

import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.application import auth_service
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
async def test_register_and_authenticate_user(async_db: AsyncSession) -> None:
    email = "newuser@example.com"
    password = "secretpassword123"

    # Kayıt ol
    user = await auth_service.register_user(email, password, async_db)
    assert user.email == email
    assert user.is_active is True

    # Başarılı giriş
    auth_user = await auth_service.authenticate_user(email, password, async_db)
    assert auth_user is not None
    assert auth_user.email == email

    # Yanlış şifre ile giriş
    wrong_user = await auth_service.authenticate_user(email, "wrongpass", async_db)
    assert wrong_user is None


@pytest.mark.asyncio
async def test_register_duplicate_user_raises_error(async_db: AsyncSession) -> None:
    email = "dupe@example.com"
    await auth_service.register_user(email, "pass12345", async_db)

    with pytest.raises(ValueError, match="zaten kayıtlı"):
        await auth_service.register_user(email, "pass12345", async_db)


def test_jwt_create_and_decode_token() -> None:
    settings = Settings(jwt_secret="my-super-secret-key-12345", jwt_expire_minutes=60)
    email = "tokenuser@example.com"

    token = auth_service.create_access_token(email, settings)
    decoded_email = auth_service.decode_access_token(token, settings)
    assert decoded_email == email


def test_decode_invalid_jwt_token_raises_error() -> None:
    settings = Settings(jwt_secret="my-super-secret-key-12345")
    with pytest.raises(jwt.InvalidTokenError):
        auth_service.decode_access_token("invalid.token.str", settings)
