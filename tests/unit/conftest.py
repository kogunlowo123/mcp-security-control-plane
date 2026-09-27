"""Unit test fixtures."""

from __future__ import annotations

import pytest

from api.main import create_app


@pytest.fixture(scope="module")
def app():
    return create_app()
