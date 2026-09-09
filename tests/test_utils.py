import datetime as dt
import uuid

import pytest

import nx
from nx.utils import (
    clean_doc,
    create_uuid,
    hash_data,
    indent,
    json_dumps,
    json_loads,
    normalize_uuid,
    slugify,
)

HEX_UUID = "6fa459ea9dc94ff8b3ba2e0e55b17d1e"
HYPHEN_UUID = "6fa459ea-9dc9-4ff8-b3ba-2e0e55b17d1e"


#
# normalize_uuid / create_uuid
#


@pytest.mark.parametrize("value", [HEX_UUID, HYPHEN_UUID, uuid.UUID(HEX_UUID)])
def test_normalize_uuid_to_hex(value: str | uuid.UUID) -> None:
    assert normalize_uuid(value, use_hyphens=False) == HEX_UUID


@pytest.mark.parametrize("value", [HEX_UUID, HYPHEN_UUID, uuid.UUID(HEX_UUID)])
def test_normalize_uuid_to_hyphenated(value: str | uuid.UUID) -> None:
    assert normalize_uuid(value, use_hyphens=True) == HYPHEN_UUID


def test_normalize_uuid_follows_config_by_default() -> None:
    nx.config.tool_uuid_use_hyphens = True
    assert normalize_uuid(HEX_UUID) == HYPHEN_UUID

    nx.config.tool_uuid_use_hyphens = False
    assert normalize_uuid(HYPHEN_UUID) == HEX_UUID


def test_normalize_uuid_allows_nulls_only_when_asked() -> None:
    assert normalize_uuid(None, allow_nulls=True) is None

    with pytest.raises(ValueError, match="Invalid UUID"):
        normalize_uuid(None)


@pytest.mark.parametrize("value", ["", "nope", HEX_UUID[:-1], HEX_UUID + "ff"])
def test_normalize_uuid_rejects_malformed_input(value: str) -> None:
    with pytest.raises(ValueError, match="Invalid UUID"):
        normalize_uuid(value)


def test_create_uuid_respects_the_requested_format() -> None:
    assert len(create_uuid(use_hyphens=False)) == 32
    assert len(create_uuid(use_hyphens=True)) == 36
    assert create_uuid() != create_uuid()


#
# hash_data
#


def test_hash_data_is_stable_and_distinguishing() -> None:
    assert hash_data({"a": 1}) == hash_data({"a": 1})
    assert hash_data({"a": 1}) != hash_data({"a": 2})
    assert len(hash_data("x")) == 64


@pytest.mark.parametrize("value", [1, 1.5, True, {"a": 1}, [1, 2], "text"])
def test_hash_data_accepts_json_serializable_types(value: object) -> None:
    assert len(hash_data(value)) == 64


#
# json helpers
#


def test_json_dumps_serializes_datetimes() -> None:
    moment = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.UTC)

    assert json_loads(json_dumps({"at": moment})) == {"at": moment.isoformat()}
    assert json_loads(json_dumps({"on": dt.date(2026, 1, 1)})) == {"on": "2026-01-01"}


def test_json_dumps_rejects_unserializable_objects() -> None:
    with pytest.raises(TypeError, match="not serializable"):
        json_dumps({"thing": object()})


def test_json_loads_accepts_bytes() -> None:
    """Redis hands back bytes, so this has to work."""
    assert json_loads(b'{"ok": true}') == {"ok": True}
    assert json_loads('{"ok": true}') == {"ok": True}


#
# slugify
#


def test_slugify_transliterates_and_joins() -> None:
    assert slugify("Příliš žluťoučký kůň") == "prilis-zlutoucky-kun"


def test_slugify_can_preserve_case() -> None:
    assert slugify("Hello World", lower=False) == "Hello-World"


def test_slugify_uses_the_requested_separator() -> None:
    assert slugify("hello world", separator="_") == "hello_world"


def test_slugify_drops_punctuation_and_collapses_gaps() -> None:
    assert slugify("Hello,   World!!! / Again") == "hello-world-again"


def test_slugify_can_return_a_set() -> None:
    assert slugify("beta alpha beta", make_set=True) == {"alpha", "beta"}


def test_slugify_honours_min_length() -> None:
    assert slugify("a bb ccc", min_length=2) == "bb-ccc"


def test_slugify_of_empty_input_is_empty() -> None:
    assert slugify("") == ""
    assert slugify("!!!") == ""


#
# text helpers
#


def test_indent_prefixes_every_line() -> None:
    assert indent("a\nb", 2) == "  a\n  b"


def test_clean_doc_normalizes_a_docstring() -> None:
    doc = """
        First line
        continues here.

        Second paragraph.
    """

    assert clean_doc(doc) == "First line continues here.\n\nSecond paragraph."


def test_clean_doc_collapses_extra_blank_lines() -> None:
    assert clean_doc("a\n\n\n\nb") == "a\n\nb"


def test_clean_doc_of_none_is_empty() -> None:
    assert clean_doc(None) == ""
