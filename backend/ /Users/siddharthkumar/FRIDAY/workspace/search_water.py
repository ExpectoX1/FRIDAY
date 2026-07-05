import os

dir_path = "/Users/siddharthkumar/Desktop"
results = []
for entry in os.listdir(dir_path):
    if "water" in entry.lower():
        results.append(entry)
print("Water-related items on Desktop:")
for r in results:
    print(r)
if not results:
    print("No water-related items found.")