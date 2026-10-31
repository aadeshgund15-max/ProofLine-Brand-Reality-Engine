"""Run with `python -m app.services.monitor_worker` as a separate process."""
from __future__ import annotations

import argparse
import logging

from app.services.monitoring import worker_loop


def main() -> None:
    parser = argparse.ArgumentParser(description="Proofline public content monitor")
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    worker_loop(args.poll_seconds)


if __name__ == "__main__":
    main()
