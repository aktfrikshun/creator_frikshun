PLATFORMS = (
    "facebook",
    "instagram",
    "youtube",
    "tiktok",
    "x",
    "fanvue",
    "chlokat_archive",
)


def sample_platform_drafts():
    return [
        {
            "platform": platform,
            "status": "placeholder",
            "caption": f"Draft generator placeholder for {platform}.",
        }
        for platform in PLATFORMS
    ]
