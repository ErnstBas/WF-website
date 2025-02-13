# Regex to get CiviCRM ID from parentheses in contact name
# https://stackoverflow.com/a/38999572/1191545

import logging

from django.core.exceptions import MultipleObjectsReturned
from tqdm import tqdm

from contact.models import (
    Meeting,
    MeetingAddress,
    MeetingWorshipTime,
    Organization,
)
from content_migration.management.shared import parse_csv_file

logging.basicConfig(
    filename="import_civicrm_contacts.log",
    level=logging.ERROR,
    format="%(message)s",
    # format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def create_meeting_addresses(meeting: Meeting, row: dict) -> None:
    row_has_mailing_address = row["Mailing-State"] != ""
    row_has_worship_address = row["Worship-State"] != ""

    if row_has_mailing_address:
        mailing_address = MeetingAddress(
            street_address=row["Mailing-Street Address"],
            extended_address=row["Mailing-Supplemental Address 1"],
            locality=row["Mailing-City"],
            region=row["Mailing-State"],
            postal_code=row["Mailing-Postal Code"],
            address_type="mailing",
            page=meeting,
        )

        mailing_address.save()

    if row_has_worship_address:
        latitude = row["Worship-Latitude"] if row["Worship-Latitude"] != "" else None
        longitude = row["Worship-Longitude"] if row["Worship-Longitude"] != "" else None

        worship_address = MeetingAddress(
            street_address=row["Worship-Street Address"],
            extended_address=row["Worship-Supplemental Address 1"],
            locality=row["Worship-City"],
            region=row["Worship-State"],
            postal_code=row["Worship-Postal Code"],
            country=row["Worship-Country"],
            address_type="worship",
            latitude=latitude,
            longitude=longitude,
            page=meeting,
        )

        worship_address.save()


def add_meeting_worship_times(
    meeting: Meeting,
    contact: dict[str, str],
) -> None:
    # For a given Meeting model instance,
    # add meeting time(s) from CiviCRM contact data

    if contact["Regular time of Worship on First Day (1)"] != "":
        worship_time = MeetingWorshipTime(
            meeting=meeting,
            worship_type="first_day_worship",
            worship_time=contact["Regular time of Worship on First Day (1)"],
        )

        worship_time.save()

    if contact["Regular time of Worship on First Day (2)"] != "":
        worship_time = MeetingWorshipTime(
            meeting=meeting,
            worship_type="first_day_worship_2nd",
            worship_time=contact["Regular time of Worship on First Day (2)"],
        )

        worship_time.save()

    if (
        contact[
            "Regular day and time of Meeting for Worship on the Occassion of Business"
        ]
        != ""
    ):
        worship_time = MeetingWorshipTime(
            meeting=meeting,
            worship_type="business_meeting",
            worship_time=contact[
                "Regular day and time of Meeting for Worship on the Occassion of Business"  # noqa: E501
            ],
        )

        worship_time.save()

    if (
        contact["Regular day and time of other weekly or monthly public meetings (1)"]
        != ""
    ):
        worship_time = MeetingWorshipTime(
            meeting=meeting,
            worship_type="other_regular_meeting",
            worship_time=contact[
                "Regular day and time of other weekly or monthly public meetings (1)"
            ],
        )

        worship_time.save()


def determine_meeting_type(
    contact_type: str,
) -> str:
    # Meeting Subtypes include
    # - Monthly_Meeting_Worship_Group
    # - Quarterly_Regional_Meeting
    # - Yearly_Meeting
    # - Worship_Group
    #
    # Each contact suptype is mapped
    # to a corresponding Meeting type

    meeting_types = {
        "Yearly_Meeting": "yearly_meeting",
        "Quarterly_Regional_Meeting": "quarterly_meeting",
        "Monthly_Meeting_Worship_Group": "monthly_meeting",
        "Worship_Group": "worship_group",
    }

    return meeting_types[contact_type]


def handle_import_civicrm_contacts(
    file_name: str,
) -> None:
    contacts = parse_csv_file(file_name)

    for contact in tqdm(
        contacts,
        total=len(contacts),
        desc="Contacts",
        unit="row",
    ):
        # Check for entity type among:
        # - Meeting
        # - Organization
        #
        # Contact Subtypes include
        # - Monthly_Meeting_Worship_Group
        # - Quarterly_Regional_Meeting
        # - Yearly_Meeting
        # - Worship_Group
        # - Quaker_Organization
        # - NULL

        if contact["Contact Subtype"] is None:
            error_message = (
                f"Contact { contact['Display Name']} does not have Contact Subtype"
            )
            logger.error(error_message)
            # Skip to next contact
            continue

        contact_type = contact["Contact Subtype"].strip()

        # Most of the contacts are meetings.
        # We will need nested logic to label the meeting based on type.
        meeting_types = [
            "Yearly_Meeting",
            "Quarterly_Regional_Meeting",
            "Monthly_Meeting_Worship_Group",
            "Worship_Group",
        ]

        # Organization types contains empty string
        # because contacts without a value
        # are organizations in the spreadsheet
        # Make sure empty string catches the contacts without subtype.
        organization_types = [
            "Quaker_Organization",
            "",
        ]

        contact_is_meeting = contact_type in meeting_types
        contact_is_organization = contact_type in organization_types

        # Get common fields for use belos
        organization_name = contact["Organization Name"]
        civicrm_id = contact["Contact ID"]

        if contact_is_meeting:
            # Make sure we have exactly one record for this organization
            try:
                meeting = Meeting.objects.get(
                    civicrm_id=civicrm_id,
                )
            except MultipleObjectsReturned:
                error_message = f"Duplicate contact found for {organization_name}"
                logger.error(error_message)
                continue
            except Meeting.DoesNotExist:
                error_message = (
                    f"Could not find contact record for meeting {organization_name}"
                )
                logger.error(error_message)
                continue

            # Update contact records with meeting data
            meeting.meeting_type = determine_meeting_type(contact_type)
            meeting.website = contact["Website"]
            meeting.phone = contact["Phone"]
            meeting.email = contact["Email"]

            meeting.save()

            add_meeting_worship_times(meeting, contact)
            create_meeting_addresses(meeting, contact)
        elif contact_is_organization:
            # Make sure we have exactly one record for this organization
            try:
                Organization.objects.get(
                    civicrm_id=civicrm_id,
                )
            except MultipleObjectsReturned:
                error_message = (
                    f"Duplicate contact records found for {organization_name}"
                )
                logger.error(error_message)
                continue
            except Organization.DoesNotExist:
                error_message = f"Could not find contact record for organization {organization_name}"  # noqa: E501
                logger.error(error_message)
                continue
        else:
            error_message = (
                f"Invalid contact type '{contact_type} for {organization_name}"
            )
            logger.error(error_message)
