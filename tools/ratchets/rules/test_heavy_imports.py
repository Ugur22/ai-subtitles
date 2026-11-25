import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import heavy_imports  # noqa: E402
import ratchet  # noqa: E402

RULE = "heavy-imports"
FIX = ("Import the library inside the function that uses it, so importing the module (and the app) stays cheap. "
       "If it truly must load at import time, the owner adds an exception with a reason.")

SAMPLE = '''\
import json
import torch
from pyannote.audio import Pipeline
from typing import TYPE_CHECKING
from . import torch_helpers
import torchvision

if TYPE_CHECKING:
    from transformers import AutoModel
else:
    import cv2

try:
    import onnxruntime
except ImportError:
    from insightface.app import FaceAnalysis


class Loader:
    from faster_whisper import WhisperModel

    def load(self):
        import torchaudio


def embed():
    from sentence_transformers import SentenceTransformer
'''


def repo(tmp_path, files):
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return tmp_path


def test_no_new_module_level_heavy_import():
    ratchet.assert_no_new(RULE, heavy_imports.collect(), FIX)


def test_every_exception_has_a_reason():
    assert ratchet.short_reasons(RULE) == {}


def test_only_imports_that_run_at_import_time_count(tmp_path):
    root = repo(tmp_path, {"backend/services/new.py": SAMPLE})
    assert sorted(heavy_imports.collect(root)) == sorted([
        "backend/services/new.py::<module>::import torch",
        "backend/services/new.py::<module>::from pyannote.audio import Pipeline",
        "backend/services/new.py::<module>::import cv2",
        "backend/services/new.py::<module>::import onnxruntime",
        "backend/services/new.py::<module>::from insightface.app import FaceAnalysis",
        "backend/services/new.py::Loader::from faster_whisper import WhisperModel",
    ])


def test_importing_a_heavy_backend_module_at_import_time_counts(tmp_path):
    root = repo(tmp_path, {
        "backend/services/translation.py": "import torch\nimport torch\n",
        "backend/services/__init__.py": "from . import translation\n",
        "backend/services/worker.py": "from . import translation\n",
        "backend/routers/a.py": "from services.translation import Translator\n",
        "backend/routers/b.py": "def f():\n    from services.translation import Translator\n",
        "backend/routers/c.py": "import librosa\nimport services.worker\n",
    })
    assert heavy_imports.collect(root) == {
        "backend/services/translation.py::<module>::import torch": "torch",
        "backend/services/translation.py::<module>::import torch#2": "torch",
        "backend/services/__init__.py::<module>::from . import translation": "via services.translation",
        "backend/services/worker.py::<module>::from . import translation": "via services.translation",
        "backend/routers/a.py::<module>::from services.translation import Translator": "via services.translation",
        "backend/routers/c.py::<module>::import librosa": "librosa",
    }, "one level deep: routers/c.py imports worker, which is only heavy through translation"


def test_tests_and_virtualenvs_are_not_scanned(tmp_path):
    root = repo(tmp_path, {"backend/tests/test_x.py": "import torch\n", "backend/test_y.py": "import torch\n",
                           "backend/conftest.py": "import torch\n", "backend/venv/lib/z.py": "import torch\n"})
    assert heavy_imports.collect(root) == {}


def test_a_new_heavy_import_fails_and_a_lazy_one_passes(tmp_path):
    empty = tmp_path / "baseline.json"
    empty.write_text('{"version": 1, "rules": {}}')
    lazy = repo(tmp_path / "lazy", {"backend/new.py": "def f():\n    import torch\n"})
    ratchet.assert_no_new(RULE, heavy_imports.collect(lazy), FIX, empty)
    eager = repo(tmp_path / "eager", {"backend/new.py": "import torch\n"})
    with pytest.raises(AssertionError, match=r"backend/new\.py::<module>::import torch"):
        ratchet.assert_no_new(RULE, heavy_imports.collect(eager), FIX, empty)
