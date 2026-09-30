# gooseecrumbs auto-poster

Posts the gooseecrumbs Instagram content on schedule, even when the laptop is off.

- `schedule.json`: every post, its time (India time), caption, media link and status.
  - `awaiting_approval`: made, not approved: **never posted**
  - `pending`: approved: posted at its time
  - `posted`: done (with the Instagram link)
  - `failed`: stopped after an error; check the Instagram profile before retrying
- `post_due.py`: posts whatever is due (one post per run).
- `.github/workflows/post.yml`: GitHub runs it every 20 minutes, 09:37 to 22:17 India time.

Posts are made on the laptop (Google Flow, ElevenLabs, Flow Music) and added here with
`tools/schedule_post.py`. Keys live only in GitHub's encrypted Actions secrets:
`INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_BUSINESS_ACCOUNT_ID`, `CLOUDINARY_URL`.

The Instagram token expires 60 days after 30 Sep 2026: regenerate it before late November.
