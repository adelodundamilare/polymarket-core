import logging
import sys
from typing import Optional

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

def configure_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
) -> None:
    root_logger = logging.getLogger()
    
    if root_logger.handlers:
        return

    root_logger.setLevel(getattr(logging, level))

    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    console_handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
