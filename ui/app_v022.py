import app_clean
from activity_log import bp as activity_log_blueprint


def _nav_with_activity(active):
    items = [
        ("dashboard", "Dashboard", "/"),
        ("accounts", "Accounts & Delivery", "/accounts"),
        ("spam", "Spam Protection", "/spam"),
        ("antivirus", "Antivirus", "/antivirus"),
        ("activity", "Activity Log", "/activity"),
        ("security", "Security / Profile", "/security"),
    ]
    return "".join(
        f'<a class="{"active" if key == active else ""}" href="{href}">{label}</a>'
        for key, label, href in items
    )


app_clean.nav = _nav_with_activity
app = app_clean.app
app.register_blueprint(activity_log_blueprint)
