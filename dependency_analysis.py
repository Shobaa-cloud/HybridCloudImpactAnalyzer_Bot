import json


# Load dependency information
with open("dependencies.json", "r") as file:
    dependencies = json.load(file)


def find_dependencies(resource, level=0):
    """Find all dependent resources recursively."""

    dependent_resources = dependencies.get(resource, [])

    for item in dependent_resources:
        print("  " * level + "→", item)

        # Find the next level of dependency
        find_dependencies(item, level + 1)


def analyze_resource(resource):
    """Analyze dependencies of a resource."""

    print()
    print("=== Resource Dependency Analysis ===")
    print()
    print("Changed Resource:", resource)
    print()
    print("Dependency Chain:")
    print(resource)

    find_dependencies(resource)