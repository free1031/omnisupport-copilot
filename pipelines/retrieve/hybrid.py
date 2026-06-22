"""PPT-compatible hybrid retrieval entrypoints for Week08.

Do not add retrieval logic here. The service runtime owns the implementation in
`services/rag_api/app/retrieval.py`; this module keeps the course deck path
stable without creating a second retrieval stack.
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAG_API_PATH = PROJECT_ROOT / "services" / "rag_api"


def _clear_non_rag_app_package() -> None:
    loaded_app = sys.modules.get("app")
    app_file = Path(getattr(loaded_app, "__file__", "") or "")
    if loaded_app is None or str(app_file).startswith(str(RAG_API_PATH)):
        return
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)


_clear_non_rag_app_package()
if str(RAG_API_PATH) not in sys.path:
    sys.path.insert(0, str(RAG_API_PATH))

from app.retrieval import (  # noqa: E402
    RetrievalResult,
    fts_search,
    hybrid_retrieve,
    reciprocal_rank_fusion,
    vector_search,
)


hybrid_search = hybrid_retrieve

__all__ = [
    "RetrievalResult",
    "fts_search",
    "hybrid_retrieve",
    "hybrid_search",
    "reciprocal_rank_fusion",
    "vector_search",
]
