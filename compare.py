import json
from dependency_analysis import analyze_resource 
# Read old configuration
with open("old_config.json", "r") as file:
    old_config = json.load(file)

# Read new configuration
with open("new_config.json", "r") as file:
    new_config = json.load(file)

print("========== Configuration Change Detection ==========\n")

change_found = False

for key in old_config:

    if old_config[key] != new_config[key]:

        print("Change Detected!")
        print("---------------------------")
        print("Setting :", key)
        print("Old Value :", old_config[key])
        print("New Value :", new_config[key])
        print()

        change_found = True

if not change_found:
    print("No configuration changes found.")
else:
    resource = old_config.get("resource")

    if resource:
        analyze_resource(resource)
    else:
        print("Resource information not found.")