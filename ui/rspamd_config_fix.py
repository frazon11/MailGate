import json
from pathlib import Path

import app_clean


def _render_actions(filters):
    return (
        "# Managed by MailGate WebUI\n"
        f"greylist = {float(filters['greylist'])};\n"
        f"add_header = {float(filters['spam_add_header'])};\n"
        f"reject = {float(filters['spam_reject'])};\n"
    )


def _render_commands(filters):
    lines = ["# Managed by MailGate WebUI"]
    lines.append(
        "enable-module greylist"
        if filters.get("greylisting_enabled", False)
        else "disable-module greylist"
    )
    lines.append(
        "enable-module antivirus"
        if filters.get("antivirus_enabled", True)
        else "disable-module antivirus"
    )
    return "\n".join(lines) + "\n"


def save_filters_fixed(filters):
    app_clean.atomic_write(
        app_clean.FILTER_FILE,
        json.dumps(filters, indent=2) + "\n",
    )
    app_clean.atomic_write(app_clean.ACTIONS_FILE, _render_actions(filters))
    app_clean.atomic_write(app_clean.COMMANDS_FILE, _render_commands(filters))


def migrate_existing_rspamd_config():
    filters = app_clean.load_filters()
    save_filters_fixed(filters)


# Replace the old generator for all subsequent WebUI saves.
app_clean.save_filters = save_filters_fixed

# Repair invalid files left by earlier MailGate builds as soon as the UI starts.
migrate_existing_rspamd_config()
