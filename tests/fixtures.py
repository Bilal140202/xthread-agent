"""Synthetic fixtures for the xthread-agent test suite.

Every ID, screen name, URL and text here is SYNTHETIC (repository rule:
no real account names, status IDs, or harvested content may be committed).
Builders return plain dicts shaped like the payloads the live services
return, so tests stay independent of the network.
"""

ROOT_ID = "1000000000000000001"
CHILD1_ID = "1000000000000000002"
CHILD2_ID = "1000000000000000003"
DECOY_ID = "1000000000000000009"      # same-author recommendation (not a reply)
MEDIA_ID = "2199999999999999999"      # bare amplify/media id (FixTweet 404s)
PARENT_ID = "1000000000000000000"     # ancestor above root (thread start)
STRANGER_ID = "1000000000000000008"   # reply by a different author

AUTHOR = {
    "screen_name": "fixtureuser",
    "name": "Fixture User",
    "id": "111",
    "description": "synthetic fixture account",
    "location": "Test City",
    "avatar_url": "https://pbs.twimg.com/profile_images/111/fixture_200x200.jpg",
    "banner_url": "https://pbs.twimg.com/profile_banners/111/1700000000",
    "followers": 1000,
    "following": 10,
    "media_count": 5,
    "verification": {"verified": True, "verified_at": None, "type": "individual"},
    "protected": False,
    "joined": "Wed Jan 01 00:00:00 +0000 2020",
    "website": {"url": "https://example.com/fixture", "display_url": "example.com/fixture"},
}


def fxtweet(tid=ROOT_ID, text="fixture post", replying_to=None,
            replying_to_status=None, screen_name=None, photos=None,
            videos=None, quote=None, created_timestamp=1700000000,
            metrics=None, source="fxtwitter"):
    """Build a FixTweet-shaped tweet payload."""
    media = {}
    if photos is not None:
        media["photos"] = photos
    if videos is not None:
        media["videos"] = videos
    tw = {
        "url": f"https://x.com/{screen_name or AUTHOR['screen_name']}/status/{tid}",
        "id": str(tid),
        "text": text,
        "raw_text": {"text": text, "display_text_range": [0, len(text)], "facets": []},
        "author": dict(AUTHOR, **({"screen_name": screen_name} if screen_name else {})),
        "replies": 3, "retweets": 4, "likes": 5, "bookmarks": 6, "quotes": 7,
        "views": 8,
        "created_at": "Tue Nov 14 22:13:20 +0000 2023",
        "created_timestamp": created_timestamp,
        "lang": "en",
        "replying_to": replying_to,
        "replying_to_status": replying_to_status,
        "is_note_tweet": False,
        "community_note": None,
        "source": "Twitter Web Client",
        "twitter_card": "tweet",
        "color": None,
        "provider": "twitter",
        "reposted_by": None,
        "_extraction_source": source,
    }
    if metrics:
        tw.update(metrics)
    if media:
        tw["media"] = media
    if quote is not None:
        tw["quote"] = quote
    return tw


def photo(url=None, alt=None, width=1200, height=800):
    return {"type": "photo", "url": url or "https://pbs.twimg.com/media/fixturephoto1?format=jpg&name=large",
            "alt_text": alt, "width": width, "height": height}


def video(url=None, thumbnail=None, duration=41.6, width=1280, height=720,
          formats=None):
    v = {"type": "video",
         "url": url or "https://video.twimg.com/ext_tw_video/2199999999999999991/pu/vid/avc1/1280x720/fixture.mp4?tag=14",
         "thumbnail_url": thumbnail or "https://pbs.twimg.com/ext_tw_video_thumb/2199999999999999991/pu/img/fixture.jpg",
         "duration": duration, "width": width, "height": height,
         "format": "video/mp4"}
    if formats is not None:
        v["formats"] = formats
    return v


def hls_video_with_mp4_variants():
    """A video whose top-level URL is an m3u8 playlist but whose formats[]
    carries mp4 variants (common shape) — the v3 variant-selection path."""
    base = "https://video.twimg.com/ext_tw_video/2199999999999999992/pu"
    return {
        "type": "video",
        "url": f"{base}/pl/fixture.m3u8?tag=14",
        "thumbnail_url": "https://pbs.twimg.com/ext_tw_video_thumb/2199999999999999992/pu/img/fixture.jpg",
        "duration": 257.857, "width": 3840, "height": 2160,
        "format": "application/x-mpegURL",
        "formats": [
            {"url": f"{base}/pl/fixture.m3u8?tag=14", "container": "m3u8"},
            {"url": f"{base}/vid/avc1/480x270/fixture_a.mp4?tag=14",
             "bitrate": 256000, "container": "mp4", "codec": "h264"},
            {"url": f"{base}/vid/avc1/1280x720/fixture_b.mp4?tag=14",
             "bitrate": 2176000, "container": "mp4", "codec": "h264"},
            {"url": f"{base}/vid/avc1/1920x1080/fixture_c.mp4?tag=14",
             "bitrate": 10368000, "container": "mp4", "codec": "h264"},
        ],
    }


def quote_tweet():
    """A quoted post carrying its own media (synthetic)."""
    return fxtweet(
        tid="1000000000000000077",
        text="fixture quoted post",
        photos=[photo()],
        videos=[video()],
    )


def unrollnow_page(member_ids, noise_ids=(), root_id=None):
    """Build an UnrollNow-shaped HTML page embedding the given IDs."""
    links = "".join(
        f'<a href="/status/{i}">fixture</a>' for i in list(member_ids) + list(noise_ids))
    page = f"""<!DOCTYPE html>
<html lang="en"><head><title>Thread By @fixtureuser - fixture post</title></head>
<body>
{links}
<script>var media_ids = [{", ".join(str(i) for i in noise_ids)}];</script>
</body></html>"""
    if root_id:
        page += f'<link rel="canonical" href="/status/{root_id}">'
    return page


def threadreader_page(member_ids, noise_ids=(), root_id=None):
    """Build a ThreadReaderApp-shaped HTML page (the fallback walker slot)
    embedding the given IDs as absolute /status/ links."""
    links = "".join(
        f'<a href="https://threadreaderapp.com/status/{i}">fixture</a>'
        for i in list(member_ids) + list(noise_ids))
    page = f"""<!DOCTYPE html>
<html lang="en"><head><title>Thread by @fixtureuser</title></head>
<body>
{links}
</body></html>"""
    if root_id:
        page += f'<link rel="canonical" href="https://threadreaderapp.com/thread/{root_id}">'
    return page


def vxtweet(tid=ROOT_ID):
    """A vxtwitter-shaped payload (fallback decoder slot)."""
    return {
        "tweetID": str(tid),
        "tweetURL": f"https://twitter.com/fixtureuser/status/{tid}",
        "text": "fixture post via vx",
        "date": "Tue Nov 14 22:13:20 +0000 2023",
        "date_epoch": 1700000000,
        "user_screen_name": "fixtureuser",
        "user_name": "Fixture User",
        "user_avatar_url": "https://pbs.twimg.com/profile_images/111/fixture_200x200.jpg",
        "likes": 5, "retweets": 4, "replies": 3,
        "lang": "en",
        "replyingTo": None,
        "replyingToID": None,
        "qrt": None,
        "mediaURLs": [],
        "media_extended": [
            {"type": "photo", "url": "https://pbs.twimg.com/media/fixturevx1?format=jpg&name=large",
             "width": 1200, "height": 800},
            {"type": "video", "url": "https://video.twimg.com/ext_tw_video/2199999999999999993/pu/vid/avc1/720x1280/fixture.mp4?tag=14",
             "thumbnail_url": "https://pbs.twimg.com/ext_tw_video_thumb/2199999999999999993/pu/img/fixture.jpg",
             "duration": 12.5, "width": 720, "height": 1280},
        ],
        "hashtags": [],
        "hasMedia": True,
        "hasVideo": True,
    }
