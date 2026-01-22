from rest_framework.request import Request
from polaris.models import Asset

def toml_contents(request, *args, **kwargs):
  asset = Asset.objects.first()
  # asset2 = Asset.objects.last()

  # Get distribution accounts from all assets
  accounts = [a.distribution_account for a in Asset.objects.exclude(distribution_seed__isnull=True).exclude(distribution_seed='') if a.distribution_account]

  return {
    "ACCOUNTS": accounts,
    "DOCUMENTATION":
      {
        "ORG_NAME": "LINK.IO GLOBAL LTD",
        "ORG_LOGO": "https://uploads-ssl.webflow.com/60a70a1080cf2974d4b1595e/60b623a4d06b3b67a49c9e82_WEBCLIP.png",
        "ORG_URL": "https://linkio.world",
        "ORG_LOGO": "https://linkio.world/logo.png",
        "ORG_DESCRIPTION": "LINK provides USDC on/off-ramp services for Nigerian users. Buy and sell USDC with NGN through our secure platform.",
        "ORG_OFFICIAL_EMAIL": "support@linkio.world",
        "ORG_SUPPORT_EMAIL": "support@linkio.world",
        "ORG_GITHUB": "/linkioafrica",
      },
    "PRINCIPALS": [
      {
        "name": "LINK Operations",
        "email": "support@linkio.africa"
      },
    ],
    "CURRENCIES": [
      {
        "code": asset.code,
        "issuer": asset.issuer,
        "anchor_asset_type": "fiat",
        "anchor_asset": "NGN",
        "redemption_instructions": "Send USDC to LINK and receive NGN via bank transfer or mobile money",
        "desc": "Circle USD Coin (USDC) on Stellar. LINK provides seamless USDC/NGN exchange services.",
        "name": "USD Coin",
        "status": "live",
        "display_decimals": 2,
        "is_asset_anchored": "true",
      },
    ]
  }
