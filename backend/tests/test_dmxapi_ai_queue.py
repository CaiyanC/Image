import asyncio
import unittest

from app.services import dmxapi_service


class AiRequestQueueTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_semaphore = dmxapi_service._AI_SEMAPHORE
        self.original_max = dmxapi_service.settings.AI_MAX_CONCURRENT_REQUESTS
        self.original_queue_timeout = dmxapi_service.settings.AI_REQUEST_QUEUE_TIMEOUT_SECONDS
        self.original_trace = dmxapi_service.agent_trace_service.trace
        self.original_log_event = dmxapi_service.customer_perf_service.log_event
        self.events = []
        dmxapi_service._AI_SEMAPHORE = asyncio.Semaphore(1)
        dmxapi_service.settings.AI_MAX_CONCURRENT_REQUESTS = 1
        dmxapi_service.settings.AI_REQUEST_QUEUE_TIMEOUT_SECONDS = 0.2
        dmxapi_service.agent_trace_service.trace = lambda stage, payload: self.events.append((stage, payload))
        dmxapi_service.customer_perf_service.log_event = (
            lambda stage, **payload: self.events.append((stage, payload))
        )

    def tearDown(self):
        dmxapi_service._AI_SEMAPHORE = self.original_semaphore
        dmxapi_service.settings.AI_MAX_CONCURRENT_REQUESTS = self.original_max
        dmxapi_service.settings.AI_REQUEST_QUEUE_TIMEOUT_SECONDS = self.original_queue_timeout
        dmxapi_service.agent_trace_service.trace = self.original_trace
        dmxapi_service.customer_perf_service.log_event = self.original_log_event

    async def test_waits_for_available_slot_instead_of_rejecting_immediately(self):
        async def slow_request():
            await asyncio.sleep(0.05)
            return "first"

        async def fast_request():
            return "second"

        first = asyncio.create_task(dmxapi_service._run_ai_request(slow_request, timeout=1))
        await asyncio.sleep(0.01)

        started = asyncio.get_running_loop().time()
        second = await dmxapi_service._run_ai_request(fast_request, timeout=1)
        elapsed = asyncio.get_running_loop().time() - started

        self.assertEqual(await first, "first")
        self.assertEqual(second, "second")
        self.assertGreaterEqual(elapsed, 0.03)
        wait_events = [payload for stage, payload in self.events if stage == "ai_semaphore_wait"]
        self.assertTrue(any(event["acquired"] for event in wait_events))
        self.assertTrue(any(event["ai_semaphore_wait_ms"] > 0 for event in wait_events))

    async def test_raises_after_queue_timeout_when_slot_is_not_available(self):
        await dmxapi_service._AI_SEMAPHORE.acquire()

        async def request():
            return "never"

        dmxapi_service.settings.AI_REQUEST_QUEUE_TIMEOUT_SECONDS = 0.01
        try:
            with self.assertRaises(RuntimeError):
                await dmxapi_service._run_ai_request(request, timeout=1)
        finally:
            dmxapi_service._AI_SEMAPHORE.release()

        wait_events = [payload for stage, payload in self.events if stage == "ai_semaphore_wait"]
        self.assertTrue(any(not event["acquired"] for event in wait_events))


if __name__ == "__main__":
    unittest.main()
