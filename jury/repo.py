"""Fetch a hackathon repository and pack the whole thing into one prompt.

This is the reason the project exists: Kimi K3.1 Pro has a 1,048,576-token
context window, so a typical hackathon repo fits in a single request. No
chunking, no vector database, no retrieval step that might miss the one file
where the "AI pipeline" turns out to return a hard-coded answer.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import httpx

MAX_DOWNLOAD_BYTES = 150 * 1024 * 1024  # stop downloading past 150 MB
MAX_FILE_BYTES = 300_000  # skip single source files larger than this
DATA_FILE_KEEP_LINES = 20  # keep the header + a few rows of CSV/JSONL/... data files
MAX_TOTAL_CHARS = 3_400_000  # ~1M tokens of code; hard stop before packing more

GITHUB_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?"
    r"(?:/tree/([^?#]+?))?/?(?:[?#].*)?$"
)

SKIP_DIRS = {
    ".git", "node_modules", "bower_components", "vendor", "dist", "build", "out",
    ".next", ".nuxt", ".svelte-kit", "target", ".gradle", "coverage", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "venv", ".venv", "env",
    "site-packages", ".idea", ".vscode", ".terraform", "Pods", ".dart_tool", ".cache",
    ".ipynb_checkpoints", "__MACOSX",
}
SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock",
    "Cargo.lock", "composer.lock", "Gemfile.lock", "go.sum", "uv.lock", "bun.lockb",
    ".DS_Store", "Thumbs.db",
}
CODE_EXT = {
    ".py", ".ipynb", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte",
    ".java", ".kt", ".kts", ".scala", ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".hpp",
    ".cs", ".swift", ".m", ".rb", ".php", ".dart", ".lua", ".r", ".jl", ".sh", ".bash",
    ".zsh", ".ps1", ".sql", ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".md", ".mdx", ".rst", ".txt", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf",
    ".env.example", ".properties", ".gradle", ".xml", ".graphql", ".gql", ".proto",
    ".tf", ".hcl", ".dockerfile", ".json", ".prisma", ".sol", ".ex", ".exs", ".clj",
}
DATA_EXT = {".csv", ".tsv", ".jsonl", ".ndjson", ".geojson", ".log"}
SPECIAL_NAMES = {
    "Dockerfile", "Makefile", "Procfile", "Gemfile", "Rakefile", "Jenkinsfile",
    "README", "LICENSE", "requirements.txt", "Pipfile", ".gitignore", ".dockerignore",
    ".env.example", ".env.sample", ".env.template",
}
ENV_EXAMPLES = {".env.example", ".env.sample", ".env.template", ".env.dist"}

# Credentials are replaced before anything leaves the machine. Committed
# secrets are also a red flag worth showing to the jury, so we keep a record.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----")),
    ("OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
]
ASSIGNED_SECRET = re.compile(
    r"""(?ix)
    (\b[\w.-]*(?:api[_-]?key|apikey|secret|token|password|passwd|access[_-]?key)[\w.-]*\b
     ["']?\s*[:=]\s*)
    (["'])([^"'\s]{12,})\2
    """
)
PLACEHOLDER_HINTS = ("your", "xxx", "<", "example", "changeme", "placeholder", "dummy", "****", "here")

REDACTED = "[REDACTED_SECRET]"


@dataclass
class PackedFile:
    path: str
    text: str
    lines: int
    note: str = ""  # e.g. "truncated data file", "notebook: code cells only"


@dataclass
class Redaction:
    path: str
    line: int
    kind: str


@dataclass
class RepoPack:
    name: str  # "owner/repo" or uploaded file name
    ref: str  # commit SHA or branch, "" for uploads
    source_url: str
    files: list[PackedFile] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)
    redactions: list[Redaction] = field(default_factory=list)
    text: str = ""

    @property
    def chars(self) -> int:
        return len(self.text)

    @property
    def approx_tokens(self) -> int:
        # Code averages ~3.3 characters per token. Used only for previews:
        # the exact count comes from Kimi's token-estimate endpoint.
        return int(self.chars / 3.3)

    def file(self, path: str) -> PackedFile | None:
        """Find a packed file, forgiving small differences in how a model writes the path."""
        wanted = path.strip().strip("`")
        while wanted.startswith(("./", "/")):
            wanted = wanted[2:] if wanted.startswith("./") else wanted[1:]
        by_path = {f.path: f for f in self.files}
        if wanted in by_path:
            return by_path[wanted]
        lower = {f.path.lower(): f for f in self.files}
        if wanted.lower() in lower:
            return lower[wanted.lower()]
        tails = [f for f in self.files if f.path.endswith("/" + wanted) or wanted.endswith("/" + f.path)]
        return tails[0] if len(tails) == 1 else None


class RepoError(Exception):
    pass


# --------------------------------------------------------------------------- fetch

def parse_github_url(url: str) -> tuple[str, str, str | None]:
    m = GITHUB_RE.match(url.strip())
    if not m:
        raise RepoError("Expected a public GitHub URL like https://github.com/owner/repo")
    owner, repo, ref = m.group(1), m.group(2), m.group(3)
    return owner, repo, ref


def download_github_zip(url: str) -> tuple[bytes, str, str]:
    """Return (zip bytes, 'owner/repo', resolved commit SHA or ref)."""
    owner, repo, ref = parse_github_url(url)
    archive = f"https://github.com/{owner}/{repo}/archive/{ref or 'HEAD'}.zip"
    try:
        with (httpx.Client(follow_redirects=True, timeout=httpx.Timeout(120, connect=15)) as client,
              client.stream("GET", archive) as r):
            if r.status_code == 404:
                raise RepoError(f"{owner}/{repo} not found. Is the repository public?")
            r.raise_for_status()
            # github.com redirects HEAD to codeload.github.com/.../zip/<sha>
            resolved = str(r.url).rstrip("/").rsplit("/", 1)[-1]
            buf = io.BytesIO()
            for chunk in r.iter_bytes():
                buf.write(chunk)
                if buf.tell() > MAX_DOWNLOAD_BYTES:
                    raise RepoError("Repository archive is larger than 150 MB; upload a trimmed .zip instead.")
    except httpx.HTTPError as e:
        raise RepoError(f"Could not download {owner}/{repo}: {e}") from e
    return buf.getvalue(), f"{owner}/{repo}", resolved


# --------------------------------------------------------------------------- filter

def _classify(path: str, size: int) -> str | None:
    """Return a skip reason, or None if the file should be read."""
    p = PurePosixPath(path)
    if any(part in SKIP_DIRS for part in p.parts[:-1]):
        return "dependency/build folder"
    name = p.name
    if name in SKIP_FILES:
        return "lock file"
    if name.startswith(".env") and name not in ENV_EXAMPLES:
        return "env file (never sent)"
    if p.suffix in {".pem", ".key", ".p12", ".pfx"} or name in {"id_rsa", "id_ed25519"}:
        return "key file (never sent)"
    if name.endswith((".min.js", ".min.css", ".map")):
        return "minified/generated"
    suffix = p.suffix.lower()
    if suffix in DATA_EXT:
        return None
    if suffix in CODE_EXT or name in SPECIAL_NAMES or name.startswith("Dockerfile"):
        if size > MAX_FILE_BYTES:
            return f"too large ({size // 1024} KB)"
        return None
    if suffix == "":
        return None if size <= 64_000 else "binary or unknown"
    return "binary or unsupported type"


def _notebook_to_text(raw: str) -> tuple[str, str]:
    """Keep notebook cell sources, drop outputs (often megabytes of base64 images)."""
    try:
        nb = json.loads(raw)
    except json.JSONDecodeError:
        return raw, ""
    parts = []
    for i, cell in enumerate(nb.get("cells", []), 1):
        src = cell.get("source", "")
        src = "".join(src) if isinstance(src, list) else str(src)
        kind = cell.get("cell_type", "code")
        parts.append(f"# %% [cell {i}: {kind}]\n{src.rstrip()}\n")
    return "\n".join(parts), "notebook: cell sources only, outputs removed"


def _redact(path: str, text: str, out: list[Redaction]) -> str:
    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    def is_placeholder(value: str) -> bool:
        return any(h in value.lower() for h in PLACEHOLDER_HINTS)

    for kind, pat in SECRET_PATTERNS:
        def repl_pattern(m: re.Match[str], kind: str = kind) -> str:
            if is_placeholder(m.group(0)):
                return m.group(0)  # e.g. "sk-paste-your-key-here" in .env.example
            out.append(Redaction(path, line_of(m.start()), kind))
            return REDACTED

        text = pat.sub(repl_pattern, text)

    def repl(m: re.Match[str]) -> str:
        value = m.group(3)
        if value == REDACTED or is_placeholder(value):
            return m.group(0)
        if value.startswith(("os.", "process.", "${", "{{")):
            return m.group(0)
        out.append(Redaction(path, line_of(m.start()), "hard-coded credential"))
        return f"{m.group(1)}{m.group(2)}{REDACTED}{m.group(2)}"

    return ASSIGNED_SECRET.sub(repl, text)


def _read_entry(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> str | None:
    with zf.open(info) as fh:
        raw = fh.read(MAX_FILE_BYTES + 1)
    if b"\x00" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("latin-1")
        except UnicodeDecodeError:
            return None


def _sort_key(path: str) -> tuple[int, str]:
    """README and docs first, then manifests, then source: how a juror reads a repo."""
    p = PurePosixPath(path)
    name = p.name.lower()
    depth = len(p.parts)
    if name.startswith("readme"):
        return (0 if depth == 1 else 1, path)
    if p.suffix.lower() in {".md", ".mdx", ".rst"}:
        return (2, path)
    if name in {"requirements.txt", "package.json", "pyproject.toml", "dockerfile", "docker-compose.yml",
                "docker-compose.yaml", "cargo.toml", "go.mod", "pom.xml", "build.gradle"}:
        return (3, path)
    if p.suffix.lower() in DATA_EXT:
        return (9, path)
    return (5, path)


def pack_zip(data: bytes, name: str, ref: str = "", source_url: str = "") -> RepoPack:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise RepoError("Not a valid .zip archive") from e

    entries = [i for i in zf.infolist() if not i.is_dir()]
    # GitHub archives (and most hand-made zips) wrap everything in one top folder.
    tops = {i.filename.split("/", 1)[0] for i in entries}
    strip = len(tops) == 1 and all("/" in i.filename for i in entries)

    pack = RepoPack(name=name, ref=ref, source_url=source_url)
    total = 0
    for info in sorted(entries, key=lambda i: _sort_key(i.filename)):
        path = info.filename.split("/", 1)[1] if strip else info.filename
        if not path:
            continue
        reason = _classify(path, info.file_size)
        if reason:
            pack.skipped.append((path, reason))
            continue
        text = _read_entry(zf, info)
        if text is None:
            pack.skipped.append((path, "binary"))
            continue
        note = ""
        suffix = PurePosixPath(path).suffix.lower()
        if suffix == ".ipynb":
            text, note = _notebook_to_text(text)
        elif suffix in DATA_EXT or (suffix == ".json" and len(text) > 50_000):
            lines = text.splitlines()
            if len(lines) > DATA_FILE_KEEP_LINES:
                text = "\n".join(lines[:DATA_FILE_KEEP_LINES])
                note = f"data file: first {DATA_FILE_KEEP_LINES} of {len(lines)} lines"
        elif len(text) > MAX_FILE_BYTES:
            pack.skipped.append((path, "too large"))
            continue
        if sum(len(line) for line in text.splitlines()[:50]) > 50 * 1000:
            pack.skipped.append((path, "minified/generated"))
            continue
        if total + len(text) > MAX_TOTAL_CHARS:
            pack.skipped.append((path, "over the 1M-token budget"))
            continue
        text = _redact(path, text, pack.redactions)
        total += len(text)
        pack.files.append(PackedFile(path=path, text=text, lines=text.count("\n") + 1, note=note))

    if not pack.files:
        raise RepoError("No readable source files found in this repository.")
    pack.text = render_pack(pack)
    return pack


def render_pack(pack: RepoPack) -> str:
    tree = "\n".join(f.path + (f"  ({f.note})" if f.note else "") for f in pack.files)
    skipped = "\n".join(f"{p}  [{r}]" for p, r in pack.skipped[:300])
    more = f"\n... and {len(pack.skipped) - 300} more" if len(pack.skipped) > 300 else ""
    parts = [
        f'<repository name="{pack.name}" ref="{pack.ref}">',
        "<included_files>\n" + tree + "\n</included_files>",
        "<skipped_files>\n" + (skipped + more if skipped else "(none)") + "\n</skipped_files>",
    ]
    if pack.redactions:
        parts.append(
            f"<note>{len(pack.redactions)} likely credential(s) were committed to this repository and were "
            f"replaced with {REDACTED} before this review.</note>"
        )
    for f in pack.files:
        note = f' note="{f.note}"' if f.note else ""
        parts.append(f'<file path="{f.path}"{note}>\n{f.text}\n</file>')
    parts.append("</repository>")
    return "\n\n".join(parts)


def load_github(url: str) -> RepoPack:
    data, name, ref = download_github_zip(url)
    return pack_zip(data, name=name, ref=ref, source_url=url.strip())


def load_dir(path: str, name: str | None = None) -> RepoPack:
    """Pack a local folder (e.g. a submission received by email, or an eval fixture)."""
    from pathlib import Path

    root = Path(path).resolve()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(root.rglob("*")):
            if p.is_file() and not any(part in SKIP_DIRS for part in p.relative_to(root).parts):
                zf.write(p, f"{root.name}/{p.relative_to(root).as_posix()}")
    return pack_zip(buf.getvalue(), name=name or root.name, ref="", source_url=f"dir:{root.name}")


def load_zip_upload(data: bytes, filename: str) -> RepoPack:
    name = PurePosixPath(filename).stem
    return pack_zip(data, name=name, ref="", source_url=f"upload:{filename}")
