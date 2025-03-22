import datetime
from pytz import timezone
from app.core.logger import logger


def get_column_letter(col_idx):
    """Convert column index to Excel column letter (1-based)"""
    from openpyxl.utils import get_column_letter as openpyxl_get_column_letter

    return openpyxl_get_column_letter(col_idx)


def format_date(date_str):
    """Convert UTC datetime string to IST date string"""
    if not date_str:
        return "N/A"
    try:
        # Check if date_str is already a datetime object
        if isinstance(date_str, str):
            # Parse the datetime string
            utc_dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        else:
            utc_dt = date_str
        # Convert to IST (UTC+5:30)
        ist = timezone("Asia/Kolkata")
        ist_dt = utc_dt.replace(tzinfo=timezone("UTC")).astimezone(ist)
        # Format as date string
        return ist_dt.strftime("%d/%m/%Y")
    except Exception as e:
        logger.error(f"Error formatting date: {e}")
        return date_str
