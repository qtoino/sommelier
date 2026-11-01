import subprocess
from pathlib import Path
from textwrap import dedent

import pytest

from sommelier import mine
from sommelier.mine import Extracted, detect_license_text, extract, license_ok, repo_license, scrub

BASE = dedent(
    """
    import os


    def helper(x):
        return x + 1


    class Pager:
        size = 20

        def pages(self, total):
            return total // self.size + 1
    """
)


def test_extracts_the_single_changed_method() -> None:
    after = BASE.replace("total // self.size + 1", "-(-total // self.size)")
    ex = extract(BASE, after)
    assert isinstance(ex, Extracted)
    assert ex.name == "Pager.pages"
    assert ex.before.startswith("def pages(self, total):")
    assert "-(-total // self.size)" in ex.after
    assert "class Pager" in ex.module_context and "import os" in ex.module_context


@pytest.mark.parametrize(
    ("after", "reason"),
    [
        (BASE.replace("return x + 1", "return x + 1  # note"), "0 functions changed"),
        (BASE.replace("x + 1", "x + 2").replace("+ 1\n", "+ 2\n"), "2 functions changed"),
        (
            BASE.replace("size = 20", "size = 25").replace("// self.size + 1", "// self.size"),
            "module-level",
        ),
        (
            BASE.replace("def pages(self, total)", "def pages(self, total: int) -> int"),
            "annotation",
        ),
        (BASE.replace("(x):\n    return x + 1", "(y):\n    return y + 1"), "rename"),
        (BASE + "\n\ndef extra():\n    pass\n", "added or removed"),
    ],
)
def test_rejects(after: str, reason: str) -> None:
    result = extract(BASE, after)
    assert isinstance(result, str) and reason in result


def test_rejects_message_only_and_long_functions() -> None:
    before = 'def f(x):\n    if x < 0:\n        raise ValueError("bad")\n    return x\n'
    assert extract(before, before.replace('"bad"', '"x must be >= 0"')) == "string/message-only"
    body = "".join(f"    y{i} = {i}\n" for i in range(70))
    long_before = f"def g():\n{body}    return 0\n"
    assert extract(long_before, long_before.replace("return 0", "return 1")) == "function too long"


def test_rejects_deprecation_changes() -> None:
    before = "def f(x):\n    return x\n"
    after = 'def f(x):\n    warnings.warn("f is deprecated", DeprecationWarning)\n    return x\n'
    assert extract(before, after) == "deprecation/version change"


def test_scrub_removes_leaky_comments_only() -> None:
    src = dedent(
        '''
        def f(items):
            """Return the total.

            .. versionchanged:: 2.1
                Handles empty input.
            """
            # fix for #1234: empty list crashed
            if not items:
                return 0  # was wrong before
            url = "https://x/#123"  # compute total
            return sum(items)  # workaround
        '''
    ).lstrip()
    out = scrub(src)
    assert "#1234" not in out and "was wrong" not in out and "workaround" not in out
    assert "versionchanged" not in out and "Handles empty input" not in out
    assert "# compute total" in out and '"https://x/#123"' in out
    assert "return 0\n" in out and "return sum(items)\n" in out
    compile(out, "<scrubbed>", "exec")


def test_scrub_pair_drops_comments_only_one_side_has() -> None:
    before = "def f(xs):\n    # sum the inputs\n    return sum(xs)\n"
    after = (
        "def f(xs):\n    # sum the inputs\n"
        "    xs = [x for x in xs if x]  # skip empties to avoid a crash\n"
        "    # explain the change\n    return sum(xs)\n"
    )
    b, a = mine.scrub_pair(before, after)
    assert b == before
    assert "# sum the inputs" in a and "skip empties" not in a and "explain the change" not in a
    assert "xs = [x for x in xs if x]\n" in a


def test_scrub_pair_drops_docstrings_only_when_they_differ() -> None:
    same = 'def f(x):\n    """Return x."""\n    return x\n'
    assert mine.scrub_pair(same, same.replace("return x\n", "return x or 0\n"))[0] == same
    b, a = mine.scrub_pair(same, 'def f(x):\n    """Return x, or 0."""\n    return x or 0\n')
    assert b == "def f(x):\n    return x\n"
    assert a == "def f(x):\n    return x or 0\n"


def test_license_text_detection() -> None:
    assert detect_license_text("Permission is hereby granted, free of charge, to any") == "MIT"
    bsd = "Redistribution and use in source and binary forms ... Neither the name of"
    assert detect_license_text(bsd) == "BSD-3-Clause"
    assert (
        detect_license_text("Redistribution and use in source and binary forms") == "BSD-2-Clause"
    )
    assert detect_license_text("Apache License\n Version 2.0, January 2004") == "Apache-2.0"
    assert detect_license_text("GNU GENERAL PUBLIC LICENSE Version 3") == "copyleft"
    assert detect_license_text("All rights reserved.") is None


def test_license_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def api(spdx: str | None) -> None:
        monkeypatch.setattr(mine, "gh_get", lambda path: {"license": {"spdx_id": spdx}})

    api("MIT")
    assert license_ok(repo_license("a/b"))
    for bad in ("GPL-3.0", "AGPL-3.0", "LGPL-2.1", "MPL-2.0"):
        api(bad)
        assert not license_ok(repo_license("a/b"))
    api("NOASSERTION")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "README").write_text("hi")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "init")
    assert repo_license("a/b", tmp_path) is None  # unknown is rejected
    (tmp_path / "LICENSE.txt").write_text("Redistribution and use in source and binary forms")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "license")
    assert repo_license("a/b", tmp_path) == "BSD-2-Clause"
    (tmp_path / "LICENSE.txt").write_text("GNU LESSER GENERAL PUBLIC LICENSE")
    _git(tmp_path, "commit", "-qam", "relicense")
    assert not license_ok(repo_license("a/b", tmp_path))


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_find_candidates_in_a_real_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mine, "LOG_DIR", tmp_path / "logs")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "pager.py").write_text(BASE)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_pager.py").write_text("x = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    (tmp_path / "pager.py").write_text(
        BASE.replace("total // self.size + 1", "-(-total // self.size)")
    )
    (tmp_path / "tests" / "test_pager.py").write_text("x = 2\n")  # tests may change too
    _git(tmp_path, "commit", "-qam", "Fix page count at exact multiples (#42)")
    (tmp_path / "pager.py").write_text(BASE.replace("x + 1", "x + 3"))
    _git(tmp_path, "commit", "-qam", "Tweak helper")  # not fix-like: ignored

    found = mine.find_candidates("a/b", tmp_path, 5, 100, set(), lambda _: None)
    assert [c.func for c in found] == ["Pager.pages"]
    assert found[0].message.startswith("Fix page count")
