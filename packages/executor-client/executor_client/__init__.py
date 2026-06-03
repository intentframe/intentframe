"""
Executor Client — adapter between IntentFrame and the Executor service.

Production path: ``ExecutorHTTPClient`` calls the executor service over UDS.

Wire-protocol models (ExecutionRequest, ExecutionResult, etc.) live in
``executor_client.models`` — zero dependency on the executor server package.
"""

from executor_client.http_client import ExecutorHTTPClient

__all__ = ["ExecutorHTTPClient"]
