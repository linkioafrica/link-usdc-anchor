from django.apps import AppConfig

class AnchorConfig(AppConfig):
    name = "anchor"

    def ready(self):
        from polaris.integrations import register_integrations

        from .integrations import (
            toml_contents,
            # AnchorDeposit,
            # AnchorWithdraw,
            # AnchorRails,
        )

        register_integrations(
            toml = toml_contents,
            # deposit=AnchorDeposit(),
            # withdrawal=AnchorWithdraw(),
            # rails=AnchorRails(),
        )
