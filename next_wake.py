"""How long the keep-alive timer should sleep before starting the poster. Run by keepalive.yml.

Prints two lines for the workflow:
    sleep=<seconds>
    post=<yes|no>
post=yes means "after sleeping, start post.yml": the next post is due about
LEAD seconds after the wake-up (post_due.py then waits for the exact minute).
post=no means the next post is further away than one job may run (GitHub stops
a job after 6 hours), so the timer only sleeps MAX_SLEEP and hands over to a
fresh copy of itself.

Notes:
  - Why this exists: GitHub's own cron never fired on this repo on 30 Sep 2026
    (zero scheduled runs in 6 hours, settings correct). A run started by the
    workflow's own GITHUB_TOKEN via workflow_dispatch IS allowed to start new
    runs, so the timer keeps itself going without cron and without any key
    outside GitHub.
  - Posts already overdue (e.g. after an outage) are retried every RETRY
    seconds, not straight away: on 30 Sep 2026 Instagram answered "API access
    blocked" for hours, and an instant retry would loop every few minutes and
    send a GitHub failure email each time.
  - The target skips posts due within SKIP seconds, because the one just
    started may not have saved "posted" yet when the next timer checks.
"""

import datetime as dt
import json
import os

LEAD = 120          # wake 2 minutes before a post
MAX_SLEEP = 5 * 3600 + 30 * 60   # 5 h 30 min, under GitHub's 6 h job limit
SKIP = 180
RETRY = 30 * 60
SCHEDULE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule.json")


def main():
    posts = json.load(open(SCHEDULE, encoding="utf-8"))
    now = dt.datetime.now(dt.timezone.utc)
    times = sorted(dt.datetime.fromisoformat(p["publish_at"]) for p in posts if p["status"] == "pending")
    if not times:
        print("sleep=0\npost=no\nnone=yes")
        return
    overdue = [t for t in times if t <= now - dt.timedelta(seconds=SKIP)]
    upcoming = [t for t in times if t > now + dt.timedelta(seconds=SKIP)]
    if overdue:
        print("sleep=%d\npost=yes" % RETRY)
        return
    if not upcoming:  # the only pending post is being posted right now
        print("sleep=%d\npost=no" % (SKIP * 2))
        return
    wait = (upcoming[0] - now).total_seconds() - LEAD
    if wait > MAX_SLEEP:
        print("sleep=%d\npost=no" % MAX_SLEEP)
    else:
        print("sleep=%d\npost=yes" % max(0, wait))


if __name__ == "__main__":
    main()
