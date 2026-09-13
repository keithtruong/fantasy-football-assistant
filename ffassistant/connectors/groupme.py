"""Write-only GroupMe connector: posts a message via a GroupMe Bot.

A GroupMe Bot (created at dev.groupme.com) is scoped to exactly one group,
so posting only ever needs its bot_id — no personal access token, and no
way for this connector to read anything back from the group. That's the
right shape for the recap flow: push the recap link into Keith's TAMS
GroupMe channel, nothing more.
"""

import requests

from ffassistant.config import GROUPME_BOT_ID

GROUPME_BOTS_POST_URL = "https://api.groupme.com/v3/bots/post"


def post_message(text: str, bot_id: str | None = None) -> None:
    """Posts `text` into whichever group the bot (identified by bot_id, or
    GROUPME_BOT_ID from .env if not passed) is attached to.

    Raises ValueError if no bot_id is available from either source, and
    requests.HTTPError on a non-2xx response — callers (e.g. the recap send
    flow) should let this propagate/report rather than silently losing a
    failed post.
    """
    resolved_bot_id = bot_id or GROUPME_BOT_ID
    if not resolved_bot_id:
        raise ValueError("GROUPME_BOT_ID not set (see .env / .env.example)")

    response = requests.post(
        GROUPME_BOTS_POST_URL,
        json={"bot_id": resolved_bot_id, "text": text},
        timeout=10,
    )
    response.raise_for_status()
