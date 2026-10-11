"""Sends one test alert through ffassistant.notify, to confirm the alerts
GroupMe bot is set up (GROUPME_ALERTS_BOT_ID in .env) and lands in the private
alerts group — not the TAMS league group.

Usage:
    python -m scripts.send_test_alert
"""

import sys

from ffassistant import notify


def main():
    record = notify.send({"kind": "test", "text": "FF Assistant test alert: if you can read this, alerts are working."})
    if record["delivered"]:
        print("Sent. Check your private alerts group in GroupMe.")
        return 0
    print(f"Not sent: {record.get('error') or 'GROUPME_ALERTS_BOT_ID is not set in .env'}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
