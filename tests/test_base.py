import asyncio
import json

import pytest
from aioredis.client import Redis
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse

from atomcache.base import Cache
from tests.conftest import TEST_AUTOREFRESH_ID, TEST_SET_AUTOREFRESH_VALUE

pytestmark = pytest.mark.asyncio

TEST_CACHE_ID = "TEST_CACHE_ID"
TEST_REDIS_URL = "redis://0.0.0.0:6379/0"
TEST_SET_VALUE = {"key": "test"}


async def test_cache_init(app_with_cache, redis_client):
    await Cache.init(app_with_cache, redis_client)


async def test_cache_init_with_invalid_params(app_with_invalid_cache, redis_client):
    with pytest.raises(ValueError):
        await Cache.init(app_with_invalid_cache, redis_client)


async def test_cache_set_json_object(app_without_cache, redis_client: Redis):
    cache = Cache(exp=30)
    await Cache.init(app_without_cache, redis_client)

    cache.set(response=TEST_SET_VALUE, cache_id=TEST_CACHE_ID)
    await asyncio.sleep(1)

    raw_response = await redis_client.get(cache.get_key(TEST_CACHE_ID))
    setted_response = json.loads(raw_response.decode())
    assert setted_response == TEST_SET_VALUE


async def test_cache_set_response_object(app_without_cache, redis_client: Redis):
    cache = Cache(exp=30)
    await Cache.init(app_without_cache, redis_client)

    response_obj = JSONResponse({"hello": "world"})

    cache.set(response=response_obj, cache_id=TEST_CACHE_ID)
    await asyncio.sleep(1)

    raw_response = await redis_client.get(cache.get_key(TEST_CACHE_ID))
    setted_response = json.loads(raw_response.decode())
    assert setted_response == {"hello": "world"}


async def test_cache_set_object_with_no_store_cache(app_without_cache, redis_client: Redis):
    cache = Cache(exp=30, cache_control=True)
    headers = {"Cache-Control": "no-cache"}
    request = Request({"type": "http", "headers": Headers(headers).raw})
    cache = await cache(request)

    await cache.init(app_without_cache, redis_client)

    response = cache.set(response=TEST_SET_VALUE, cache_id=TEST_CACHE_ID)
    await asyncio.sleep(1)
    assert response == TEST_SET_VALUE

    cached_value = await redis_client.get(cache.get_key(TEST_CACHE_ID))
    assert not cached_value


async def test_cache_get(app_without_cache, redis_client: Redis):
    cache = Cache(exp=30)
    await Cache.init(app_without_cache, redis_client)
    jsonified = json.dumps(TEST_SET_VALUE)
    await redis_client.set(cache.get_key(TEST_CACHE_ID), jsonified)

    getted_value = await cache.get(TEST_CACHE_ID)

    assert getted_value == TEST_SET_VALUE


async def test_cache_get_without_decode(app_without_cache, redis_client: Redis):
    cache = Cache(exp=30)
    await Cache.init(app_without_cache, redis_client)
    jsonified = json.dumps(TEST_SET_VALUE)
    await redis_client.set(cache.get_key(TEST_CACHE_ID), jsonified)

    getted_value = await cache.get(TEST_CACHE_ID, decode=False)

    assert getted_value == f"{jsonified}"


async def test_cache_get_with_cache_control(app_without_cache, redis_client: Redis):
    cache = Cache(exp=30, cache_control=True)
    await Cache.init(app_without_cache, redis_client)
    headers = {"Cache-Control": "no-cache"}
    request = Request({"type": "http", "headers": Headers(headers).raw})
    cache = await cache(request)
    jsonified = json.dumps(TEST_SET_VALUE)
    await redis_client.set(cache.get_key(TEST_CACHE_ID), jsonified)

    getted_value = await cache.get(TEST_CACHE_ID)

    assert getted_value is None


async def test_cache_call():
    cache = Cache(exp=30)

    request = Request({"type": "http"})

    returned_value = await cache(request)
    assert returned_value == cache


async def test_cache_raise_try_return_none(app_without_cache, redis_client: Redis):
    cache = Cache(exp=30, cache_control=True)
    await Cache.init(app_without_cache, redis_client)
    headers = {"Cache-Control": "no-cache"}
    request = Request({"type": "http", "headers": Headers(headers).raw})
    cache = await cache(request)

    await redis_client.set(TEST_CACHE_ID, json.dumps(TEST_SET_VALUE))

    raised = await cache.raise_try(TEST_CACHE_ID)

    assert raised is None


async def test_cache_call_with_cache_control():
    cache = Cache(exp=30, cache_control=True)
    headers = {"Cache-Control": "no-cache"}

    request = Request({"type": "http", "headers": Headers(headers).raw})

    await cache(request)

    assert cache._cache_control


async def test_cache_call_with_auto_refresh(app_without_cache, redis_client):

    cache = Cache(exp=60, auto_refresh=True)
    await Cache.init(app_without_cache, redis_client)
    request = Request({"type": "http"})

    await cache(request)


async def test_cache_api_route_with_auto_refresh(app_with_cache, redis_client: Redis):
    await Cache.init(app_with_cache, redis_client, autorefresh=True)
    await asyncio.sleep(3)
    route_path = "/items/{item_id}"
    all_path = f"{route_path}{TEST_AUTOREFRESH_ID}"
    setted_value = await redis_client.get(all_path)
    await asyncio.sleep(3)
    assert json.loads(setted_value.decode()) == TEST_SET_AUTOREFRESH_VALUE
