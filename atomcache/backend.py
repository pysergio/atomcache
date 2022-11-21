from typing import Optional, Tuple, TypeVar, Union

KT = TypeVar("KT")
VT = TypeVar("VT")
TTL = int
EX = Union[int, None]
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

    async def set(self, key: KT, value: VT, expire: EX, unlock: bool = True) -> bool:
        raise NotImplementedError

    async def mget(self, *keys: KT) -> dict[KT, VT]:
        raise NotImplementedError

    async def mset(self, hmap: dict[KT, VT], expire: EX) -> None:
        raise NotImplementedError

    async def lock(self, key: KT, timeout: int = DEFAULT_LOCK_TIMEOUT) -> bool:
        raise NotImplementedError

    async def unlock(self, key: KT) -> bool:
        raise NotImplementedError

    async def expire(self, key: KT, ttl: TTL) -> bool:
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
