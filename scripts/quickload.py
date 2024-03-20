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
    def __init__(self, test_id: str, n: int, args, kwargs, cases, t0, t1):
        self.test_id = test_id
        self.n = n
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
        success_rate = num_completed / self.n
        return LoadTestResultSummary(
            completions=num_completed,
            failures=num_failed,
            exceptions=num_exceptions,
            avg_duration=sum(result.duration for result in self.cases) / self.n,
            success_rate=success_rate,
        )

    def print(self):
        print(f"Test ID: {self.test_id}")
        print(f"Number of requests: {self.n}")
        print(f"Arguments: {self.args}")
        print(f"Keyword arguments: {self.kwargs}")
        print(f"Start time: {self.t0}")
        print(f"End time: {self.t1}")
        print("Results:")
        for case in self.cases:
            print(
                f"Request {case.index} - Success: {case.success},",
                f"Duration: {case.duration}, Error: {case.error}",
            )

    def dump(self):
        return {
            "n": self.n,
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
        self, index: int, success: bool, duration: float, error: str | None, result: Any
    ):
        self.index = index
        self.success = success
        self.duration = duration
        self.error = error
        self.result = result

    def dump(self):
        return {
            "index": self.index,
            "success": self.success,
            "duration": self.duration,
            "error": self.error,
            "result": self.result,
        }


class LoadTest:
    def __init__(self):
        self.results = []
        self.test_id = f"{self.__class__.__name__}_{time.time()}"

    def run(self, n: int, *args, **kwargs):
        print("Starting load test...")
        t0 = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as executor:
            futures = [
                executor.submit(self._run_test, i, *args, **kwargs) for i in range(n)
            ]
            cases = [
                future.result() for future in concurrent.futures.as_completed(futures)
            ]

        t1 = time.time()
        result = LoadTestResult(self.test_id, n, args, kwargs, cases, t0, t1)
        self.results.append(result)
        return result

    @property
    def latest(self):
        if not self.results:
            return
        return self.results[-1]

    def _run_test(self, idx: int, *args, **kwargs):
        try:
            t0 = time.time()
            result = self.test(*args, **kwargs)
            return LoadTestSample(
                index=idx,
                success=True,
                duration=time.time() - t0,
                error=None,
                result=result,
            )
        except Exception as e:
            return LoadTestSample(
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


@click.group()
def cli():
    pass


@cli.command()
@click.option("--num_requests", default=10, help="Number of concurrent requests")
@click.option("--api_key", help="OpenAI API key")
@click.option("--assistant_id", help="Assistant ID")
def assistants(num_requests, api_key, assistant_id):
    """Run the load test of the Assistants API with the given parameters."""
    test = AssistantsApiRateLimitLoadTest()
    result = test.run(num_requests, api_key, assistant_id)
    result.save()
    result.print()
    result.summarize().print()


if __name__ == "__main__":
    cli()
