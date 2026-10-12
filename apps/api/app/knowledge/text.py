"""Deterministic text normalisation shared by the local embedder and lexical scoring."""

import re

WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    """a an and are as at be been but by can could did do does for from had has have how i if
    in into is it its may me might must my no not of on or our shall should so such than that
    the their them then there these they this those to us was we were what when where which
    who whom why will with would you your about any all also each other only own same some
    very just over under again further once here both few more most""".split()
)
SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ed", "es", "s")


def stem(word: str) -> str:
    """A tiny suffix stripper: 'requirements' and 'required' both become 'requir'."""
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            break
    if word.endswith("e") and len(word) > 4:
        word = word[:-1]
    return word


def terms(text: str) -> list[str]:
    """Lower-cased, stop-word-free, stemmed tokens in order (duplicates kept)."""
    return [stem(word) for word in WORD.findall(text.casefold()) if word not in STOPWORDS]


def keywords(text: str) -> list[str]:
    """Distinct terms in first-seen order: what a query asks about."""
    return list(dict.fromkeys(terms(text)))
