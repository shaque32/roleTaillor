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

from .errors import InvalidDocument
from .model import ParsedDocument

MAX_ZIP_MEMBERS = 2000
MAX_ZIP_TOTAL_BYTES = 64 * 1024 * 1024
EXIT_REJECTED = 3
_PASS_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TESSDATA_PREFIX", "OMP_THREAD_LIMIT",
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


def check_docx_container(data: bytes) -> None:
    try:
        infos = zipfile.ZipFile(io.BytesIO(data)).infolist()
    except zipfile.BadZipFile as exc:
        raise InvalidDocument("not a DOCX (zip) file") from exc
    if len(infos) > MAX_ZIP_MEMBERS or sum(i.file_size for i in infos) > MAX_ZIP_TOTAL_BYTES:
        raise DocumentRejected("This document is too large once unpacked. Remove embedded "
                               "images or objects and try again.")


def _parse(kind: str, data: bytes, max_pages: int, max_blocks: int) -> ParsedDocument:
    if kind == "docx":
        from .docx_reader import read_docx

        check_docx_container(data)
        doc = read_docx(data)
    else:
        from .pdf import count_pdf_pages, read_pdf_text

        if count_pdf_pages(data) > max_pages:
            raise DocumentRejected(f"Resumes can be at most {max_pages} pages.")
        doc = read_pdf_text(data)
    if len(doc.blocks) > max_blocks:
        raise DocumentRejected("This document has too many paragraphs to be a resume.")
    return doc


def main(argv: list[str]) -> int:
    import resource

    kind, memory_mb, cpu_seconds, max_pages, max_blocks = argv[0], *map(int, argv[1:5])
    limit = memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    data = sys.stdin.buffer.read()
    try:
        doc = _parse(kind, data, max_pages, max_blocks)
    except DocumentRejected as exc:
        sys.stdout.write(json.dumps({"rejected": str(exc)}))
        return EXIT_REJECTED
    sys.stdout.write(doc.model_dump_json())
    return 0


def parse_untrusted(data: bytes, kind: str, *, timeout: float, memory_mb: int, cpu_seconds: int,
                    max_pages: int, max_blocks: int) -> ParsedDocument:
    """Parse `data` ("docx" or "pdf") in a sandboxed child. Raises DocumentRejected with a
    user-facing reason, ParserBusy when no slot frees up, ParseFailed otherwise."""
    if not _SLOTS.acquire(timeout=SLOT_WAIT_SECONDS):
        raise ParserBusy("all document parser slots are busy")
    try:
        env = {k: v for k, v in os.environ.items() if k in _PASS_ENV}
        proc = subprocess.Popen(
            [sys.executable, "-m", "roletailor.documents.sandbox", kind, str(memory_mb),
             str(cpu_seconds), str(max_pages), str(max_blocks)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, start_new_session=True,
        )
        try:
            out, _ = proc.communicate(data, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _kill_group(proc)
            raise ParseFailed("parsing timed out") from exc
        finally:
            if proc.poll() is None:
                _kill_group(proc)
    finally:
        _SLOTS.release()
    if proc.returncode == EXIT_REJECTED:
        try:
            reason = str(json.loads(out)["rejected"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ParseFailed("parser gave no reason") from exc
        raise DocumentRejected(reason)
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
    except (ProcessLookupError, PermissionError):
        proc.kill()
    proc.wait()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
