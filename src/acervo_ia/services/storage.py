"""Private persistent document storage with local-development and S3 adapters."""

import os
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from acervo_ia import config


class StorageUnavailable(RuntimeError):
    """Safe storage error; underlying provider details are intentionally omitted."""


def _validate_key(storage_key: str) -> None:
    if len(storage_key) != 32 or any(c not in "0123456789abcdef" for c in storage_key):
        raise StorageUnavailable


def _s3_client():
    try:
        import boto3

        return boto3.client(
            "s3",
            endpoint_url=config.S3_ENDPOINT_URL,
            region_name=config.S3_REGION,
            aws_access_key_id=config.S3_ACCESS_KEY_ID,
            aws_secret_access_key=config.S3_SECRET_ACCESS_KEY,
        )
    except Exception:
        raise StorageUnavailable from None


def store(storage_key: str, content: bytes) -> None:
    _validate_key(storage_key)
    if config.STORAGE_BACKEND == "local":
        path = config.DOCUMENT_STORAGE_DIRECTORY / storage_key
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as target:
                target.write(content)
            return
        except OSError:
            raise StorageUnavailable from None
    if config.STORAGE_BACKEND != "s3" or not config.S3_BUCKET:
        raise StorageUnavailable
    try:
        _s3_client().put_object(
            Bucket=config.S3_BUCKET,
            Key=storage_key,
            Body=content,
            ServerSideEncryption="AES256",
            ContentLength=len(content),
        )
    except Exception:
        raise StorageUnavailable from None


def open_file(storage_key: str) -> BinaryIO:
    _validate_key(storage_key)
    if config.STORAGE_BACKEND == "local":
        path = config.DOCUMENT_STORAGE_DIRECTORY / storage_key
        try:
            return path.open("rb")
        except OSError:
            raise StorageUnavailable from None
    if config.STORAGE_BACKEND != "s3" or not config.S3_BUCKET:
        raise StorageUnavailable
    try:
        body = _s3_client().get_object(Bucket=config.S3_BUCKET, Key=storage_key)["Body"].read()
        return BytesIO(body)
    except Exception:
        raise StorageUnavailable from None


def delete(storage_key: str) -> None:
    _validate_key(storage_key)
    if config.STORAGE_BACKEND == "local":
        try:
            (config.DOCUMENT_STORAGE_DIRECTORY / storage_key).unlink(missing_ok=True)
            return
        except OSError:
            raise StorageUnavailable from None
    if config.STORAGE_BACKEND != "s3" or not config.S3_BUCKET:
        raise StorageUnavailable
    try:
        _s3_client().delete_object(Bucket=config.S3_BUCKET, Key=storage_key)
    except Exception:
        raise StorageUnavailable from None


def local_path(storage_key: str) -> Path:
    _validate_key(storage_key)
    if config.STORAGE_BACKEND != "local":
        raise StorageUnavailable
    return config.DOCUMENT_STORAGE_DIRECTORY / storage_key
