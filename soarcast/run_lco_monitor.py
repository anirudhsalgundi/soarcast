from soarcast.lco_monitor import main as get_lco_digest
from soarcast.notify import send_lco_changes, send_lco_aeon_reminder, send_slack_failure

try:
    digest = get_lco_digest()
    send_lco_changes(digest)
    send_lco_aeon_reminder(digest)
except Exception as e:
    send_slack_failure(e, LCO_CHANGES_WEBHOOK)