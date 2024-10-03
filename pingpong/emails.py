from typing import Optional
import re

from sqlalchemy.ext.asyncio import AsyncSession
from pingpong import models
from pingpong.schemas import EmailValidationResult, EmailValidationResults

def parse_addresses(input: str) -> list[EmailValidationResult]:
    result: list[EmailValidationResult] = []

    # Split the input string by newlines
    lines = [line.strip() for line in input.splitlines() if line.strip()]

    for line in lines:
        # Check if the line contains a group definition (e.g., Friends: alice@example.com, bob@example.com;)
        group_match = re.match(r"^(.*?):\s*(.*?)\s*;$", line)

        if group_match:
            # Parse the group: groupName and groupAddresses
            _, group_addresses = group_match.groups()
            inner_addresses = [addr.strip() for addr in group_addresses.split(",")]

            # Push each address in the group, skipping the group name
            for addr in inner_addresses:
                result.append(parse_single_address(addr))
            continue

        # Split the line by commas in case it contains multiple addresses (e.g., john@example.com, jane@example.com)
        addresses = [addr.strip() for addr in line.split(",")]

        # Process each address in the line
        for address in addresses:
            result.append(parse_single_address(address))

    return result

# Helper function to check if an email address is valid
def is_email_valid(email: str) -> bool:
    email_regex = re.compile(
        r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
        r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
    )
    return bool(email_regex.match(email))

# Helper function to parse a single address or name <email>
def parse_single_address(address: str) -> EmailValidationResult:
    match = re.match(r"^(.*?)\s*<([^>]+)>$", address)

    if match:
        # If there's a match, we have a name and an email
        name, email = match.groups()
        is_valid = is_email_valid(email.strip())
        return EmailValidationResult(
            name=name.strip() if name.strip() else None, email=email.strip(), valid=is_valid
        )
    else:
        # If it's just an email address, check validity
        is_valid = is_email_valid(address.strip())
        return EmailValidationResult(
            name=None, email=address.strip(), valid=is_valid
        )

async def validate_email_addresses(session: AsyncSession, input: str) -> EmailValidationResults:
    result = parse_addresses(input)
    validated_addresses = [x for x in result if x.valid]
    unvalidated_addresses = [x for x in result if not x.valid]

    # Check if user exists in the database and replace name if it does
    for i, data in enumerate(validated_addresses):
        user = await models.User.get_by_email(session, data.email)
        if user:
            validated_addresses[i].name = user.first_name + " " + user.last_name if user.first_name and user.last_name else user.display_name if user.display_name else None
            validated_addresses[i].isUser = True

    return EmailValidationResults(results=validated_addresses + unvalidated_addresses)