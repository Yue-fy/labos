"""Cooperative operation deadlines and terminal backend admission failures."""
from __future__ import annotations

import time


class OperationStopped(RuntimeError):
    """Terminal control failure: never use another backend in this operation."""


class OperationCancelled(OperationStopped):
    pass


class OperationDeadlineExceeded(OperationStopped):
    pass


class InvocationBudgetExhausted(OperationStopped):
    pass


class ReservationFailed(OperationStopped):
    pass


class ProcessCleanupFailed(OperationStopped):
    pass


class BackendAttemptTimeout(RuntimeError):
    """An individual backend expired while aggregate time may remain."""


class InputTooLarge(ValueError):
    pass


class Operation:
    """One active preparation/dispatch cycle; callers may pass check to preparation."""

    def __init__(self, timeout, *, clock=None, stopped=None):
        self.clock = clock or time.monotonic
        self.stopped = stopped or (lambda: False)
        self.deadline = self.clock() + timeout

    def check(self):
        if self.stopped():
            raise OperationCancelled("Report operation cancelled")
        if self.clock() >= self.deadline:
            raise OperationDeadlineExceeded("Report operation deadline exceeded")

    def remaining(self):
        self.check()
        return self.deadline - self.clock()

    def attempt_remaining(self, deadline):
        self.check()
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise BackendAttemptTimeout("Backend attempt deadline exceeded")
        return remaining
