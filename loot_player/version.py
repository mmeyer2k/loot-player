"""Single source of truth for the release version.

Read by pyproject.toml (dynamic version), the ``--version`` flag, and the
release workflow's tag guard. Bump this, then tag ``v<version>``.
"""

__version__ = "0.1.0"
