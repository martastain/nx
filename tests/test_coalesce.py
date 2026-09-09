import asyncio

import pytest

from nx.utils.coalesce import Coalescer, _func_identity, _hash_args


async def _slow_echo(value: int, delay: float = 0.05) -> int:
    await asyncio.sleep(delay)
    return value


class Service:
    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.calls = 0

    async def load(self, value: int) -> str:
        self.calls += 1
        await asyncio.sleep(0.05)
        return f"{self.tag}:{value}"


def test_hash_is_stable_for_identical_calls() -> None:
    assert _hash_args(_slow_echo, 1) == _hash_args(_slow_echo, 1)
    assert _hash_args(_slow_echo, 1) != _hash_args(_slow_echo, 2)


def test_hash_ignores_keyword_order() -> None:
    """Kwargs are sorted, so call-site ordering must not split the key."""
    assert _hash_args(_slow_echo, value=1, delay=0.1) == _hash_args(
        _slow_echo, delay=0.1, value=1
    )


def test_hash_ignores_underscore_prefixed_kwargs() -> None:
    """Bookkeeping kwargs (_trace_id and friends) must not fragment the key."""
    assert _hash_args(_slow_echo, value=1) == _hash_args(
        _slow_echo, value=1, _trace_id="abc"
    )


def test_hash_separates_distinct_functions() -> None:
    async def other(value: int) -> int:
        return value

    assert _hash_args(_slow_echo, 1) != _hash_args(other, 1)


def test_hash_separates_closures_sharing_a_qualname() -> None:
    """Two closures from the same factory are different callables."""

    def make(result: int):
        async def inner() -> int:
            return result

        return inner

    first, second = make(1), make(2)
    assert _hash_args(first) != _hash_args(second)


def test_bound_method_identity_is_stable_across_lookups() -> None:
    """obj.method is a fresh object each lookup; identity must survive that."""
    service = Service("a")
    assert _func_identity(service.load) == _func_identity(service.load)


def test_bound_method_identity_separates_instances() -> None:
    a, b = Service("a"), Service("b")
    assert _func_identity(a.load) != _func_identity(b.load)


async def test_concurrent_identical_calls_run_once() -> None:
    coalesce = Coalescer()
    calls = 0

    async def work(value: int) -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return value

    results = await asyncio.gather(*(coalesce(work, value=7) for _ in range(5)))

    assert results == [7] * 5
    assert calls == 1


async def test_distinct_arguments_are_not_coalesced() -> None:
    coalesce = Coalescer()
    calls = 0

    async def work(value: int) -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return value

    results = await asyncio.gather(coalesce(work, value=1), coalesce(work, value=2))

    assert sorted(results) == [1, 2]
    assert calls == 2


async def test_sequential_calls_are_not_cached() -> None:
    """Coalescing shares an in-flight call; it is not a result cache."""
    coalesce = Coalescer()
    calls = 0

    async def work() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert await coalesce(work) == 1
    assert await coalesce(work) == 2


async def test_bound_methods_coalesce_per_instance() -> None:
    """Previously id(obj.method) changed per lookup, so this never engaged."""
    coalesce = Coalescer()
    service = Service("a")

    results = await asyncio.gather(*(coalesce(service.load, 1) for _ in range(4)))

    assert results == ["a:1"] * 4
    assert service.calls == 1


async def test_bound_methods_on_different_instances_do_not_share() -> None:
    coalesce = Coalescer()
    a, b = Service("a"), Service("b")

    results = await asyncio.gather(coalesce(a.load, 1), coalesce(b.load, 1))

    assert sorted(results) == ["a:1", "b:1"]
    assert (a.calls, b.calls) == (1, 1)


async def test_exception_reaches_every_waiter() -> None:
    coalesce = Coalescer()
    calls = 0

    async def failing() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        raise ValueError("boom")

    results = await asyncio.gather(
        *(coalesce(failing) for _ in range(3)), return_exceptions=True
    )

    assert calls == 1
    assert all(isinstance(r, ValueError) for r in results)


async def test_failed_call_does_not_poison_the_key() -> None:
    """A failure must be evicted, so the next caller gets a fresh attempt."""
    coalesce = Coalescer()
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("boom")
        return "recovered"

    with pytest.raises(ValueError, match="boom"):
        await coalesce(flaky)

    assert await coalesce(flaky) == "recovered"


async def test_futures_are_released_after_completion() -> None:
    coalesce = Coalescer()

    await coalesce(_slow_echo, 1, 0.0)

    assert coalesce.current_futures == {}
