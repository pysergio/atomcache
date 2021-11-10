from typing import Optional, Tuple, TypeVar

KT = TypeVar("KT")
VT = TypeVar("VT")
TTL = int
DEFAULT_LOCK_TIMEOUT = 5


class BaseCacheBackend:
    lock_name: str

    async def get(
        self,
        key: KT,
        default: VT = None,
        timeout: int = DEFAULT_LOCK_TIMEOUT,
        with_lock: bool = True,
        lockspace: Optional[str] = None,
    ) -> Tuple[VT, TTL]:
        raise NotImplementedError

    async def set(self, key: KT, value: VT, expire: int, unlock: bool = True) -> bool:  # noqa: WPS125, WPS110
        raise NotImplementedError

    async def lock(self, key: KT, timeout: int = DEFAULT_LOCK_TIMEOUT) -> bool:
        raise NotImplementedError

    async def unlock(self, key: KT) -> bool:
        raise NotImplementedError

    async def expire(self, key: KT, ttl: int) -> bool:
        raise NotImplementedError

    async def exists(self, *keys: KT) -> bool:
        raise NotImplementedError

    async def delete(self, key: KT) -> bool:
        raise NotImplementedError

    async def ttl(self, key: KT) -> TTL:
        raise NotImplementedError

    async def flush(self) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError
