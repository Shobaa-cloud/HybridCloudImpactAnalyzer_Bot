def calculate_impact(dependent_resources):
    """Calculate impact level based on number of affected resources."""

    count = len(dependent_resources)

    if count == 0:
        return "LOW"
    elif count == 1:
        return "MEDIUM"
    else:
        return "HIGH"


def show_impact(resource, dependent_resources):
    """Display the impact assessment."""

    impact = calculate_impact(dependent_resources)

    print()
    print("=== Impact Assessment ===")
    print()
    print("Changed Resource:", resource)
    print("Affected Resources:", len(dependent_resources))
    print()
    print("Impact Level:", impact)
    return impact
