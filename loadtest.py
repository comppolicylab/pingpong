import os
import random
from threading import Lock

import requests
from locust import HttpUser, between, events, task

from aitutor.auth import encode_auth_token
from aitutor.config import config

TEST_INST = None


class WebUser(HttpUser):
    wait_time = between(1, 5)

    @task(5)
    def get_me(self):
        self.client.get("/api/v1/me")

    @task(2)
    def get_stuff(self):
        self.client.get("/api/v1/classes")
        self.client.get(f"/api/v1/class/{TEST_INST.cls_id}/threads")
        self.client.get(f"/api/v1/class/{TEST_INST.cls_id}/assistants")
        self.client.get(f"/api/v1/class/{TEST_INST.cls_id}")
        self.client.get(f"/api/v1/class/{TEST_INST.cls_id}/files")
        self.client.get("/api/v1/institutions")

    @task(1)
    def new_thread(self):
        resp = self.client.post(
            f"/api/v1/class/{TEST_INST.cls_id}/thread",
            json={
                "parties": [self.user["id"]],
                "message": "Hi, can you help me understand what a normal distribution is?",
                "assistant_id": TEST_INST.ai_id,
            },
        )

        thread_id = resp.json()["thread"]["id"]
        with self.thread_lock(thread_id):
            self.threads.append(thread_id)
            self.client.get(
                f"/api/v1/class/{TEST_INST.cls_id}/thread/{thread_id}/last_run"
            )

    @task(2)
    def add_to_thread(self):
        if not self.threads:
            return

        lock = self.thread_lock(random.choice(self.threads))
        if lock.locked():
            # Just return empty if the thread is running. This is similar to
            # what the UI will do if somehow the user tries to bypass the lock
            # on the input field and submit a message before a response comes.
            return

        thread_id = random.choice(self.threads)
        self.client.post(
            f"/api/v1/class/{TEST_INST.cls_id}/thread/{thread_id}",
            json={
                "message": (
                    "I'm not sure I understand, "
                    "can you try explaining in a different way?"
                )
            },
        )
        self.client.get(f"/api/v1/class/{TEST_INST.cls_id}/thread/{thread_id}/last_run")

    @task(4)
    def poll_last_thread_run(self):
        if not self.threads:
            return
        some_thread = random.choice(self.threads)
        with self.thread_lock(some_thread):
            self.client.get(
                f"/api/v1/class/{TEST_INST.cls_id}/thread/{some_thread}/last_run"
            )

    def thread_lock(self, thread_id):
        return self.thread_locks.setdefault(thread_id, Lock())

    def on_start(self):
        user = TEST_INST.create_test_user()
        self.user = user
        self.client.cookies.set("session", user["token"])
        self.threads = []
        self.thread_locks = {}


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


class TestInstance:
    def __init__(self, url: str, token: str):
        self.session = Session(url, token)
        self.cls_id = self._create_test_class("test class")
        self.ai_id = self._create_test_ai(self.cls_id, os.environ["OPENAI_API_KEY"])
        self._ctr = 0

    def cleanup(self):
        self._delete_test_ai(self.cls_id, self.ai_id)

    def _create_test_class(self, name: str):
        # Create the institution
        print("Creating institution ...")
        resp = self.session.post("/institution", json={"name": f"test inst for {name}"})
        inst_id = resp.json()["id"]
        # Create the class
        print("Creating class ...")
        resp = self.session.post(
            f"/institution/{inst_id}/class", json={"name": name, "term": "test term"}
        )
        return resp.json()["id"]

    def _create_test_ai(self, cls_id: int, api_key: str):
        s = self.session
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
        return ai_id

    def _delete_test_ai(self, cls_id: int, ai_id: int):
        self.session.delete(f"/class/{cls_id}/assistant/{ai_id}")

    def create_test_user(self):
        return self.create_test_users(1)[0]

    def create_test_users(self, num_users: int):
        cls_id = self.cls_id
        # Create the users
        emails = [f"fake-{i}@test" for i in range(self._ctr, self._ctr + num_users)]
        print("Creating users ...")
        resp = self.session.post(
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
        self._ctr += num_users

        return [
            {
                "email": emails[i],
                "id": x["user_id"],
                "token": encode_auth_token(x["user_id"]),
            }
            for i, x in enumerate(resp.json()["roles"])
        ]


@events.test_start.add_listener
def on_test_start(**kwargs):
    print("Starting test", kwargs)
    global TEST_INST
    TEST_INST = TestInstance(config.public_url, encode_auth_token(1))


@events.test_stop.add_listener
def on_test_stop(**kwargs):
    print("Stopping test", kwargs)
    global TEST_INST
    TEST_INST.cleanup()
