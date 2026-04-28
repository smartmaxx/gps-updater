from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


def configure(config: dict[str, Any], log_path_override: str | None, verbose: bool, quiet: bool) -> None:
    """
    Configure the root gps_updater logger with console and optional file handlers.
    """
    logging_cfg = config["logging"]

    console_level_name = "DEBUG" if verbose else ("ERROR" if quiet else logging_cfg["level_console"])
    console_level = getattr(logging, console_level_name, logging.WARNING)

    root = logging.getLogger("gps_updater")
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    try:
        from rich.logging import RichHandler
        console_handler = RichHandler(
            level=console_level,
            show_time=False,
            show_path=False,
            markup=False,
        )
    except ImportError:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        console_handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

    root.addHandler(console_handler)

    log_path = log_path_override or (logging_cfg["file"] if logging_cfg["enabled"] else None)
    if log_path:
        file_level_name = logging_cfg["level_file"]
        file_level = getattr(logging, file_level_name, logging.DEBUG)
        file_mode = "a" if logging_cfg.get("log_append", False) else "w"
        file_handler = logging.FileHandler(log_path, mode=file_mode, encoding="utf-8")
        file_handler.setLevel(file_level)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        )
        root.addHandler(file_handler)
