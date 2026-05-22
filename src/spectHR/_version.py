"""Single source of truth for the spectHR package version.

Bumped by the release workflow (``.github/workflows/release.yml``)
when a ``bump`` / ``bump-X.Y.Z`` tag is pushed; ``pyproject.toml``
reads from here via ``[tool.setuptools.dynamic]`` so that
``project.version`` is built from this module. The runtime UI title
(``spectUI.MainWindow``) imports ``__version__`` from here too — both
the build metadata and the on-screen version label come from the same
constant, kept in sync automatically.
"""

__version__ = "1.2.5"