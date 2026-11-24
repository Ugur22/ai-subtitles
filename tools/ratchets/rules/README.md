One test file per ratchet rule (`test_<rule>.py`), each with a collector registered in `../tighten.py` and a
passing and a failing fixture case. `make check` runs this directory; the machinery's own tests
(`../test_framework.py`) run in CI's tooling job.
