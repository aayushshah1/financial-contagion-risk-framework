import json

# 1. Load the original "weird" file
with open('test_basel_II.json', 'r') as f:
    data = json.load(f)

# 2. Extract the string inside "docs" and parse it into a real Python object
# We use json.loads() here because we are loading from a String
if isinstance(data.get('docs'), str):
    data['docs'] = json.loads(data['docs'])

# 3. Save the result to a new file with nice formatting (indentation)
with open('cleaned_test_basel_II.json', 'w') as f:
    json.dump(data, f, indent=4)

print("File successfully cleaned and saved to 'cleaned_test.json'")