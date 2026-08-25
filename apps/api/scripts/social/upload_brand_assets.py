import json
from pathlib import Path

from dotenv import load_dotenv

from services.social_storage import upload_social_asset


def main() -> None:
    load_dotenv()
    artifact_dir = Path("artifacts")
    assets = {
        "SOCIAL_INTRO_VIDEO_URL": artifact_dir / "daily-trivia-intro.mp4",
        "SOCIAL_PROMO_VIDEO_URL": artifact_dir / "daily-trivia-promo.mp4",
    }
    urls = {}
    for env_name, path in assets.items():
        if not path.exists():
            raise FileNotFoundError(f"Generate the asset first: {path}")
        urls[env_name] = upload_social_asset(
            path.read_bytes(),
            "video/mp4",
            "mp4",
            prefix="assets/video",
        )
    print(json.dumps(urls, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
