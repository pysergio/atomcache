import asyncio
from typing import Awaitable, Optional, Tuple

from aioredis.client import Redis, PubSub
from .backend import (
    DEFAULT_LOCK_TIMEOUT,
    KT,
    TTL,
    VT,
    BaseCacheBackend,
)

DEFAULT_ENCODING = "utf-8"


class RedisCacheBackend(BaseCacheBackend):  # noqa: WPS214
    lock_name = "__"

    def __init__(self, redis: Redis, encoding: str = DEFAULT_ENCODING) -> None:
        self.client = redis  # client might be used to perform direct redis calls
        self.client
        self._encoding = encoding
        self._channel: Optional[PubSub] = None

    def lock_key(self, key: str):
        return f"{key}{self.lock_name}"

    async def init(self):
        self._channel = self.client.pubsub()
        await self._channel.psubscribe(f"__keyspace@{self.client.connection.db}__:*")

    async def get(
        self,
        key: KT,
        default: VT = None,
        timeout: int = DEFAULT_LOCK_TIMEOUT,
        with_lock=True,
        lockspace: Optional[str] = None,
        **kwargs,
    ) -> Tuple[VT, TTL]:
        kwargs.setdefault("encoding", self._encoding)
        pipe: Redis = self.client.pipeline()
        pipe.get(key, **kwargs)
        pipe.ttl(key)
        if not with_lock:
            cached_value, ttl = await pipe.execute()
            return cached_value or default, ttl
        lock_name = self.lock_key(lockspace) if lockspace else self.lock_key(key)
        pipe.get(lock_name)
        cached_value, ttl, lock = await pipe.execute()

        if cached_value:
            return cached_value, ttl

        if not lock and await self.lock(lock_name):
            return default, 0
        try:
            return await asyncio.wait_for(self._get_or_wait(key, **kwargs), timeout=timeout)
        except (asyncio.exceptions.TimeoutError, LookupError):
            return default, 0

    async def set(
        self,
        key: KT,
        value: VT,  # noqa: WPS110
        expire: int,
        unlock=True,
        **kwargs,
    ) -> bool:

        if not unlock:
            return await self.client.set(key, value, expire=expire, **kwargs)
        pipe: Redis = self.client.pipeline()
        pipe.set(key, value, expire=expire, **kwargs)
        pipe.delete(self.lock_key(key))
        is_setted, _ = await pipe.execute()
        return is_setted

    async def expire(self, key: KT, ttl: TTL) -> bool:
        return await self.client.expire(key, ttl)

    async def lock(self, key: KT, timeout: int = DEFAULT_LOCK_TIMEOUT) -> bool:
        return await self.client.set(key, value=b"1", expire=timeout, exist="SET_IF_NOT_EXIST")

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
        return await self.client.flushdb(async_op=True)

    def close(self) -> Awaitable[None]:
        return self.client.close()

    async def _get_or_wait(self, key: KT, **kwargs) -> Tuple[VT, TTL]:  # noqa: WPS231
        channel = await self.get_channel()
        while True:
            msg = await self._channel.get_message(ignore_subscribe_messages=True)
            # TODO: check for the key set message
            # received_key = msg["type"].decode("utf-8").split(":")[1]
            # if received_key == key:
            #     if msg["type"] == "set":
            #         break

            #     if msg["type"]  in {"expired", "del", "expire"}:
            #         raise LookupError()
            break

        pipe: Redis = self.client.pipeline()
        pipe.get(key, **kwargs)
        pipe.ttl(key)

        return await pipe.execute()
