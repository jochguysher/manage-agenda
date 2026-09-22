"""
Custom exceptions for manage-agenda application.
"""


class ManageAgendaError(Exception):
    """Base exception for all manage-agenda errors."""

    pass


class ConfigurationError(ManageAgendaError):
    """Raised when there's a configuration problem."""

    pass


class APIError(ManageAgendaError):
    """Raised when an API call fails."""

    pass


class AuthenticationError(APIError):
    """Raised when authentication fails."""

    pass


class CalendarError(ManageAgendaError):
    """Raised when calendar operations fail."""

    pass


class CalendarAccountChoiceRequired(CalendarError):
    """Raised by connections.select_calendar_account() when several calendar accounts are
    configured, none is saved and -i was not given: nothing is guessed and no account is
    connected. str(error) is the user-facing message asking for -i."""

    pass


class EmailError(ManageAgendaError):
    """Raised when email operations fail."""

    pass


class LLMError(ManageAgendaError):
    """Raised when LLM operations fail."""

    pass


class ValidationError(ManageAgendaError):
    """Raised when data validation fails."""

    pass
