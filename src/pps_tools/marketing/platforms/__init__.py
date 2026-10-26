"""Ad platform connectors and the registry of the ones the hub loads."""

from __future__ import annotations


def default_platform_classes() -> list:
    """Every connector, in the order the UI lists them."""
    from pps_tools.marketing.platforms.google_ads import GoogleAdsPlatform
    from pps_tools.marketing.platforms.linkedin import LinkedInPlatform
    from pps_tools.marketing.platforms.meta import MetaPlatform
    from pps_tools.marketing.platforms.microsoft_ads import MicrosoftAdsPlatform
    from pps_tools.marketing.platforms.pinterest import PinterestPlatform
    from pps_tools.marketing.platforms.tiktok import TikTokPlatform
    from pps_tools.marketing.platforms.x import XPlatform

    return [
        GoogleAdsPlatform, MetaPlatform, PinterestPlatform, XPlatform, LinkedInPlatform, TikTokPlatform,
        MicrosoftAdsPlatform,
    ]
