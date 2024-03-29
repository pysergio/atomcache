import asyncio
import inspect
import json
from functools import partial
from hashlib import sha256
from typing import Any, Awaitable, Callable, Coroutine, Dict, Optional, TypeVar, Union

from fastapi import FastAPI, Request, Response, params
from fastapi.encoders import jsonable_encoder
from fastapi.routing import APIRoute
from starlette.datastructures import CommaSeparatedStrings

from redis.asyncio import Redis

from .backend import DEFAULT_LOCK_TIMEOUT, EX, BaseCacheBackend
from .redis import RedisCacheBackend

MIN_AUTOREFRESH_RATE = 20
_ResponseT = TypeVar("_ResponseT")


class CachedResponse(Exception):  # noqa: N818
    def __init__(self, *args, content: str, ttl: int) -> None:
        self.content = content
        self.ttl = ttl

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"{class_name}(ttl={self.ttl!r})"  # noqa: WPS237


class Cache:
    app: FastAPI
    backend: BaseCacheBackend
    autorefresh: Dict[str, "Cache"] = {}

    def __init__(
        self,
        exp: EX,
        auto_refresh: bool = False,
        cache_control: bool = False,
        namespace: Optional[str] = None,
        lock_timeout: int = DEFAULT_LOCK_TIMEOUT,
    ):
        """Atomic cache manager.
        Args:
            exp (int): Cache expire. None mean infinite.
            auto_refresh (bool, optional): Refresh cache in background. Defaults to False.
            cache_control (bool, optional): React based on cache Cache-Control from request's header. Defaults to False.
            namespace (Optional[str], optional): Cache storage namespace. Defaults is the route path.
            lock_timeout (int, optional): Max time required to refresh the cache (do the calculation).
                Defaults to DEFAULT_LOCK_TIMEOUT.
        NOTE: Autorefresh is not active if Cache was `init`-ed with autorefresh=False. On DEBUG mode autorefresh=False.
        ```
        @router.get("/cache", response_model=List[TheResponseModel], name="main:test-example")
        async def welcome(offset: int = 0, items: int = 10, cache: Cache = Depends(Cache(exp=100, lock_timeout=10+1))):
            cache_id = f"{offset}-{items}"  # Build cache identifier
            await cache.raise_try(cache_id)  # Try to respond from cache
            response = await db.find(TheResponseModel, skip=offset, limit=items)
            await asyncio.sleep(10)  # Do some heavy work for 10 sec, see `lock_timeout`
            return cache.set(response, cache_id=cache_id)
        """
        assert not auto_refresh or exp is not None, "Autorefresh doesn't support inifinite rate expire"
        assert not auto_refresh or exp >= MIN_AUTOREFRESH_RATE, f"Min autorefresh rate is {MIN_AUTOREFRESH_RATE}"
        assert exp is None or exp >= lock_timeout, f"ValueError: {lock_timeout=} must be less than {exp=}"
        self.auto_refresh = auto_refresh
        self._expire = exp
        self.namespace = namespace
        self._lock_timeout = lock_timeout
        self._allow_cache_control = cache_control
        self._autorefresh_callback: Union[Callable, Awaitable, None] = None
        self._no_cache: bool = False

    async def __call__(self, request: Request):
        if self._allow_cache_control:
            self._no_cache = "no-cache" in CommaSeparatedStrings(request.headers.get("Cache-Control", ""))
        return self

    def set_namespace(self, namespace: str):  # noqa: WPS615 FIXME: unpythonic setter
        self.namespace = namespace

    def set_autorefresh_callback(self, endpoint: Union[Callable, Coroutine]):  # noqa: WPS231 WPS615
        kwargs = {}
        signature = inspect.signature(endpoint)
        for prm in signature.parameters.values():
            if isinstance(prm.default, params.Param):
                default = prm.default.default
            elif isinstance(prm.default, params.Depends) and isinstance(prm.default.dependency, Cache):
                default = self
            else:
                default = prm.default
            kwargs[prm.name] = default
            if default == inspect._empty or isinstance(default, params.Depends):  # noqa: WPS437
                raise ValueError(f"{endpoint} does not support auto cache refresh. Args {prm.name} has no default")

        autorefresh_callback = partial(endpoint, **kwargs)
        if asyncio.iscoroutinefunction(endpoint):
            self._autorefresh_callback = autorefresh_callback
        else:
            loop = asyncio.get_running_loop()
            self._autorefresh_callback = partial(loop.run_in_executor, None, autorefresh_callback)

        Cache.autorefresh[self.namespace] = self

    def get_key(self, cache_id: str = "") -> str:
        return f"{self.namespace}{cache_id}"

    def set(self, response: _ResponseT, cache_id: str = "") -> _ResponseT:  # noqa: WPS125
        if isinstance(response, Response):
            cache = response.body
        else:
            cache = json.dumps(jsonable_encoder(response))
        if not self._no_cache:
            asyncio.ensure_future(self.backend.set(key=self.get_key(cache_id), value=cache, expire=self._expire))
        return response

    def mset(self, cache: dict[str, Any]) -> dict[str, Any]:
        encoded_cache = {self.get_key(k): json.dumps(jsonable_encoder(v)) for k, v in cache.items()}
        asyncio.ensure_future(self.backend.mset(encoded_cache, self._expire))
        return cache

    async def get(
        self,
        cache_id: str = "",
        with_lock=True,
        decode=True,
        lockspace: Optional[str] = None,
    ) -> Any:
        if self._no_cache:
            return None
        cached, _ = await self.backend.get(
            key=self.get_key(cache_id), timeout=self._lock_timeout, with_lock=with_lock, lockspace=lockspace
        )
        return json.loads(cached) if cached is not None and decode else cached

    async def mget(self, *cache_ids: str, decode=True) -> dict[str, Any]:
        if not cache_ids:
            return {}
        cache = await self.backend.mget(*map(self.get_key, cache_ids))
        if decode:
            return {k.removeprefix(self.namespace): json.loads(v) for k, v in cache.items()}
        return {k.removeprefix(self.namespace): v for k, v in cache.items()}

    async def raise_try(self, cache_id: str = "", with_lock=True, lockspace: Optional[str] = None) -> None:
        """Try to raise Response from cache otherwise do nothing.

        Args:
            cache_id (str, optional): Cache identifier. Defaults to "".
            with_lock (bool, optional): Lock the cache if there is no response. Defaults to True.
            lockspace (str, optional): Key to use for lock

        Raises:
            CachedResponse: generate response from cache.
        """
        if self._no_cache:
            return
        cached_content, ttl = await self.backend.get(
            self.get_key(cache_id),
            timeout=self._lock_timeout,
            with_lock=with_lock,
            lockspace=lockspace,
        )
        if cached_content is not None:
            raise CachedResponse(content=cached_content, ttl=ttl)

    def schedule_autorefresh(self, __task: Optional[asyncio.Task[None]] = None) -> None:  # noqa: WPS112
        if __task is None:
            autorefresh_task = asyncio.create_task(self._autorefresh())
            autorefresh_task.add_done_callback(self.schedule_autorefresh)
            return
        if __task.cancelled():
            return
        loop = asyncio.get_running_loop()
        loop.call_later(MIN_AUTOREFRESH_RATE, self.schedule_autorefresh, None)

    @classmethod
    async def init(cls, app: FastAPI, cache_client: Redis, autorefresh: bool = True):
        cls.app = app
        if isinstance(cache_client, Redis):
            cls.backend = await RedisCacheBackend(cache_client)
        else:
            raise TypeError(f"Unsupported {type(cache_client)} cache client type.")
        app.add_exception_handler(CachedResponse, cached_response_handler)
        cls._config_caches(app)
        if not autorefresh:
            return
        for cache in cls.autorefresh.values():
            cache.schedule_autorefresh()

    @classmethod
    def _config_caches(cls, app: FastAPI) -> None:  # noqa: WPS231
        """
        Should be called only after all routes have been added.
        """
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            signature = inspect.signature(route.endpoint)
            for prm in signature.parameters.values():
                default = prm.default
                if not default or not isinstance(default, params.Depends) or not isinstance(default.dependency, cls):
                    continue
                cache = default.dependency
                if cache.namespace is None:
                    cache.set_namespace(route.path)
                if cache.auto_refresh:
                    cache.set_autorefresh_callback(route.endpoint)

    async def _autorefresh(self) -> None:
        while True:  # noqa: WPS457
            try:
                await self._autorefresh_callback()
            except CachedResponse as cached_response:
                await asyncio.sleep(cached_response.ttl or 1)
            else:
                await asyncio.sleep(self._lock_timeout)


def cached_response_handler(request: Request, exc: CachedResponse) -> Response:
    if_none_match = request.headers.get("if-none-match")
    etag = f"W/{hashsum(exc.content)}"
    if if_none_match == etag:
        response = Response(status_code=304, headers={"Cache-Control": f"max-age={exc.ttl}"})  # noqa:WPS432
    else:
        response = Response(
            media_type="application/json",
            content=exc.content,
            headers={"Cache-Control": f"max-age={exc.ttl}", "ETag": etag},
        )
    return response


def hashsum(obj: str) -> str:
    return sha256(obj.encode()).hexdigest()
