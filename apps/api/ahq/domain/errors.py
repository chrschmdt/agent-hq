from __future__ import annotations


class AhqError(Exception):
    pass


class NotFoundError(AhqError):
    pass


class ConflictError(AhqError):
    pass


class InvalidRequest(AhqError):
    pass


class RetryLater(AhqError):
    def __init__(self, after_seconds: float, reason: str) -> None:
        super().__init__(f"retry in {after_seconds}s: {reason}")
        self.after_seconds = after_seconds
        self.reason = reason


def deferral(error: BaseException) -> RetryLater | None:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, RetryLater):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


class ConfigurationError(AhqError):
    pass


class DuplicateCall(ConflictError):
    def __init__(self, key: str) -> None:
        super().__init__(f"tool call {key} was already recorded")
        self.key = key
