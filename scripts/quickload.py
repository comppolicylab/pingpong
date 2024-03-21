"""This script runs a load test on the OpenAI Assistants API.

It tries to simulate a high number of concurrent requests to the API
to determine when we get rate-limited or when the API starts to fail.
"""
import concurrent.futures
import json
import random
import time
from abc import abstractmethod
from typing import Any

import click
import openai
import requests
from tqdm import tqdm


class LoadTestResultSummary:
    def __init__(
        self,
        completions: int,
        failures: int,
        exceptions: int,
        avg_duration: float,
        success_rate: float,
    ):
        self.completions = completions
        self.failures = failures
        self.exceptions = exceptions
        self.avg_duration = avg_duration
        self.success_rate = success_rate

    def print(self):
        print(
            f"Completed: {self.completions},",
            f"Failed: {self.failures},",
            f"Exceptions: {self.exceptions}",
        )
        print("Average duration:" f"{self.avg_duration:.2f} seconds")

        # Print success rate
        print(f"Success rate: {self.success_rate:.2%}")


class LoadTestResult:
    def __init__(
        self, test_id: str, n: int, k: int, jitter: float, args, kwargs, cases, t0, t1
    ):
        self.test_id = test_id
        self.n = n
        self.k = k
        self.jitter = jitter
        self.total = n * k
        self.args = args
        self.kwargs = kwargs
        self.cases = cases
        self.t0 = t0
        self.t1 = t1

    def summarize(self):
        num_completed = sum(1 for result in self.cases if result.success)
        num_failed = sum(1 for result in self.cases if not result.success)
        num_exceptions = sum(1 for result in self.cases if result.error)

        # Print success rate
        success_rate = num_completed / self.total
        return LoadTestResultSummary(
            completions=num_completed,
            failures=num_failed,
            exceptions=num_exceptions,
            avg_duration=sum(result.duration for result in self.cases) / self.total,
            success_rate=success_rate,
        )

    def print(self):
        print(f"Test ID: {self.test_id}")
        print(f"Number of requests: {self.total}")
        print(f"Concurrent requests: {self.n}")
        print(f"Tests per thread: {self.k}")
        print(f"Jitter: {self.jitter}")
        print(f"Arguments: {self.args}")
        print(f"Keyword arguments: {self.kwargs}")
        print(f"Start time: {self.t0}")
        print(f"End time: {self.t1}")
        print("Results:")
        for case in self.cases:
            case.print()

    def dump(self):
        return {
            "n": self.n,
            "k": self.k,
            "total": self.total,
            "jitter": self.jitter,
            "args": self.args,
            "kwargs": self.kwargs,
            "cases": [c.dump() for c in self.cases],
            "t0": self.t0,
            "t1": self.t1,
        }

    def save(self):
        fname = f"{self.test_id}-{self.t0}_results.json"
        with open(fname, "w") as f:
            json.dump(self.dump(), f)


class LoadTestSample:
    def __init__(
        self,
        delay: float,
        index: int,
        success: bool,
        duration: float,
        error: str | None,
        result: Any,
    ):
        self.delay = delay
        self.index = index
        self.success = success
        self.duration = duration
        self.error = error
        self.result = result

    def dump(self):
        return {
            "delay": self.delay,
            "index": self.index,
            "success": self.success,
            "duration": self.duration,
            "error": self.error,
            "result": self.result,
        }

    def print(self):
        print(
            f"Index: {self.index},",
            f"Success: {self.success},",
            f"Duration: {self.duration:.2f} seconds,",
            f"Error: {self.error}",
            f"Delay: {self.delay:.2f} seconds",
        )


class LoadTest:
    def __init__(self, n: int, k: int = 1, jitter: float = 0.0):
        self.n = n
        self.k = k
        self.jitter = jitter
        self.results = list[LoadTestResult]()
        self.test_id = f"{self.__class__.__name__}_{time.time()}"

    def run(self, *args, **kwargs):
        print("Starting load test...")
        t0 = time.time()
        cases = list[LoadTestSample]()
        total = self.n * self.k
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.n) as executor:
            futures = [
                executor.submit(self._run_test, i, *args, **kwargs)
                for i in range(total)
            ]
            for future in tqdm(concurrent.futures.as_completed(futures), total=total):
                cases.append(future.result())

        t1 = time.time()
        result = LoadTestResult(
            self.test_id, self.n, self.k, self.jitter, args, kwargs, cases, t0, t1
        )
        self.results.append(result)
        return result

    @property
    def latest(self):
        if not self.results:
            return
        return self.results[-1]

    def _run_test(self, idx: int, *args, **kwargs):
        delay = random.uniform(0, self.jitter)
        time.sleep(delay)
        try:
            t0 = time.time()
            result = self.test(*args, **kwargs)
            return LoadTestSample(
                delay=delay,
                index=idx,
                success=True,
                duration=time.time() - t0,
                error=None,
                result=result,
            )
        except Exception as e:
            return LoadTestSample(
                delay=delay,
                index=idx,
                success=False,
                duration=time.time() - t0,
                error=str(e),
                result=None,
            )

    @abstractmethod
    def test(self, *args, **kwargs):
        ...


COUNTRIES = [
    "United States",
    "Canada",
    "Mexico",
    "Brazil",
    "Argentina",
    "United Kingdom",
    "France",
    "Germany",
    "Italy",
    "Russia",
    "China",
    "Japan",
    "India",
    "Australia",
    "South Africa",
    "Nigeria",
    "Egypt",
    "Kenya",
    "Ghana",
    "Morocco",
    "Spain",
    "Portugal",
    "Netherlands",
    "Belgium",
    "Sweden",
    "Norway",
    "Denmark",
    "Finland",
    "Poland",
    "Czech Republic",
    "Greece",
]


class UrlBurstTest(LoadTest):
    def test(self, url: str, session: str | None = None):
        """Make a single request to the given URL and return the result."""
        cookies = {"session": session} if session else None
        r = requests.get(url, cookies=cookies)
        r.raise_for_status()
        return r.text


class AssistantsApiRateLimitLoadTest(LoadTest):
    def test(self, api_key: str, assistant_id: str):
        """Make a single request to the assistant and return the result."""
        client = openai.Client(api_key=api_key)

        # Create a thread
        thread = client.beta.threads.create(
            messages=[
                {
                    "role": "user",
                    "content": f"Can you tell me about {random.choice(COUNTRIES)}?",
                }
            ],
        )
        # Start a run
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant_id,
        )

        # Poll until run is in terminal state
        while run.status not in {"completed", "failed", "expired", "cancelled"}:
            time.sleep(1)
            run = client.beta.threads.runs.retrieve(
                run_id=run.id,
                thread_id=thread.id,
            )

        if run.last_error:
            raise Exception(json.dumps(run.last_error.model_dump()))

        if run.status != "completed":
            raise Exception(f"Run {run.id} did not complete, had status {run.status}")

        return run.model_dump()


def run_test(test: LoadTest, *args, **kwargs):
    result = test.run(*args, **kwargs)
    result.save()
    result.print()
    result.summarize().print()


@click.group()
def cli():
    pass


@cli.command()
@click.option("--n", default=10, help="Number of concurrent requests")
@click.option("--api_key", help="OpenAI API key")
@click.option("--assistant_id", help="Assistant ID")
def assistants(n, api_key, assistant_id):
    """Run the load test of the Assistants API with the given parameters."""
    run_test(AssistantsApiRateLimitLoadTest(n=n), api_key, assistant_id)


@cli.command()
@click.option("--n", default=10, help="Number of concurrent requests")
@click.option("--k", default=1, help="Number of tests per thread")
@click.option("--jitter", default=0, help="Random jitter in seconds")
@click.option("--url", help="URL to test")
@click.option("--session", help="Session cookie", required=False, default=None)
def burst(n, k, jitter, url, session):
    """Send a burst of requests to the given URL."""
    run_test(UrlBurstTest(n=n, k=k, jitter=jitter), url, session)


if __name__ == "__main__":
    cli()
