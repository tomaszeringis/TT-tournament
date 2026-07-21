"""Optional classifier stub for future Torch-based surface/spin inference.

No Torch is imported at module load time. If Torch/torchaudio are missing or
the model directory is empty, ``available`` is ``False`` and ``classify``
returns a safe fallback.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class TTClassifier:
    def __init__(self, model_dir: str = "") -> None:
        self._model_dir = model_dir
        self._available = False
        self._load_model()

    def _load_model(self) -> None:
        try:
            import torch  # noqa: F401
            import torchaudio  # noqa: F401
            if self._model_dir:
                self._available = True
            else:
                self._available = False
        except ImportError:
            self._available = False
        except Exception:
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def classify(self, chunk: Any) -> Dict[str, Any]:
        if not self._available:
            return {"surface": "unknown", "spin_hint": "unknown", "available": False}
        return {"surface": "unknown", "spin_hint": "unknown", "available": True}
