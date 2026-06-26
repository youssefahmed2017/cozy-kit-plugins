# ============= cozy_kit/_internal/errors.py =============

from cozy_kit._internal.errors.inheritance_errors import CozyKitMainError

# ============= Timer ERRORS =============


class InvalidTimeAmountError(CozyKitMainError):
    pass


class StopWatchNotStartedError(CozyKitMainError):
    pass


class InvalidTimeTypeError(CozyKitMainError):
    pass


class PomodoroNotStartedError(CozyKitMainError):
    pass


class PomodoroNotPausedError(CozyKitMainError):
    pass


# ============= TextEditor ERRORS =============


class InvalidShiftError(CozyKitMainError):
    pass


class EmptyTextError(CozyKitMainError):
    pass


# ============= TextCustomizations ERRORS =============


class InvalidStyleError(CozyKitMainError):
    pass


# ============= Greeting ERRORS =============


class InvalidStoryError(CozyKitMainError):
    pass


class InvalidMotivationError(CozyKitMainError):
    pass


class InvalidFunFactError(CozyKitMainError):
    pass


# ============= JSON ERRORS =============


class DatabaseNotFoundError(CozyKitMainError):
    pass


# ============= SMTPMailer ERRORS =============


class UnfilledPasswordAndEmailError(CozyKitMainError):
    pass


class NoRecipientError(CozyKitMainError):
    pass


class AttachmentNotFoundError(CozyKitMainError):
    pass
