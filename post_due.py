"""Publish every gooseecrumbs post whose time has come. Run by GitHub Actions.

schedule.json holds the posts, made in advance on the laptop and already
uploaded to Cloudinary. This script:
  1. finds the earliest post with status "pending" whose publish_at has passed,
  2. creates it on Instagram from its Cloudinary link(s) (reel, photo or carousel),
  3. waits for Instagram to finish processing, then publishes it,
  4. records status "posted", the time and the post's link in schedule.json
     (the workflow commits that file back, so a post can never go out twice),
  5. deletes the Cloudinary copy.

Only one post per run: if the laptop was off and several are overdue, they go
out one per run (every 20 min) instead of all at once.

Statuses:
  awaiting_approval  made but not approved yet: never posted
  pending            approved: posted at publish_at
  posted             done
  failed             stopped after an error; needs a human (see "error")

Secrets (GitHub > Settings > Secrets and variables > Actions):
  INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ACCOUNT_ID, CLOUDINARY_URL

Notes:
  - An Instagram-Login token only accepts media by public URL (video_url /
    image_url); direct upload is refused. Hence Cloudinary.
  - Photo and carousel images must be JPEG.
  - Never retry a publish blindly: if media_publish fails, the post is marked
    "failed" so a human checks the profile first (a timeout can still post).
  - GitHub's own timer (cron) never fired on this repo on 30 Sep 2026 - zero
    scheduled runs in 5 hours, settings all correct. GitHub's cron is best
    effort only. The real timer is an outside service (cron-job.org) that
    starts this workflow a few minutes before each post; GitHub's cron is kept
    as a backup.
  - So posts land on time even when the trigger comes early, a run waits (up
    to WAIT_AHEAD minutes) for a post that is almost due, then posts it.
  - Two runs close together could both see the same post as pending (the
    second checked out before the first saved "posted"). Guards: the workflow
    pulls the newest schedule before running and rebases before saving, and
    this script skips a post whose caption is already on the profile.
  - The Instagram token lasts 60 days (generated 30 Sep 2026, so it must be
    regenerated before late November 2026).
"""

import datetime as dt
import hashlib
import json
import os
import sys
import time

import requests

GRAPH = "https://graph.instagram.com/v23.0"
WAIT_AHEAD = 15  # minutes
SCHEDULE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule.json")


def env(name):
    v = os.environ.get(name)
    if not v:
        sys.exit("missing secret: %s" % name)
    return v


def ig(method, path, **params):
    params["access_token"] = env("INSTAGRAM_ACCESS_TOKEN")
    r = requests.request(method, GRAPH + path, params=params, timeout=120)
    j = r.json() if r.content else {}
    if r.status_code != 200 or "error" in j:
        raise RuntimeError("Instagram %s %s: %s" % (method, path, j.get("error") or r.text[:300]))
    return j


def wait_ready(cid):
    for _ in range(60):
        s = ig("GET", "/%s" % cid, fields="status_code,status")
        if s.get("status_code") == "FINISHED":
            return
        if s.get("status_code") == "ERROR":
            raise RuntimeError("Instagram could not process media: %s" % s.get("status"))
        time.sleep(10)
    raise RuntimeError("Instagram still processing after 10 minutes")


def already_posted(uid, caption):
    """Link of a recent post with this exact caption, or None."""
    items = ig("GET", "/%s/media" % uid, fields="caption,permalink", limit=10).get("data", [])
    for m in items:
        if (m.get("caption") or "").strip() == caption.strip():
            return m.get("permalink") or "(link unknown)"
    return None


def cloudinary_delete(public_id, rtype):
    url = env("CLOUDINARY_URL")
    creds, cloud = url[len("cloudinary://"):].split("@", 1)
    key, secret = creds.split(":", 1)
    p = {"public_id": public_id, "timestamp": str(int(time.time()))}
    p["signature"] = hashlib.sha1(("&".join("%s=%s" % (k, p[k]) for k in sorted(p)) + secret)
                                  .encode()).hexdigest()
    p["api_key"] = key
    requests.post("https://api.cloudinary.com/v1_1/%s/%s/destroy" % (cloud, rtype), data=p, timeout=60)


def create(post, uid):
    t = post["type"]
    if t == "reel":
        c = ig("POST", "/%s/media" % uid, media_type="REELS", video_url=post["media"][0]["url"],
               caption=post["caption"], share_to_feed="true")
    elif t == "photo":
        c = ig("POST", "/%s/media" % uid, image_url=post["media"][0]["url"], caption=post["caption"])
    elif t == "carousel":
        kids = []
        for m in post["media"]:
            k = ig("POST", "/%s/media" % uid, image_url=m["url"], is_carousel_item="true")
            kids.append(k["id"])
        for k in kids:
            wait_ready(k)
        c = ig("POST", "/%s/media" % uid, media_type="CAROUSEL", children=",".join(kids),
               caption=post["caption"])
    else:
        raise RuntimeError("unknown post type %s" % t)
    wait_ready(c["id"])
    return c["id"]


def main():
    uid = env("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    posts = json.load(open(SCHEDULE, encoding="utf-8"))
    now = dt.datetime.now(dt.timezone.utc)
    due = [p for p in posts if p["status"] == "pending"
           and dt.datetime.fromisoformat(p["publish_at"]) <= now]
    waiting = [p["id"] for p in posts if p["status"] == "awaiting_approval"]
    if waiting:
        print("not approved yet (will not post):", ", ".join(waiting))
    if not due:
        soon = [p for p in posts if p["status"] == "pending"
                and dt.datetime.fromisoformat(p["publish_at"]) <= now + dt.timedelta(minutes=WAIT_AHEAD)]
        if not soon:
            print("nothing due at %s" % now.isoformat(timespec="minutes"))
            return
        post = min(soon, key=lambda p: p["publish_at"])
        wait = (dt.datetime.fromisoformat(post["publish_at"]) - now).total_seconds()
        print("%s is due in %.0f s: waiting" % (post["id"], wait))
        time.sleep(max(0, wait))
        due = [post]
    post = min(due, key=lambda p: p["publish_at"])
    print("posting %s (%s, due %s)" % (post["id"], post["type"], post["publish_at"]))

    already = already_posted(uid, post["caption"])
    if already:  # an earlier run posted it but could not save the status
        post["status"] = "posted"
        post["permalink"] = already
        save(posts)
        print("ALREADY ON PROFILE %s: %s (not posting again)" % (post["id"], already))
        return

    try:
        cid = create(post, uid)
    except Exception as e:  # nothing published yet: safe to try again next run
        post["attempts"] = post.get("attempts", 0) + 1
        post["last_error"] = str(e)[:500]
        if post["attempts"] >= 3:
            post["status"] = "failed"
        save(posts)
        sys.exit("could not prepare %s: %s" % (post["id"], e))

    try:
        pub = ig("POST", "/%s/media_publish" % uid, creation_id=cid)
    except Exception as e:  # may or may not have gone out: a human must check
        post["status"] = "failed"
        post["last_error"] = "publish step: %s" % str(e)[:500]
        save(posts)
        sys.exit("publish failed for %s: %s" % (post["id"], e))

    post["status"] = "posted"
    post["posted_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    try:
        post["permalink"] = ig("GET", "/%s" % pub["id"], fields="permalink").get("permalink")
    except Exception:
        post["permalink"] = None
    save(posts)
    print("POSTED %s: %s" % (post["id"], post["permalink"]))
    for m in post["media"]:
        try:
            cloudinary_delete(m["public_id"], "video" if post["type"] == "reel" else "image")
        except Exception as e:
            print("warning: could not delete Cloudinary copy %s: %s" % (m["public_id"], e))


def save(posts):
    with open(SCHEDULE, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
