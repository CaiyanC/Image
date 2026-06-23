import argparse
import asyncio
import json
import os
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import redis

try:
    import psycopg2
except ImportError:  # pragma: no cover - optional at runtime
    psycopg2 = None


QUESTIONS = [
    "LOADTEST_RUN_ID={run_id} 推荐三款适合露营多人做饭的套锅，并说明区别。",
    "LOADTEST_RUN_ID={run_id} 这款产品适合新手户外用户吗？请给出卖点。",
    "LOADTEST_RUN_ID={run_id} 客户想要轻量便携，预算中等，应该怎么推荐？",
    "LOADTEST_RUN_ID={run_id} 对比一下高端和入门款，分别适合什么客户。",
    "LOADTEST_RUN_ID={run_id} 继续上一个问题，帮我整理成客服回复话术。",
]


@dataclass
class Result:
    name: str
    status: int
    latency_ms: float
    error: str = ""


@dataclass
class Stats:
    results: list[Result] = field(default_factory=list)
    stop_reason: str | None = None
    monitor_samples: list[dict[str, Any]] = field(default_factory=list)
    worker_prev_cpu: dict[int, float] = field(default_factory=dict)
    worker_prev_at: float | None = None

    def add(self, result: Result) -> None:
        self.results.append(result)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = min(len(values) - 1, max(0, int(round((pct / 100.0) * (len(values) - 1)))))
    return values[index]


def summarize(stats: Stats) -> dict[str, Any]:
    latencies = [r.latency_ms for r in stats.results if r.status < 500 and not r.error]
    total = len(stats.results)
    status_counts: dict[str, int] = {}
    for result in stats.results:
        key = str(result.status) if result.status else "exception"
        status_counts[key] = status_counts.get(key, 0) + 1
    errors = [r for r in stats.results if r.status >= 400 or r.error]
    return {
        "total_requests": total,
        "success_rate": round((total - len(errors)) / total, 4) if total else 0,
        "status_counts": status_counts,
        "error_rate_4xx": round(sum(1 for r in stats.results if 400 <= r.status < 500) / total, 4) if total else 0,
        "error_rate_5xx": round(sum(1 for r in stats.results if r.status >= 500) / total, 4) if total else 0,
        "timeout_or_exception": sum(1 for r in stats.results if r.status == 0),
        "p50_ms": round(statistics.median(latencies), 2) if latencies else 0,
        "p95_ms": round(percentile(latencies, 95), 2),
        "p99_ms": round(percentile(latencies, 99), 2),
        "stop_reason": stats.stop_reason,
        "db_connections_peak": max((s.get("db_connections") or 0 for s in stats.monitor_samples), default=0),
        "redis_ops_peak": max((s.get("redis_ops_per_sec") or 0 for s in stats.monitor_samples), default=0),
        "worker_cpu_peak_percent": max((s.get("worker_cpu_percent_total") or 0 for s in stats.monitor_samples), default=0),
        "worker_memory_peak_mb": max((s.get("worker_memory_total_mb") or 0 for s in stats.monitor_samples), default=0),
        "last_monitor_sample": stats.monitor_samples[-1] if stats.monitor_samples else None,
    }


async def request_json(client: httpx.AsyncClient, method: str, path: str, **kwargs: Any) -> Any:
    response = await client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json()


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    data = await request_json(client, "POST", "/api/auth/login", json={"username": username, "password": password})
    return data["access_token"]


async def prepare_users(args: argparse.Namespace) -> list[tuple[str, str]]:
    password = args.test_password
    users = [(f"{args.user_prefix}{i:02d}", password) for i in range(1, args.users + 1)]
    async with httpx.AsyncClient(base_url=args.base_url, timeout=30) as client:
        admin_token = await login(client, args.admin_username, args.admin_password)
        headers = {"Authorization": f"Bearer {admin_token}"}
        groups = await request_json(client, "GET", "/api/admin/groups", headers=headers)
        customer_group = next((g for g in groups if g.get("group_name") == "客服团队"), None)
        if not customer_group:
            raise RuntimeError("客服团队 group not found")
        existing = await request_json(client, "GET", "/api/users?skip=0&limit=200", headers=headers)
        existing_names = {item["username"] for item in existing}
        for username, user_password in users:
            if username in existing_names:
                continue
            await request_json(
                client,
                "POST",
                "/api/users",
                headers=headers,
                json={
                    "username": username,
                    "password": user_password,
                    "display_name": f"Load Test {username}",
                    "email": f"{username}@loadtest.local",
                    "group_id": customer_group["id"],
                    "group_role": "member",
                },
            )
    return users


async def ask_stream(client: httpx.AsyncClient, question: str, conversation_id: str | None) -> tuple[int, str | None]:
    conversation = conversation_id
    async with client.stream(
        "POST",
        "/api/customer-service/ask-stream",
        json={"question": question, "conversation_id": conversation},
        timeout=150,
    ) as response:
        body = ""
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                body = line[5:].strip()
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    continue
                if payload.get("conversation_id"):
                    conversation = payload["conversation_id"]
        return response.status_code, conversation


async def virtual_user(
    args: argparse.Namespace,
    username: str,
    password: str,
    run_id: str,
    end_at: float,
    stats: Stats,
) -> None:
    timeout = httpx.Timeout(connect=10, read=160, write=20, pool=20)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout) as client:
        try:
            token = await login(client, username, password)
        except Exception as exc:
            stats.add(Result("login", 0, 0, repr(exc)))
            return
        client.headers.update({"Authorization": f"Bearer {token}"})
        conversation_id = None
        product_skus: list[str] = []
        question_index = 0
        while time.monotonic() < end_at and not stats.stop_reason:
            scenario = question_index % 3
            started = time.perf_counter()
            try:
                if scenario == 0:
                    response = await client.get("/api/products?skip=0&limit=10")
                    status = response.status_code
                    if response.status_code < 400:
                        payload = response.json()
                        product_skus = [item.get("sku") for item in payload.get("items", []) if item.get("sku")]
                    name = "products.list"
                elif scenario == 1 and product_skus:
                    sku = product_skus[question_index % len(product_skus)]
                    response = await client.get(f"/api/products/by-sku/{sku}")
                    status = response.status_code
                    name = "products.detail"
                else:
                    question = QUESTIONS[question_index % len(QUESTIONS)].format(run_id=run_id)
                    status, conversation_id = await ask_stream(client, question, conversation_id)
                    name = "customer.ask_stream"
                latency_ms = (time.perf_counter() - started) * 1000
                stats.add(Result(name, status, latency_ms))
            except Exception as exc:
                latency_ms = (time.perf_counter() - started) * 1000
                stats.add(Result("scenario", 0, latency_ms, repr(exc)))
            question_index += 1
            await asyncio.sleep(args.user_think_seconds)


def db_connections(database_url: str | None, target_db: str) -> int | None:
    if not database_url or psycopg2 is None:
        return None
    database_url = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = %s", (target_db,))
            return int(cursor.fetchone()[0])
    finally:
        conn.close()


def redis_sample(redis_url: str | None) -> dict[str, Any]:
    if not redis_url:
        return {}
    client = redis.Redis.from_url(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
    info = client.info()
    return {
        "redis_connected_clients": info.get("connected_clients"),
        "redis_ops_per_sec": info.get("instantaneous_ops_per_sec"),
        "redis_used_memory_human": info.get("used_memory_human"),
        "redis_dbsize": client.dbsize(),
    }


def worker_sample(port: int, stats: Stats) -> dict[str, Any]:
    command = (
        f"$candidates=Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -like '*--port {port}*' }}; "
        "$parent=($candidates | ForEach-Object { "
        "$candidatePid=$_.ProcessId; "
        "$children=(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $candidatePid }).Count; "
        "[PSCustomObject]@{Pid=$candidatePid; Children=$children} "
        "} | Sort-Object Children -Descending | Select-Object -First 1 -ExpandProperty Pid); "
        "if ($parent) { "
        "$ids=@($parent)+(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $parent } | Select-Object -ExpandProperty ProcessId); "
        "Get-Process -Id $ids | Select-Object Id,CPU,WorkingSet64 | ConvertTo-Json -Compress "
        "}"
    )
    try:
        output = subprocess.check_output(["powershell", "-NoProfile", "-Command", command], text=True, timeout=5)
        raw = output.strip()
        if not raw:
            return {"workers": []}
        parsed = json.loads(raw)
        rows = parsed if isinstance(parsed, list) else [parsed]
        now = time.monotonic()
        cpu_percent_total = 0.0
        if stats.worker_prev_at is not None:
            elapsed = max(now - stats.worker_prev_at, 0.001)
            logical_cpus = max(os.cpu_count() or 1, 1)
            for row in rows:
                pid = int(row["Id"])
                cpu = float(row.get("CPU") or 0.0)
                previous = stats.worker_prev_cpu.get(pid)
                if previous is not None:
                    cpu_percent_total += max(cpu - previous, 0.0) / elapsed / logical_cpus * 100.0
        stats.worker_prev_at = now
        stats.worker_prev_cpu = {int(row["Id"]): float(row.get("CPU") or 0.0) for row in rows}
        return {
            "worker_pids": [int(row["Id"]) for row in rows],
            "worker_cpu_percent_total": round(cpu_percent_total, 2),
            "worker_memory_total_mb": round(sum(int(row.get("WorkingSet64") or 0) for row in rows) / 1024 / 1024, 1),
        }
    except Exception as exc:
        return {"workers_error": repr(exc)}


async def monitor(args: argparse.Namespace, stats: Stats, end_at: float) -> None:
    async with httpx.AsyncClient(base_url=args.base_url, timeout=5) as client:
        while time.monotonic() < end_at and not stats.stop_reason:
            sample: dict[str, Any] = {"at": time.strftime("%Y-%m-%d %H:%M:%S")}
            try:
                health = await client.get("/api/health/ready")
                sample["health_status"] = health.status_code
                if health.status_code >= 500:
                    stats.stop_reason = f"health check failed: {health.status_code}"
            except Exception as exc:
                sample["health_error"] = repr(exc)
                stats.stop_reason = "health check exception"
            try:
                sample["db_connections"] = db_connections(args.database_url, args.database_name)
                if sample["db_connections"] and sample["db_connections"] >= args.db_connection_threshold:
                    stats.stop_reason = f"db connections reached {sample['db_connections']}"
            except Exception as exc:
                sample["db_error"] = repr(exc)
            try:
                sample.update(redis_sample(args.redis_url))
            except Exception as exc:
                sample["redis_error"] = repr(exc)
            sample.update(worker_sample(args.port, stats))
            stats.monitor_samples.append(sample)

            summary = summarize(stats)
            if summary["total_requests"] >= 20 and summary["error_rate_5xx"] > 0.01:
                stats.stop_reason = "5xx error rate exceeded 1%"
            recent = [r.latency_ms for r in stats.results[-40:] if r.status < 500 and not r.error]
            if len(recent) >= 10 and percentile(recent, 95) > 30000:
                stats.stop_reason = "recent p95 exceeded 30s"
            if sample.get("worker_cpu_percent_total", 0) > args.cpu_threshold_percent:
                stats.stop_reason = f"worker cpu exceeded {args.cpu_threshold_percent}%"
            await asyncio.sleep(args.monitor_interval)


async def run_load(args: argparse.Namespace) -> dict[str, Any]:
    users = await prepare_users(args)
    run_id = time.strftime("%Y%m%d_%H%M%S")
    stats = Stats()
    if args.warmup_seconds:
        warmup_end = time.monotonic() + args.warmup_seconds
        warmup_stats = Stats()
        await asyncio.gather(
            *[
                virtual_user(args, username, password, f"{run_id}_warmup", warmup_end, warmup_stats)
                for username, password in users
            ]
        )
    end_at = time.monotonic() + args.duration_seconds
    tasks = [monitor(args, stats, end_at)]
    tasks.extend(virtual_user(args, username, password, run_id, end_at, stats) for username, password in users)
    await asyncio.gather(*tasks)
    return summarize(stats)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Customer service load test for isolated backend instance.")
    parser.add_argument("--base-url", default=os.getenv("LOADTEST_BASE_URL", "http://127.0.0.1:8015"))
    parser.add_argument("--port", type=int, default=int(os.getenv("LOADTEST_PORT", "8015")))
    parser.add_argument("--admin-username", default=os.getenv("CAIYAN_ADMIN_USERNAME", "admin"))
    parser.add_argument("--admin-password", default=os.getenv("CAIYAN_ADMIN_PASSWORD", "admin123"))
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--user-prefix", default="loadtest_user_")
    parser.add_argument("--test-password", default=os.getenv("LOADTEST_USER_PASSWORD", "LoadTest123!"))
    parser.add_argument("--warmup-seconds", type=int, default=60)
    parser.add_argument("--duration-seconds", type=int, default=180)
    parser.add_argument("--user-think-seconds", type=float, default=1.0)
    parser.add_argument("--monitor-interval", type=int, default=5)
    parser.add_argument("--database-url", default=os.getenv("LOADTEST_DATABASE_URL"))
    parser.add_argument("--database-name", default=os.getenv("LOADTEST_DATABASE_NAME", "product_knowledge_loadtest"))
    parser.add_argument("--redis-url", default=os.getenv("LOADTEST_REDIS_URL", "redis://localhost:6379/15"))
    parser.add_argument("--db-connection-threshold", type=int, default=80)
    parser.add_argument("--cpu-threshold-percent", type=float, default=85.0)
    parser.add_argument("--prepare-users", action="store_true")
    parser.add_argument("--run", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.prepare_users and not args.run:
        users = await prepare_users(args)
        print(json.dumps({"prepared_users": len(users), "base_url": args.base_url}, ensure_ascii=False))
        return
    if not args.run:
        print(json.dumps({"ok": False, "message": "Pass --run to start the load test."}, ensure_ascii=False))
        return
    summary = await run_load(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
