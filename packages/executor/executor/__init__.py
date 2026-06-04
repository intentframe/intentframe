"""
IntentFrame Executor - A Standalone, Protocol-Driven Capability Service.

"The Hands" -- the only entity that touches the real world.

The Executor is an OS Capability Bridge that runs as a standalone,
process-isolated service. It communicates exclusively through validated
protocols (gRPC, REST, Unix socket) and secure channels.

Core Invariants:
    1. Fail-Closed: Any failure -> rejection, never silent approval
    2. Authorization Required: Every request must carry valid auth proof
    3. Credentials Never Leave: Creds stay in executor process memory
    4. Virtual Paths Only: Agents see virtual paths, never real paths

Architecture:
    Transport Layer   -> How requests arrive (pluggable)
    Auth Layer        -> How authorization is verified (pluggable)
    Gateway           -> Orchestration: verify -> validate -> route -> execute
    Adapter Layer     -> How capabilities are executed (pluggable per platform)
    Services Layer    -> Cross-cutting: audit, credentials, state, VFS
"""

__version__ = "0.1.0"
