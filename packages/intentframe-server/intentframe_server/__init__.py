"""
IntentFrame Server — the security gateway process.

Houses the pipeline (IntentFrameRuntime) and the FastAPI app.
"""

from intentframe_server.pipeline import IntentFrameRuntime

__all__ = ["IntentFrameRuntime"]
