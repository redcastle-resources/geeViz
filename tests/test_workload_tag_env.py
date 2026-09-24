"""The env a workload tag was minted by has to be readable off the tag.

Earth Engine's ``goog-earth-engine-workload-tag`` label is per GCP
project, and every deployment of a tenant shares one project. So a
puller reads its own tags and its siblings' out of the same Cloud
Monitoring stream, with the tag as the only label to tell them apart.

While the mint produced a bare ``wl_<16hex>``, it could not: an
unrecognized hash looks exactly like a tag nobody registered
attribution for, and the puller's rule -- record what you cannot place
rather than drop it -- then banks the sibling's spend as
``unattributed``. Production absorbed 141 CDU of test's Earth Engine
usage that way.

These tests pin the two halves of the fix: the env is spelled out, and
a tag that does NOT spell it out still reads as "cannot say" rather
than as foreign. The second half is the one that matters most -- every
tag minted before this change returns empty, and treating empty as
someone else's would discard real money.
"""
import re

import pytest

from geeViz.eeAuth.tags import (
    build_workload_tag,
    env_of_workload_tag,
    mint_workload_tag,
)

SECRET = "test-secret"
# EE's own rule, from ee/_state.py.
EE_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,61}[a-z0-9]$")


def _parts(**over):
    base = {"user_sub": "1138", "session_id": "abc", "action": "run_code",
            "auth_mode": "adc", "tenant": "askterra", "env": "prod"}
    base.update(over)
    return base


def test_the_env_is_readable_off_the_minted_tag():
    tag = mint_workload_tag(_parts(), secret=SECRET)
    assert env_of_workload_tag(tag) == "prod"


def test_test_and_prod_are_distinguishable_without_a_lookup():
    """The whole point. Both tags are for the same person; a puller
    holding only the strings must still be able to reject the other."""
    prod = mint_workload_tag(_parts(env="prod"), secret=SECRET)
    test = mint_workload_tag(_parts(env="test"), secret=SECRET)
    assert prod != test
    assert env_of_workload_tag(prod) == "prod"
    assert env_of_workload_tag(test) == "test"


def test_a_tag_minted_without_an_env_keeps_the_old_shape():
    """Standalone geeViz deployments define no env. They must keep
    minting what they always did, not acquire a spurious suffix."""
    parts = _parts()
    del parts["env"]
    tag = mint_workload_tag(parts, secret=SECRET)
    assert re.fullmatch(r"wl_[0-9a-f]{16}", tag), tag
    assert env_of_workload_tag(tag) == ""


def test_an_empty_env_is_treated_as_no_env():
    for value in ("", None, "   "):
        tag = mint_workload_tag(_parts(env=value), secret=SECRET)
        assert re.fullmatch(r"wl_[0-9a-f]{16}", tag), (value, tag)


def test_a_pre_env_tag_reads_as_cannot_say_not_as_foreign():
    """The load-bearing negative. A bare hash is what every tag minted
    before this change looks like, and 121 of them are already in
    ee_workload_tags. If ``env_of_workload_tag`` invented an answer for
    them, the puller would file real spend as another deployment's and
    drop it."""
    assert env_of_workload_tag("wl_0123456789abcdef") == ""
    assert env_of_workload_tag("") == ""
    assert env_of_workload_tag(None) == ""


def test_long_form_legacy_tags_are_not_mistaken_for_minted_ones():
    """A pre-v2 tag is full of ``__`` separators, so a naive "last
    segment" read would hand back a session id as an env name."""
    legacy = "agent__run_code__askterra__ian-example-com__db208a06"
    assert env_of_workload_tag(legacy) == ""


def test_the_prefix_every_caller_checks_still_holds():
    """``tag.startswith("wl_")`` gates the v2 path in the puller, the
    backfill script and geeView. The suffix must not break it."""
    tag = mint_workload_tag(_parts(), secret=SECRET)
    assert tag.startswith("wl_")


def test_the_tag_stays_a_legal_earth_engine_tag():
    for env in ("prod", "test", "dev", "staging-eu", "a" * 40):
        tag = mint_workload_tag(_parts(env=env), secret=SECRET)
        assert len(tag) <= 63, (env, len(tag), tag)
        assert EE_TAG_RE.match(tag), (env, tag)


def test_a_long_env_is_clamped_rather_than_truncated_by_the_length_limit():
    """Truncation at 63 chars would eat the END of the tag, which is
    where the env now lives -- so a long env could silently arrive
    looking like a different, shorter env. Clamping the part first keeps
    the failure in the part instead of the tag."""
    tag = mint_workload_tag(_parts(env="production-europe-west4"),
                            secret=SECRET)
    named = env_of_workload_tag(tag)
    assert named
    assert "production-europe-west4".startswith(named)
    assert len(tag) <= 63


def test_the_env_is_sanitized_like_any_other_part():
    tag = mint_workload_tag(_parts(env="PROD.eu"), secret=SECRET)
    assert env_of_workload_tag(tag) == "prod-eu"


def test_minting_is_still_deterministic():
    a = mint_workload_tag(_parts(), secret=SECRET)
    b = mint_workload_tag(_parts(), secret=SECRET)
    assert a == b


def test_the_env_is_still_part_of_the_hash_not_only_the_suffix():
    """Belt and braces: strip the suffixes and the hashes must still
    differ, so the suffix is a convenience for readers and not the only
    thing separating two deployments' tags."""
    prod = mint_workload_tag(_parts(env="prod"), secret=SECRET)
    test = mint_workload_tag(_parts(env="test"), secret=SECRET)
    assert prod.split("__")[0] != test.split("__")[0]


def test_a_whole_tag_must_not_be_fed_back_through_build_workload_tag():
    """Pinning a trap, not a feature.

    ``build_workload_tag`` sanitizes each part it is given, and part
    sanitization collapses runs of ``_`` so that ``__`` stays unambiguous
    as the separator. Hand it an already-joined tag and it eats the
    separator: ``wl_<hex>__prod`` comes back ``wl_<hex>_prod``, and the
    env is no longer parseable. The mint used to end with exactly that
    call as a belt-and-braces re-sanitize, which is why this is written
    down -- it silently swallowed the env on the first attempt at this
    change, and every test above passed except the ones reading the env.

    Build from parts. Never re-sanitize a finished tag.
    """
    tag = mint_workload_tag(_parts(), secret=SECRET)
    assert env_of_workload_tag(tag) == "prod"
    assert env_of_workload_tag(build_workload_tag(tag)) == ""
