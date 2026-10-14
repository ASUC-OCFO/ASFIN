from concurrent.futures import Future, ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=4)


def submit(fn, *args, **kwargs) -> Future:
    """Submit a callable to the shared thread pool. Returns a Future.

    Interface is intentionally minimal: swap _executor for a Celery task
    and callers require zero changes.
    """
    return _executor.submit(fn, *args, **kwargs)
