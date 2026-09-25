import pytest
from gmail_unsubscriber.runtime import InstanceLock


def test_one_instance_per_directory_and_release(tmp_path):
    with InstanceLock(tmp_path):
        with pytest.raises(RuntimeError):
            with InstanceLock(tmp_path):
                pass
        with InstanceLock(tmp_path / "different-account-directory"):
            pass
    with InstanceLock(tmp_path):
        assert (tmp_path / "app.lock").stat().st_mode & 0o777 == 0o600
