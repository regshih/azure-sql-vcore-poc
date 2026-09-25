import shutil
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def no_real_evidence_upload(monkeypatch):
    monkeypatch.delenv("EVIDENCE_STORAGE_ACCOUNT", raising=False)
    monkeypatch.delenv("EVIDENCE_STORAGE_CONTAINER", raising=False)
    monkeypatch.delenv("CONTAINER_APP_JOB_NAME", raising=False)


@pytest.fixture
def workdir():
    root = Path(__file__).parent / ".generated" / uuid4().hex
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root)
        if root.parent.exists() and not any(root.parent.iterdir()):
            root.parent.rmdir()
