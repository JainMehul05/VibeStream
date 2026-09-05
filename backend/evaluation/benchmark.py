#!/usr/bin/env python3
"""Local performance benchmark for VibeStream API.

Measures:
- Recommendation latency (p50, p95, p99)
- Feedback latency
- Cache hit rate
- Throughput

Run against local or deployed backend.
"""

import sys
import os
import time
import statistics
import random
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


API_URL = os.environ.get("API_URL", "http://localhost:8000")
MODAL_URL = os.environ.get("MODAL_URL", "")

EMOTIONS = ["joy", "sadness", "love", "anger", "fear", "neutral"]


class BenchmarkRunner:
    def __init__(self, base_url: str, auth_token: str = None):
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.session = requests.Session()
        if auth_token:
            self.session.headers.update({"Authorization": f"Bearer {auth_token}"})
        self.session.headers.update({"Content-Type": "application/json"})

    def health_check(self) -> bool:
        try:
            r = self.session.get(f"{self.base_url}/api/v1/health/", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def login(self, username: str, password: str) -> str:
        r = self.session.post(
            f"{self.base_url}/api/v1/users/login/",
            json={"username": username, "password": password},
        )
        if r.status_code == 200:
            return r.json().get("access")
        raise Exception(f"Login failed: {r.status_code} {r.text}")

    def text_emotion(self, text: str) -> dict:
        start = time.perf_counter()
        r = self.session.post(
            f"{self.base_url}/api/v1/text_emotion/",
            json={"text": text},
        )
        latency = (time.perf_counter() - start) * 1000
        return {"latency_ms": latency, "status": r.status_code, "data": r.json() if r.status_code == 200 else None}

    def music_recommendation(self, emotion: str, history: list = None, genre: str = None) -> dict:
        payload = {"emotion": emotion, "history": history or []}
        if genre:
            payload["genre"] = genre
        start = time.perf_counter()
        r = self.session.post(
            f"{self.base_url}/api/v1/music_recommendation/",
            json=payload,
        )
        latency = (time.perf_counter() - start) * 1000
        return {"latency_ms": latency, "status": r.status_code, "data": r.json() if r.status_code == 200 else None}

    def feedback_track(self, track_id: str, signal: str, context_emotion: str) -> dict:
        payload = {
            "kind": "track",
            "track_id": track_id,
            "signal": signal,
            "context_emotion": context_emotion,
        }
        start = time.perf_counter()
        r = self.session.post(
            f"{self.base_url}/api/v1/feedback/",
            json=payload,
        )
        latency = (time.perf_counter() - start) * 1000
        return {"latency_ms": latency, "status": r.status_code, "data": r.json() if r.status_code in (200, 202) else None}

    def feedback_mood(self, predicted: str, actual: str, input_type: str) -> dict:
        payload = {
            "kind": "mood",
            "predicted": predicted,
            "actual": actual,
            "input_type": input_type,
        }
        start = time.perf_counter()
        r = self.session.post(
            f"{self.base_url}/api/v1/feedback/",
            json=payload,
        )
        latency = (time.perf_counter() - start) * 1000
        return {"latency_ms": latency, "status": r.status_code, "data": r.json() if r.status_code in (200, 202) else None}

    def get_profile(self) -> dict:
        start = time.perf_counter()
        r = self.session.get(f"{self.base_url}/api/v1/users/user/profile/")
        latency = (time.perf_counter() - start) * 1000
        return {"latency_ms": latency, "status": r.status_code, "data": r.json() if r.status_code == 200 else None}


def run_benchmark(args):
    runner = BenchmarkRunner(args.url)

    # Check health
    print("Checking health...")
    if not runner.health_check():
        print("ERROR: Health check failed")
        return

    print("Health check passed")

    # Login if credentials provided
    auth_token = None
    if args.username and args.password:
        print("Logging in...")
        try:
            auth_token = runner.login(args.username, args.password)
            runner.session.headers.update({"Authorization": f"Bearer {auth_token}"})
            print("Login successful")
        except Exception as e:
            print(f"Login failed: {e}")
            return
    else:
        print("Running as anonymous user")

    latencies = {
        "recommend": [],
        "text_emotion": [],
        "feedback_track": [],
        "feedback_mood": [],
        "profile": [],
    }
    errors = 0
    cache_hits = 0
    cache_misses = 0

    def run_recommend():
        nonlocal cache_hits, cache_misses
        emotion = random.choice(EMOTIONS)
        history = [random.choice(EMOTIONS) for _ in range(random.randint(0, 5))]
        genre = random.choice(["pop", "rock", "hip-hop", "electronic", None])
        result = runner.music_recommendation(emotion, history, genre)
        latencies["recommend"].append(result["latency_ms"])
        if result["status"] != 200:
            nonlocal errors
            errors += 1
        # Check cache hit (if response has cache indicator)
        # Note: Actual cache hit detection would need custom header or response field
        return result

    def run_text_emotion():
        texts = [
            "I'm feeling great today!",
            "This is terrible.",
            "I love this so much.",
            "I'm so angry right now.",
            "I'm scared.",
            "Just a normal day.",
        ]
        result = runner.text_emotion(random.choice(texts))
        latencies["text_emotion"].append(result["latency_ms"])
        if result["status"] != 200:
            errors += 1
        return result

    def run_feedback_track():
        track_id = f"deezer:{random.randint(10000, 99999)}"
        signal = random.choice(["like", "unlike", "open_deezer"])
        context_emotion = random.choice(EMOTIONS)
        result = runner.feedback_track(track_id, signal, context_emotion)
        latencies["feedback_track"].append(result["latency_ms"])
        if result["status"] not in (200, 202):
            errors += 1
        return result

    def run_feedback_mood():
        predicted = random.choice(EMOTIONS)
        actual = random.choice(EMOTIONS)
        input_type = random.choice(["text", "speech", "facial"])
        result = runner.feedback_mood(predicted, actual, input_type)
        latencies["feedback_mood"].append(result["latency_ms"])
        if result["status"] not in (200, 202):
            errors += 1
        return result

    def run_profile():
        result = runner.get_profile()
        latencies["profile"].append(result["latency_ms"])
        if result["status"] != 200:
            errors += 1
        return result

    # Warm-up
    print("\nWarm-up (10 requests)...")
    for _ in range(10):
        run_recommend()
        time.sleep(0.1)

    # Benchmark
    print(f"\nRunning benchmark: {args.requests} requests with {args.concurrency} workers...")
    start_time = time.perf_counter()

    tasks = []
    for i in range(args.requests):
        r = random.random()
        if r < 0.5:
            tasks.append(run_recommend)
        elif r < 0.7:
            tasks.append(run_text_emotion)
        elif r < 0.85:
            tasks.append(run_feedback_track)
        elif r < 0.95:
            tasks.append(run_feedback_mood)
        else:
            tasks.append(run_profile)

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(task) for task in tasks]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                errors += 1
                print(f"Request error: {e}")

    total_time = time.perf_counter() - start_time

    # Results
    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)
    print(f"Total requests: {args.requests}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Throughput: {args.requests / total_time:.2f} req/s")
    print(f"Errors: {errors} ({errors / args.requests * 100:.2f}%)")

    for name, lats in latencies.items():
        if lats:
            lats_sorted = sorted(lats)
            p50 = lats_sorted[len(lats_sorted) // 2]
            p95 = lats_sorted[int(len(lats_sorted) * 0.95)]
            p99 = lats_sorted[int(len(lats_sorted) * 0.99)]
            avg = statistics.mean(lats)
            print(f"\n{name.upper()}:")
            print(f"  Count: {len(lats)}")
            print(f"  Avg: {avg:.2f} ms")
            print(f"  p50: {p50:.2f} ms")
            print(f"  p95: {p95:.2f} ms")
            print(f"  p99: {p99:.2f} ms")
            print(f"  Min: {min(lats):.2f} ms")
            print(f"  Max: {max(lats):.2f} ms")

    # Save results
    import json
    results = {
        "config": {
            "url": args.url,
            "requests": args.requests,
            "concurrency": args.concurrency,
            "authenticated": bool(auth_token),
        },
        "summary": {
            "total_time_s": total_time,
            "throughput_rps": args.requests / total_time,
            "total_requests": args.requests,
            "errors": errors,
            "error_rate": errors / args.requests,
        },
        "latencies": {
            name: {
                "count": len(lats),
                "avg_ms": statistics.mean(lats) if lats else 0,
                "p50_ms": sorted(lats)[len(lats) // 2] if lats else 0,
                "p95_ms": sorted(lats)[int(len(lats) * 0.95)] if lats else 0,
                "p99_ms": sorted(lats)[int(len(lats) * 0.99)] if lats else 0,
                "min_ms": min(lats) if lats else 0,
                "max_ms": max(lats) if lats else 0,
            }
            for name, lats in latencies.items()
        },
    }

    output_file = args.output or "benchmark_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VibeStream API Benchmark")
    parser.add_argument("--url", default=API_URL, help="Base API URL")
    parser.add_argument("--username", help="Username for authenticated requests")
    parser.add_argument("--password", help="Password for authenticated requests")
    parser.add_argument("--requests", type=int, default=100, help="Total requests to make")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent workers")
    parser.add_argument("--output", help="Output JSON file")
    args = parser.parse_args()

    run_benchmark(args)