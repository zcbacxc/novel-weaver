"""Domain-level exceptions."""


class DomainError(Exception):
    """Base error for domain rule violations."""


class StaleRevisionError(DomainError):
    """Raised when an operation targets an outdated story revision."""


class GuardRejectError(DomainError):
    """Raised when Commit Guard rejects a candidate commit."""
