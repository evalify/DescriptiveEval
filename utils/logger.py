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
