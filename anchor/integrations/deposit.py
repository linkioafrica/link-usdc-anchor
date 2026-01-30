from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, List
from django import forms
from rest_framework.request import Request
from polaris.models import Transaction, Asset
from polaris.templates import Template
from .forms import DepositForm
from urllib.parse import (urlparse, parse_qs, urlencode, quote_plus)
from polaris.integrations import (
    DepositIntegration,
    TransactionForm
)
from django.conf import settings
from stellar_sdk import Server, Keypair, TransactionBuilder, Network, Asset as StellarAsset
from stellar_sdk.exceptions import BaseHorizonError
import logging

logger = logging.getLogger(__name__)

class AnchorDeposit(DepositIntegration):
    def form_for_transaction(
        self,
        request: Request,
        transaction: Transaction,
        post_data: dict = None,
        amount: Decimal = None,
        *args,
        **kwargs
    ) -> Optional[forms.Form]:
        # if we haven't collected amount, collect it
        if not transaction.amount_in:
            if post_data:
                return DepositForm(transaction, post_data)
            else:
                return DepositForm(transaction, initial={"amount": amount})
        # we don't have anything more to collect
        else:
            return None

    def content_for_template(
        self,
        request: Request,
        template: Template,
        form: Optional[forms.Form] = None,
        transaction: Optional[Transaction] = None,
        *args,
        **kwargs,
    ) -> Optional[Dict]:
        if template == Template.DEPOSIT:
            if not form:  # we're done
                return None
            elif isinstance(form, DepositForm):
                return {
                    "title": ("Deposit Transaction Form"),
                    "guidance": (
                        "Provide all info enquired below"
                    ),
                    "icon_label": ("USDC Anchor Deposit"),
                    # "icon_path": "image/NGNC.png"
                }
        elif  template == Template.MORE_INFO:
            # provides a label for the image displayed at the top of each page
            content = {
                "title": ("Asset Selection Form"),
                "guidance": (
                    "If business or recipient doesn’t have, generate one and send"
                ),
                "icon_label": ("USDC Anchor Deposit"),
                # "icon_path": "image/NGNC.png"
            }
            return content

    def after_form_validation(
        self,
        request: Request,
        form: forms.Form,
        transaction: Transaction,
        *args,
        **kwargs,
    ):
        if isinstance(form, DepositForm ):
            # Polaris automatically assigns amount to Transaction.amount_in
           transaction.save()

    def after_deposit(self, transaction: Transaction, *args, **kwargs):
        transaction.channel_seed = None
        transaction.save()

    def interactive_url(
        self,
        request: Request,
        transaction: Transaction,
        asset: Asset,
        amount: Optional[Decimal],
        callback: Optional[str],
        *args: List,
        **kwargs: Dict,
    ) -> Optional[str]:
        if request.query_params.get("step"):
          raise NotImplementedError()

        ownUrl = "http://localhost:3000/menu"  # Use for local testing
        # ownUrl = "https://ramp.linkio.world/buy"

        # Full interactive url /sep24/transactions/deposit/webapp
        url = request.build_absolute_uri()
        parsed_url = urlparse(url)
        query_result = parse_qs(parsed_url.query)
        print("query_result", query_result)

        token = (query_result['token'][0])
        # amount = (query_result['amount'][0])

        ownUrl += "?" if parsed_url.query else "?"

        payload = {
            'type': 'deposit',
            'asset_code': asset.code,
            'transaction_id':transaction.id,
            'token': token,
            'wallet': transaction.stellar_account,
            'callback': callback,
            # 'amount': amount
        }

        # Change status from incomplete to pending_anchor so demo wallet doesn't think it failed
        # while user is filling out the form
        # transaction.status = Transaction.STATUS.pending_anchor
        # transaction.save()

        # The anchor uses a standalone interactive flow
        fullUrl = ownUrl + urlencode(payload, quote_via=quote_plus)
        print("fullUrl", fullUrl)
        return fullUrl

    def after_interactive_flow(
        self,
        request: Request,
        transaction: Transaction
    ):
        """
        Called by Polaris after user completes interactive UI at ramp.linkio.world

        At this point:
        - User has submitted deposit request
        - They have payment instructions (bank details)
        - We're waiting for them to send fiat payment

        This function:
        - Updates transaction status to pending_user_transfer_start when amounts are valid
        - Logs request for admin visibility
        - Does NOT send USDC yet (that happens after manual verification via complete_deposit)
        """
        amount_str = request.query_params.get("amount")

        # Validate required parameters exist
        if amount_str is None:
            logger.error(
                "Missing required query params for deposit after_interactive_flow: "
                f"amount={amount_str}, amount_fee={fee_str}, transaction_id={transaction.id}"
            )
            transaction.status = Transaction.STATUS.error
            transaction.status_message = "Missing amount or amount_fee from interactive deposit callback"
            transaction.save()
            return

        # Safely parse Decimal values
        # try:
        #     transaction.amount_in = Decimal(amount_str)
        # except (InvalidOperation, TypeError) as e:
        #     logger.error(
        #         "Invalid Decimal values for deposit after_interactive_flow: "
        #         f"amount={amount_str}, transaction_id={transaction.id}, error={e}",
        #         exc_info=True
        #     )
        #     transaction.status = Transaction.STATUS.error
        #     transaction.status_message = "Invalid amount or amount_fee format in interactive deposit callback"
        #     transaction.save()
        #     return

        transaction.status = Transaction.STATUS.pending_user_transfer_complete
        transaction.amount_in = (request.query_params.get("amount"))
        transaction.amount_out = (request.query_params.get("amount_out"))
        transaction.memo_type = (request.query_params.get("memo_type"))
        transaction.memo = (request.query_params.get("hashed"))
        transaction.from_address = (request.query_params.get("account"))
        transaction.external_transaction_id = (request.query_params.get("externalId"))
        transaction.on_change_callback = (request.query_params.get("callback"))
        transaction.save()

        # Log deposit request for admin visibility
        logger.info(
            f"Deposit request received - Transaction ID: {transaction.id}, "
            f"Amount: {transaction.amount_in}, Stellar Account: {transaction.stellar_account}, "
            f"Status: {transaction.status}"
        )


def complete_deposit(transaction_id: str) -> bool:
    """
    MANUAL FUNCTION called by admin after verifying fiat payment received

    Called via:
    - Management command: python manage.py complete_deposit <transaction_id>
    - Admin panel action
    - Internal API endpoint

    Steps:
    1. Verify transaction exists and is in correct status
    2. Check hot wallet USDC balance (fail if insufficient)
    3. Send USDC from hot wallet to user's Stellar address
    4. Update transaction status to completed
    5. Log success/failure

    Args:
        transaction_id: The transaction ID to complete

    Returns:
        True if successful, False if failed
    """
    try:
        # 1. Fetch and validate transaction
        transaction = Transaction.objects.get(id=transaction_id, kind=Transaction.KIND.deposit)

        if transaction.status not in [
            Transaction.STATUS.pending_user_transfer_complete,
            Transaction.STATUS.pending_anchor
        ]:
            logger.error(
                f"Transaction {transaction_id} is in invalid status: {transaction.status}. "
                f"Expected pending_user_transfer_complete or pending_anchor"
            )
            return False

        logger.info(f"Processing deposit completion for transaction {transaction_id}")

        # 2. Initialize Stellar server and get hot wallet balance
        server = Server(horizon_url=settings.HORIZON_URL)
        hot_wallet_account = server.accounts().account_id(settings.USDC_HOT_WALLET_PUBLIC).call()

        # Find USDC balance in hot wallet
        usdc_balance = Decimal(0)
        for balance in hot_wallet_account['balances']:
            if (balance.get('asset_code') == 'USDC' and
                balance.get('asset_issuer') == settings.USDC_ISSUER):
                usdc_balance = Decimal(balance['balance'])
                break

        logger.info(f"Hot wallet USDC balance: {usdc_balance}")

        # 3. Check if sufficient balance
        required_amount = transaction.amount_out
        if usdc_balance < required_amount:
            logger.error(
                f"Insufficient hot wallet balance. Required: {required_amount}, "
                f"Available: {usdc_balance}. Transaction {transaction_id} cannot be completed."
            )
            # TODO: Send alert email to admin
            return False

        # 4. Build and submit Stellar payment transaction
        usdc_asset = StellarAsset("USDC", settings.USDC_ISSUER)
        source_keypair = Keypair.from_secret(settings.USDC_HOT_WALLET_SECRET)
        source_account = server.load_account(settings.USDC_HOT_WALLET_PUBLIC)

        # Get base fee from network
        base_fee = server.fetch_base_fee()

        # Build transaction
        stellar_transaction = (
            TransactionBuilder(
                source_account=source_account,
                network_passphrase=settings.STELLAR_NETWORK_PASSPHRASE,
                base_fee=base_fee
            )
            .append_payment_op(
                destination=transaction.stellar_account,
                asset=usdc_asset,
                amount=str(required_amount)
            )
            .add_text_memo(f"LINK Deposit {transaction.id}")
            .set_timeout(30)
            .build()
        )

        # Sign and submit
        stellar_transaction.sign(source_keypair)
        response = server.submit_transaction(stellar_transaction)

        # 5. Update transaction record
        transaction.status = Transaction.STATUS.completed
        transaction.stellar_transaction_id = response['hash']
        transaction.completed_at = transaction.completed_at or transaction.started_at
        transaction.save()

        logger.info(
            f"Deposit completed successfully for transaction {transaction_id}. "
            f"Stellar TX: {response['hash']}, Amount: {required_amount} USDC"
        )

        return True

    except Transaction.DoesNotExist:
        logger.error(f"Transaction {transaction_id} not found")
        return False

    except BaseHorizonError as e:
        logger.error(
            f"Stellar network error while completing deposit {transaction_id}: {e}"
        )
        transaction.status = Transaction.STATUS.error
        transaction.status_message = f"Stellar error: {str(e)}"
        transaction.save()
        return False

    except Exception as e:
        logger.error(
            f"Unexpected error while completing deposit {transaction_id}: {e}",
            exc_info=True
        )
        transaction.status = Transaction.STATUS.error
        transaction.status_message = f"Error: {str(e)}"
        transaction.save()
        return False
