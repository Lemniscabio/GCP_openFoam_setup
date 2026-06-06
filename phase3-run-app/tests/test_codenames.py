import re

from core.codenames import WORDLIST, is_valid_codename, suggest_unused

_RE = re.compile(r"^[a-z][a-z0-9]{1,9}$")  # wordlist entries are pure single words


def test_wordlist_is_large_and_clean():
    assert len(WORDLIST) >= 1000
    assert len(WORDLIST) == len(set(WORDLIST))        # unique
    assert all(_RE.match(w) for w in WORDLIST)        # one word, short, lowercase


def test_is_valid_codename():
    assert is_valid_codename("phoenix")
    assert is_valid_codename("wind-tunnel-v3")        # custom slug allowed
    assert not is_valid_codename("Phoenix")           # caps
    assert not is_valid_codename("wind tunnel")       # space
    assert not is_valid_codename("3phoenix")          # must start with a letter
    assert not is_valid_codename("a")                 # too short
    assert not is_valid_codename("x" * 40)            # too long


def test_suggest_unused_avoids_used():
    used = {WORDLIST[0], WORDLIST[1]}
    for _ in range(50):
        assert suggest_unused(used) not in used


def test_suggest_unused_exhaustion_appends_suffix():
    name = suggest_unused(set(WORDLIST))              # everything used
    assert name.endswith("-2") or re.match(r".+-\d+$", name)
    assert is_valid_codename(name)
