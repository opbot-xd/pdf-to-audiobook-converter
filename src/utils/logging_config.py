import logging
import logging.config
from pathlib import Path


def setup_logging(log_dir: Path, level: int = logging.INFO) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": level,
                "formatter": "standard",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.FileHandler",
                "level": level,
                "formatter": "standard",
                "filename": str(log_file),
                "encoding": "utf-8",
            },
        },
        "root": {
            "level": level,
            "handlers": ["console", "file"],
        },
    }
    logging.config.dictConfig(config)
    return log_file
