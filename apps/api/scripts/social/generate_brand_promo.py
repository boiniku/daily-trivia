import argparse
from pathlib import Path

from services.brand_promo import generate_brand_promo_video


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the reusable Daily Trivia promo clip")
    parser.add_argument("--output", default="artifacts/daily-trivia-promo.mp4")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    duration = generate_brand_promo_video(output)
    print(f"Generated {output} ({duration:.1f}s)")


if __name__ == "__main__":
    main()
