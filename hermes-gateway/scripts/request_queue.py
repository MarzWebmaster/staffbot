#!/usr/bin/env python3
"""
StaffBot.my — Request Queue
============================
Per-client FIFO queue for LLM calls. Prevents overload when multiple
conversations from the same client hit the LLM simultaneously.

Architecture:
  - One asyncio.Queue per client_id
  - Semaphore limits concurrent LLM calls per client
  - Configurable max concurrency per package
  - Timeout for stale requests (prevents queue buildup)

Usage:
  from request_queue import RequestQueue
  
  queue = RequestQueue()
  
  # Enqueue and wait for turn
  result = await queue.enqueue(
      client_id=1,
      coro=call_llm(prompt)
  )
"""

import asyncio
import time
import argparse
from typing import Callable, Coroutine, Any, Optional


# Per-package concurrency limits
MAX_CONCURRENT = {
    "trial": 1,
    "basic": 2,
    "pro": 5,
    "enterprise": 10,
}

REQUEST_TIMEOUT = 120  # seconds — max time a request can wait in queue


class RequestQueue:
    """Per-client FIFO queue with concurrency limits."""

    def __init__(self, max_concurrent_default: int = 3):
        self._queues: dict[int, asyncio.Queue] = {}
        self._semaphores: dict[int, asyncio.Semaphore] = {}
        self._max_concurrent_default = max_concurrent_default
        self._client_packages: dict[int, str] = {}
        self._lock = asyncio.Lock()

    def _get_max_concurrent(self, client_id: int) -> int:
        """Get max concurrent LLM calls for a client."""
        package = self._client_packages.get(client_id, "basic")
        return MAX_CONCURRENT.get(package, self._max_concurrent_default)

    async def _ensure_bucket(self, client_id: int):
        """Create queue and semaphore if not exists."""
        if client_id not in self._queues:
            self._queues[client_id] = asyncio.Queue()
            self._semaphores[client_id] = asyncio.Semaphore(
                self._get_max_concurrent(client_id)
            )

    async def enqueue(self, client_id: int, coro: Coroutine) -> Any:
        """Enqueue a coroutine and wait for execution slot."""
        async with self._lock:
            await self._ensure_bucket(client_id)

        # Start worker if not running
        semaphore = self._semaphores[client_id]
        
        async with semaphore:
            try:
                result = await asyncio.wait_for(coro, timeout=REQUEST_TIMEOUT)
                return result
            except asyncio.TimeoutError:
                raise TimeoutError(f"Request for client #{client_id} timed out")

    async def _worker(self, client_id: int):
        """Background worker that processes queue for a client."""
        queue = self._queues.get(client_id)
        semaphore = self._semaphores.get(client_id)

        if not queue or not semaphore:
            return

        while True:
            try:
                # Get next request
                coro, future, enqueue_time = await queue.get()

                # Check if expired
                if time.monotonic() - enqueue_time > REQUEST_TIMEOUT:
                    if not future.done():
                        future.set_exception(TimeoutError("Request expired in queue"))
                    queue.task_done()
                    continue

                # Execute with semaphore
                async with semaphore:
                    try:
                        result = await coro
                        if not future.done():
                            future.set_result(result)
                    except Exception as e:
                        if not future.done():
                            future.set_exception(e)

                queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def start_workers(self):
        """Start background workers for all known clients."""
        for client_id in list(self._queues.keys()):
            asyncio.create_task(self._worker(client_id))

    async def set_package(self, client_id: int, package: str):
        """Update client package — resizes semaphore."""
        async with self._lock:
            self._client_packages[client_id] = package
            if client_id in self._semaphores:
                # Resize semaphore by recreating
                new_limit = self._get_max_concurrent(client_id)
                self._semaphores[client_id] = asyncio.Semaphore(new_limit)

    async def get_stats(self, client_id: int) -> dict:
        """Get queue stats for a client."""
        queue = self._queues.get(client_id)
        semaphore = self._semaphores.get(client_id)

        return {
            "queue_size": queue.qsize() if queue else 0,
            "max_concurrent": self._get_max_concurrent(client_id),
            "semaphore_available": semaphore._value if semaphore else 0 if semaphore else 0,
        }

    def get_all_stats(self) -> dict:
        """Get stats for all clients."""
        return {
            cid: {
                "queue_size": self._queues[cid].qsize() if cid in self._queues else 0,
                "max_concurrent": self._get_max_concurrent(cid),
            }
            for cid in set(list(self._queues.keys()) + list(self._client_packages.keys()))
        }


# ── CLI for testing ─────────────────────────────────────────────────────

async def _cli_test(client_id: int):
    """Test the queue with a simulated LLM call."""
    queue = RequestQueue()

    async def fake_llm():
        await asyncio.sleep(1)
        return f"LLM response for client #{client_id}"

    print(f"Enqueuing request for client #{client_id}...")
    result = await queue.enqueue(client_id, fake_llm())
    print(f"Result: {result}")

    stats = await queue.get_stats(client_id)
    print(f"Stats: {stats}")


def main():
    parser = argparse.ArgumentParser(description="StaffBot Request Queue")
    sub = parser.add_subparsers(dest="command")

    p_test = sub.add_parser("test")
    p_test.add_argument("--client-id", type=int, required=True)

    p_stats = sub.add_parser("stats")
    p_stats.add_argument("--client-id", type=int, required=True)

    args = parser.parse_args()

    if args.command == "test":
        asyncio.run(_cli_test(args.client_id))
    elif args.command == "stats":
        queue = RequestQueue()
        stats = asyncio.run(queue.get_stats(args.client_id))
        print(stats)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
