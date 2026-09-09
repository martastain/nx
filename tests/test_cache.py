import datetime as dt
from typing import Any

import pytest
from pydantic import BaseModel
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from nx.redis import (
    _deserialize,
    _has_unstable_repr,
    _infer_model,
    _make_key_builder,
    _serialize,
    redis,
)


class Payload(BaseModel):
    value: int
    label: str = "default"


class Other(BaseModel):
    value: int


class Opaque:
    """No __str__/__repr__, so formatting it embeds a memory address."""


#
# Key template validation (happens at decoration time)
#


def test_template_referencing_unknown_argument_is_rejected() -> None:
    """A typo must fail on import, not silently redirect every call."""

    with pytest.raises(ValueError, match="unknown argument"):

        @redis.cached(ns="t", key="user:{userid}")
        async def load(user_id: int) -> dict[str, Any]:
            return {"id": user_id}


def test_template_error_lists_available_arguments() -> None:
    with pytest.raises(ValueError, match="Available: user_id, verbose"):

        @redis.cached(ns="t", key="user:{nope}")
        async def load(user_id: int, verbose: bool = False) -> dict[str, Any]:
            return {"id": user_id}


def test_positional_template_fields_are_rejected() -> None:
    for template in ("user:{}", "user:{0}"):
        with pytest.raises(ValueError, match="positional field"):

            @redis.cached(ns="t", key=template)
            async def load(user_id: int) -> dict[str, Any]:
                return {"id": user_id}


def test_valid_template_is_accepted() -> None:
    @redis.cached(ns="t", key="user:{user_id}")
    async def load(user_id: int) -> dict[str, Any]:
        return {"id": user_id}

    assert load.cache_key(5) == "t:user:5"


def test_template_may_reach_into_attributes() -> None:
    @redis.cached(ns="t", key="user:{user.value}")
    async def load(user: Payload) -> int:
        return user.value

    assert load.cache_key(Payload(value=9)) == "t:user:9"


def test_template_is_unchecked_for_var_keyword_functions() -> None:
    """**kwargs can supply anything, so names cannot be validated up front."""

    @redis.cached(ns="t", key="thing:{whatever}")
    async def load(**kwargs: Any) -> Any:
        return kwargs

    assert load.cache_key(whatever="x") == "t:thing:x"


#
# Key building
#


def test_defaults_are_applied_to_the_key() -> None:
    """f(5) and f(5, verbose=False) are the same call and must share a key."""
    builder = _make_key_builder(_sample, "u:{user_id}:{verbose}")

    assert builder((5,), {}) == builder((5,), {"verbose": False}) == "u:5:False"


def test_positional_and_keyword_calls_agree() -> None:
    builder = _make_key_builder(_sample, "u:{user_id}:{verbose}")

    assert builder((5, True), {}) == builder((), {"user_id": 5, "verbose": True})


def test_self_is_excluded_from_the_key() -> None:
    """Two instances share a cache entry; the key describes the arguments."""

    class Repo:
        @redis.cached(ns="t", key="item:{item_id}")
        async def load(self, item_id: int) -> dict[str, Any]:
            return {"id": item_id}

    first, second = Repo(), Repo()

    # The helpers mirror the function's own signature, so `self` is passed
    # through even though it is dropped from the key.
    assert first.load.cache_key(first, 3) == "t:item:3"
    assert second.load.cache_key(second, 3) == "t:item:3"


def test_unstable_repr_detection() -> None:
    assert _has_unstable_repr(Opaque()) is True
    assert _has_unstable_repr(object()) is True
    assert _has_unstable_repr(42) is False
    assert _has_unstable_repr("x") is False
    assert _has_unstable_repr(Payload(value=1)) is False
    assert _has_unstable_repr(None) is False


def test_unstable_key_argument_is_reported_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    builder = _make_key_builder(_takes_object, "t:{thing}")

    builder((Opaque(),), {})
    builder((Opaque(),), {})

    assert capsys.readouterr().err.count("has no __str__/__repr__") == 1


#
# Model inference from the return annotation
#


def test_model_is_inferred_from_return_annotation() -> None:
    async def load() -> Payload: ...

    assert _infer_model(load) is Payload


def test_model_is_inferred_through_optional() -> None:
    async def load() -> Payload | None: ...

    assert _infer_model(load) is Payload


def test_ambiguous_union_infers_nothing() -> None:
    async def load() -> Payload | Other: ...

    assert _infer_model(load) is None


def test_non_model_annotations_infer_nothing() -> None:
    async def as_dict() -> dict[str, Any]: ...
    async def unannotated(): ...

    assert _infer_model(as_dict) is None
    assert _infer_model(unannotated) is None


def test_unresolvable_annotation_infers_nothing() -> None:
    """A forward ref that never resolves must not blow up decoration."""

    async def load() -> "NeverDefined": ...  # type: ignore[name-defined]  # noqa: F821

    assert _infer_model(load) is None


#
# Serialization
#


def test_model_round_trip_preserves_every_field() -> None:
    payload = Payload(value=1, label="default")

    restored = _deserialize(_as_bytes(_serialize(payload, Payload)), Payload)

    assert restored == payload
    assert restored.label == "default"


def test_model_round_trip_preserves_datetimes() -> None:
    class Event(BaseModel):
        at: dt.datetime

    event = Event(at=dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.UTC))

    assert _deserialize(_as_bytes(_serialize(event, Event)), Event) == event


def test_model_payloads_are_dumped_in_full() -> None:
    """set_json() drops defaults; a cache must not, or a later change of a
    default would silently rewrite values already stored."""
    assert b'"label":"default"' in _as_bytes(
        _serialize(Payload(value=1), Payload)
    ).replace(b" ", b"")


def test_none_round_trips_under_an_optional_model() -> None:
    assert _deserialize(_as_bytes(_serialize(None, Payload)), Payload) is None


def test_bytes_mode_round_trips_verbatim() -> None:
    assert (
        _deserialize(_as_bytes(_serialize(b"\x00raw", "bytes")), "bytes") == b"\x00raw"
    )


def test_bytes_mode_rejects_non_bytes() -> None:
    with pytest.raises(TypeError, match="expects a bytes-like result"):
        _serialize({"not": "bytes"}, "bytes")


def test_plain_json_round_trip() -> None:
    assert _deserialize(_as_bytes(_serialize({"a": [1, 2]}, None)), None) == {
        "a": [1, 2]
    }


def test_malformed_payload_raises_a_catchable_error() -> None:
    """The decorator treats these as a miss, so they must be ValueError/TypeError."""
    with pytest.raises((ValueError, TypeError)):
        _deserialize(b"not json", None)


def test_payload_from_an_older_model_raises_a_catchable_error() -> None:
    class Grown(BaseModel):
        value: int
        added_later: str

    with pytest.raises((ValueError, TypeError)):
        _deserialize(b'{"value": 1}', Grown)


#
# Fault tolerance: a broken cache degrades to a miss, it never breaks the call
#


def _always_raises(exc: Exception) -> Any:
    async def raiser(*args: Any, **kwargs: Any) -> Any:
        raise exc

    return raiser


@pytest.mark.parametrize(
    "error",
    [
        RedisConnectionError("connection closed by server"),
        RedisTimeoutError("timed out"),
        # What Redis.connect() itself raises when the pool cannot be reached.
        ConnectionError("Redis is not connected"),
        OSError("network unreachable"),
    ],
    ids=["redis-connection", "redis-timeout", "builtin-connection", "os-error"],
)
async def test_unreachable_redis_on_read_still_returns_a_result(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    calls = 0

    @redis.cached(ns="t", key="k:{x}")
    async def load(x: int) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"x": x}

    monkeypatch.setattr(redis, "get", _always_raises(error))
    monkeypatch.setattr(redis, "set", _always_raises(error))

    assert await load(1) == {"x": 1}
    assert calls == 1


async def test_unreachable_redis_on_write_still_returns_a_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @redis.cached(ns="t", key="k:{x}")
    async def load(x: int) -> dict[str, Any]:
        return {"x": x}

    async def missing(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(redis, "get", missing)
    monkeypatch.setattr(redis, "set", _always_raises(RedisError("write rejected")))

    assert await load(1) == {"x": 1}


async def test_unserializable_result_is_returned_uncached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """json_dumps raises TypeError here; the caller should never see it."""
    stored: list[Any] = []

    async def missing(*args: Any, **kwargs: Any) -> None:
        return None

    async def record(*args: Any, **kwargs: Any) -> None:
        stored.append(args)

    monkeypatch.setattr(redis, "get", missing)
    monkeypatch.setattr(redis, "set", record)

    @redis.cached(ns="t", key="k:{x}")
    async def load(x: int) -> Any:
        return {"opaque": Opaque()}

    result = await load(1)

    assert isinstance(result["opaque"], Opaque)
    assert stored == []


async def test_corrupt_payload_is_discarded_and_recomputed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def corrupt(*args: Any, **kwargs: Any) -> bytes:
        return b"}{ not json"

    async def noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(redis, "get", corrupt)
    monkeypatch.setattr(redis, "set", noop)

    @redis.cached(ns="t", key="k:{x}")
    async def load(x: int) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"x": x}

    assert await load(1) == {"x": 1}
    assert calls == 1


async def test_caching_a_model_without_one_warns_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def missing(*args: Any, **kwargs: Any) -> None:
        return None

    async def noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(redis, "get", missing)
    monkeypatch.setattr(redis, "set", noop)

    # No model= and an annotation nothing can be inferred from.
    @redis.cached(ns="t", key="k:{x}")
    async def load(x: int) -> Any:
        return Payload(value=x)

    await load(1)
    await load(2)

    assert capsys.readouterr().err.count("will return plain dicts") == 1


async def _sample(user_id: int, verbose: bool = False) -> dict[str, Any]:
    return {"id": user_id, "verbose": verbose}


async def _takes_object(thing: Any) -> Any:
    return thing


def _as_bytes(value: str | bytes) -> bytes:
    return value.encode() if isinstance(value, str) else value
