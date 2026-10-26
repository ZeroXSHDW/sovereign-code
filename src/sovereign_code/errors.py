"""A shared base for the project's error types.

Each module used to define its own exception class with no common
ancestor, so callers had to know which module raised what. They now derive
from :class:`SovereignError`, which makes "something in the local stack
failed" a single catch.
"""

from __future__ import annotations


class SovereignError(Exception):
    """Base class for every error this package raises."""


class ConfigError(SovereignError):
    """A setting or config file could not be read."""


class ServiceError(SovereignError):
    """A local service (Ollama, the gateway, the bridge, the monitor) failed."""


class SourceError(ServiceError):
    """A file or URL could not be read."""


class PolicyError(ServiceError):
    """A browser URL was refused by the policy."""


class BrowserError(ServiceError):
    """The browser operator could not perform an action."""


class ActionError(BrowserError):
    """The browser action could not be parsed."""


class PlannerError(BrowserError):
    """The browser planner failed."""


class SensitiveFieldError(BrowserError):
    """A field that holds a secret was about to be filled."""


class EmbedError(ServiceError):
    """An embedding request failed."""


class HFError(ServiceError):
    """A Hugging Face request failed."""


class OllamaError(ServiceError):
    """An Ollama request failed."""


__all__ = [
    "BrowserError",
    "ConfigError",
    "EmbedError",
    "HFError",
    "OllamaError",
    "PolicyError",
    "ServiceError",
    "SourceError",
    "SovereignError",
]
