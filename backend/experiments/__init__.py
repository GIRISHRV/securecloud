"""Reproducible, isolated evaluation tooling for SecureCloud.

Import the runner explicitly so ``python -m backend.experiments.runner`` does
not preload the module and emit a misleading execution warning.
"""
