"""Bounded episode scheduling shared by validation and standalone evaluation.

Each task runs an existing benchmark episode loop. Executors own placement,
transports and result handling; the scheduler only admits and refills work.
"""

from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import FIRST_COMPLETED, wait as wait_futures


def run_bounded(
    items: Iterable,
    slots: Sequence,
    *,
    submit: Callable,
    wait: Callable,
    consume: Callable,
    cancel: Callable,
) -> None:
    """Keep one episode per compatible slot; refill the slot that finishes.

    Run separately for each resource class. References and payloads stay in the
    executor's transport. Cancellation only targets work submitted by this call.
    ``consume(item, reference)`` resolves the result and handles executor errors.
    """
    if not slots:
        raise ValueError("Evaluation requires at least one execution slot")
    source = iter(items)
    pending = {}

    def refill(slot):
        try:
            item = next(source)
        except StopIteration:
            return
        reference = submit(item, slot)
        if reference in pending:
            raise ValueError("Executor returned a duplicate pending reference")
        pending[reference] = (item, slot)

    try:
        for slot in slots:
            refill(slot)
        while pending:
            ready = wait(list(pending))
            if not ready:
                raise RuntimeError("Evaluation executor wait returned no completed work")
            # Consume all ready items before admitting more. A failed consumer
            # must not silently start additional episodes.
            free = []
            for reference in ready:
                item, slot = pending.pop(reference)
                consume(item, reference)
                free.append(slot)
            for slot in free:
                refill(slot)
    finally:
        for reference in pending:
            cancel(reference)


def map_evaluation(executor, function: Callable, items: Iterable, *, capacity: int, on_result=None) -> list:
    """Bounded process/thread execution with results in ledger order."""
    ordered = {}

    def consume(item, future):
        ordered[item[0]] = future.result()
        if on_result is not None:
            on_result(ordered[item[0]])

    run_bounded(
        enumerate(items), range(capacity),
        submit=lambda item, slot: executor.submit(function, item[1]),
        wait=lambda refs: wait_futures(refs, return_when=FIRST_COMPLETED).done,
        consume=consume,
        cancel=lambda future: future.cancel(),
    )
    return [ordered[index] for index in range(len(ordered))]
