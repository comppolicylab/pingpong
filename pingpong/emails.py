from sqlalchemy.ext.asyncio import AsyncSession
from pingpong import models
from email.utils import getaddresses
from email_validator import validate_email, EmailSyntaxError
from pingpong.schemas import EmailValidationResult, EmailValidationResults


def parse_addresses(input: str) -> list[EmailValidationResult]:
    emails = getaddresses([input])
    return [parse_single_address(email) for email in emails if email[1]]


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


# Helper function to handle user lookup and update the name field if the user exists
async def update_user_info(
    session: AsyncSession, email_data: EmailValidationResult
) -> EmailValidationResult:
    user = await models.User.get_by_email(session, email_data.email)
    if user:
        email_data.name = (
            f"{user.first_name} {user.last_name}"
            if user.first_name and user.last_name
            else user.display_name
            if user.display_name
            else email_data.name
        )
        email_data.isUser = True
    return email_data


# Helper function to deduplicate email addresses and update names if necessary
def deduplicate_emails(
    addresses: list[EmailValidationResult],
) -> list[EmailValidationResult]:
    unique_addresses: dict[str, EmailValidationResult] = {}

    for data in addresses:
        if data.email not in unique_addresses:
            unique_addresses[data.email] = data
        else:
            existing_entry = unique_addresses[data.email]
            if data.name and (not existing_entry.name or not existing_entry.isUser):
                unique_addresses[data.email] = data

    return list(unique_addresses.values())


async def validate_email_addresses(
    session: AsyncSession, input: str
) -> EmailValidationResults:
    parsed_addresses = parse_addresses(input)

    validated_addresses = [x for x in parsed_addresses if x.valid]
    unvalidated_addresses = [x for x in parsed_addresses if not x.valid]

    for i, data in enumerate(validated_addresses):
        validated_addresses[i] = await update_user_info(session, data)

    deduplicated_valid_addresses = deduplicate_emails(validated_addresses)

    return EmailValidationResults(
        results=deduplicated_valid_addresses + unvalidated_addresses
    )


async def revalidate_email_addresses(
    session: AsyncSession, input: list[EmailValidationResult]
) -> EmailValidationResults:
    for email in input:
        try:
            validate_email(email.email, check_deliverability=False)
            email.valid = True
        except EmailSyntaxError as e:
            email.valid = False
            email.error = str(e)

        await update_user_info(session, email)

    deduplicated_addresses = deduplicate_emails(input)

    return EmailValidationResults(results=deduplicated_addresses)
