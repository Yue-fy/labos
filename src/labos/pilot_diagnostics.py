"""Bounded in-memory engine evidence; observation never controls acquisition."""

from contextlib import contextmanager


class RunEvidence:
    """Store completed spans and publish copied start/completion records.

    Callback-only ``started`` records have zero duration. They make a blocked
    stage visible without counting an unfinished span as a completed one.
    """

    def __init__(self, result, clock, start, observer=None, on_failure=None):
        self.result = result
        self.clock = clock
        self.start = start
        self.observer = observer
        self.on_failure = on_failure
        self.run_deadline = None
        self.phase_deadline = None
        self.context = ("run", None)
        result["timing"] = {"stages": [], "dropped_count": 0, "total_elapsed_s": 0}

    def _observe(self, record):
        if self.observer is not None:
            try:
                self.observer(dict(record))
            except BaseException:
                # Telemetry, including an observer interrupt, cannot skip protection.
                pass

    def fail(self, error, stage=None, phase=None):
        if self.result["failure"] is not None:
            return
        now = self.clock()
        run_expired = self.run_deadline is not None and now >= self.run_deadline
        phase_expired = self.phase_deadline is not None and now >= self.phase_deadline
        scope = ("run_and_phase" if run_expired and phase_expired else
                 "run" if run_expired else "phase" if phase_expired else None)
        effective = ("run" if self.phase_deadline is None else
                     "run_and_phase" if self.phase_deadline == self.run_deadline else
                     "phase" if self.phase_deadline < self.run_deadline else "run")
        self.result["failure"] = {
            "stage": stage or self.context[0],
            "phase": phase if stage is not None else self.context[1],
            "exception_type": type(error).__name__, "elapsed_s": now - self.start,
            "deadline": {"scope": scope, "run_exhausted": run_expired,
                         "phase_exhausted": phase_expired, "effective_scope": effective}}
        if self.on_failure is not None:
            try:
                self.on_failure()
            except BaseException:
                pass

    @contextmanager
    def stage(self, name, phase=None):
        self.context = (name, phase)
        started = self.clock()
        record = {"stage": name, "phase": phase, "started_elapsed_s": started - self.start,
                  "duration_s": 0, "outcome": "started"}
        self._observe(record)
        try:
            yield
        except BaseException as exc:
            record["outcome"] = "failed"
            self.fail(exc, name, phase)
            raise
        else:
            record["outcome"] = "completed"
        finally:
            record["duration_s"] = self.clock() - started
            timing = self.result["timing"]
            if len(timing["stages"]) < 256:
                timing["stages"].append(record)
            else:
                timing["dropped_count"] += 1
            self._observe(record)
            self.finish()

    def finish(self):
        self.result["timing"]["total_elapsed_s"] = self.clock() - self.start
