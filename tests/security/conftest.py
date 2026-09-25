import os
import shutil
import stat
from pathlib import Path
from uuid import uuid4

import pytest


def remove_readonly(function, path, _exception):
    os.chmod(path, stat.S_IWRITE)
    function(path)


@pytest.fixture
def workdir():
    root = Path(__file__).parent / ".generated" / uuid4().hex
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, onexc=remove_readonly)
        if root.parent.exists() and not any(root.parent.iterdir()):
            root.parent.rmdir()
