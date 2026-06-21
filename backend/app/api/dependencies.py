import os
from typing import Optional

from app.core.config import settings
from app.utils.context_assembler import ContextAssembler


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_DB_PATH = os.path.join(CURRENT_DIR, "checkpoints.db")

_assembler: Optional[ContextAssembler] = None


async def get_assembler() -> ContextAssembler:
    """Return the shared ContextAssembler instance."""
    global _assembler
    if _assembler is None:
        _assembler = ContextAssembler(total_budget=settings.total_token_budget)
    return _assembler
