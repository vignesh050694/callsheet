"""Domain errors raised by the service layer.

Services know nothing about HTTP. They raise these; a single exception handler in
`app.main` maps each one to a status code, so controllers stay free of error plumbing.
"""


class DomainError(Exception):
    """Base class for every expected, business-level failure."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__


class ResourceNotFoundError(DomainError):
    """A record the caller referenced does not exist. -> 404"""


class ResourceConflictError(DomainError):
    """The request collides with existing state, e.g. a duplicate slug. -> 409"""


class ValidationFailedError(DomainError):
    """Input is well-formed but violates a business rule. -> 422"""


class AuthenticationRequiredError(DomainError):
    """The caller did not identify themselves, or the identity does not resolve. -> 401"""


class PermissionDeniedError(DomainError):
    """The caller is authenticated but not allowed to do this. -> 403"""


class ServiceUnavailableError(DomainError):
    """A dependency this request needs is not configured or not reachable. -> 503

    Distinct from a 500: the request was fine and the caller can retry once the
    dependency is back, so the message says what is missing rather than apologising.
    """
