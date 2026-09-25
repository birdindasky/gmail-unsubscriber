"""Private verification timings, without message IDs, DNS names or mail data.

Each opaque trace belongs to one selected representative message. Events are
fsynced before/after operations; failure stops preview instead of losing evidence.
Counts describe library calls, not packets or resolver-internal retries.
"""
import json
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path


class TraceError(RuntimeError):
    pass


class VerificationTrace:
    def __init__(self, directory):
        self.id = uuid.uuid4().hex
        self.path = Path(directory) / (self.id + ".jsonl")
        self.sequence = 0
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.path.parent.is_symlink():
                raise OSError()
            self.path.parent.chmod(0o700)
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        except OSError:
            raise TraceError("无法保存核验记录，已停止预览。") from None

    def event(self, operation, state, *, attempt=0, reason="none"):
        # Deliberate closed vocabulary: never accept an exception/URL as text.
        if operation not in {"verification", "metadata", "raw", "dns", "dkim"} or state not in {"start", "ok", "failed", "cancelled", "unverified", "verified"} or reason not in {"none", "retryable", "terminal", "cancelled", "no_answer"} or type(attempt) is not int or not 0 <= attempt <= 8:
            raise TraceError("核验记录格式无效，已停止预览。")
        record = dict(sequence=self.sequence + 1, time=datetime.now(timezone.utc).isoformat(),
                      operation=operation, state=state, attempt=attempt, reason=reason)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
            with os.fdopen(fd, "a", encoding="utf-8") as output:
                if not stat.S_ISREG(os.fstat(output.fileno()).st_mode):
                    raise OSError()
                output.write(json.dumps(record) + "\n")
                output.flush()
                os.fsync(output.fileno())
            self.sequence += 1
        except OSError:
            raise TraceError("无法保存核验记录，已停止预览。") from None
