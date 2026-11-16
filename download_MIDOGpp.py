import argparse
import logging
from pathlib import Path
import requests
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def get_args():
    parser = argparse.ArgumentParser(description="Download MIDOG++ dataset (annotations + images) from Figshare.")
    parser.add_argument('--location', type=str, default='images', help='Folder to store files.')
    parser.add_argument('--max-images', type=int, default=None, help='Limit number of .tiff images (use 0 for metadata only).')
    return parser.parse_args()


def fetch_all_midogpp_files():
    log.info("Searching Figshare API for all MIDOG++ dataset entries...")
    resp = requests.post(
        "https://api.figshare.com/v2/articles/search",
        json={"search_for": "MIDOG++", "page_size": 50},
        headers=HEADERS,
        timeout=30
    )
    resp.raise_for_status()
    articles = resp.json()

    matching_articles = [a for a in articles if "MIDOG++" in a.get("title", "")]
    if not matching_articles:
        raise RuntimeError("Could not find any MIDOG++ dataset on Figshare.")

    # Collect files from all matching MIDOG++ articles (gets both MIDOGpp.json and MIDOGpp.sqlite + all .tiff images)
    files_by_name = {}
    for article in matching_articles:
        article_id = article["id"]
        log.info(f"Fetching file list from: '{article['title']}' (Article ID: {article_id})")
        files_resp = requests.get(
            f"https://api.figshare.com/v2/articles/{article_id}/files",
            params={"page_size": 1000},
            headers=HEADERS,
            timeout=30
        )
        files_resp.raise_for_status()
        for f in files_resp.json():
            if f["name"] not in files_by_name:
                files_by_name[f["name"]] = f

    return list(files_by_name.values())


def download_file(url: str, dest: Path):
    temp_dest = dest.with_name(dest.name + ".part")
    with requests.get(url, headers=HEADERS, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(temp_dest, "wb") as f, tqdm(
            total=total, unit="B", unit_scale=True, desc=dest.name, leave=False
        ) as bar:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    bar.update(len(chunk))
    temp_dest.replace(dest)


def main(args):
    location = Path(args.location)
    location.mkdir(exist_ok=True, parents=True)

    # Clean up any leftover .part files from previous interrupted downloads
    for part_file in location.glob("*.part"):
        part_file.unlink()

    all_files = fetch_all_midogpp_files()

    # Separate annotation/database files (MIDOGpp.json, MIDOGpp.sqlite) from .tiff images
    meta_files = sorted(
        [f for f in all_files if not f["name"].lower().endswith(".tiff")],
        key=lambda x: x["name"]
    )
    image_files = sorted(
        [f for f in all_files if f["name"].lower().endswith(".tiff")],
        key=lambda x: x["name"]
    )

    log.info(f"Found metadata files: {[f['name'] for f in meta_files]}")

    if args.max_images is not None:
        image_files = image_files[:args.max_images]
        log.info(f"Limiting download to {len(image_files)} images.")

    download_queue = meta_files + image_files
    log.info(f"Total files queued: {len(download_queue)} ({len(meta_files)} metadata + {len(image_files)} images).")

    for file_info in tqdm(download_queue, desc="Overall Progress"):
        dest = location / file_info["name"]
        if dest.exists() and dest.stat().st_size > 0:
            continue
        try:
            download_file(file_info["download_url"], dest)
        except Exception as e:
            log.error(f"Failed to download {file_info['name']}: {e}")
            raise

    log.info("Download complete.")


if __name__ == '__main__':
    main(get_args())