"""
Executor Client — adapter between IntentFrame and the Executor service.

Provides two implementations of the Executor ABC:
    - ExecutorHTTPClient: calls the Executor service over HTTP/UDS (production)
    - ExecutorBridge: calls the ExecutorGateway in-process (tests / demo)

Wire-protocol models (ExecutionRequest, ExecutionResult, etc.) live in
executor_client.models — zero dependency on the executor server package.
"""

from executor_client.bridge import ExecutorBridge
from executor_client.http_client import ExecutorHTTPClient
