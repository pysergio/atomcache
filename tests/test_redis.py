import asyncio

import pytest
from redis.asyncio import Redis

from atomcache.redis import RedisCacheBackend

pytestmark = pytest.mark.asyncio

TEST_LOCK_KEY = "TEST_LOCK_KEY"
TEST_GET_VALUE = "TEST_GET_VALUE"
TEST_SET_KEY = "TEST_SET_KEY"
TEST_DEFAULT_VALUE = "TEST_DEFAULT_VALUE"


EXPIRE_TIME = 10
DEFAULT_ENCODING = "utf-8"


async def test_redis_cache_backend_close(redis_client):
    redis_backend = RedisCacheBackend(redis=redis_client)
    await redis_backend.close()
    assert not redis_backend.client.connection


def test_lock_key(redis_client):
    redis_backend = RedisCacheBackend(redis=redis_client)
    lock_name = redis_backend.lock_key(TEST_LOCK_KEY)

    assert TEST_LOCK_KEY in lock_name


async def test_get_cached_value_is_present(redis_client: Redis):
    redis_backend = RedisCacheBackend(redis=redis_client)

    await redis_client.set(name=TEST_SET_KEY, value=TEST_GET_VALUE, ex=EXPIRE_TIME)

    value, ttl = await redis_backend.get(key=TEST_SET_KEY)

    assert value == TEST_GET_VALUE
    assert ttl == EXPIRE_TIME


async def test_get_with_no_lock(redis_client: Redis):
    redis_backend = RedisCacheBackend(redis=redis_client)

    await redis_client.set(name=TEST_SET_KEY, value=TEST_GET_VALUE, ex=EXPIRE_TIME)

    value, ttl = await redis_backend.get(key=TEST_SET_KEY, with_lock=False)

    assert value == TEST_GET_VALUE
    assert ttl == EXPIRE_TIME


async def test_get_when_no_cached_value_is_present_and_set_lock(redis_client: Redis):
    redis_backend = RedisCacheBackend(redis=redis_client)
    lock_name = redis_backend.lock_key(TEST_SET_KEY)

    value, ttl = await redis_backend.get(key=TEST_SET_KEY, default=TEST_DEFAULT_VALUE, timeout=10)
    assert value == TEST_DEFAULT_VALUE, ttl == 0

    value = await redis_client.get(lock_name)
    assert value.decode() == "1"


async def test_get_when_lock_is_present_and_wait(redis_client: Redis):
    redis_backend = RedisCacheBackend(redis=redis_client)

    lock_name = redis_backend.lock_key(TEST_SET_KEY)
    await redis_client.set(lock_name, value=b"1", ex=100)

    get_task = asyncio.create_task(redis_backend.get(key=TEST_SET_KEY, timeout=5))
    await asyncio.sleep(1)
    await redis_client.set(name=TEST_SET_KEY, value=TEST_GET_VALUE, ex=EXPIRE_TIME)

    value, ttl = await get_task
    assert value == TEST_GET_VALUE, ttl == EXPIRE_TIME


async def test_get_when_lock_is_present_and_is_lookup_error(redis_client: Redis):
    redis_backend = RedisCacheBackend(redis=redis_client)

    lock_name = redis_backend.lock_key(TEST_SET_KEY)

    await redis_client.set(lock_name, value=b"1", ex=EXPIRE_TIME)

    value, _ = await asyncio.create_task(redis_backend.get(key=TEST_SET_KEY, default=TEST_DEFAULT_VALUE, timeout=0.1))

    assert value == TEST_DEFAULT_VALUE


async def test_set_with_no_params(redis_client: Redis):
    redis_backend = RedisCacheBackend(redis=redis_client)

    is_setted = await redis_backend.set(key=TEST_SET_KEY, value=TEST_GET_VALUE, expire=EXPIRE_TIME)
    assert is_setted

    value = await redis_client.get(name=TEST_SET_KEY)

    await redis_backend.delete(TEST_LOCK_KEY)
    assert value.decode() == TEST_GET_VALUE


async def test_set_with_no_unlock(redis_client: Redis):
    redis_backend = RedisCacheBackend(redis=redis_client)
    lock_name = redis_backend.lock_key(TEST_SET_KEY)

    await redis_client.set(lock_name, value=b"1", ex=EXPIRE_TIME)
    is_setted = await redis_backend.set(key=TEST_SET_KEY, value=TEST_GET_VALUE, expire=EXPIRE_TIME, unlock=False)
    assert is_setted

    value = await redis_client.get(name=lock_name)

    assert value == b"1"


async def test_set_expire_and_verify_ttl(redis_client: Redis):
    redis_backend = RedisCacheBackend(redis=redis_client)

    await redis_client.set(TEST_SET_KEY, value=TEST_GET_VALUE, ex=EXPIRE_TIME)

    is_setted = await redis_backend.expire(key=TEST_SET_KEY, ttl=EXPIRE_TIME * 2)
    ttl = await redis_backend.ttl(key=TEST_SET_KEY)
    assert is_setted and ttl == EXPIRE_TIME * 2


async def test_set_unlock(redis_client: Redis):
    redis_backend = RedisCacheBackend(redis=redis_client)
    lock_name = redis_backend.lock_key(TEST_SET_KEY)

    await redis_client.set(lock_name, value=b"1", ex=EXPIRE_TIME)

    delete_count = await redis_backend.unlock(TEST_SET_KEY)

    assert delete_count == 1


async def test_exists(redis_client: Redis):
    redis_backend = RedisCacheBackend(redis=redis_client)

    await redis_client.set(TEST_SET_KEY, value=TEST_GET_VALUE, ex=EXPIRE_TIME)

    exist = await redis_backend.exists(TEST_SET_KEY)

    assert exist


async def test_flush_db(redis_client: Redis):
    redis_backend = RedisCacheBackend(redis=redis_client)

    await redis_client.set(TEST_SET_KEY, value=TEST_GET_VALUE, ex=EXPIRE_TIME)

    ok = await redis_backend.flush()

    assert ok


async def test_get_or_wait(redis_client: Redis):
    redis_backend = RedisCacheBackend(redis=redis_client)

    get_task = asyncio.create_task(redis_backend._get_or_wait(TEST_SET_KEY))
    await asyncio.sleep(1)
    await redis_client.set(TEST_SET_KEY, TEST_GET_VALUE, ex=EXPIRE_TIME)
    value, ttl = await get_task
    assert value == TEST_GET_VALUE, ttl == EXPIRE_TIME


async def test_get_or_wait_lookup_error(redis_client: Redis):
    redis_backend = RedisCacheBackend(redis=redis_client)

    await redis_client.set(TEST_SET_KEY, TEST_GET_VALUE, ex=EXPIRE_TIME)

    get_task = asyncio.create_task(redis_backend._get_or_wait(TEST_SET_KEY))
    await asyncio.sleep(2)
    await redis_client.delete(TEST_SET_KEY)
    try:
        await get_task
    except LookupError as error:
        assert error


async def test_get_or_wait_multiple_commands(redis_client: Redis):
    redis_backend = RedisCacheBackend(redis=redis_client)

    await redis_client.delete(TEST_SET_KEY)

    get_task = asyncio.create_task(redis_backend._get_or_wait(TEST_SET_KEY))
    assert await redis_client.get(TEST_SET_KEY) is None
    await asyncio.sleep(1)
    await redis_client.set(TEST_SET_KEY, TEST_GET_VALUE, ex=EXPIRE_TIME)

    value, ttl = await get_task
    assert value == TEST_GET_VALUE, ttl == EXPIRE_TIME
