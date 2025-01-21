import json
from datetime import datetime

class DateTimeEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (datetime)):
                return obj.isoformat()  # Convert to ISO format
            return super().default(obj)