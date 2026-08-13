"""Domain exceptions.

Services raise these; routes turn them into a short flash message. A
DomainError carries text that is safe to show a user. Anything else that
escapes a service is a defect, is logged with its traceback, and reaches
the user only as a generic message.
"""

from __future__ import annotations


class DomainError(Exception):
    """A business rule was violated. The message is user-facing."""


class NotFound(DomainError):
    """A referenced record does not exist."""


class ValidationError(DomainError):
    """Input failed validation before any database work was attempted."""


class InvalidTransition(DomainError):
    """A quote state change is not permitted from the current state."""


class ConversionError(DomainError):
    """Policy issuance cannot proceed, or has already happened."""


class GovernanceError(DomainError):
    """An action would breach a governance control."""
