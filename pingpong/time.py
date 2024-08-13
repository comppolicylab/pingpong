def convert_seconds(seconds):
    # Define time units in seconds
    time_units = [
        ("week", 7 * 24 * 60 * 60),
        ("day", 24 * 60 * 60),
        ("hour", 60 * 60),
        ("minute", 60),
        ("second", 1),
    ]

    # Calculate the time for each unit
    time_list = []
    for name, unit in time_units:
        if seconds >= unit:
            value, seconds = divmod(seconds, unit)
            time_list.append((value, name))

    # If there's only one unit, default to the lower one if applicable
    if len(time_list) == 1:
        value, name = time_list[0]
        if name == "day":
            return f"{value * 24} hours"
        elif name == "week":
            return f"{value * 7} days"

    # Create the formatted time string
    result = []
    for value, name in time_list:
        if value > 1:
            result.append(f"{value} {name}s")
        else:
            result.append(f"{value} {name}")

    return ", ".join(result)
