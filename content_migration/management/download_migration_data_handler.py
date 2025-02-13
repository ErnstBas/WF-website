import os
import requests
from tqdm import tqdm

from content_migration.management.constants import (
    IMPORT_FILENAMES,
    LOCAL_MIGRATION_DATA_DIRECTORY,
)


def handle_file_downloads(data_directory_url: str) -> None:
    # ensure url ends with a slash
    if not data_directory_url.endswith("/"):
        data_directory_url += "/"

    # ensure local directory exists
    if not os.path.exists(LOCAL_MIGRATION_DATA_DIRECTORY):
        os.makedirs(LOCAL_MIGRATION_DATA_DIRECTORY)

    # download files
    for filename in tqdm(
        IMPORT_FILENAMES.values(),
        desc="Downloading files",
        unit="file",
    ):
        download_url = f"{data_directory_url}{filename}"
        local_file_path = f"{LOCAL_MIGRATION_DATA_DIRECTORY}{filename}"

        response = requests.get(download_url)
        with open(local_file_path, "wb") as f:
            f.write(response.content)
