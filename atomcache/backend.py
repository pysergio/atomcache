from typing import AnyStr, Optional, Tuple, Union

KT = Union[AnyStr, float, int]
VT = Union[AnyStr, float, int]
TTL = int
DEFAULT_LOCK_TIMEOUT = 5


class BaseCacheBackend:
    lock_name: str

    async def get(
        self,
        key: KT,
        default: VT = None,
        timeout: int = DEFAULT_LOCK_TIMEOUT,
        with_lock=True,
        lockspace: Optional[str] = None,
        **kwargs
    ) -> Tuple[VT, TTL]:
        raise NotImplementedError

    async def set(self, key: KT, value: VT, expire: int, unlock=True, **kwargs) -> bool:  # noqa: WPS125, WPS110
        raise NotImplementedError

    async def lock(self, key: KT, timeout: int = DEFAULT_LOCK_TIMEOUT) -> bool:
        raise NotImplementedError

    async def unlock(self, key: KT, **kwargs) -> bool:
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
