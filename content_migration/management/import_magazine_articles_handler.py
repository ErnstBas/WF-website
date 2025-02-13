import logging

from bs4 import BeautifulSoup
from django.core.exceptions import ObjectDoesNotExist
from tqdm import tqdm
from content_migration.management.errors import (
    CouldNotFindMatchingContactError,
    DuplicateContactError,
)

from magazine.models import (
    MagazineArticle,
    MagazineArticleAuthor,
    MagazineDepartment,
    MagazineIssue,
)

from content_migration.management.shared import (
    create_permanent_redirect,
    get_existing_magazine_author_from_db,
    parse_csv_file,
    parse_media_blocks,
    parse_body_blocks,
    parse_media_string_to_list,
)

logging.basicConfig(
    filename="import_log_magazine_articles.log",
    level=logging.ERROR,
    format="%(message)s",
    # format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def parse_article_authors(
    article: MagazineArticle,
    article_authors: str,
) -> MagazineArticle:
    """Fetch all related article authors and create an article relationship."""
    for drupal_author_id in article_authors.split(", "):
        try:
            author = get_existing_magazine_author_from_db(
                drupal_author_id,
            )
        except (
            CouldNotFindMatchingContactError,
            DuplicateContactError,
        ):
            logger.error(
                f"Could not find author from Drupal ID: { drupal_author_id }",
            )
            continue

        # check if author already exists
        if article.authors.filter(  # type: ignore
            author=author,
        ).exists():
            continue

        article_author = MagazineArticleAuthor(
            article=article,
            author=author,
        )

        article.authors.add(article_author)  # type: ignore

    return article


def assign_article_to_issue(
    article: MagazineArticle,
    drupal_issue_node_id: int,
) -> None:
    try:
        related_issue = MagazineIssue.objects.get(
            drupal_node_id=drupal_issue_node_id,
        )
    except ObjectDoesNotExist as error:
        error_message = f"Could not find issue from Drupal ID: { drupal_issue_node_id }"
        logger.error(error_message)
        raise ObjectDoesNotExist(error_message) from error

    related_issue.add_child(
        instance=article,
    )


def parse_article_body_blocks(row: dict, article: MagazineArticle) -> list[tuple]:
    """Parse article body and media blocks."""

    article_body_blocks = []

    if row["body"] != "":
        article_body_blocks = parse_body_blocks(row["body"])

    # Download and parse article media
    if row["media"] != "":
        media_blocks = parse_media_blocks(
            parse_media_string_to_list(row["media"]),
        )

        # Merge media blocks with article body blocks
        article_body_blocks += media_blocks

    return article_body_blocks


def parse_teaser_from_body(body: str) -> str:
    """Parse article body with beautiful soup.

    Extract the first paragraph and return it as a teaser. Make sure to
    only return the first paragraph, since there may be multipe
    paragraphs.

    Return the paragraph as a string.
    """
    soup = BeautifulSoup(body, "html.parser")

    # find the first paragraph
    # aong multiple paragraphs
    teaser = soup.find("p")

    if teaser is None:
        return ""

    return teaser.text


def handle_import_magazine_articles(file_name: str) -> None:
    articles_data = parse_csv_file(file_name)

    for row in tqdm(
        articles_data,
        desc="Articles",
        unit="row",
    ):
        article_exists = MagazineArticle.objects.filter(
            drupal_node_id=row["drupal_node_id"],
        ).exists()

        # Skip import for existing articles
        if article_exists:
            # get existing article
            article = MagazineArticle.objects.get(
                drupal_node_id=row["drupal_node_id"],
            )
        else:
            # create a new article instance
            article = MagazineArticle()

        article.title = row["title"]
        article.drupal_node_id = row["drupal_node_id"]
        article.is_featured = row["is_featured"] == "True"

        article.department = MagazineDepartment.objects.get(
            title=row["department"],
        )
        article.teaser = parse_teaser_from_body(row["body"])

        # Parse article body
        article.body = parse_article_body_blocks(row, article)

        article.body_migrated = row["body"]

        # Assign article to issue
        if not article_exists:
            assign_article_to_issue(
                article=article,
                drupal_issue_node_id=row["related_issue_id"],
            )

        # Assign authors to article
        if row["authors"] != "":
            article = parse_article_authors(
                article,
                row["authors"],
            )

        # Assign keywards to article
        if row["keywords"] != "":
            for keyword in row["keywords"].split(", "):
                article.tags.add(keyword)

        article.save()

        create_permanent_redirect(
            redirect_path=row["url_path"],
            redirect_entity=article,
        )
