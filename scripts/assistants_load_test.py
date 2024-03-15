"""This script runs a load test on the OpenAI Assistants API.

It tries to simulate a high number of concurrent requests to the API
to determine when we get rate-limited or when the API starts to fail.
"""
import concurrent.futures
import json
import random
import time

import click
import openai

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


def make_request(i: int, api_key: str, assistant_id: str):
    """Make a single request to the assistant and return the result."""
    client = openai.Client(api_key=api_key)
    t_start = time.time()
    print("Making request", i, "at", t_start, "...")

    try:
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
        print(
            "Request",
            i,
            "completed at",
            time.time(),
            "with status",
            run.status,
            "and error",
            run.last_error,
        )

        return {
            "status": run.status,
            "duration": time.time() - t_start,
            "index": i,
            "error": run.last_error.model_dump() if run.last_error else None,
            "result": run.model_dump(),
        }
    except Exception as e:
        print("Exception in", i, ":", e)
        return {
            "status": "exception",
            "duration": time.time() - t_start,
            "error": str(e),
            "index": i,
            "result": None,
        }


def load_test(num_requests: int, api_key: str, assistant_id: str):
    """Run a load test with the given number of concurrent requests."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_requests) as executor:
        futures = [
            executor.submit(make_request, i, api_key, assistant_id)
            for i in range(num_requests)
        ]
        results = [
            future.result() for future in concurrent.futures.as_completed(futures)
        ]

    return results


@click.command()
@click.option("--num_requests", default=10, help="Number of concurrent requests")
@click.option("--api_key", help="OpenAI API key")
@click.option("--assistant_id", help="Assistant ID")
def run(num_requests, api_key, assistant_id):
    """Run the load test of the Assistants API with the given parameters."""
    print("Starting load test...")
    results = load_test(num_requests, api_key, assistant_id)

    # Dump raw results to a file. File name includes the date/time.
    fname = f"load_test_results_{time.strftime('%Y-%m-%d_%H-%M-%S')}.json"
    with open(fname, "w") as f:
        json.dump(
            {
                "results": results,
                "ts": time.time(),
                "num_requests": num_requests,
                "assistant_id": assistant_id,
                "api_key": api_key[:4]
                + "..."
                + api_key[-4:],  # Redacted, but still useful for debugging
            },
            f,
        )

    print("Results:")
    for i, result in enumerate(results):
        print(
            f"  {i} (#{result['index']}).",
            f"{result['status']}",
            f"({result['duration']:.2f} seconds)",
            f"{result['error']}",
        )

    # Print summary
    num_completed = sum(1 for result in results if result["status"] == "completed")
    num_failed = sum(1 for result in results if result["status"] == "failed")
    num_exceptions = sum(1 for result in results if result["status"] == "exception")
    print(
        f"Completed: {num_completed}, Failed: {num_failed}, Exceptions: {num_exceptions}"
    )
    print(
        "Average duration:"
        f"{sum(result['duration'] for result in results) / num_requests:.2f} seconds"
    )

    # Print success rate
    success_rate = num_completed / num_requests
    print(f"Success rate: {success_rate:.2%}")


if __name__ == "__main__":
    run()
