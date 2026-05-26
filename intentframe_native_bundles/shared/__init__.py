"""Shared libraries for first-party native bundles.

Plain Python — no ``ActionBundle`` subclasses, no SDK registry calls.
Any bundle may import from these packages; bundles must never import
from each other's action folders.
"""
