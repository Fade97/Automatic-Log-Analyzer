"""RAM sampling thread for memory profiling."""
import tracemalloc
from time import sleep


def _sample_ram(samples, stop_event, interval=0.01):
    """Sample current traced-memory usage at a regular interval.

    Intended to run in a daemon thread. Appends byte counts to `samples`
    until `stop_event` is set.

    Args:
        samples (list): Mutable list to append memory readings (bytes) to.
        stop_event (threading.Event): Signal to stop sampling.
        interval (float): Seconds between samples. Defaults to 0.01.
    """
    tracemalloc.start()
    while not stop_event.is_set():
        current, _ = tracemalloc.get_traced_memory()
        samples.append(current)
        sleep(interval)
    tracemalloc.stop()
