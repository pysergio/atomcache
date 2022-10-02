<p align="center">
<a href="https://codecov.io/gh/pysergio/atomcache"> 
 <img src="https://codecov.io/gh/pysergio/atomcache/branch/master/graph/badge.svg?token=OVZABBE1UJ"/> 
</a>
<a href="https://pypi.org/project/atomcache" target="_blank">
    <img src="https://img.shields.io/pypi/v/atomcache?color=%2334D058&label=pypi%20package" alt="Package version">
</a>
<a href="https://pypi.org/project/atomcache" target="_blank">
    <img src="https://img.shields.io/pypi/pyversions/atomcache.svg?color=%2334D058" alt="Supported Python versions">
</a>
</p>

## Introduction
Asynchronous cache manager designed for horizontally scaled web applications.
**NOTE:** _Currently has implementation only for FastAPI using Redis._

## Requirements

Python 3.7+

* <a href="https://aioredis.readthedocs.io" class="external-link" target="_blank">aioredis</a> for cache implementation.
* <a href="https://fastapi.tiangolo.com" class="external-link" target="_blank">FastAPI</a> for the web parts.
  
## Installation

<div class="termy">

```console
$ pip install atomcache

---> 100%
```

## Explanation schema

![Class Diagram](http://www.plantuml.com/plantuml/proxy?src=https://raw.githubusercontent.com/pysergio/atomcache/master/README.md)

<details markdown="1">
<summary>As UML</summary>

```plantuml
@startuml
    !theme materia
    participant Redis
    participant Instance_A as A
    participant Instance_B as B
    participant Instance_N as C


    B <-> Redis: GET: Cache=null & GET: Lock=null

    B <-> Redis: SET: Lock = true

    activate B #Red
    A <--> Redis: GET: Cache=null & GET: Lock=true
    activate A #Transparent
    C <--> Redis: GET: Cache=null & GET: Lock=true
    activate C #Transparent
    B <--> B: Do the computation
    B -> Redis: SET: Cache={...}
    deactivate B

    group Notify Cache SET
        Redis -> C
        Redis -> A
    end
    group GET Cache
        Redis <-> C
    deactivate C
        Redis <-> A
    deactivate A
    end
@enduml
```
</details>

## Examples:

### Usage as FastAPI Dependency

* Create a file `events.py` with:

```Python
from typing import Optional, Callable

import aioredis
from fastapi import FastAPI, Depends
from atomcache import Cache


def create_start_app_handler(app: FastAPI) -> Callable:
    async def start_app() -> None:
        redis: aioredis.Redis = await aioredis.from_url(url="redis://localhost", encoding="utf-8")
        await Cache.init(app, redis)

    return start_app


def create_stop_app_handler(app: FastAPI) -> Callable:
    async def stop_app() -> None:
        await Cache.backend.close()

    return stop_app
```

* Create a file `main.py` with:

```Python
from typing import Optional

from fastapi import FastAPI, Depends
from atomcache import Cache

from .events import create_start_app_handler, create_stop_app_handler

app = FastAPI()

app.add_event_handler("startup", create_start_app_handler(app))
app.add_event_handler("shutdown", create_stop_app_handler(app))


@router.get("/resources", response_model=List[TheResponseModel], name="main:test-example")
async def resources(offset: int = 0, items: int = 10, cache: Cache = Depends(Cache(exp=600)):
    cache_id = f"{offset}-{items}"  # Build cache identifier
    await cache.raise_try(cache_id)  # Try to respond from cache
    response = await db.find(TheResponseModel, skip=offset, limit=items)
    await asyncio.sleep(10)  # Do some heavy work for 10 sec, see `lock_timeout`
    return cache.set(response, cache_id=cache_id)
```

### Direct cache usage for avoiding repetitive calling on external resources:

```Python
from aiohttp import ClientSession
from atomcache import Cache

cache = Cache(exp=1200, namespace="my-namespace:")


async def requesting_helper(ref: str) -> List[dict]:
    cached_value = await cache.get(cache_id=ref)
    if cached_value is not None:
        return cached_value

    async with ClientSession() as session:
        async with session.get(f"https://external-api.io/{ref}") as response:
            if response.ok:
                cached_value = response.json()
                return cache.set(cached_value, cache_id=ref)
    return []
```
