import logging
from datetime import datetime

from tqdm import tqdm
from content_migration.management.errors import (
    CouldNotFindMatchingContactError,
    CouldNotParseAuthorIdError,
    DuplicateContactError,
)
from content_migration.management.shared import (
    get_existing_magazine_author_from_db,
    parse_csv_file,
)


from memorials.models import Memorial, MemorialIndexPage

logging.basicConfig(
    filename="import_memorials.log",
    level=logging.ERROR,
    format="%(message)s",
    # format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def handle_import_memorials(file_name: str) -> None:
    # Get the only instance of Magazine Department Index Page
    memorial_index_page = MemorialIndexPage.objects.get()

    memorials = parse_csv_file(file_name)

    for memorial_data in tqdm(memorials, desc="Memorials", unit="row"):
        memorial_exists = Memorial.objects.filter(
            drupal_memorial_id=int(
                memorial_data["memorial_id"],
            )
        ).exists()

        if memorial_exists:
            memorial = Memorial.objects.get(
                drupal_memorial_id=int(
                    memorial_data["memorial_id"],
                )
            )
        else:
            memorial = Memorial(
                drupal_memorial_id=int(
                    memorial_data["memorial_id"],
                ),
            )

        full_name = f'{memorial_data["First Name"]} {memorial_data["Last Name"]}'

        # Make sure we can find the related Meeting contact
        # otherwise, we can't link the memorial ot a meeting
        meeting_author_id = memorial_data["memorial_meeting_drupal_author_id"]

        if meeting_author_id is None:
            logger.error(f"Meeting ID is null for {full_name}")
            continue

        try:
            memorial.memorial_meeting = get_existing_magazine_author_from_db(
                meeting_author_id
            )
        except CouldNotFindMatchingContactError:
            message = f"Could not find memorial meeting contact: {meeting_author_id}"
            logger.error(message)
            continue
        except DuplicateContactError:
            message = f"Duplicate memorial meeting contact: {meeting_author_id}"
            logger.error(message)
            continue
        except CouldNotParseAuthorIdError:
            message = f"Could not parse memorial meeting ID: {meeting_author_id}"
            logger.error(message)
            continue

        # Make sure we can find the related memorial person contact
        # otherwise, we can't link the memorial to a contact
        try:
            memorial.memorial_person = get_existing_magazine_author_from_db(
                memorial_data["drupal_author_id"]
            )
        except CouldNotFindMatchingContactError:
            message = f"Could not find memorial person contact: {memorial_data['drupal_author_id']}"  # noqa: E501
            logger.error(message)
            # go to next item
            # since all memorials should be linked to an author contact
            continue
        except DuplicateContactError:
            message = f"Duplicate memorial person contact: {memorial_data['drupal_author_id']}"  # noqa: E501
            logger.error(message)
            # go to next item
            # since all memorials should be linked to an author contact
            continue

        memorial.title = full_name

        memorial.memorial_minute = memorial_data["body"]

        # Strip out time from datetime strings
        datetime_format = "%Y-%m-%dT%X"

        # Dates are optional
        if memorial_data["Date of Birth"] != "":
            memorial.date_of_birth = datetime.strptime(
                memorial_data["Date of Birth"], datetime_format
            )

        if memorial_data["Date of Death"] != "":
            memorial.date_of_death = datetime.strptime(
                memorial_data["Date of Death"], datetime_format
            )

        if memorial_data["Dates are approximate"] != "":
            memorial.dates_are_approximate = True

        if not memorial_exists:
            # Add memorial to memorials collection
            try:
                memorial_index_page.add_child(instance=memorial)
                memorial_index_page.save()
            except AttributeError as error:
                # log the error message
                logger.error(error)

        else:
            memorial.save()
