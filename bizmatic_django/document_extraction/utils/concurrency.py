"""Run asynchronous work concurrently with ordered results and raised errors."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


async def concurrent_map(
    function: Callable[[T], Awaitable[R]],
    items: Iterable[T],
    max_concurrency: int,
    *,
    semaphore: asyncio.Semaphore | None = None,
) -> list[R]:
    if max_concurrency < 1:
        raise ValueError("Concurrency must be at least 1.")
    limiter = semaphore if semaphore is not None else asyncio.Semaphore(max_concurrency)

    async def run(item: T) -> R:
        async with limiter:
            return await function(item)

    tasks: list[asyncio.Task[R]] = [asyncio.create_task(run(item)) for item in items]
    try:
        # gather preserves input order even when tasks finish out of order.
        return list(await asyncio.gather(*tasks))
    except BaseException:
        # Cancel remaining work and raise the original error to the caller.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
