# Rebuilding the restricted local v2 delivery

Validated platform: macOS arm64, CPython 3.14.4. No system installation, service registration, signing or packaging is included.

The runtime lock is `requirements-v2.lock`. The test lock, `requirements-v2-test.lock`, includes the runtime plus pytest and its supporting packages. The older range-based requirements files remain historical inputs, not the reproducible delivery instructions.

From the project directory, with a destination environment that does not already exist:

```sh
python3 -m venv .venv-v2
.venv-v2/bin/python -m pip install -r requirements-v2-test.lock
.venv-v2/bin/python -m pip check
.venv-v2/bin/python -m pytest tests_v2 -q
```

For runtime-only setup, use `requirements-v2.lock` instead of the test lock. Do not overwrite an existing environment. Launchers select `.venv-v2-p5` first when present, then `.venv-v2`; they never fall back to legacy `venv` or system Python. Dependency checks reject missing/incomplete imports. Other Python versions and machines are not validated.

Package retrieval uses the configured package index. This is an exact-version dependency lock, not an offline wheel archive or a package-content hash lock. A future unavailable index/version can prevent reconstruction; retain the actual failure rather than assuming a working existing environment proves a new install. No pip upgrade is necessary.

The test suite uses synthetic data in temporary directories. The public test command does not require a real Gmail account or sender endpoint.

Local trial and acceptance records may contain private usage details and are intentionally excluded from the public repository. A fresh install and test run should be assessed from its own command output; a successful prior run on another machine does not prove this machine is ready.

Native Finder double-click and security dialogs remain NOT_RUN if exclusive desktop ownership cannot be confirmed. Shell-launcher execution and isolated browser checks are not native desktop acceptance. Live Gmail and sender requests are outside P5.
