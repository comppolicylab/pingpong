import asyncio
from contextlib import contextmanager

import click
import requests
from aiohttp import ClientSession

from aitutor.auth import encode_auth_token


class Session(requests.Session):
    def __init__(self, url: str, token: str):
        super().__init__()
        self.cookies.set("session", token)
        self.url = url + "/api/v1"

    def request(self, method, url, *args, **kwargs):
        full_url = self.url + url
        print("Requesting", method, full_url)
        r = super().request(method, full_url, *args, **kwargs)
        r.raise_for_status()
        return r


@contextmanager
def test_class(s: Session, name: str):
    # Create the institution
    print("Creating institution ...")
    resp = s.post("/institution", json={"name": f"test inst for {name}"})
    inst_id = resp.json()["id"]
    # Create the class
    print("Creating class ...")
    resp = s.post(
        f"/institution/{inst_id}/class", json={"name": name, "term": "test term"}
    )
    cls_id = resp.json()["id"]
    yield cls_id
    # TODO - cleanup


@contextmanager
def test_ai(s: Session, cls_id: int, api_key: str):
    ai_id = None
    # Create the AI
    # TODO do this with file retrieval?
    print("Creating AI ...")
    s.put(f"/class/{cls_id}/api_key", json={"api_key": api_key})
    resp = s.post(
        f"/class/{cls_id}/assistant",
        json={
            "name": "test ai",
            "file_ids": [],
            "instructions": "You are a friendly AI for testing purposes",
            "model": "gpt-4-1106-preview",
            "tools": [],  # TODO retrieval, code interpretter
            "published": True,
        },
    )
    ai_id = resp.json()["id"]
    try:
        yield ai_id
    except Exception as e:
        print("Error happened running tests:", e)
    finally:
        # Delete the AI
        print("Deleting AI ...")
        resp = s.delete(f"/class/{cls_id}/assistant/{ai_id}")


@contextmanager
def test_users(s: Session, cls_id: int, num_users: int):
    # Create the users
    emails = [f"fake-{i}@test" for i in range(num_users)]
    print("Creating users ...")
    resp = s.post(
        f"/class/{cls_id}/user",
        json={
            "roles": [
                {
                    "role": "read",
                    "email": emails[i],
                    "title": "tester",
                }
                for i in range(num_users)
            ],
            "silent": True,
        },
    )

    yield [
        {
            "email": emails[i],
            "id": x["user_id"],
            "token": encode_auth_token(x["user_id"]),
        }
        for i, x in enumerate(resp.json()["roles"])
    ]

    # TODO cleanup


async def get_me(base_url: str, user: dict):
    print(f"Getting /me for {user['email']} ...")
    async with ClientSession(cookies={"session": user["token"]}) as s:
        async with s.get(f"{base_url}/api/v1/me") as resp:
            return await resp.json()


async def run_me_test(base_url: str, users: list[dict]):
    # run async tasks and collect results
    print("Running /me tests ...")
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(get_me(base_url, user)) for user in users]
    return [task.result() for task in tasks]


@click.command("run")
@click.option("--num-users", default=1, help="Number of users to simulate")
@click.option("--super_id", default=1, help="ID to use for authentication")
@click.option("--url", default="http://localhost:8000", help="URL to load test")
@click.option("--api-key", required=True, help="API key to use for authentication")
def run(num_users: int, super_id: int, url: str, api_key: str):
    token = encode_auth_token(super_id)
    session = Session(url, token)

    with test_class(session, "test class") as cls_id:
        with test_ai(session, cls_id, api_key):
            with test_users(session, cls_id, num_users) as users:
                # Run /me tests
                results = asyncio.run(run_me_test(url, users))
                print(results)


if __name__ == "__main__":
    run()
