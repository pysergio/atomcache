import asyncio
from typing import Any, Awaitable, Generator, Optional, Tuple

from aioredis.client import KeyT, Redis

from .backend import DEFAULT_LOCK_TIMEOUT, EX, KT, TTL, VT, BaseCacheBackend

DEFAULT_ENCODING = "utf-8"
DEFAULT_TTL = 0


class RedisCacheBackend(BaseCacheBackend):  # noqa: WPS214
    lock_name = "__"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._db = self.client.connection_pool.connection_kwargs["db"]

    def __await__(self) -> Generator[Any, None, "RedisCacheBackend"]:  # noqa:WPS611
        """Setup keyspace notification events required by `_get_or_wait`"""
        yield from self._redis.execute_command(  # noqa:WPS609
            "config", "set", "notify-keyspace-events", "KEA"
        ).__await__()
        return self

    @property
    def client(self) -> Redis:
        """Client might be used to perform direct redis calls
        Returns:
            Redis: Client from connection pool
        """
        return self._redis

    def lock_key(self, key: str) -> str:
        return f"{key}{self.lock_name}"

    async def get(
        self,
        key: KeyT,
        default: VT = None,
        timeout: int = DEFAULT_LOCK_TIMEOUT,
        with_lock: bool = True,
        lockspace: Optional[str] = None,
    ) -> Tuple[VT, TTL]:
        async with self._redis.pipeline() as pipe:
            pipe.get(key)
            pipe.ttl(key)
            if not with_lock:
                cached_value, ttl = await pipe.execute()
                return cached_value.decode() or default, ttl
            lock_name = self.lock_key(lockspace) if lockspace else self.lock_key(key)
            pipe.get(lock_name)
            cached_value, ttl, lock = await pipe.execute()

            if cached_value:
                return cached_value.decode(), ttl

            if not lock and await self.lock(lockspace or key, timeout=timeout):
                return default, DEFAULT_TTL
            try:
                return await asyncio.wait_for(self._get_or_wait(key), timeout=timeout)
            except (asyncio.exceptions.TimeoutError, LookupError):
                return default, DEFAULT_TTL

    async def set(self, key: KT, value: VT, expire: EX, unlock=True) -> bool:
        async with self._redis.client() as conn:
            if not unlock:
                return await conn.set(key, value, ex=expire)
            pipe = conn.pipeline()
            pipe.set(key, value, ex=expire)
            pipe.delete(self.lock_key(key))
            is_setted, _ = await pipe.execute()
            return is_setted

    async def mget(self, *keys: KT) -> dict[KT, VT]:
        async with self._redis.client() as conn:
            return {k: v for k, v in zip(keys, await conn.mget(keys)) if v is not None}

    async def mset(self, values: dict[KT, VT], expire: EX) -> None:
        async with self._redis.pipeline() as pipe:
            for key, value in values.items():
                pipe.set(key, value, ex=expire)
            await pipe.execute()

    async def expire(self, key: KT, ttl: TTL) -> bool:
        async with self._redis.client() as conn:
            return await conn.expire(key, ttl)

    async def lock(self, key: KT, timeout: int = DEFAULT_LOCK_TIMEOUT) -> bool:
        async with self._redis.client() as conn:
            return await conn.set(self.lock_key(key), value=b"1", ex=timeout, nx=True)

    async def unlock(self, key: KT) -> bool:
        async with self._redis.client() as conn:
            return await conn.delete(self.lock_key(key))

    async def delete(self, key: KT) -> bool:
        async with self._redis.client() as conn:
            return await conn.delete(key)

    async def ttl(self, key: KT) -> TTL:
        async with self._redis.client() as conn:
            return await conn.ttl(key)

    async def exists(self, *keys: KT) -> bool:
        async with self._redis.client() as conn:
            return bool(await conn.exists(*keys))

    async def flush(self) -> bool:
        async with self._redis.client() as conn:
            return await conn.flushdb(asynchronous=True)

    def close(self) -> Awaitable[None]:
        return self._redis.close()

    async def _get_or_wait(self, key: KT) -> Tuple[VT, TTL]:
        async with self._redis.pubsub(ignore_subscribe_messages=True) as channel:
            await channel.psubscribe(f"__keyspace@{self._db}__:{key}")
            async for msg in channel.listen():
                msg_type = msg["data"]
                if msg_type == b"set":
                    break
                if msg_type in {b"expired", b"del", b"expire"}:
                    raise LookupError()

        async with self._redis.pipeline() as pipe:
            pipe.get(key)
            pipe.ttl(key)
            value, ttl = await pipe.execute()
            return value.decode(), ttl
