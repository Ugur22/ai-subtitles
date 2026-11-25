import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import polling  # noqa: E402
import ratchet  # noqa: E402

RULE = "polling"
FIX = ("A loop that calls the backend must stop when the work is done or failed, back off, and not run in a hidden "
       "tab. Prefer the existing hooks (useJobTracker, useSupabaseRealtime). A local UI tick or a bounded retry is "
       "an owner exception: say why in the PR description.")

LOOPS = '''\
function poll() {
  fetch("/api/jobs");
  timer = setTimeout(poll, 2000);
}
const tick = useCallback(async () => {
  await load();
  setTimeout(() => {
    void tick();
  }, 500);
}, []);
const id = setInterval(() => api.get("/api/jobs"), 2000);
useQuery({ queryKey: ["job"], refetchInterval: 2000 });
await new Promise((r) => setTimeout(r, 1000));
await new Promise((resolve) => {
  setTimeout(resolve, 1000);
});
class Poller {
  async poll(): Promise<void> {
    await this.load();
    setTimeout(() => this.poll(), 1000);
  }
}
const again = () => setTimeout(again, 1000);
const typed: () => void = () => {
  setTimeout(typed, 1000);
};
'''

NOT_LOOPS = '''\
const center = () => { measure(); };
const timer = setTimeout(center, 50);
const el = ref.current;
if (ok) {
  setTimeout(() => el?.focus(), 0);
}
useQuery({ queryKey: ["job"], refetchInterval: false });
// setInterval(() => api.get("/api/jobs"), 2000);
const doc = "setInterval(";
/* poll(); setTimeout(poll, 1) */
const focus = () => {
  setTimeout(() => ref.current?.focus(), 0);
};
const f = () => g()
useEffect(() => {
  setTimeout(() => f(), 1);
});
'''


def kinds(text):
    lines = text.splitlines()
    return {lines[n].strip(): kind for n, kind in polling.loops_by_line_index(text).items()}


def test_no_new_polling_loop():
    ratchet.assert_no_new(RULE, polling.collect(), FIX)


def test_every_exception_has_a_reason():
    assert ratchet.short_reasons(RULE) == {}


def test_loops_are_found():
    assert kinds(LOOPS) == {
        "timer = setTimeout(poll, 2000);": "setTimeout re-scheduling itself",
        "setTimeout(() => {": "setTimeout re-scheduling itself",
        'const id = setInterval(() => api.get("/api/jobs"), 2000);': "setInterval",
        'useQuery({ queryKey: ["job"], refetchInterval: 2000 });': "refetchInterval",
        "await new Promise((r) => setTimeout(r, 1000));": "sleep",
        "await new Promise((resolve) => {": "sleep",
        "setTimeout(() => this.poll(), 1000);": "setTimeout re-scheduling itself",
        "const again = () => setTimeout(again, 1000);": "setTimeout re-scheduling itself",
        "setTimeout(typed, 1000);": "setTimeout re-scheduling itself",
    }


def test_one_shot_timers_comments_and_strings_are_not_loops():
    assert kinds(NOT_LOOPS) == {}


def test_a_copy_of_an_excepted_line_is_a_new_violation(tmp_path):
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    line = "const id = setInterval(() => {}, 1000);\n"
    (src / "a.ts").write_text(line + line)
    assert list(polling.collect(tmp_path)) == [f"frontend/src/a.ts::{line.strip()}",
                                               f"frontend/src/a.ts::{line.strip()}#2"]


def test_a_new_poll_fails_and_tests_are_not_scanned(tmp_path):
    src = tmp_path / "frontend" / "src"
    (src / "hooks").mkdir(parents=True)
    (src / "hooks" / "useStatus.ts").write_text('const id = setInterval(() => api.get("/api/status"), 2000);\n')
    (src / "hooks" / "useStatus.test.ts").write_text("setInterval(() => {}, 1);\n")
    (src / "__tests__").mkdir()
    (src / "__tests__" / "x.ts").write_text("setInterval(() => {}, 1);\n")
    current = polling.collect(tmp_path)
    assert list(current) == ['frontend/src/hooks/useStatus.ts::const id = setInterval(() => api.get("/api/status"), 2000);']
    empty = tmp_path / "baseline.json"
    empty.write_text('{"version": 1, "rules": {}}')
    with pytest.raises(AssertionError, match="useStatus.ts"):
        ratchet.assert_no_new(RULE, current, FIX, empty)
