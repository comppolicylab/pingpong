import os

from dotenv import load_dotenv

load_dotenv()
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
PINGPONG_URL = os.getenv("PINGPONG_URL")
JIRA_URL = os.getenv("JIRA_URL")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")
JIRA_CLOUD_ID = os.getenv("JIRA_CLOUD_ID")
