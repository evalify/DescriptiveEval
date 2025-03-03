"""This module contains production-grade logging for evaluation results"""

import json
import logging
import colorlog
from datetime import datetime
from pathlib import Path
import socket
import os
from pythonjsonlogger import json as jsonlogger
from dotenv import load_dotenv

load_dotenv()

# Create logs directory if it doesn't exist
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# Enhanced format with host info and process ID
file_format = (
    "%(asctime)s - %(levelname)s - [%(name)s] [%(hostname)s:%(process)d] - %(message)s"
)
console_format = "%(log_color)s%(asctime)s - %(levelname)s - [%(name)s] [%(hostname)s:%(process)d] - %(message)s%(reset)s"
quiz_format = "%(asctime)s - %(levelname)s - [%(quiz_id)s] [%(hostname)s:%(process)d] - %(message)s"
json_format = "%(timestamp)s %(level)s %(name)s %(hostname)s %(processid)s %(message)s"


# Create base record factory with hostname
def create_record_factory(old_factory, **extra_fields):
    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.hostname = socket.gethostname()
        for key, value in extra_fields.items():
            setattr(record, key, value)
        return record

    return record_factory


# Set up base logging config
logging.setLogRecordFactory(create_record_factory(logging.getLogRecordFactory()))

# Create logger
logger = logging.getLogger(__name__)

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
level = getattr(logging, log_level, logging.INFO)
logger.setLevel(level)
print(f"Log level set to {log_level}")
logger.propagate = False  # Prevent propagation to avoid duplicate logs

# Remove any existing handlers
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# Create console handler with color
console_handler = colorlog.StreamHandler()
console_handler.setFormatter(
    colorlog.ColoredFormatter(
        console_format,
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )
)

# Create file handlers - one for regular logs and one for JSON
file_handler = logging.FileHandler(
    log_dir / f"eval_{datetime.now().strftime('%Y%m%d')}.log"
)
file_handler.setFormatter(logging.Formatter(file_format))

json_handler = logging.FileHandler(
    log_dir / f"eval_{datetime.now().strftime('%Y%m%d')}.json.log"
)
json_formatter = jsonlogger.JsonFormatter(
    json_format,
    rename_fields={
        "levelname": "level",
        "processid": "process",
        "asctime": "timestamp",
    },
    timestamp=True,
)
json_handler.setFormatter(json_formatter)

# Add handlers to logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)
logger.addHandler(json_handler)


class QuizLogger:
    """Quiz-specific logger that writes to both global and quiz-specific log files with different verbosity levels"""

    def __init__(self, quiz_id: str):
        self.quiz_id = quiz_id
        self.quiz_log_dir = Path(f"data/json/{quiz_id}")
        self.quiz_log_dir.mkdir(parents=True, exist_ok=True)
        self.quiz_log_file = self.quiz_log_dir / "quiz.log"
        self.quiz_json_file = self.quiz_log_dir / "quiz.json.log"

        # Create quiz-specific logger
        self.logger = logging.getLogger(f"quiz.{quiz_id}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False  # Prevent propagation to avoid duplicate logs

        # Remove any existing handlers
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)

        # Create quiz-specific handlers
        self.quiz_handler = logging.FileHandler(self.quiz_log_file)
        self.quiz_handler.setFormatter(logging.Formatter(quiz_format))

        self.quiz_json_handler = logging.FileHandler(self.quiz_json_file)
        self.quiz_json_handler.setFormatter(
            jsonlogger.JsonFormatter(
                json_format,
                rename_fields={
                    "levelname": "level",
                    "processid": "process",
                    "asctime": "timestamp",
                },
                timestamp=True,
            )
        )

        self.logger.addHandler(self.quiz_handler)
        self.logger.addHandler(self.quiz_json_handler)

        # Use LoggerAdapter instead of overriding makeRecord
        self.logger = logging.LoggerAdapter(self.logger, {"quiz_id": self.quiz_id})

    def debug(self, msg, *args, **kwargs):
        """Log debug message (quiz-specific only)"""
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        """Log info message (both quiz-specific and main logs)"""
        self.logger.debug(msg, *args, **kwargs)  # Always log details to quiz log
        # Only log key events to main logger
        if any(
            key in msg.lower()
            for key in [
                "start",
                "complete",
                "completed",
                "finish",
                "fail",
                "error",
                "score",
            ]
        ):
            # Avoid duplicating the quiz ID if it's already in the message
            log_msg = msg if f"[{self.quiz_id}]" in msg else f"[{self.quiz_id}] {msg}"
            logger.info(log_msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        """Log warning message (both loggers)"""
        self.logger.warning(msg, *args, **kwargs)
        # Avoid duplicating the quiz ID if it's already in the message
        log_msg = msg if f"[{self.quiz_id}]" in msg else f"[{self.quiz_id}] {msg}"
        logger.warning(log_msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        """Log error message (both loggers)"""
        self.logger.error(msg, *args, **kwargs)
        # Avoid duplicating the quiz ID if it's already in the message
        log_msg = msg if f"[{self.quiz_id}]" in msg else f"[{self.quiz_id}] {msg}"
        logger.error(log_msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        """Log critical message (both loggers)"""
        self.logger.critical(msg, *args, **kwargs)
        # Avoid duplicating the quiz ID if it's already in the message
        log_msg = msg if f"[{self.quiz_id}]" in msg else f"[{self.quiz_id}] {msg}"
        logger.critical(log_msg, *args, **kwargs)

    def __del__(self):
        """Cleanup logging handlers"""
        if hasattr(self, "quiz_handler"):
            self.quiz_handler.close()
            self.quiz_json_handler.close()
            self.logger.logger.removeHandler(self.quiz_handler)
            self.logger.logger.removeHandler(self.quiz_json_handler)


def log_evaluation(test_name: str, params: dict, result: dict):
    """Log an evaluation event with structured data"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "event_type": "evaluation",
        "test_name": test_name,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "parameters": params,
        "result": result,
    }
    logger.info(json.dumps(log_entry))
