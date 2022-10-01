import asyncio
from typing import Optional

import aioredis
import pytest
from aioredis.client import Redis
from fastapi import Depends
from fastapi.applications import FastAPI
from fastapi.params import Query

from atomcache.base import Cache
from atomcache.redis import DEFAULT_ENCODING

pytestmark = pytest.mark.asyncio

TEST_REDIS_URL = "redis://0.0.0.0:6379/0"

TEST_AUTOREFRESH_ID = "TEST_AUTOREFRESH_ID"
TEST_SET_AUTOREFRESH_VALUE = "TEST_SET_AUTOREFRESH_VALUE"


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    policy = asyncio.get_event_loop_policy()
    res = policy.new_event_loop()
    res._close = res.close
    res.close = lambda: None

    yield res

    res._close()


@pytest.fixture
async def app_with_cache():
    app = FastAPI()

    @app.get("/items/{item_id}")
    async def get_item_by_id(item_id: int = 1, cache: Cache = Depends(Cache(exp=60, auto_refresh=True))):

        cache.set(TEST_SET_AUTOREFRESH_VALUE, TEST_AUTOREFRESH_ID)
        return {"item_id": item_id}

    @app.get("/items")
    async def get_items(
        q: Optional[str] = Query(None, max_length=50), cache: Cache = Depends(Cache(exp=60, auto_refresh=True))
    ):

        return [{"item_id": 1}]

    yield app


@pytest.fixture
async def app_with_invalid_cache():
    app = FastAPI()

    @app.get("/empty")
    async def empty_endpoint(q: str, cache: Cache = Depends(Cache(exp=60, auto_refresh=True))):

        return {}

    yield app


@pytest.fixture
async def app_without_cache():
    app = FastAPI()

    @app.get("/")
    async def root():
        return {"message": "Hello World"}

    return app


@pytest.fixture(scope="session")
async def redis_client() -> Redis:
    redis: Redis = aioredis.from_url(url=TEST_REDIS_URL, encoding=DEFAULT_ENCODING)
    async with redis.client() as client:
        yield client


@pytest.fixture(autouse=True)
async def clean_redis(redis_client: Redis) -> Redis:
    await redis_client.flushall()
