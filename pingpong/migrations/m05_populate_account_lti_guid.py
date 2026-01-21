import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models


logger = logging.getLogger(__name__)

ACCOUNT_LTI_GUID_KEY = "https://canvas.instructure.com/lti/account_lti_guid"


async def populate_account_lti_guid(session: AsyncSession) -> None:
    """Populate canvas_account_lti_guid from openid_configuration JSON.

    For each LTIRegistration missing a canvas_account_lti_guid, extracts
    the value from the openid_configuration JSON field using the key
    "https://canvas.instructure.com/lti/account_lti_guid".
    """
    updated = 0
    skipped = 0
    errors = 0

    registrations = await models.LTIRegistration.get_all(session)

    for registration in registrations:
        if registration.canvas_account_lti_guid:
            skipped += 1
            continue

        if not registration.openid_configuration:
            logger.debug(
                "LTIRegistration id=%s has no openid_configuration, skipping",
                registration.id,
            )
            skipped += 1
            continue

        try:
            openid_config = json.loads(registration.openid_configuration)
        except json.JSONDecodeError as e:
            logger.warning(
                "Failed to parse openid_configuration for LTIRegistration id=%s: %s",
                registration.id,
                e,
            )
            errors += 1
            continue

        account_lti_guid = openid_config.get(ACCOUNT_LTI_GUID_KEY)
        if not account_lti_guid:
            logger.debug(
                "LTIRegistration id=%s openid_configuration does not contain %s",
                registration.id,
                ACCOUNT_LTI_GUID_KEY,
            )
            skipped += 1
            continue

        registration.canvas_account_lti_guid = account_lti_guid
        session.add(registration)
        updated += 1
        logger.info(
            "Updated LTIRegistration id=%s with canvas_account_lti_guid=%s",
            registration.id,
            account_lti_guid,
        )

    await session.flush()
    logger.info(
        "Finished populating canvas_account_lti_guid: updated=%s, skipped=%s, errors=%s",
        updated,
        skipped,
        errors,
    )
