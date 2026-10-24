"""PDF reading and OCR for Sovereign Code.

PDFs are the most common way a model is asked to "read a document", and most
of them are either born-digital (text already present) or scanned (images of
text).  This module handles both fast and accurately:

* born-digital pages are extracted with Poppler's ``pdftotext`` (layout aware,
  sub-second for whole documents);
* scanned or image-only pages are rendered with ``pdftoppm`` and run through
  Tesseract OCR;
* every page can also be rendered to a PNG so a local vision model can review
  the page images directly.

The helpers are dependency-light: they shell out to the Poppler and Tesseract
binaries (``brew install poppler tesseract``) instead of pulling in a heavy
Python PDF stack, and they degrade cleanly when a binary is missing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .safefile import ensure_private_dir, harden, write_private_bytes

DEFAULT_DPI = 200
DEFAULT_LANG = "eng"
DEFAULT_PSM = 3
DEFAULT_MIN_TEXT_CHARS = 10
DEFAULT_TIMEOUT = 300


# --------------------------------------------------------------------------- #
# data types
# --------------------------------------------------------------------------- #


@dataclass
class PDFPage:
    """One page of a PDF."""

    number: int
    text: str = ""
    ocr_text: str = ""
    image_paths: list[str] = field(default_factory=list)
    image_base64: list[str] = field(default_factory=list)
    has_text: bool = False

    def combined_text(self) -> str:
        parts = [self.text.strip(), self.ocr_text.strip()]
        return "\n".join(p for p in parts if p)

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "text": self.text,
            "ocr_text": self.ocr_text,
            "combined_text": self.combined_text(),
            "image_paths": list(self.image_paths),
            "has_text": self.has_text,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


@dataclass
class PDFDocument:
    """A fully read PDF."""

    path: str
    page_count: int
    pages: list[PDFPage] = field(default_factory=list)
    text: str = ""
    ocr_text: str = ""
    images: list[str] = field(default_factory=list)
    image_base64: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def extract(self) -> str:
        return self.combined_text()

    def ocr(self) -> str:
        return self.ocr_text

    def render(self, **kwargs: Any) -> list[Path]:
        return render_pages(self.path, **kwargs)

    def to_text(self) -> str:
        if self.text:
            return self.text
        return self.ocr_text

    def combined_text(self) -> str:
        parts = [self.text.strip(), self.ocr_text.strip()]
        return "\n\n".join(p for p in parts if p)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "page_count": self.page_count,
            "pages": [p.to_dict() for p in self.pages],
            "text": self.text,
            "ocr_text": self.ocr_text,
            "combined_text": self.combined_text(),
            "images": list(self.images),
            "image_base64": list(self.image_base64),
            "metadata": dict(self.metadata),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __iter__(self) -> Any:
        return iter(self.pages)

    def __len__(self) -> int:
        return self.page_count

    def __contains__(self, item: Any) -> bool:
        haystack = self.combined_text().lower()
        if isinstance(item, str):
            return item.lower() in haystack
        return any(item == p for p in self.pages)

    def __str__(self) -> str:
        return self.combined_text()


# --------------------------------------------------------------------------- #
# binary helpers
# --------------------------------------------------------------------------- #


def _which(name: str) -> str | None:
    return shutil.which(name)


def available() -> dict[str, bool]:
    """Report which external helpers are installed."""
    return {
        "pdfinfo": _which("pdfinfo") is not None,
        "pdftotext": _which("pdftotext") is not None,
        "pdftoppm": _which("pdftoppm") is not None,
        "tesseract": _which("tesseract") is not None,
    }


def _require(binary: str) -> str:
    path = _which(binary)
    if path is None:
        raise RuntimeError(
            f"{binary} not found on PATH; install with `brew install poppler tesseract`"
        )
    return path


def _run(args: list[str], *, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"command timed out after {timeout}s: {' '.join(args)}") from exc


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# core operations
# --------------------------------------------------------------------------- #


def is_pdf(path: str | Path) -> bool:
    target = Path(path).expanduser()
    if not target.is_file():
        return False
    try:
        with target.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def page_count(path: str | Path) -> int:
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"not a file: {target}")
    _require("pdfinfo")
    result = _run(["pdfinfo", str(target)])
    if result.returncode != 0:
        raise RuntimeError(_decode(result.stderr).strip() or "pdfinfo failed")
    for line in _decode(result.stdout).splitlines():
        if line.lower().startswith("pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                continue
    raise RuntimeError("could not determine page count")


def extract_text(
    path: str | Path,
    *,
    layout: bool = True,
    first: int | None = None,
    last: int | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Extract born-digital text from a PDF (fast path)."""
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"not a file: {target}")
    _require("pdftotext")
    args = ["pdftotext"]
    if layout:
        args.append("-layout")
    if first is not None:
        args += ["-f", str(first)]
    if last is not None:
        args += ["-l", str(last)]
    args += [str(target), "-"]
    result = _run(args, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(_decode(result.stderr).strip() or "pdftotext failed")
    return _decode(result.stdout)


def extract_pages(path: str | Path, **kwargs: Any) -> list[str]:
    """Return one text string per page.

    Poppler separates pages with a form-feed (``\\f``) when extracting the
    whole document, so we can do a single ``pdftotext`` invocation instead of
    one process per page.  Falls back to the per-page path if the count cannot
    be determined.
    """
    layout = kwargs.pop("layout", True)
    first = kwargs.pop("first", None)
    last = kwargs.pop("last", None)
    timeout = kwargs.pop("timeout", DEFAULT_TIMEOUT)
    if first is not None or last is not None:
        count = page_count(path) if first is None and last is None else None
        if count is None:
            try:
                count = page_count(path)
            except RuntimeError:
                count = 1
        lo = first if first is not None else 1
        hi = last if last is not None else count
        return [
            extract_text(path, layout=layout, first=i, last=i, timeout=timeout)
            for i in range(lo, hi + 1)
        ]
    try:
        count = page_count(path)
    except RuntimeError:
        return [extract_text(path, layout=layout, timeout=timeout)]
    whole = extract_text(path, layout=layout, timeout=timeout)
    pages = whole.split("\f")
    # pdftotext emits a trailing empty page after the last form feed.
    while len(pages) > count and pages and pages[-1].strip() == "":
        pages.pop()
    while len(pages) < count:
        pages.append("")
    return pages[:count]


def needs_ocr(path: str | Path, *, min_chars: int = DEFAULT_MIN_TEXT_CHARS) -> bool:
    """Heuristic: is the document effectively image-only?"""
    try:
        text = extract_text(path)
    except RuntimeError:
        return True
    total = len("".join(text.split()))
    try:
        pages = page_count(path)
    except RuntimeError:
        pages = 1
    threshold = max(min_chars, min_chars * max(1, pages // 2))
    return total < threshold


def _page_number(path: Path) -> int | None:
    """The page number in a pdftoppm filename (``page-12.png`` -> 12)."""
    match = re.search(r"-(\d+)\.", path.name)
    return int(match.group(1)) if match else None


def _render_sort_key(path: Path) -> tuple[int, str]:
    """Sort rendered pages numerically: page-2 comes before page-10.

    A plain lexicographic sort puts ``page-10`` before ``page-2``, which made
    every consumer that indexes ``rendered[i]`` by page mis-attribute images
    on documents with ten or more pages.
    """
    number = _page_number(path)
    return (number if number is not None else 10**9, path.name)


def render_pages(
    path: str | Path,
    *,
    output_dir: str | Path | None = None,
    dpi: int = DEFAULT_DPI,
    fmt: str = "png",
    first: int | None = None,
    last: int | None = None,
    prefix: str = "page",
    timeout: int = DEFAULT_TIMEOUT,
) -> list[Path]:
    """Render PDF pages to images; return the list of image paths."""
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"not a file: {target}")
    _require("pdftoppm")
    managed = output_dir is None
    if output_dir is None:
        output_dir = DATA_DIR / "pdf" / "images" / _safe_stem(target)
    out = Path(output_dir).expanduser()
    if managed:
        ensure_private_dir(out)
    else:
        # A caller-supplied directory (``--out .``) belongs to the user; do
        # not chmod a whole project checkout to 0700 just to write images.
        out.mkdir(parents=True, exist_ok=True)
    # The default output directory is a deterministic per-document cache.
    # Without clearing the previous render, asking for pages 1-2 after pages
    # 5-6 returns four images and a vision review silently examines stale
    # pages. A caller-supplied directory is never cleared.
    if managed:
        for stale in out.glob(f"{prefix}-*.{fmt}"):
            try:
                stale.unlink()
            except OSError:
                pass
    stem = out / prefix
    args = ["pdftoppm", f"-{fmt}", "-r", str(dpi)]
    if first is not None:
        args += ["-f", str(first)]
    if last is not None:
        args += ["-l", str(last)]
    args += [str(target), str(stem)]
    result = _run(args, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(_decode(result.stderr).strip() or "pdftoppm failed")
    pattern = f"{prefix}-*.{fmt}"
    files = sorted(out.glob(pattern), key=_render_sort_key)
    # pdftoppm names files like page-1.png or page-01.png depending on page count
    if not files:
        files = sorted(out.glob(f"*.{fmt}"), key=_render_sort_key)
    selected = [p for p in files if p.is_file()]
    low = first if first is not None else 1
    high = last
    if high is None:
        try:
            high = page_count(target)
        except Exception:
            high = None
    if first is not None or high is not None:
        selected = [
            p
            for p in selected
            if (number := _page_number(p)) is not None
            and number >= low
            and (high is None or number <= high)
        ]
    for image in selected:
        harden(image)
    return selected


def _safe_stem(path: Path) -> str:
    digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]
    return f"{path.stem}-{digest}"


def ocr_image(
    image_path: str | Path,
    *,
    lang: str = DEFAULT_LANG,
    psm: int = DEFAULT_PSM,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """OCR a single image with Tesseract."""
    target = Path(image_path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"not a file: {target}")
    _require("tesseract")
    args = ["tesseract", str(target), "stdout", "-l", lang, "--psm", str(psm)]
    result = _run(args, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(_decode(result.stderr).strip() or "tesseract failed")
    return _decode(result.stdout)


def ocr_images(
    image_paths: Iterable[str | Path],
    *,
    lang: str = DEFAULT_LANG,
    psm: int = DEFAULT_PSM,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[str]:
    return [ocr_image(p, lang=lang, psm=psm, timeout=timeout) for p in image_paths]


def ocr_pdf(
    path: str | Path,
    *,
    dpi: int = DEFAULT_DPI,
    lang: str = DEFAULT_LANG,
    psm: int = DEFAULT_PSM,
    pages: list[int] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """OCR a (scanned) PDF and return its text."""
    target = Path(path).expanduser()
    if pages is not None and not pages:
        # An explicit empty selection means "no pages", not "all pages".
        return ""
    first = min(pages) if pages else None
    last = max(pages) if pages else None
    images = render_pages(target, dpi=dpi, first=first, last=last, timeout=timeout)
    # If specific pages requested, filter rendered set.
    if pages is not None:
        wanted = set(pages)
        filtered: list[Path] = []
        for img in images:
            stem = img.stem
            num_str = "".join(ch for ch in stem.split("-")[-1] if ch.isdigit())
            try:
                if int(num_str) in wanted:
                    filtered.append(img)
            except ValueError:
                filtered.append(img)
        # Trust the filter even when it is empty: falling back to every page
        # would OCR pages the caller did not ask for.
        images = filtered
    # OCR pages in parallel for speed.
    workers = min(len(images), 4) or 1
    texts: list[str] = []
    if workers == 1:
        texts = ocr_images(images, lang=lang, psm=psm, timeout=timeout)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(ocr_image, img, lang=lang, psm=psm, timeout=timeout)
                for img in images
            ]
            for future in futures:
                try:
                    texts.append(future.result())
                except RuntimeError:
                    texts.append("")
    return "\n\n".join(texts)


def ocr_pdf_pages(
    path: str | Path,
    *,
    dpi: int = DEFAULT_DPI,
    lang: str = DEFAULT_LANG,
    psm: int = DEFAULT_PSM,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[str]:
    # Render once, then OCR in parallel.
    images = render_pages(path, dpi=dpi, timeout=timeout)
    workers = min(len(images), 4) or 1
    if workers == 1:
        return [ocr_image(img, lang=lang, psm=psm, timeout=timeout) for img in images]
    out: list[str] = [""] * len(images)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_index = {
            executor.submit(ocr_image, img, lang=lang, psm=psm, timeout=timeout): idx
            for idx, img in enumerate(images)
        }
        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                out[idx] = future.result()
            except RuntimeError:
                out[idx] = ""
    return out


def read_pdf(
    path: str | Path,
    *,
    ocr: bool | str = True,
    render_images: bool = False,
    dpi: int = DEFAULT_DPI,
    lang: str = DEFAULT_LANG,
    psm: int = DEFAULT_PSM,
    min_chars: int = DEFAULT_MIN_TEXT_CHARS,
    vision: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    ollama_url: str | None = None,
    model: str | None = None,
    prompt: str | None = None,
) -> PDFDocument:
    """Read a PDF: extract text, OCR scanned pages, optionally render images."""
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"not a file: {target}")

    count = _safe_page_count(target)
    text_pages = _safe_extract_pages(target, timeout=timeout)
    # pad/truncate to count
    while len(text_pages) < count:
        text_pages.append("")
    text_pages = text_pages[:count]

    if isinstance(ocr, str):
        low = ocr.lower().strip()
        do_ocr = low not in {"false", "no", "0", "none", "off", "never"}
    else:
        do_ocr = bool(ocr)

    # Decide which pages need OCR.
    force_all = isinstance(ocr, str) and ocr.lower().strip() in {"force", "all"}
    sparse_indices: list[int] = []
    if do_ocr:
        for i, page_text in enumerate(text_pages):
            if force_all or len("".join(page_text.split())) < min_chars:
                sparse_indices.append(i)

    # Render once for OCR and/or images. Rendering is best effort: a missing
    # pdftoppm or one damaged page must not throw away text that pdftotext
    # already extracted successfully.
    need_render = bool(sparse_indices) or render_images or vision
    rendered: list[Path] = []
    render_error = ""
    if need_render:
        try:
            rendered = render_pages(target, dpi=dpi, timeout=timeout)
        except Exception as exc:
            render_error = str(exc)

    ocr_pages_text: list[str] = [""] * count
    if sparse_indices and rendered:
        workers = min(len(sparse_indices), 4) or 1
        available = [i for i in sparse_indices if i < len(rendered)]
        if workers == 1:
            for i in available:
                try:
                    ocr_pages_text[i] = ocr_image(rendered[i], lang=lang, psm=psm, timeout=timeout)
                except RuntimeError:
                    ocr_pages_text[i] = ""
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_index = {
                    executor.submit(ocr_image, rendered[i], lang=lang, psm=psm, timeout=timeout): i
                    for i in available
                }
                for future in as_completed(future_to_index):
                    i = future_to_index[future]
                    try:
                        ocr_pages_text[i] = future.result()
                    except RuntimeError:
                        ocr_pages_text[i] = ""

    images: list[str] = []
    image_b64: list[str] = []
    if render_images or vision:
        images = [str(p) for p in rendered]
        if vision:
            image_b64 = [_b64_file(p) for p in rendered]

    pages: list[PDFPage] = []
    for i in range(count):
        has = len("".join(text_pages[i].split())) >= min_chars
        # Each page owns its own image. Copying the whole document onto every
        # page made to_dict() O(n^2) in both paths and base64 payloads.
        page_images = [images[i]] if (render_images or vision) and i < len(images) else []
        page_b64 = [image_b64[i]] if vision and i < len(image_b64) else []
        pages.append(
            PDFPage(
                number=i + 1,
                text=text_pages[i],
                ocr_text=ocr_pages_text[i],
                image_paths=page_images,
                image_base64=page_b64,
                has_text=has,
            )
        )

    full_text = "\n\n".join(p for p in text_pages if p.strip())
    full_ocr = "\n\n".join(p for p in ocr_pages_text if p.strip())

    doc = PDFDocument(
        path=str(target),
        page_count=count,
        pages=pages,
        text=full_text,
        ocr_text=full_ocr,
        images=images,
        image_base64=image_b64,
        metadata={"dpi": dpi, "lang": lang, "ocr": do_ocr},
    )
    if render_error:
        doc.metadata["ocr_error"] = render_error

    if vision and ollama_url and model:
        try:
            review = vision_review_images(
                image_b64 or [_b64_file(Path(p)) for p in images],
                prompt=prompt or "Describe this PDF page for data extraction.",
                model=model,
                ollama_url=ollama_url,
                timeout=timeout,
            )
            doc.metadata["vision_review"] = review
        except Exception as exc:  # pragma: no cover - best effort
            doc.metadata["vision_error"] = str(exc)

    return doc


def _safe_page_count(target: Path) -> int:
    try:
        return page_count(target)
    except Exception:
        return 1


def _safe_extract_pages(target: Path, *, timeout: int = DEFAULT_TIMEOUT) -> list[str]:
    try:
        return extract_pages(target, timeout=timeout)
    except Exception:
        try:
            return [extract_text(target, timeout=timeout)]
        except Exception:
            return []


def _b64_file(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def images_base64(path: str | Path, **kwargs: Any) -> list[str]:
    """Render a PDF and return page images as base64 strings."""
    allowed = {"dpi", "fmt", "first", "last", "prefix", "output_dir", "timeout"}
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    rendered = render_pages(path, **filtered)
    return [_b64_file(p) for p in rendered]


def vision_review_images(
    images: Iterable[str],
    *,
    prompt: str,
    model: str,
    ollama_url: str = "http://127.0.0.1:11434",
    timeout: int = 300,
) -> list[str]:
    """Ask a local vision model to review page images."""
    import httpx

    base = ollama_url.rstrip("/")
    if not base.startswith("http"):
        base = f"http://{base}"
    image_list = list(images)

    def _review_one(img: str) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt, "images": [img]},
            ],
            "stream": False,
        }
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(f"{base}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            return str((data.get("message") or {}).get("content") or "")
        except Exception as exc:
            return f"[vision error: {exc}]"

    out: list[str] = [""] * len(image_list)
    workers = min(len(image_list), 2) or 1
    if workers == 1:
        return [_review_one(img) for img in image_list]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_index = {
            executor.submit(_review_one, img): idx for idx, img in enumerate(image_list)
        }
        for future in as_completed(future_to_index):
            out[future_to_index[future]] = future.result()
    return out


def _download_filename(name: str, url: str) -> str:
    """A basename that cannot escape the download directory."""
    candidate = (name or "").replace("\\", "/").split("/")[-1].strip()
    candidate = re.sub(r"[\x00-\x1f\x7f]", "", candidate)
    if not candidate or candidate in {".", ".."}:
        candidate = url.split("?")[0].rstrip("/").split("/")[-1] or "document.pdf"
    if not candidate.lower().endswith(".pdf"):
        candidate = f"{candidate}.pdf"
    return candidate


def download_pdf(
    url: str,
    *,
    output_dir: str | Path | None = None,
    filename: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_bytes: int = 50 * 1024 * 1024,
    allow_local: bool = False,
) -> Path:
    """Download a PDF from a URL into the local cache.

    The URL is checked against the same policy as the browser (each redirect
    hop separately), the body is capped, and only the basename of a
    ``Content-Disposition`` filename is used. Without those checks a hostile
    server could write ``../../.zshrc`` or make the process fetch a loopback
    admin page.
    """
    import httpx

    from .browser.actions import BrowserPolicy, PolicyError, check_url

    if output_dir is None:
        output_dir = DATA_DIR / "pdf" / "downloads"
        managed = True
    else:
        managed = False
    out = Path(output_dir).expanduser()
    if managed:
        ensure_private_dir(out)
    else:
        out.mkdir(parents=True, exist_ok=True)
    policy = BrowserPolicy(allow_local=allow_local)
    current = url
    response: httpx.Response | None = None
    data = b""
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        for _hop in range(6):
            try:
                current = check_url(current, policy)
            except PolicyError as exc:
                raise ValueError(f"refused to download {url}: {exc}") from exc
            with client.stream("GET", current) as candidate:
                if candidate.is_redirect and candidate.headers.get("location"):
                    from urllib.parse import urljoin

                    current = urljoin(current, candidate.headers["location"])
                    continue
                candidate.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                for chunk in candidate.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"PDF is larger than the {max_bytes} byte download limit")
                    chunks.append(chunk)
                data = b"".join(chunks)
                response = candidate
                break
        else:
            raise ValueError(f"too many redirects while downloading {url}")
    if response is None or not data:
        raise ValueError(f"could not download {url}")
    if not data.startswith(b"%PDF-"):
        raise ValueError(f"{current} did not return a PDF")
    if filename is None:
        disposition = response.headers.get("content-disposition", "")
        match = re.search(r'filename="?([^";]+)"?', disposition)
        filename = match.group(1) if match else ""
    name = _download_filename(filename or "", current)
    target = (out / name).resolve()
    if target.parent != out.resolve():
        raise ValueError(f"refusing to write outside the download directory: {name}")
    if managed:
        write_private_bytes(target, data)
    else:
        # Do not chmod the caller's directory; harden the file after writing.
        target.write_bytes(data)
        harden(target)
    return target


def read_pdf_url(url: str, **kwargs: Any) -> PDFDocument:
    """Download (if needed) and read a PDF from a URL."""
    download_options: dict[str, Any] = {
        key: kwargs.pop(key) for key in ("output_dir", "filename") if key in kwargs
    }
    if "timeout" in kwargs:
        download_options["timeout"] = kwargs["timeout"]
    if "allow_local" in kwargs:
        download_options["allow_local"] = kwargs.pop("allow_local")
    path = download_pdf(url, **download_options)
    return read_pdf(path, **kwargs)


def auto_read(source: str, **kwargs: Any) -> PDFDocument | str:
    """Auto-handle a path or URL: download if needed, OCR if needed, return text."""
    if source.startswith(("http://", "https://")):
        doc = read_pdf_url(source, **kwargs)
    else:
        doc = read_pdf(source, **kwargs)
    return doc


def vision_review(
    path: str | Path,
    *,
    prompt: str = "Read this PDF page and extract all data accurately.",
    model: str | None = None,
    ollama_url: str = "http://127.0.0.1:11434",
    dpi: int = DEFAULT_DPI,
    timeout: int = 300,
) -> list[str]:
    """Render a PDF and have a vision model review every page."""
    if model is None:
        model = "qwen3.8:27b"
    rendered = render_pages(path, dpi=dpi, timeout=timeout)
    b64 = [_b64_file(p) for p in rendered]
    return vision_review_images(
        b64, prompt=prompt, model=model, ollama_url=ollama_url, timeout=timeout
    )


def pdf_to_text(path: str | Path, *, ocr: bool = True, **kwargs: Any) -> str:
    allowed = {"dpi", "lang", "psm", "min_chars", "timeout"}
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    doc = read_pdf(path, ocr=ocr, **filtered)
    return doc.combined_text()


def to_dict(path: str | Path, **kwargs: Any) -> dict[str, Any]:
    return read_pdf(path, **kwargs).to_dict()


def to_json(path: str | Path, **kwargs: Any) -> str:
    return json.dumps(to_dict(path, **kwargs), indent=2)


# --------------------------------------------------------------------------- #
# aliases for common names
# --------------------------------------------------------------------------- #

# functions
extract_pdf = extract_text
extract_pdf_text = extract_text
read_pdf_text = extract_text
get_pdf_text = extract_text
get_text = extract_text
pdf_text = extract_text
load_pdf_text = extract_text

ocr = ocr_pdf
ocr_document = ocr_pdf
ocr_file = ocr_pdf
pdf_ocr_text = ocr_pdf

render_pdf = render_pages
render_pdf_pages = render_pages
pdf_to_images = render_pages
pdf_pages_to_images = render_pages
to_images = render_pages

pdf_page_count = page_count
count_pages = page_count
num_pages = page_count
pages = page_count

pdf_needs_ocr = needs_ocr


def has_text(path: str | Path, **kwargs: Any) -> bool:
    return not needs_ocr(path, **kwargs)


pdf_images_base64 = images_base64
pdf_to_base64_images = images_base64

review_pdf = vision_review
review_pdf_with_vision = vision_review

read_document = read_pdf
open_pdf = read_pdf
load_pdf = read_pdf
read_url = read_pdf_url
read_pdf_from_url = read_pdf_url
auto = auto_read


class PDFReader:
    """Convenience reader that reads a PDF on construction."""

    def __init__(self, path: str | Path, **kwargs: Any) -> None:
        self.path = str(Path(path).expanduser())
        self.document = read_pdf(path, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.document, name)

    def __str__(self) -> str:
        return str(self.document)

    def __repr__(self) -> str:
        return f"PDFReader({self.path!r})"


# --------------------------------------------------------------------------- #
# extended extraction API (tables, figures, validation)
# --------------------------------------------------------------------------- #


class PDFReaderError(Exception):
    """Base error raised by the PDF reader."""


class PDFExtractError(PDFReaderError):
    """Raised when a PDF cannot be extracted."""


@dataclass
class TableData:
    """A table extracted from one PDF page."""

    page: int
    rows: list[list[str]] = field(default_factory=list)
    text: str = ""


@dataclass
class FigureData:
    """A figure/image extracted from one PDF page."""

    page: int
    path: str = ""
    image_base64: str = ""


def is_valid_pdf(path: str | Path) -> bool:
    """Return True when ``path`` looks like a readable PDF."""
    target = Path(path).expanduser()
    if not target.is_file():
        return False
    try:
        return page_count(target) >= 1
    except Exception:
        try:
            return target.read_bytes()[:5] == b"%PDF-"
        except OSError:
            return False


def extract_text_from_pdf(path: str | Path, **kwargs: Any) -> str:
    """Extract text from a PDF (alias for :func:`extract_text`)."""
    try:
        return extract_text(path, **kwargs)
    except Exception as exc:
        raise PDFExtractError(str(exc)) from exc


def extract_tables(path: str | Path, **kwargs: Any) -> list[TableData]:
    """Best-effort table extraction: group lines with 2+ columns."""
    allowed = {"timeout", "first", "last", "layout"}
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    try:
        pages = extract_pages(path, **filtered)
    except Exception as exc:
        raise PDFExtractError(str(exc)) from exc
    if not pages:
        try:
            pages = [extract_text(path, **filtered)]
        except Exception:
            pages = []
    tables: list[TableData] = []
    for i, page_text in enumerate(pages, 1):
        rows: list[list[str]] = []
        for line in page_text.splitlines():
            cols = [c.strip() for c in re.split(r"\s{2,}", line.strip()) if c.strip()]
            if len(cols) >= 2:
                rows.append(cols)
        if rows:
            tables.append(TableData(page=i, rows=rows, text=page_text))
    return tables


def extract_figures(path: str | Path, **kwargs: Any) -> list[FigureData]:
    """Render a PDF and return one :class:`FigureData` per page image."""
    allowed = {"dpi", "timeout", "output_dir", "fmt", "first", "last", "prefix"}
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    try:
        rendered = render_pages(path, **filtered)
    except Exception as exc:
        raise PDFExtractError(str(exc)) from exc
    figures: list[FigureData] = []
    for i, img in enumerate(rendered, 1):
        try:
            b64 = _b64_file(img)
        except OSError:
            b64 = ""
        # Keep the real page number when the caller asked for a range
        # (e.g. first=5); renumbering from 1 would lie about the source page.
        figures.append(FigureData(page=_page_number(img) or i, path=str(img), image_base64=b64))
    return figures


PDFOCR = PDFReader
PDFExtractor = PDFReader
OCRReader = PDFReader
PDF = PDFReader
Document = PDFReader

# module-level convenience
__all__ = [
    "DEFAULT_DPI",
    "DEFAULT_LANG",
    "PDF",
    "PDFOCR",
    "Document",
    "FigureData",
    "OCRReader",
    "PDFDocument",
    "PDFExtractError",
    "PDFExtractor",
    "PDFPage",
    "PDFReader",
    "PDFReaderError",
    "TableData",
    "auto_read",
    "available",
    "count_pages",
    "download_pdf",
    "extract_figures",
    "extract_pages",
    "extract_pdf",
    "extract_pdf_text",
    "extract_tables",
    "extract_text",
    "extract_text_from_pdf",
    "get_pdf_text",
    "get_text",
    "has_text",
    "images_base64",
    "is_pdf",
    "is_valid_pdf",
    "load_pdf",
    "load_pdf_text",
    "needs_ocr",
    "num_pages",
    "ocr",
    "ocr_document",
    "ocr_file",
    "ocr_image",
    "ocr_images",
    "ocr_pdf",
    "ocr_pdf_pages",
    "open_pdf",
    "page_count",
    "pages",
    "pdf_images_base64",
    "pdf_needs_ocr",
    "pdf_ocr_text",
    "pdf_page_count",
    "pdf_pages_to_images",
    "pdf_text",
    "pdf_to_base64_images",
    "pdf_to_images",
    "pdf_to_text",
    "read_document",
    "read_pdf",
    "read_pdf_text",
    "read_pdf_url",
    "render_pages",
    "render_pdf",
    "render_pdf_pages",
    "review_pdf",
    "review_pdf_with_vision",
    "to_dict",
    "to_images",
    "to_json",
    "vision_review",
    "vision_review_images",
]
