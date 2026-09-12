class AISearchError(Exception):
    """Base exception for expected application failures."""


class ConfigurationError(AISearchError, ValueError):
    """Raised when configuration is invalid."""


class ProviderError(AISearchError):
    """Raised when an external provider fails."""


class ReaderError(AISearchError):
    """Raised when a document cannot be read or extracted."""
