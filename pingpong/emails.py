from sqlalchemy.ext.asyncio import AsyncSession
from pingpong import models
from email.utils import getaddresses
from email_validator import validate_email, EmailSyntaxError
from pingpong.schemas import EmailValidationResult, EmailValidationResults


def parse_addresses(input: str) -> list[EmailValidationResult]:
    result: list[EmailValidationResult] = []
    emails = getaddresses([input])

    for email in emails:
        result.append(parse_single_address(email))

    return result


# Helper function to parse a single address or name <email>
def parse_single_address(address: tuple[str, str]) -> EmailValidationResult:
    try:
        validated = validate_email(address[1], check_deliverability=False)
        return EmailValidationResult(
            name=address[0].strip() if address[0].strip() else None,
            email=validated.normalized,
            valid=True,
        )
    except EmailSyntaxError as e:
        return EmailValidationResult(
            name=address[0].strip() if address[0].strip() else None,
            email=address[1].strip(),
            valid=False,
            error=str(e),
        )


async def validate_email_addresses(
    session: AsyncSession, input: str
) -> EmailValidationResults:
    result = parse_addresses(input)
    validated_addresses = [x for x in result if x.valid]
    unvalidated_addresses = [x for x in result if not x.valid]

    unique_addresses = {}

    # Check if user exists in the database and replace name if it does
    for i, data in enumerate(validated_addresses):
        user = await models.User.get_by_email(session, data.email)
        if user:
            validated_addresses[i].name = (
                user.first_name + " " + user.last_name
                if user.first_name and user.last_name
                else user.display_name
                if user.display_name
                else validated_addresses[i].name
            )
            validated_addresses[i].isUser = True

        if data.email not in unique_addresses:
            unique_addresses[data.email] = data
        else:
            existing_entry = unique_addresses[data.email]
            if data.name and (not existing_entry.name or not existing_entry.isUser):
                unique_addresses[data.email] = data

    validated_addresses = list(unique_addresses.values())

    return EmailValidationResults(results=validated_addresses + unvalidated_addresses)


async def revalidate_email_addresses(
    session: AsyncSession, input: list[EmailValidationResult]
) -> EmailValidationResults:
    unique_addresses = {}
    for email in input:
        try:
            validate_email(email.email, check_deliverability=False)
            email.valid = True
            user = await models.User.get_by_email(session, email.email)
            if user:
                email.name = (
                    user.first_name + " " + user.last_name
                    if user.first_name and user.last_name
                    else user.display_name
                    if user.display_name
                    else email.name
                )
                email.isUser = True

        except EmailSyntaxError as e:
            email.valid = False
            email.error = str(e)

        if email.email not in unique_addresses:
            unique_addresses[email.email] = email
        else:
            existing_entry = unique_addresses[email.email]
            if email.name and (
                not existing_entry.name or existing_entry.isUser is False
            ):
                unique_addresses[email.email] = email

    results = list(unique_addresses.values())
    return EmailValidationResults(results=results)
