import json

import app_clean


def _render_actions(filters):
    greylist = float(filters["greylist"])
    add_header = float(filters["spam_add_header"])
    reject = float(filters["spam_reject"])

    # Rspamd 3.11 can fail in lua_cfg_transform when an action threshold is
    # merged as `null` (userdata) while other thresholds are numeric. DMS uses
    # rewrite_subject when SPAM_SUBJECT is configured, so always provide a
    # numeric rewrite threshold as part of the complete action set.
    # Keep it just above add_header so ordinary spam headers are applied first.
    rewrite_subject = round(add_header + 0.1, 2)
    if rewrite_subject >= reject:
        rewrite_subject = round((add_header + reject) / 2, 2)

    return (
        "# Managed by MailGate WebUI\n"
        f"greylist = {greylist};\n"
        f"add_header = {add_header};\n"
        f"rewrite_subject = {rewrite_subject};\n"
        f"reject = {reject};\n"
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
    greylist = float(filters["greylist"])
    add_header = float(filters["spam_add_header"])
    reject = float(filters["spam_reject"])
    if not 0 <= greylist <= add_header < reject:
        raise ValueError("Required order: greylist ≤ add-header < reject.")

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
