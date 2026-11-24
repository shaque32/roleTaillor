"""Object storage for uploaded and generated files, plus content checks.

`LocalStorage` (dev/tests) keeps objects under settings.storage_local_dir and issues
HMAC-signed URLs served by `GET /v1/files/{token}`. `S3Storage` uses versioned
buckets and presigned GET URLs. Callers never serve a file whose stored_files row is
not `clean`; see services/files.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import time
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol

from roletailor.config import get_settings

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MEDIA_TYPE = "application/pdf"
EXTENSIONS = {DOCX_MEDIA_TYPE: ".docx", PDF_MEDIA_TYPE: ".pdf"}

ScanStatus = Literal["clean", "blocked", "failed"]


class UnsupportedFile(ValueError):
    """The bytes are not an accepted document type or exceed the size limit."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff_media_type(data: bytes, max_bytes: int) -> str:
    """Return the media type of an accepted upload (DOCX or PDF) from its bytes,
    ignoring the client-supplied name and Content-Type."""
    if len(data) == 0:
        raise UnsupportedFile("file_empty", "The file is empty.")
    if len(data) > max_bytes:
        raise UnsupportedFile("file_too_large", f"Files must be at most {max_bytes} bytes.")
    if data.startswith(b"%PDF-"):
        return PDF_MEDIA_TYPE
    if data.startswith(b"PK\x03\x04"):
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except zipfile.BadZipFile:
            names = set()
        if {"[Content_Types].xml", "word/document.xml"} <= names:
            return DOCX_MEDIA_TYPE
    raise UnsupportedFile("unsupported_file_type", "Only DOCX and PDF files are accepted.")


# --------------------------------------------------------------------------
# Malware scanning hook
# --------------------------------------------------------------------------


class Scanner(Protocol):
    def scan(self, data: bytes, media_type: str) -> ScanStatus: ...


class DevScanner:
    """Marks everything clean. Production plugs in a real scanner here, e.g. a
    ClamAV scanner that streams `data` to clamd (INSTREAM) and returns 'blocked'
    on a FOUND reply and 'failed' when clamd is unreachable."""

    def scan(self, data: bytes, media_type: str) -> ScanStatus:
        return "clean"


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SignedTarget:
    key: str
    filename: str
    media_type: str


class Storage(Protocol):
    bucket: str

    def put(self, key: str, data: bytes, media_type: str) -> str | None:
        """Store bytes and return the object version, when the backend has one."""

    def get(self, key: str, version: str | None = None) -> bytes: ...

    def delete(self, key: str, version: str | None = None) -> None: ...

    def signed_url(
        self, key: str, version: str | None, *, filename: str, media_type: str, ttl: int
    ) -> str: ...


class LocalStorage:
    bucket = "local"

    def __init__(self, root: Path, base_url: str, secret: str):
        self.root = root.resolve()
        self.base_url = base_url.rstrip("/")
        self._secret = secret.encode()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("object key escapes the storage root")
        return path

    def put(self, key: str, data: bytes, media_type: str) -> str | None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return None

    def get(self, key: str, version: str | None = None) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str, version: str | None = None) -> None:
        self._path(key).unlink(missing_ok=True)

    def _sign(self, body: bytes) -> str:
        return hmac.new(self._secret, body, hashlib.sha256).hexdigest()

    def signed_url(
        self, key: str, version: str | None, *, filename: str, media_type: str, ttl: int
    ) -> str:
        claims = {"k": key, "f": filename, "m": media_type, "e": int(time.time()) + ttl}
        body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
        return f"{self.base_url}/v1/files/{body.decode()}.{self._sign(body)}"

    def verify_token(self, token: str) -> SignedTarget | None:
        body, _, signature = token.rpartition(".")
        if not body or not hmac.compare_digest(self._sign(body.encode()), signature):
            return None
        try:
            claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except ValueError:
            return None
        if claims["e"] < time.time():
            return None
        return SignedTarget(key=claims["k"], filename=claims["f"], media_type=claims["m"])


class S3Storage:
    def __init__(self, bucket: str, region: str, endpoint_url: str | None = None):
        import boto3

        self.bucket = bucket
        self._s3 = boto3.client("s3", region_name=region, endpoint_url=endpoint_url or None)

    def put(self, key: str, data: bytes, media_type: str) -> str | None:
        response = self._s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=media_type,
            ChecksumAlgorithm="SHA256",
            ServerSideEncryption="AES256",
        )
        return response.get("VersionId")

    def _version_args(self, version: str | None) -> dict[str, str]:
        return {"VersionId": version} if version else {}

    def get(self, key: str, version: str | None = None) -> bytes:
        response = self._s3.get_object(Bucket=self.bucket, Key=key, **self._version_args(version))
        return response["Body"].read()

    def delete(self, key: str, version: str | None = None) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=key, **self._version_args(version))

    def signed_url(
        self, key: str, version: str | None, *, filename: str, media_type: str, ttl: int
    ) -> str:
        params = {
            "Bucket": self.bucket,
            "Key": key,
            "ResponseContentType": media_type,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
            **self._version_args(version),
        }
        return self._s3.generate_presigned_url("get_object", Params=params, ExpiresIn=ttl)


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    if settings.storage_backend == "s3":
        return S3Storage(settings.s3_bucket, settings.s3_region, settings.s3_endpoint_url)
    return LocalStorage(settings.storage_local_dir, settings.api_base_url, settings.secret_key)


@lru_cache
def get_scanner() -> Scanner:
    return DevScanner()
