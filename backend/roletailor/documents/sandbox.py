"""Parse untrusted uploads in a resource-limited child process.

DOCX and PDF parsing (zip inflation, XML, PDF content streams, embedded fonts, OCR) is the
largest untrusted-input surface in the product: a 200 KB file can expand to gigabytes or
minutes of CPU. The parent never parses an upload itself. It runs this module as
`python -m roletailor.documents.sandbox`, which caps its own address space and CPU time,
rejects oversized inputs before the heavy parse, and prints the ParsedDocument as JSON.
The child gets a minimal environment, so no credentials are in reach of a parser bug.
"""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import threading
import zipfile
from typing import TYPE_CHECKING

from .errors import InvalidDocument
from .model import ParsedDocument

if TYPE_CHECKING:
    from .pdf import OcrOptions

MAX_ZIP_MEMBERS = 2000
MAX_ZIP_TOTAL_BYTES = 64 * 1024 * 1024
EXIT_REJECTED = 3
EXIT_USAGE = 2
_PASS_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TESSDATA_PREFIX", "OMP_THREAD_LIMIT",
             "RT_TESSERACT",
             "PYTHONPATH", "VIRTUAL_ENV", "LD_LIBRARY_PATH")
# Parses are CPU-bound; a small pool keeps a burst of uploads from starving the API.
_SLOTS = threading.BoundedSemaphore(2)
SLOT_WAIT_SECONDS = 20.0


class DocumentRejected(InvalidDocument):
    """The file breaks a published limit; `str(exc)` is safe to show the user."""


class ParserBusy(RuntimeError):
    pass


class ParseFailed(InvalidDocument):
    """The child crashed, ran out of memory or time, or could not read the file."""


class ParseTimeout(ParseFailed):
    """The child exceeded its wall-clock timeout or its CPU limit."""


def check_docx_container(data: bytes) -> None:
    try:
        infos = zipfile.ZipFile(io.BytesIO(data)).infolist()
    except zipfile.BadZipFile as exc:
        raise InvalidDocument("not a DOCX (zip) file") from exc
    if len(infos) > MAX_ZIP_MEMBERS or sum(i.file_size for i in infos) > MAX_ZIP_TOTAL_BYTES:
        raise DocumentRejected("This document is too large once unpacked. Remove embedded "
                               "images or objects and try again.")


def _parse(kind: str, data: bytes, max_pages: int, max_blocks: int,
           ocr: OcrOptions) -> ParsedDocument:
    if kind == "docx":
        from .docx_reader import read_docx

        check_docx_container(data)
        doc = read_docx(data)
    else:
        from .pdf import count_pdf_pages, read_pdf_text

        if count_pdf_pages(data) > max_pages:
            raise DocumentRejected(f"Resumes can be at most {max_pages} pages.")
        doc = read_pdf_text(data, ocr=ocr)
    if len(doc.blocks) > max_blocks:
        raise DocumentRejected("This document has too many paragraphs to be a resume.")
    return doc


CPU_HARD_GRACE_SECONDS = 2


def apply_limits(memory_mb: int, cpu_seconds: int) -> None:
    """Cap this process's address space and CPU time; children (Tesseract) inherit both.

    The CPU budget is the soft limit, which ends the process with SIGXCPU so the parent can
    tell "ran out of CPU" from a crash. The hard limit sits just above it as the forced stop:
    with both equal the kernel sends SIGKILL first and the reason is lost.
    """
    import resource

    limit = memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + CPU_HARD_GRACE_SECONDS))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main(argv: list[str]) -> int:

    from .pdf import OcrOptions

    # Strict argv: kind memory_mb cpu_seconds max_pages max_blocks ocr(0|1) ocr_max_pages ocr_deadline
    if len(argv) != 8 or argv[0] not in ("docx", "pdf") or argv[5] not in ("0", "1"):
        sys.stderr.write("usage: sandbox docx|pdf MEMORY_MB CPU_S MAX_PAGES MAX_BLOCKS 0|1 OCR_PAGES OCR_S\n")
        return EXIT_USAGE
    try:
        kind, memory_mb, cpu_seconds, max_pages, max_blocks = argv[0], *map(int, argv[1:5])
        ocr = OcrOptions(enabled=argv[5] == "1", max_pages=int(argv[6]), deadline=float(argv[7]))
    except ValueError:
        return EXIT_USAGE
    apply_limits(memory_mb, cpu_seconds)
    data = sys.stdin.buffer.read()
    try:
        doc = _parse(kind, data, max_pages, max_blocks, ocr)
    except DocumentRejected as exc:
        sys.stdout.write(json.dumps({"rejected": str(exc)}))
        return EXIT_REJECTED
    sys.stdout.write(doc.model_dump_json())
    return 0


def parse_untrusted(data: bytes, kind: str, *, timeout: float, memory_mb: int, cpu_seconds: int,
                    max_pages: int, max_blocks: int, ocr: bool = False, ocr_max_pages: int = 6,
                    ocr_deadline: float = 45.0) -> ParsedDocument:
    """Parse `data` ("docx" or "pdf") in a sandboxed child. Raises DocumentRejected with a
    user-facing reason, ParserBusy when no slot frees up, ParseFailed (ParseTimeout when the
    child ran out of wall-clock or CPU time) otherwise.

    Scanned PDFs are only OCR'd when `ocr` is true (request paths leave it off); the outcome
    is then in `layout_metadata["ocr_outcome"]` of a document without blocks."""
    if not _SLOTS.acquire(timeout=SLOT_WAIT_SECONDS):
        raise ParserBusy("all document parser slots are busy")
    try:
        env = {k: v for k, v in os.environ.items() if k in _PASS_ENV}
        proc = subprocess.Popen(
            [sys.executable, "-m", "roletailor.documents.sandbox", kind, str(memory_mb),
             str(cpu_seconds), str(max_pages), str(max_blocks), "1" if ocr else "0",
             str(ocr_max_pages), repr(float(ocr_deadline))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, start_new_session=True,
        )
        try:
            out, _ = proc.communicate(data, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ParseTimeout("parsing timed out") from exc
        finally:
            # Always, even after a clean exit: a parser that died on a signal can leave
            # Tesseract running, and `poll()` only knows about the parser itself.
            _kill_group(proc)
    finally:
        _SLOTS.release()
    if proc.returncode == EXIT_REJECTED:
        try:
            reason = str(json.loads(out)["rejected"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ParseFailed("parser gave no reason") from exc
        raise DocumentRejected(reason)
    if proc.returncode == -signal.SIGXCPU:
        raise ParseTimeout("parser exceeded its CPU limit")
    if proc.returncode != 0:
        raise ParseFailed(f"parser exited with status {proc.returncode}")
    try:
        return ParsedDocument.model_validate_json(out)
    except ValueError as exc:
        raise ParseFailed("parser output was not a document") from exc


def _kill_group(proc: subprocess.Popen) -> None:
    """Kill the child and anything it started (Tesseract), then reap it."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # the whole group is already gone
    except PermissionError:
        proc.kill()
    proc.wait()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
