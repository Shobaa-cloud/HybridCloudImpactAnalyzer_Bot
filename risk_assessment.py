def calculate_risk(impact_level, setting):
    """Calculate risk based on impact and configuration type."""

    if setting == "allowed_ip":
        if impact_level == "HIGH":
            return "CRITICAL"
        elif impact_level == "MEDIUM":
            return "HIGH"
        else:
            return "MEDIUM"

    if impact_level == "HIGH":
        return "HIGH"
    elif impact_level == "MEDIUM":
        return "MEDIUM"
    else:
        return "LOW"


def show_risk(resource, setting, impact_level):
    """Display the risk assessment."""

    risk = calculate_risk(impact_level, setting)

    print()
    print("=== Risk Assessment ===")
    print()
    print("Resource:", resource)
    print("Changed Setting:", setting)
    print("Impact Level:", impact_level)
    print()
    print("Risk Level:", risk)