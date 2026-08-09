import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "packaging"))

import release_version as rv  # noqa: E402


# The four cases that motivate having this module at all. Each one is a place
# where doing the arithmetic by hand plausibly goes wrong.
@pytest.mark.parametrize(
    "current,kind,expected",
    [
        ("0.9.0", "minor", "0.10.0"),   # not 1.0.0
        ("1.2.9", "patch", "1.2.10"),   # not 1.3.0
        ("1.2.3", "minor", "1.3.0"),    # patch resets
        ("0.0.9", "major", "1.0.0"),    # minor and patch both reset
        ("0.0.0", "patch", "0.0.1"),
        ("0.0.0", "minor", "0.1.0"),
        ("0.0.0", "major", "1.0.0"),
    ],
)
def test_bump(current, kind, expected):
    assert rv.bump(current, kind) == expected


def test_bump_rejects_unknown_kind():
    with pytest.raises(rv.VersionError):
        rv.bump("0.0.0", "prerelease")


@pytest.mark.parametrize(
    "bad",
    ["1.2", "v1.2.3", "1.2.3-rc1", "1.2.3.4", "", "one.two.three", "1.2.3 "],
)
def test_parse_rejects_anything_but_three_plain_numbers(bad):
    with pytest.raises(rv.VersionError):
        rv.parse(bad)


def test_parse_accepts_multi_digit_components():
    assert rv.parse("10.20.30") == (10, 20, 30)


def test_is_newer_compares_numerically_not_as_strings():
    # The whole point: "0.10.0" > "0.9.0" is False for strings.
    assert "0.10.0" < "0.9.0"
    assert rv.is_newer("0.10.0", "0.9.0")


def test_is_newer_is_false_for_equal_and_older():
    assert not rv.is_newer("1.0.0", "1.0.0")
    assert not rv.is_newer("0.9.9", "1.0.0")


def test_read_current_matches_the_shipped_version_module():
    from loot_player.version import __version__

    assert rv.read_current() == __version__


def test_write_current_roundtrips_and_preserves_the_docstring(tmp_path):
    target = tmp_path / "version.py"
    target.write_text('"""Docstring stays."""\n\n__version__ = "0.0.0"\n')

    rv.write_current("1.2.3", path=target)

    assert rv.read_current(path=target) == "1.2.3"
    assert '"""Docstring stays."""' in target.read_text()


def test_write_current_refuses_junk(tmp_path):
    target = tmp_path / "version.py"
    original = '__version__ = "0.0.0"\n'
    target.write_text(original)

    with pytest.raises(rv.VersionError):
        rv.write_current("v1.2.3", path=target)

    assert target.read_text() == original


def test_cli_newer_exit_codes():
    assert rv.main(["newer", "0.10.0", "0.9.0"]) == 0
    assert rv.main(["newer", "0.9.0", "0.10.0"]) == 1


def test_cli_reports_bad_input_without_traceback(capsys):
    assert rv.main(["newer", "nonsense", "0.0.0"]) == 2
    assert "error:" in capsys.readouterr().err
