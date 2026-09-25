"""Single application instance per private data directory (macOS/Linux)."""
import os
from pathlib import Path


class InstanceLock:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.fd = None

    def __enter__(self):
        import fcntl
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.directory / "app.lock"
        self.fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.fchmod(self.fd, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            os.close(self.fd)
            self.fd = None
            raise RuntimeError("这个数据目录已有轻邮在运行，请回到已打开的窗口。") from None
        return self

    def __exit__(self, *args):
        if self.fd is not None:
            import fcntl
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None
