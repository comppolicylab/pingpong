from fastapi import FastAPI
from slack_sdk.web.async_client import AsyncWebClient

from .app import run_slack_bot
from .config import config


async def lifespan(app: FastAPI):
    """Run the agent until it's done."""
    async with run_slack_bot():
        yield


app = FastAPI(lifespan=lifespan)


@app.get("/config")
def get_config():
    return {"config": config.dict()}


@app.get("/user/{user_id}")
async def get_user(user_id: str):
    client = AsyncWebClient(token=config.slack[0].web_token)
    user = await client.users_profile_get(user=user_id)
    data = user.get("data")
    if not data.get("ok"):
        raise RuntimeError("failed to get user profile")
    return {"user": data.get("profile")}
