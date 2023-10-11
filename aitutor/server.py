from fastapi import FastAPI, HTTPException
from slack_sdk.web.async_client import AsyncWebClient

from .bot import run_slack_bot
from .config import config
from .errors import sentry
from .metrics import metrics

v1 = FastAPI()


@v1.get("/config")
def get_config():
    return {"config": config.dict()}


@v1.get("/user/{user_id}")
async def get_user(user_id: str):
    client = AsyncWebClient(token=config.slack[0].web_token)
    user = await client.users_profile_get(user=user_id)
    data = user.data
    if not data.get("ok"):
        raise HTTPException(
            status_code=502, detail="failed to get user profile from Slack"
        )
    return {"user": data.get("profile")}


async def lifespan(app: FastAPI):
    """Run Slack Bot agent in the background."""
    with sentry(), metrics():
        async with run_slack_bot():
            yield


app = FastAPI(lifespan=lifespan)

app.mount("/api/v1", v1)
