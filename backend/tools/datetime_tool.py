from datetime import datetime


def get_date_time() -> str:
    now = datetime.now()
    return now.strftime("It's %I:%M %p on %A, %B %d %Y.")
