import string
from typing import Literal, overload

import unidecode

SLUG_WHITELIST = string.ascii_letters + string.digits
SLUG_SEPARATORS = " ,./\\;:!|*^#@~+-_="


@overload
def slugify(
    input_string: str,
    *,
    separator: str = "-",
    lower: bool = True,
    make_set: Literal[False] = False,
    min_length: int = 1,
    slug_whitelist: str = SLUG_WHITELIST,
    split_chars: str = SLUG_SEPARATORS,
) -> str: ...


@overload
def slugify(
    input_string: str,
    *,
    separator: str = "-",
    lower: bool = True,
    make_set: Literal[True] = True,
    min_length: int = 1,
    slug_whitelist: str = SLUG_WHITELIST,
    split_chars: str = SLUG_SEPARATORS,
) -> set[str]: ...


def slugify(  # noqa: PLR0913
    input_string: str,
    *,
    separator: str = "-",
    lower: bool = True,
    make_set: bool = False,
    min_length: int = 1,
    slug_whitelist: str = SLUG_WHITELIST,
    split_chars: str = SLUG_SEPARATORS,
) -> str | set[str]:
    """Slugify a text string.

    This function removes transliterates input string to ASCII,
    removes special characters and use join resulting elements
    using specified separator.

    Args:
        input_string (str):
            Input string to slugify

        separator (str):
            A string used to separate returned elements (default: "-")

        lower (bool):
            Convert to lower-case (default: True)

        make_set (bool):
            Return "set" object instead of string

        min_length (int):
            Minimal length of an element (word)

        slug_whitelist (str):
            Characters allowed in the output
            (default: ascii letters, digits and the separator)

        split_chars (str):
            Set of characters used for word splitting (there is a sane default)

    """
    input_string = unidecode.unidecode(input_string)
    if lower:
        input_string = input_string.lower()
    input_string = "".join(
        [ch if ch not in split_chars else " " for ch in input_string]
    )
    input_string = "".join(
        [ch if ch in slug_whitelist + " " else "" for ch in input_string]
    )
    elements = [
        elm.strip() for elm in input_string.split(" ") if len(elm.strip()) >= min_length
    ]
    return set(elements) if make_set else separator.join(elements)
