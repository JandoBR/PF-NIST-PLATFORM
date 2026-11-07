import threading
import time

from app.ai.parallel import concurrency, map_ordered, slot


def test_map_ordered_keeps_input_order_even_when_tasks_finish_out_of_order():
    def work(n):
        time.sleep(0.05 if n == 0 else 0)
        return n

    assert map_ordered(work, range(8)) == list(range(8))


def test_map_ordered_runs_tasks_concurrently(monkeypatch):
    monkeypatch.setenv("AI_MAX_CONCURRENCY", "4")
    barrier = threading.Barrier(4, timeout=2)

    def work(n):
        barrier.wait()
        return n

    assert map_ordered(work, range(4)) == [0, 1, 2, 3]


def test_concurrency_one_is_sequential(monkeypatch):
    monkeypatch.setenv("AI_MAX_CONCURRENCY", "1")
    main = threading.get_ident()
    assert map_ordered(lambda _: threading.get_ident(), range(3)) == [main] * 3


def test_invalid_concurrency_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("AI_MAX_CONCURRENCY", "abc")
    assert concurrency() == 6
    monkeypatch.setenv("AI_MAX_CONCURRENCY", "0")
    assert concurrency() == 1


def test_slot_limits_simultaneous_calls(monkeypatch):
    monkeypatch.setenv("AI_MAX_CONCURRENCY", "2")
    active = peak = 0
    lock = threading.Lock()

    def call(_):
        nonlocal active, peak
        with slot():
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1

    threads = [threading.Thread(target=call, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak <= 2


def test_call_context_reaches_worker_threads():
    from app.ai.calllog import call_context, current_context

    with call_context(paso="U1"):
        assert map_ordered(lambda _: current_context().get("paso"), range(3)) == ["U1"] * 3
