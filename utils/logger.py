"""This module contains a simple logger for evaluation results"""

import json
import logging
from datetime import datetime
from pathlib import Path

# Create logs directory if it doesn't exist
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / f"eval_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger()  # Use the root logger


def log_evaluation(test_name, params, result):
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "test_name": test_name,
        "parameters": params,
        "result": result
    }
    logger.info(json.dumps(log_entry, indent=2)) #TODO: Add better logging
