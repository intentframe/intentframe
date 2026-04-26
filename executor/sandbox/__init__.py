"""Executor-internal RUN_COMMAND sandboxing.

Provides kernel-enforced sandbox enforcement for shell commands.
The pipeline decides allow/block; this module decides *how* to run
allowed commands (which template, which filesystem scope).

Nothing outside executor/ imports from here.
"""
