class CrowdcheckError(Exception):
    """Base class. Messages must never contain an API key."""


class MissingApiKey(CrowdcheckError):
    def __init__(self, variable: str):
        self.variable = variable
        super().__init__(f"environment variable {variable} is not set")


class ProviderError(CrowdcheckError):
    """A provider call failed. The message is a short phrase safe to print."""


class RateLimited(ProviderError):
    """Still rate limited (HTTP 429) after every retry."""


class NotSupported(ProviderError):
    """This backend cannot answer this question."""
