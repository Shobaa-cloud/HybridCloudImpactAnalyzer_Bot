import json


# Load dependency information
with open("dependencies.json", "r") as file:
    dependencies = json.load(file)


def find_dependencies(resource, level=0):
    """Find all dependent resources recursively."""

    dependent_resources = dependencies.get(resource, [])

    all_dependencies = []

    for item in dependent_resources:
        print("  " * level + "→", item)

        all_dependencies.append(item)

        # Find the next level
        child_dependencies = find_dependencies(item, level + 1)

        all_dependencies.extend(child_dependencies)

    return all_dependencies

def analyze_resource(resource):
    """Analyze dependencies of a resource."""

    print()
    print("=== Resource Dependency Analysis ===")
    print()
    print("Changed Resource:", resource)
    print()
    print("Dependency Chain:")
    print(resource)

    all_dependencies = find_dependencies(resource)

    return all_dependencies