"""This module contains production-grade logging for evaluation results"""

import json
import logging
import colorlog
from datetime import datetime
from pathlib import Path
import socket
import os

# Create logs directory if it doesn't exist
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# Enhanced format with host info and process ID
file_format = '%(asctime)s - %(levelname)s - [%(name)s] [%(hostname)s:%(process)d] - %(message)s'
console_format = '%(log_color)s%(asctime)s - %(levelname)s - [%(name)s] [%(hostname)s:%(process)d] - %(message)s%(reset)s'
quiz_format = '%(asctime)s - %(levelname)s - [%(quiz_id)s] [%(hostname)s:%(process)d] - %(message)s'

# Add hostname to log record
old_factory = logging.getLogRecordFactory()
def record_factory(*args, **kwargs):
    record = old_factory(*args, **kwargs)
    record.hostname = socket.gethostname()
    return record
logging.setLogRecordFactory(record_factory)

# Create logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG if os.getenv('DEBUG') else logging.INFO)

# Remove any existing handlers
logger.handlers = []

# Create console handler with color
console_handler = colorlog.StreamHandler()
console_handler.setFormatter(colorlog.ColoredFormatter(
    console_format,
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
    }
))

# Create file handler
file_handler = logging.FileHandler(log_dir / f"eval_{datetime.now().strftime('%Y%m%d')}.log")
file_handler.setFormatter(logging.Formatter(file_format))

# Add handlers to logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)

class QuizLogger:
    """Quiz-specific logger that writes to both global and quiz-specific log files with different verbosity levels"""
    def __init__(self, quiz_id: str):
        self.quiz_id = quiz_id
        self.quiz_log_dir = Path(f"data/json/{quiz_id}")
        self.quiz_log_dir.mkdir(parents=True, exist_ok=True)
        self.quiz_log_file = self.quiz_log_dir / "quiz.log"
        
        # Create quiz-specific file handler with detailed formatting
        self.quiz_handler = logging.FileHandler(self.quiz_log_file)
        self.quiz_handler.setFormatter(logging.Formatter(quiz_format))
        
        # Create logger for this quiz
        self.logger = logging.getLogger(f"quiz.{quiz_id}")
        self.logger.setLevel(logging.DEBUG)  # Always use DEBUG for quiz-specific logs
        self.logger.addHandler(self.quiz_handler)
        
        # Add quiz_id to log records
        self.old_factory = logging.getLogRecordFactory()
        def record_factory(*args, **kwargs):
            record = self.old_factory(*args, **kwargs)
            record.quiz_id = self.quiz_id
            return record
        self.record_factory = record_factory
        logging.setLogRecordFactory(self.record_factory)

    def debug(self, msg, *args, **kwargs):
        """Log debug message (quiz-specific only)"""
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        """Log info message (both quiz-specific and main, but with different detail levels)"""
        self.logger.debug(msg, *args, **kwargs)  # Detailed in quiz log
        # Only log important info messages to main logger
        if any(key in msg.lower() for key in ['start', 'complet', 'finish', 'fail', 'error', 'score']):
            logger.info(f"[{self.quiz_id}] {msg}", *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        """Log warning message (both loggers)"""
        self.logger.warning(msg, *args, **kwargs)
        logger.warning(f"[{self.quiz_id}] {msg}", *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        """Log error message (both loggers)"""
        self.logger.error(msg, *args, **kwargs)
        logger.error(f"[{self.quiz_id}] {msg}", *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        """Log critical message (both loggers)"""
        self.logger.critical(msg, *args, **kwargs)
        logger.critical(f"[{self.quiz_id}] {msg}", *args, **kwargs)

    def __del__(self):
        """Cleanup logging handlers"""
        self.quiz_handler.close()
        self.logger.removeHandler(self.quiz_handler)
        logging.setLogRecordFactory(self.old_factory)

def log_evaluation(test_name: str, params: dict, result: dict):
    """
    Log an evaluation event with structured data
    
    Args:
        test_name: Name/identifier of the evaluation
        params: Dictionary of evaluation parameters
        result: Dictionary containing evaluation results
    """
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "event_type": "evaluation",
        "test_name": test_name,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "parameters": params,
        "result": result
    }
    logger.info(json.dumps(log_entry, indent=2))
