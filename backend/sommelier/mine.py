"""Mine before/after pairs from bug-fix commits in permissively licensed repos.

license gate -> candidate commits (BugsInPy + fix-pattern regex) -> single changed function
(Python `ast`) -> filters -> leak scrubbing -> LLM judge -> Item.
Only the extractors here are Python-specific; nothing else assumes a language.
"""

import ast
import copy
import difflib
import io
import json
import os
import re
import subprocess
import textwrap
import tokenize
import tomllib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel
from sqlmodel import Session, select

from sommelier.llm import LLM, LLMError
from sommelier.models import Category, Difficulty, Item, validate_item

PERMISSIVE = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC"}
REPOS_DIR = Path(".cache/repos")
LOG_DIR = Path(".cache/mine")
BUGSINPY = REPOS_DIR / "soarsmu__BugsInPy"
BUGSINPY_ALIASES = {"httpie/cli": "httpie"}  # renamed since BugsInPy was published

MAX_FUNC_LINES = 60
MAX_CHANGED_LINES = 15

Log = Callable[[str], None]


# ---------------------------------------------------------------- repos & licenses


def allowlist(path: Path = Path("repos.toml")) -> list[str]:
    return list(tomllib.loads(path.read_text(encoding="utf-8"))["repos"])


def resolve_repo(name: str, repos: list[str]) -> str:
    """Accept 'owner/name' or just 'name' (case-insensitive) from the allowlist."""
    for repo in repos:
        if name.lower() in (repo.lower(), repo.split("/")[1].lower()):
            return repo
    raise ValueError(f"{name!r} is not in repos.toml")


def github_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None


def gh_get(path: str) -> Any:
    token = github_token()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # Renamed/transferred repos answer with a redirect.
    resp = httpx.get(
        f"https://api.github.com{path}", headers=headers, timeout=30, follow_redirects=True
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


_LICENSE_SIGNATURES = [
    ("Apache-2.0", [r"apache license", r"version 2\.0"]),
    ("MIT", [r"permission is hereby granted, free of charge"]),
    ("ISC", [r"permission to use, copy, modify, and(/or)? distribute this software"]),
    ("BSD-3-Clause", [r"redistribution and use in source and binary forms", r"neither the name"]),
    ("BSD-2-Clause", [r"redistribution and use in source and binary forms"]),
]
_COPYLEFT = re.compile(r"gnu (affero |lesser )?general public license|mozilla public license", re.I)


def detect_license_text(text: str) -> str | None:
    """Best-effort SPDX id from a LICENSE file. Copyleft text wins over everything."""
    if _COPYLEFT.search(text):
        return "copyleft"
    low = " ".join(text.lower().split())
    for spdx, patterns in _LICENSE_SIGNATURES:
        if all(re.search(p, low) for p in patterns):
            return spdx
    return None


def repo_license(repo: str, clone: Path | None = None) -> str | None:
    """SPDX id from the GitHub API, falling back to the LICENSE file in the clone."""
    try:
        data = gh_get(f"/repos/{repo}")
    except httpx.HTTPError:
        data = None
    spdx = ((data or {}).get("license") or {}).get("spdx_id")
    if spdx and spdx not in ("NOASSERTION", "OTHER"):
        return str(spdx)
    if clone and clone.is_dir():
        # Read from history, not the worktree: blobless clones are never checked out.
        names = git(clone, "ls-tree", "--name-only", "HEAD").splitlines()
        for name in sorted(n for n in names if re.match(r"(LICEN[CS]E|COPYING)", n, re.I)):
            found = detect_license_text(git(clone, "show", f"HEAD:{name}"))
            if found:
                return found
    return None


def license_ok(spdx: str | None) -> bool:
    return spdx in PERMISSIVE


# ---------------------------------------------------------------- git


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {out.stderr.strip()[:300]}")
    return out.stdout


def ensure_clone(repo: str) -> Path:
    dest = REPOS_DIR / repo.replace("/", "__")
    if not dest.is_dir():
        REPOS_DIR.mkdir(parents=True, exist_ok=True)
        # Blobless: history is local, file contents are fetched lazily for candidates only.
        subprocess.run(
            ["git", "clone", "-q", "--filter=blob:none", "--no-checkout",
             f"https://github.com/{repo}.git", str(dest)],
            check=True,
        )  # fmt: skip
    return dest


FIX_RE = re.compile(
    r"\b(fix(es|ed|ing)?|bug(s|fix)?|incorrect(ly)?|wrong(ly)?|crash(es|ed|ing)?"
    r"|regression|edge[- ]cases?)\b",
    re.I,
)
ISSUE_RE = re.compile(r"(?:#|\bgh-)(\d{1,6})\b")
NON_SOURCE_RE = re.compile(
    r"(^|/)(tests?|testing|docs?|doc_src|examples?|benchmarks?|asv_bench|scripts|ci)/"
    r"|(^|/)(test_[^/]*|[^/]*_tests?|conftest|setup|noxfile|conf)\.py$"
)


def bugsinpy_commits(repo: str) -> list[str]:
    """Fixed-commit ids BugsInPy lists for this repo (metadata only, no code is used)."""
    if not BUGSINPY.is_dir():
        return []
    target = BUGSINPY_ALIASES.get(repo.lower(), repo.split("/")[1].lower())
    shas: list[str] = []
    for info in (BUGSINPY / "projects").glob("*/project.info"):
        m = re.search(r'github_url="([^"]+)"', info.read_text(encoding="utf-8"))
        if not m or m.group(1).rstrip("/").split("/")[-1].lower() != target:
            continue
        for bug in sorted(info.parent.glob("bugs/*/bug.info")):
            fixed = re.search(r'fixed_commit_id="([0-9a-f]+)"', bug.read_text(encoding="utf-8"))
            if fixed:
                shas.append(fixed.group(1))
    return shas


def candidate_commits(clone: Path, repo: str, max_scan: int) -> Iterator[tuple[str, str]]:
    """Yield (sha, origin): BugsInPy fixes first, then fix-pattern commits, newest first."""
    seen = set()
    for sha in bugsinpy_commits(repo):
        seen.add(sha)
        yield sha, "bugsinpy"
    log = git(
        clone, "log", "--no-merges", f"--max-count={max_scan}", "--format=%H%x00%s", "--", "*.py"
    )
    for line in log.splitlines():
        sha, _, subject = line.partition("\x00")
        if sha not in seen and FIX_RE.search(subject):
            yield sha, "regex"


def single_source_file(clone: Path, sha: str) -> str | None:
    """The one non-test .py file modified by the commit, or None."""
    try:
        out = git(clone, "diff", "--name-status", "--no-renames", f"{sha}^", sha)
    except RuntimeError:
        return None
    rows = [ln.split("\t") for ln in out.splitlines() if ln.strip()]
    py = [r for r in rows if r[-1].endswith(".py") and not NON_SOURCE_RE.search(r[-1])]
    if len(py) != 1 or py[0][0] != "M":
        return None
    return py[0][-1]


# ---------------------------------------------------------------- python extraction


FuncNode = ast.FunctionDef | ast.AsyncFunctionDef


def functions(tree: ast.Module) -> dict[str, FuncNode]:
    """Top-level functions and methods by qualified name (nested defs belong to their parent)."""
    found: dict[str, FuncNode] = {}

    def visit(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                found[prefix + node.name] = node
            elif isinstance(node, ast.ClassDef):
                visit(node.body, f"{prefix}{node.name}.")
            elif isinstance(node, ast.If | ast.Try):  # e.g. `if sys.version_info >= ...:`
                visit(node.body, prefix)
                visit(node.orelse, prefix)

    visit(tree.body, "")
    return found


def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    first = body[0] if body else None
    is_doc = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
    if is_doc and isinstance(first.value.value, str):  # type: ignore[union-attr]
        return body[1:] or [ast.Pass()]
    return body


class _Normalizer(ast.NodeTransformer):
    def __init__(self, annotations: bool, strings: bool, rename: bool) -> None:
        self.annotations, self.strings, self.rename = annotations, strings, rename
        self.names: dict[str, str] = {}

    def _canon(self, name: str) -> str:
        return self.names.setdefault(name, f"v{len(self.names)}")

    def generic_visit(self, node: ast.AST) -> ast.AST:
        if hasattr(node, "body") and isinstance(node.body, list):
            node.body = _strip_docstring(node.body)
        return super().generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        if self.annotations:
            node.returns = None
        if self.rename:
            node.name = "f"
        return self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]  # noqa: N815

    def visit_arg(self, node: ast.arg) -> ast.AST:
        if self.annotations:
            node.annotation = None
        if self.rename:
            node.arg = self._canon(node.arg)
        return node

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if self.rename:
            node.id = self._canon(node.id)
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST | None:
        if self.annotations:
            if node.value is None:
                return None
            return self.visit(ast.Assign(targets=[node.target], value=node.value, lineno=0))
        return self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if self.strings and isinstance(node.value, str):
            return ast.Constant(value="")
        return node


def norm(
    node: ast.AST, *, annotations: bool = False, strings: bool = False, rename: bool = False
) -> str:
    """AST fingerprint ignoring docstrings, comments and layout (optionally more)."""
    tree = _Normalizer(annotations, strings, rename).visit(copy.deepcopy(node))
    return ast.dump(tree, include_attributes=False)


def skeleton(tree: ast.Module) -> str:
    """Module minus function bodies, imports and docstrings: catches changes outside functions."""

    class Hollow(ast.NodeTransformer):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
            return ast.Name(id=f"def:{node.name}")

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]  # noqa: N815

        def visit_Import(self, node: ast.Import) -> None:
            return None

        visit_ImportFrom = visit_Import  # type: ignore[assignment]  # noqa: N815

    return norm(Hollow().visit(copy.deepcopy(tree)))


def func_source(src: str, node: FuncNode) -> str:
    lines = src.splitlines()
    start = min([d.lineno for d in node.decorator_list] + [node.lineno]) - 1
    assert node.end_lineno is not None
    return textwrap.dedent("\n".join(lines[start : node.end_lineno])) + "\n"


def changed_lines(before: str, after: str) -> tuple[int, int]:
    """(removed, added) line counts between two snippets."""
    removed = added = 0
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0):
        if line.startswith("-") and not line.startswith("---"):
            removed += 1
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
    return removed, added


NOISE_RE = re.compile(
    r"__version__|DeprecationWarning|PendingDeprecationWarning|FutureWarning|warnings\.warn|deprecat",
    re.I,
)


@dataclass
class Extracted:
    name: str
    before: str
    after: str
    module_context: str


def extract(before_src: str, after_src: str) -> Extracted | str:
    """The single meaningfully changed function, or a rejection reason."""
    try:
        tb, ta = ast.parse(before_src), ast.parse(after_src)
    except SyntaxError:
        return "syntax error"
    fb, fa = functions(tb), functions(ta)
    if set(fb) != set(fa):
        return "functions added or removed"
    changed = [n for n in fb if norm(fb[n]) != norm(fa[n])]
    if len(changed) != 1:
        return f"{len(changed)} functions changed"
    if skeleton(tb) != skeleton(ta):
        return "module-level code changed"
    name = changed[0]
    nb, na = fb[name], fa[name]
    before, after = func_source(before_src, nb), func_source(after_src, na)
    reason = filter_pair(nb, na, before, after)
    if reason:
        return reason
    return Extracted(name, before, after, module_context(ta, name, na))


def filter_pair(nb: FuncNode, na: FuncNode, before: str, after: str) -> str | None:
    if max(len(before.splitlines()), len(after.splitlines())) > MAX_FUNC_LINES:
        return "function too long"
    removed, added = changed_lines(before, after)
    if not 1 <= max(removed, added) <= MAX_CHANGED_LINES:
        return f"changed lines out of range ({removed}-/{added}+)"
    if norm(nb, rename=True) == norm(na, rename=True):
        return "rename-only"
    if norm(nb, annotations=True) == norm(na, annotations=True):
        return "type-annotation-only"
    if norm(nb, strings=True) == norm(na, strings=True):
        return "string/message-only"
    diff = "\n".join(
        ln for ln in difflib.unified_diff(before.splitlines(), after.splitlines(), n=0)
    )
    if NOISE_RE.search(diff):
        return "deprecation/version change"
    return None


def module_context(tree: ast.Module, name: str, node: FuncNode) -> str:
    """Imports, the enclosing class header, and signatures of module functions it calls."""
    parts = [ast.unparse(n) for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
    if "." in name:
        cls_name = name.rsplit(".", 1)[0].split(".")[-1]
        for cls in ast.walk(tree):
            if isinstance(cls, ast.ClassDef) and cls.name == cls_name:
                attrs = [
                    ast.unparse(s) for s in cls.body if isinstance(s, ast.Assign | ast.AnnAssign)
                ]
                bases = ", ".join(ast.unparse(b) for b in cls.bases)
                parts.append(
                    f"class {cls.name}({bases}):\n" + "".join(f"    {a}\n" for a in attrs[:15])
                )
                break
    called = {
        c.func.id if isinstance(c.func, ast.Name) else c.func.attr
        for c in ast.walk(node)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name | ast.Attribute)
    }
    for qual, fn in functions(tree).items():
        if fn.name in called and qual != name:
            sig = ast.unparse(fn).split("\n", 1)[0]
            parts.append(f"{sig}  # {qual}")
    return "\n".join(parts)[:4000]


# ---------------------------------------------------------------- leak scrubbing


LEAK_RE = re.compile(
    r"\b(fix(e[sd])?|bugs?|buggy|workaround|regression|hack|was (wrong|broken|incorrect)"
    r"|used to|no longer|previously|issue|gh-\d+|bpo-\d+)\b|#\d+|https?://\S*/(issues|pull)/\d+",
    re.I,
)
_DIRECTIVE_RE = re.compile(r"^(\s*)\.\. (versionchanged|versionadded)::")


def comments(src: str) -> set[str]:
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError):
        return set()
    return {t.string.strip() for t in toks if t.type == tokenize.COMMENT}


def scrub_pair(before: str, after: str) -> tuple[str, str]:
    """Scrub both versions. A comment present in only one version is itself a tell (fixes
    usually add one explaining themselves), so only comments shared by both survive."""
    shared = comments(before) & comments(after)

    def leaky(text: str) -> bool:
        return text.strip() not in shared or bool(LEAK_RE.search(text))

    before, after = scrub(before, leaky), scrub(after, leaky)
    # Same idea for docstrings: a reworded docstring marks the newer version.
    if _docstring(before) != _docstring(after):
        before, after = _drop_docstring(before), _drop_docstring(after)
    return before, after


def _docstring_node(src: str) -> ast.Expr | None:
    try:
        fn = ast.parse(src).body[0]
    except (SyntaxError, IndexError):
        return None
    if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) or len(fn.body) < 2:
        return None
    first = fn.body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        return first if isinstance(first.value.value, str) else None
    return None


def _docstring(src: str) -> str | None:
    node = _docstring_node(src)
    return ast.get_docstring(ast.parse(src).body[0], clean=False) if node else None  # type: ignore[arg-type]


def _drop_docstring(src: str) -> str:
    node = _docstring_node(src)
    if node is None or node.end_lineno is None:
        return src
    lines = src.splitlines()
    return "\n".join(lines[: node.lineno - 1] + lines[node.end_lineno :]) + "\n"


def scrub(src: str, leaky: Callable[[str], object] = LEAK_RE.search) -> str:
    """Drop comments that give the answer away, plus versionchanged/added docstring notes.

    Code is otherwise untouched. Comments are found with `tokenize`, so '#' inside strings
    is safe.
    """
    lines = src.splitlines()
    cuts: dict[int, int] = {}  # 0-based line -> column where a leaky comment starts
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT and leaky(tok.string):
                cuts[tok.start[0] - 1] = tok.start[1]
    except (tokenize.TokenError, IndentationError):
        return src
    out: list[str] = []
    skip_indent: int | None = None
    for i, line in enumerate(lines):
        if skip_indent is not None:
            if not line.strip() or len(line) - len(line.lstrip()) > skip_indent:
                continue
            skip_indent = None
        m = _DIRECTIVE_RE.match(line)
        if m:
            skip_indent = len(m.group(1))
            continue
        if i in cuts:
            kept = line[: cuts[i]].rstrip()
            if not kept.strip():
                continue
            line = kept
        out.append(line)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- judge


class Verdict(BaseModel):
    accept: bool
    reason: str
    category: Category | None = None
    difficulty: Difficulty | None = None
    prompt: str | None = None
    context_code: str | None = None
    explanation: str | None = None
    tell: str | None = None


JUDGE_SYSTEM = """\
You curate items for Sommelier, a trainer where experienced engineers see two versions of the \
same function side by side (unlabelled, random order) and must pick the better one, then read \
an explanation. You are given a real bug-fix commit: the function BEFORE and AFTER the fix.

Accept only if ALL hold:
1. AFTER is a real improvement in correctness, safety, performance, or clarity (not style, \
not a refactor that only moves code, not a behaviour change that is merely different).
2. A sharp reviewer could plausibly tell which is better from the two functions plus a small \
context snippet, WITHOUT the rest of the repository, the test suite, or project history.
3. The difference matters in production and teaches a reusable lesson.
4. Neither version contains a comment, docstring, or name that gives the answer away.
Prefer fewer, sharper items. A great item makes an experienced engineer hesitate a few \
seconds. Reject trivial typo fixes, pure error-message changes, framework-internal plumbing \
that needs deep project knowledge, and changes whose correctness depends on unseen callers.

If accepting, write:
- prompt: one or two neutral sentences of context shown BEFORE answering, e.g. "Both versions \
of `parse_range` parse a byte range from an HTTP header." Never hint which is better, never \
mention bugs, fixes, versions, before/after, or old/new.
- context_code: the minimum surrounding code needed to judge (imports, a class header, helper \
signatures), or null. Must not reveal the answer.
- category: one of correctness, edge-case, security, performance, readability, api-design, \
sql-and-schema.
- difficulty: easy | medium | hard for an experienced engineer.
- explanation: 3-6 sentences. Refer to "the fixed version" and "the original version", never \
A/B or left/right. Say concretely what input or situation breaks the original and why the \
fixed version handles it. End by noting the fixed version is better, not necessarily perfect.
- tell: one sentence a reviewer can carry into real code reviews, in the form "Whenever you \
see X, check Y."

Reply with JSON only: {"accept": bool, "reason": str, "category": ..., "difficulty": ..., \
"prompt": ..., "context_code": ..., "explanation": ..., "tell": ...}. When rejecting, only \
accept and reason are needed.
"""


@dataclass
class Candidate:
    repo: str
    sha: str
    path: str
    origin: str
    message: str
    func: str
    before: str
    after: str
    module_context: str
    issue_url: str | None = None
    issue_text: str | None = None

    @property
    def growth(self) -> int:
        return len(self.after.splitlines()) - len(self.before.splitlines())


def judge_prompt(c: Candidate) -> str:
    diff = "".join(
        difflib.unified_diff(
            c.before.splitlines(True), c.after.splitlines(True), "before", "after", n=3
        )
    )
    issue = f"\nLINKED ISSUE/PR ({c.issue_url}):\n{c.issue_text}\n" if c.issue_text else ""
    return (
        f"REPO: {c.repo}\nFILE: {c.path}\nFUNCTION: {c.func}\n\n"
        f"COMMIT MESSAGE:\n{c.message.strip()[:2000]}\n{issue}\n"
        f"MODULE CONTEXT (imports, class header, called helpers):\n{c.module_context}\n\n"
        f"BEFORE:\n{c.before}\nAFTER:\n{c.after}\nDIFF:\n{diff}"
    )


def linked_issue(repo: str, message: str) -> tuple[str | None, str | None]:
    m = ISSUE_RE.search(message)
    if not m:
        return None, None
    url = f"https://github.com/{repo}/issues/{m.group(1)}"
    try:
        data = gh_get(f"/repos/{repo}/issues/{m.group(1)}")
    except httpx.HTTPError:
        return url, None
    if not data:
        return None, None
    return data.get("html_url", url), f"{data.get('title', '')}\n{(data.get('body') or '')[:1500]}"


def to_item(c: Candidate, v: Verdict, spdx: str) -> dict[str, Any]:
    return validate_item(
        {
            "language": "python",
            "category": v.category,
            "difficulty": v.difficulty or "medium",
            "prompt": v.prompt,
            "context_code": v.context_code or None,
            "version_good": c.after,
            "version_bad": c.before,
            "is_tradeoff": False,
            "explanation": v.explanation,
            "tell": v.tell,
            "source_type": "mined",
            "repo": c.repo,
            "commit_sha": c.sha,
            "commit_url": f"https://github.com/{c.repo}/commit/{c.sha}",
            "license_spdx": spdx,
            "original_path": c.path,
            "commit_message": c.message.strip(),
            "linked_issue_url": c.issue_url,
            "generator_model": None,
        }
    )


# ---------------------------------------------------------------- orchestration


def find_candidates(
    repo: str, clone: Path, want: int, max_scan: int, skip: set[str], log: Log
) -> list[Candidate]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    rejects = (LOG_DIR / f"{repo.replace('/', '__')}.rejects.jsonl").open("a", encoding="utf-8")
    found: list[Candidate] = []
    scanned = 0
    for sha, origin in candidate_commits(clone, repo, max_scan):
        if len(found) >= want:
            break
        if sha in skip:
            continue
        scanned += 1
        path = single_source_file(clone, sha)
        if path is None:
            continue  # cheap tree-only check; not worth logging
        try:
            before_src = git(clone, "show", f"{sha}^:{path}")
            after_src = git(clone, "show", f"{sha}:{path}")
        except RuntimeError:
            continue
        ex = extract(before_src, after_src)
        if isinstance(ex, str):
            rejects.write(
                json.dumps({"sha": sha, "path": path, "stage": "extract", "reason": ex}) + "\n"
            )
            continue
        before, after = scrub_pair(ex.before, ex.after)
        try:
            ast.parse(before), ast.parse(after)
        except SyntaxError:
            continue
        if before.strip() == after.strip():
            continue
        message = git(clone, "log", "-1", "--format=%B", sha)
        found.append(
            Candidate(repo, sha, path, origin, message, ex.name, before, after, ex.module_context)
        )
        log(f"  candidate {sha[:10]} {path}::{ex.name} ({origin}, {found[-1].growth:+d} lines)")
    rejects.close()
    log(f"  scanned {scanned} commits, {len(found)} candidates")
    return found


def mine_repo(
    session: Session,
    llm: LLM,
    name: str,
    limit: int,
    max_scan: int = 4000,
    log: Log = print,
) -> int:
    """Mine up to `limit` accepted items from one repo. Returns how many were added."""
    repo = resolve_repo(name, allowlist())
    clone = ensure_clone(repo)
    spdx = repo_license(repo, clone)
    if not license_ok(spdx):
        log(f"{repo}: license {spdx or 'unknown'} is not permissive; skipped")
        return 0
    log(f"{repo}: {spdx}")
    known = set(session.exec(select(Item.commit_sha).where(Item.repo == repo)).all())
    judged = LOG_DIR / f"{repo.replace('/', '__')}.judged.jsonl"
    done = (
        {json.loads(ln)["sha"] for ln in judged.read_text().splitlines()}
        if judged.exists()
        else set()
    )
    candidates = find_candidates(
        repo, clone, limit * 5, max_scan, {s for s in known if s} | done, log
    )
    # Shape-bias countermeasure: try fixes that don't grow the function first.
    candidates.sort(key=lambda c: (c.growth > 2, c.origin != "bugsinpy"))
    added = 0
    for c in candidates:
        if added >= limit:
            break
        c.issue_url, c.issue_text = linked_issue(repo, c.message)
        try:
            verdict = llm.ask_model("judge", JUDGE_SYSTEM, judge_prompt(c), Verdict)
        except LLMError as e:
            log(f"  {c.sha[:10]} judge error: {e}")
            continue
        if verdict is None:
            log(f"  [dry-run] would judge {c.sha[:10]} {c.func}")
            continue
        with judged.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"sha": c.sha, "func": c.func, **verdict.model_dump()}) + "\n")
        if not verdict.accept:
            log(f"  reject {c.sha[:10]} {c.func}: {verdict.reason[:120]}")
            continue
        try:
            item = Item(**to_item(c, verdict, spdx or ""))
        except ValueError as e:
            log(f"  invalid verdict for {c.sha[:10]}: {e}")
            continue
        session.add(item)
        session.commit()
        added += 1
        log(f"  ACCEPT {c.sha[:10]} {c.func} -> {verdict.category}/{verdict.difficulty}")
    return added
