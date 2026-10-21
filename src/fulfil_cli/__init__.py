"""Fulfil CLI — command-line interface for the Fulfil ERP platform.

Also usable as a library: ``from fulfil_cli import Workspace``.
"""

from importlib.metadata import version

# Set before the imports below: the HTTP client reads it for its User-Agent.
__version__ = version("fulfil-cli")

from fulfil_cli.client.errors import FulfilError
from fulfil_cli.workspace import Model, Workspace

__all__ = ["FulfilError", "Model", "Workspace", "__version__"]
