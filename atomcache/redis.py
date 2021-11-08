import asyncio
from contextlib import asynccontextmanager
from typing import Awaitable, Optional, Tuple

from aioredis.client import PubSub, Redis

from .backend import DEFAULT_LOCK_TIMEOUT, KT, TTL, VT, BaseCacheBackend

DEFAULT_ENCODING = "utf-8"
DEFAULT_TTL = 0


class RedisCacheBackend(BaseCacheBackend):  # noqa: WPS214
    lock_name = "__"

    def __init__(self, redis: Redis, encoding: str = DEFAULT_ENCODING) -> None:
        self._client = redis  # client might be used to perform direct redis calls
        self._channel: PubSub = redis.pubsub()

    @property
    def client(self):
        return self._client.client()

    def lock_key(self, key: str):
        return f"{key}{self.lock_name}"

    @asynccontextmanager
    async def subscribe(self, key: str):
        db = self.client.connection_pool.connection_kwargs["db"]
        await self._channel.psubscribe(f"__keyspace@{db}__:{key}")
        try:
            yield self._channel
        finally:
            await self._channel.punsubscribe(f"__keyspace@{db}__:{key}")

    async def get(
        self,
        key: KT,
        default: VT = None,
        timeout: int = DEFAULT_LOCK_TIMEOUT,
        with_lock=True,
        lockspace: Optional[str] = None,
        **kwargs,
    ) -> Tuple[VT, TTL]:
        pipe: Redis = self.client.pipeline()
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

        if not lock and await self.lock(lock_name, timeout=timeout):
            return default, DEFAULT_TTL
        try:
            return await asyncio.wait_for(self._get_or_wait(key, **kwargs), timeout=timeout)
        except (asyncio.exceptions.TimeoutError, LookupError) as e:
            return default, DEFAULT_TTL

    async def set(
        self,
        key: KT,
        value: VT,  # noqa: WPS110
        expire: int,
        unlock=True,
        **kwargs,
    ) -> bool:

        if not unlock:
            return await self.client.set(key, value, ex=expire, **kwargs)
        pipe: Redis = self.client.pipeline()
        pipe.set(key, value, ex=expire, **kwargs)
        pipe.delete(self.lock_key(key))
        is_setted, _ = await pipe.execute()
        return is_setted

    async def expire(self, key: KT, ttl: TTL) -> bool:
        return await self.client.expire(key, ttl)

    async def lock(self, key: KT, timeout: int = DEFAULT_LOCK_TIMEOUT) -> bool:
        return await self.client.set(key, value=b"1", ex=timeout, nx=True)

    async def unlock(self, key: KT) -> bool:
        return await self.client.delete(self.lock_key(key))

    async def delete(self, key: KT) -> bool:
        return await self.client.delete(key)

    async def ttl(self, key: KT) -> TTL:
        return await self.client.ttl(key)

    async def exists(self, *keys: KT) -> bool:
        exists = await self.client.exists(*keys)
        return bool(exists)

    async def flush(self) -> bool:
        return await self.client.flushdb(asynchronous=True)

    def close(self) -> Awaitable[None]:
        return self.client.close()

    async def _get_or_wait(self, key: KT) -> Tuple[VT, TTL]:  # noqa: WPS231
        # TODO: check for the key set message
        async with self.subscribe(key) as chn:
            async for msg in chn.listen():
                received_key = msg["channel"].decode().split(":")[-1].rstrip("__")
                if received_key == key:
                    if isinstance(msg["data"], bytes):
                        msg_type = msg["data"].decode()
                    else:
                        msg_type = msg["data"]
                    if msg_type == "set":
                        break
                    if msg_type in {"expired", "del", "expire"}:
                        raise LookupError()

        pipe: Redis = self.client.pipeline()
        pipe.get(key)
        pipe.ttl(key)
        value, ttl = await pipe.execute()
        return value.decode(), ttl
