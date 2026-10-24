"""Local semantic code search over an indexed directory."""

from __future__ import annotations

import heapq
import math
import os
import sqlite3
from array import array
from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import httpx

from .config import DATA_DIR
from .errors import EmbedError as EmbedError
from .http import shared_client

DEFAULT_EMBED = "nomic-embed-text"
CHUNK_CHARS = 2000
CHUNK_OVERLAP = 240
MAX_FILE_BYTES = 1024 * 1024
EMBED_BATCH = 32

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "target",
    ".idea",
    ".vscode",
    "vendor",
}

IGNORED_EXT = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".zip",
    ".gz",
    ".tar",
    ".7z",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".mp3",
    ".mp4",
    ".mov",
    ".wasm",
    ".so",
    ".dylib",
    ".o",
    ".a",
    ".pyc",
    ".min.js",
    ".min.css",
}


@dataclass(frozen=True)
class SearchResult:
    path: str
    line: int
    text: str
    score: float


def _base(url: str) -> str:
    value = str(url or "").strip()
    return value if value.startswith("http") else f"http://{value}"


def embed(
    ollama_url: str,
    model: str,
    texts: list[str],
    timeout: float = 300.0,
) -> list[list[float]]:
    try:
        response = shared_client().post(
            f"{_base(ollama_url).rstrip('/')}/api/embed",
            json={"model": model, "input": texts},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise EmbedError(f"Ollama unreachable: {exc.__class__.__name__}") from exc
    if response.status_code != 200:
        raise EmbedError(f"embed HTTP {response.status_code}")
    try:
        vectors: list[list[float]] = response.json()["embeddings"]
    except (ValueError, KeyError, TypeError) as exc:
        raise EmbedError("malformed embedding response") from exc
    if len(vectors) != len(texts):
        raise EmbedError(f"expected {len(texts)} embeddings, got {len(vectors)}")
    return vectors


def pack(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def unpack(blob: bytes) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    return list(values)


def cosine(left: list[float], right: list[float]) -> float:
    """Cosine similarity; 0.0 when the vectors cannot be compared.

    A dimension mismatch used to raise ValueError out of the search. That
    happens in practice when the index was built with a different embedding
    model, and it turned "no match" into a crash.
    """
    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0 or norm_right == 0:
        return 0.0
    return dot / (norm_left * norm_right)


def chunk_text(
    text: str, max_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP
) -> list[tuple[int, str]]:
    """Split text into overlapping chunks tagged with their 1-based start line."""
    if not text.strip():
        return []
    if len(text) <= max_chars:
        return [(1, text)]
    chunks: list[tuple[int, str]] = []
    start = 0
    size = len(text)
    overlap = min(overlap, max(0, max_chars - 1))
    while start < size:
        end = min(start + max_chars, size)
        chunk = text[start:end]
        line = text.count("\n", 0, start) + 1
        chunks.append((line, chunk))
        if end >= size:
            break
        start = end - overlap
        if start <= 0:
            start = end
    return chunks


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:1024]


def iter_source_files(root: Path) -> Iterator[Path]:
    """Yield text source files, pruning ignored and hidden directories."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames if name not in IGNORED_DIRS and not name.startswith(".")
        )
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            path = Path(dirpath) / name
            if path.suffix.lower() in IGNORED_EXT:
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                with path.open("rb") as handle:
                    head = handle.read(1024)
            except OSError:
                continue
            if path.suffix.lower() != ".pdf" and _looks_binary(head):
                continue
            yield path


def index_path_for(root: Path) -> Path:
    key = sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]
    directory = DATA_DIR / "index"
    directory.mkdir(parents=True, exist_ok=True)
    name = (root.name or "root").replace("/", "-") + f"-{key}.sqlite"
    return directory / name


class IndexStore:
    def __init__(self, db_path: Path) -> None:
        from .safefile import ensure_private_dir, harden

        ensure_private_dir(db_path.parent)
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS chunks "
            "(id INTEGER PRIMARY KEY, path TEXT, line INTEGER, text TEXT, vec BLOB)"
        )
        self.conn.commit()
        harden(db_path)

    def clear(self) -> None:
        self.conn.execute("DROP TABLE IF EXISTS chunks")
        self.conn.execute(
            "CREATE TABLE chunks "
            "(id INTEGER PRIMARY KEY, path TEXT, line INTEGER, text TEXT, vec BLOB)"
        )

    def add(self, path: str, line: int, text: str, vector: list[float]) -> None:
        self.conn.execute(
            "INSERT INTO chunks(path, line, text, vec) VALUES (?, ?, ?, ?)",
            (path, line, text, pack(vector)),
        )

    def commit(self) -> None:
        self.conn.commit()

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return int(row[0]) if row else 0

    def search(self, vector: list[float], top: int = 5) -> list[SearchResult]:
        """Return the best matching chunks.

        Only the best few are kept in memory: the whole table is streamed
        through a bounded heap instead of being materialised as a list, so a
        large index costs a constant amount of RAM.
        """
        limit = max(1, top)
        best: list[tuple[float, str, int, str]] = []
        for path, line, text, blob in self.conn.execute("SELECT path, line, text, vec FROM chunks"):
            score = cosine(vector, unpack(blob))
            entry = (score, path, line, text)
            if len(best) < limit:
                heapq.heappush(best, entry)
            elif score > best[0][0]:
                heapq.heapreplace(best, entry)
        results = [
            SearchResult(path=path, line=line, text=text, score=score)
            for score, path, line, text in best
        ]
        results.sort(key=lambda result: result.score, reverse=True)
        return results

    def close(self) -> None:
        self.conn.close()


def search_query(
    ollama_url: str,
    db_path: Path,
    query: str,
    model: str = DEFAULT_EMBED,
    top: int = 5,
) -> list[SearchResult]:
    """Embed a query and return the top matching chunks from an existing index."""
    store = IndexStore(db_path)
    try:
        vector = embed(ollama_url, model, [query])[0]
        return store.search(vector, top=top)
    finally:
        store.close()


def build_index(
    root: Path,
    ollama_url: str,
    model: str = DEFAULT_EMBED,
    limit: int | None = None,
) -> tuple[int, int, IndexStore]:
    """Build an index without destroying the previous one on failure.

    The old implementation cleared the live database before the first
    embedding call. If Ollama was down (or the run was interrupted), the user
    was left with no index at all and ``knowledge roots`` still showing the
    previous counts. Build into a sibling file and swap it in only on success.
    """
    final_path = index_path_for(root)
    # A unique temp file per build: two indexes for the same root must not
    # share one `.tmp` and corrupt each other. The last successful build wins.
    temp_path = final_path.with_name(f"{final_path.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp")
    store = IndexStore(temp_path)
    files = 0
    chunks = 0
    batch: list[tuple[str, int, str]] = []

    def flush() -> None:
        nonlocal chunks
        if not batch:
            return
        vectors = embed(ollama_url, model, [text for _, _, text in batch])
        for (path, line, text), vector in zip(batch, vectors, strict=True):
            store.add(path, line, text, vector)
        store.commit()
        chunks += len(batch)
        batch.clear()

    try:
        for path in iter_source_files(root):
            if limit is not None and files >= limit:
                break
            try:
                if path.suffix.lower() == ".pdf":
                    from .pdf import read_pdf

                    text = read_pdf(path).combined_text()
                else:
                    text = path.read_text(encoding="utf-8", errors="replace")
            except (OSError, RuntimeError, ValueError):
                continue
            files += 1
            for line, chunk in chunk_text(text):
                batch.append((str(path), line, chunk))
                if len(batch) >= EMBED_BATCH:
                    flush()
        flush()
    except BaseException:
        store.close()
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    store.close()
    os.replace(temp_path, final_path)
    return files, chunks, IndexStore(final_path)
