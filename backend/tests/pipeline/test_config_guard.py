import pytest
from pydantic import ValidationError

from roletailor.config import Settings

LONG_KEY = "x" * 40


def make(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_dev_defaults_pass():
    make()


def test_prod_with_default_key_fails():
    with pytest.raises(ValidationError):
        make(environment="prod", storage_backend="s3")


def test_prod_with_short_key_fails():
    with pytest.raises(ValidationError):
        make(environment="prod", storage_backend="s3", secret_key="short")


def test_prod_with_local_storage_fails():
    with pytest.raises(ValidationError):
        make(environment="staging", secret_key=LONG_KEY)


def test_prod_with_long_key_and_s3_passes():
    make(environment="prod", secret_key=LONG_KEY, storage_backend="s3")
