import os

from dotenv import load_dotenv

load_dotenv()
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
QUALTRICS_API_KEY = os.getenv("QUALTRICS_API_KEY")
