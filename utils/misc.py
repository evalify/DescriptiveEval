import json
import re
from datetime import datetime

class DateTimeEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (datetime)):
                return obj.isoformat()  # Convert to ISO format
            return super().default(obj)
        
# Create a function that will remove all html tags in a given string
def remove_html_tags(data):
    p = re.compile(r'<.*?>')
    return p.sub('', data)

if __name__ == '__main__':
    # Sample data
    data = {
        "_id": "678f1e9ddf031e96652e5c1e",
        "type": "MCQ",
        "difficulty": "MEDIUM",
        "mark": 1,
        "question": "<p>Four different mathematics books, six different physics books and two different chemistry books are to be arranged on a shelf. How many different arrangements are possible if only the mathematics books must stand together?&nbsp;&nbsp;</p><p></p>",
        "created_at": datetime.now(),
    }

    # Convert data to JSON with custom DateTimeEncoder
    json_data = json.dumps(data, cls=DateTimeEncoder, indent=4) # Testing the DateTimeEncoder
    print(json_data)

    # Remove HTML tags from description
    cleaned_description = remove_html_tags(data['question']) # Testing the remove_html_tags function
    print(cleaned_description)