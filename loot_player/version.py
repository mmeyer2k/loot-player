"""Single source of truth for the app version.

CI overwrites the literal below with the git tag value at release build time
(see .github/workflows/release.yml). Keep it a plain string assignment so
setuptools can read it statically (see pyproject.toml dynamic version).
"""

__version__ = "0.0.0+dev"
