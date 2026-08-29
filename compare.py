import json
from dependency_analysis import analyze_resource 
from impact_assessment import show_impact
from risk_assessment import show_risk
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
        affected_resources = analyze_resource(resource)

        impact_level = show_impact(resource, affected_resources)

        setting = "allowed_ip"

        show_risk(resource, setting, impact_level)

    else:
        print("Resource information not found.")