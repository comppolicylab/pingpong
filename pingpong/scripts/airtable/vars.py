import json
import logging
import os

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

default_billing_providers = {"NO_SELECTION": None}
billing_providers_env = os.getenv("BILLING_PROVIDERS")

if billing_providers_env:
    try:
        billing_providers = json.loads(billing_providers_env)
        BILLING_PROVIDERS = {
            **billing_providers,
            **default_billing_providers,  # overwrite default in case env has incorrect value
        }
    except json.JSONDecodeError as e:
        logger.warning(f"Error decoding billing providers: {e}, using default.")
        BILLING_PROVIDERS = default_billing_providers
else:
    logger.info("No billing providers found in environment, using default.")
    BILLING_PROVIDERS = default_billing_providers

AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_NONSTUDY_BASE_ID = os.getenv("AIRTABLE_NONSTUDY_BASE_ID")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
PINGPONG_COOKIE = os.getenv("PINGPONG_COOKIE")
PINGPONG_URL = os.getenv("PINGPONG_URL")
