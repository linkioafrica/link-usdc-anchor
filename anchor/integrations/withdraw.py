from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, List
from django import forms
from django.http import JsonResponse
from rest_framework.request import Request
from polaris.models import Transaction, Asset
from polaris.templates import Template
from .forms import WithdrawForm, ConfirmationForm
from urllib.parse import (urlparse, parse_qs, urlencode, quote_plus)
from polaris.integrations import (
  WithdrawalIntegration,
  TransactionForm
)
from django.conf import settings
from stellar_sdk import Server, Keypair, TransactionBuilder, Network, Asset as StellarAsset
from stellar_sdk.exceptions import BaseHorizonError
import logging
import environ
logger = logging.getLogger(__name__)

env = environ.Env()

ENVIRONMENT = env('ENVIRONMENT')

class AnchorWithdraw(WithdrawalIntegration):
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
                return WithdrawForm(transaction, post_data)
            else:
                return WithdrawForm(transaction, initial={"amount": amount})
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
        if template == Template.WITHDRAW:
            if not form:  # we're done
                return None
            elif isinstance(form, WithdrawForm):
                return {
                    "title": ("Withdrawal Transaction Form"),
                    "guidance": (
                        "Please enter amount you would like to withdraw from wallet"
                    ),
                    "icon_label": ("USDC Anchor Withdraw"),
                    # "icon_path": "image/NGNC.png",
                    # "show_fee_table": False,
                }
        elif  template == Template.MORE_INFO:
            # provides a label for the image displayed at the top of each page
            content = {
                "title": ("Asset Selection Form"),
                "icon_label": ("USDC Anchor Withdraw"),
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
        if isinstance(form, WithdrawForm ):
            # Polaris automatically assigns amount to Transaction.amount_in
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

        if ENVIRONMENT == "development":
            ownUrl = "http://localhost:3000/menu"  # Use for local testing
        else:
            ownUrl = "https://origin.linkio.world/menu"

         # Full interactive url /sep24/transactions/deposit/webapp
        url = request.build_absolute_uri()
        parsed_url = urlparse(url)
        query_result = parse_qs(parsed_url.query)

        token = (query_result['token'][0])

        ownUrl += "?" if parsed_url.query else "&"

        payload = {
            'type': 'withdraw',
            'asset_code': asset.code,
            'transaction_id':transaction.id,
            'token': token,
            'wallet': transaction.stellar_account,
            'callback': callback
        }
        # The anchor uses a standalone interactive flow
        return ownUrl + urlencode(payload, quote_via=quote_plus)

    def after_interactive_flow(
        self,
        request: Request,
        transaction: Transaction
    ):
        """
        Called by Polaris after user completes interactive UI at ramp.linkio.world

        At this point:
        - User has submitted withdrawal request
        - They provided bank account details for fiat payout
        - User will now send USDC from their wallet to our address
        - We're waiting for USDC to arrive on Stellar

        This function:
        - Updates transaction status to pending_user_transfer_start when amounts are valid
        - Logs request with bank details for admin reference
        - Sets our receiving address for USDC
        - Does NOT process fiat payout yet (that happens after USDC verification)
        """
        amount_str = request.query_params.get("amount")
        fee_str = request.query_params.get("amount_fee")

        # Validate required parameters exist
        if amount_str is None or fee_str is None:
            logger.error(
                "Missing required query params for withdraw after_interactive_flow: "
                f"amount={amount_str}, amount_fee={fee_str}, transaction_id={transaction.id}"
            )
            transaction.status = Transaction.STATUS.error
            transaction.status_message = "Missing amount or amount_fee from interactive withdraw callback"
            transaction.save()
            return

        # Safely parse Decimal values
        try:
            transaction.amount_in = Decimal(amount_str)
            transaction.amount_fee = Decimal(fee_str)
        except (InvalidOperation, TypeError) as e:
            logger.error(
                "Invalid Decimal values for withdraw after_interactive_flow: "
                f"amount={amount_str}, amount_fee={fee_str}, transaction_id={transaction.id}, error={e}",
                exc_info=True
            )
            transaction.status = Transaction.STATUS.error
            transaction.status_message = "Invalid amount or amount_fee format in interactive withdraw callback"
            transaction.save()
            return

        transaction.status = Transaction.STATUS.pending_user_transfer_start
        transaction.amount_out = transaction.amount_in - transaction.amount_fee
        transaction.memo_type = (request.query_params.get("memo_type"))
        transaction.memo = (request.query_params.get("hashed"))
        transaction.to_address = (request.query_params.get("account"))  # Bank details stored here
        transaction.external_transaction_id = (request.query_params.get("externalId"))
        transaction.on_change_callback = (request.query_params.get("callback"))
        transaction.receiving_anchor_account = settings.USDC_RECEIVING_ADDRESS
        transaction.save()

        # Log withdrawal request for admin visibility
        logger.info(
            f"Withdrawal request received - Transaction ID: {transaction.id}, "
            f"USDC Amount: {transaction.amount_in}, Fiat Amount: {transaction.amount_out}, "
            f"Bank Details: {transaction.to_address}, "
            f"Stellar Account: {transaction.stellar_account}, "
            f"Status: {transaction.status}, "
            f"Receiving Address: {transaction.receiving_anchor_account}"
        )


def verify_usdc_payment(stellar_tx: dict, expected_amount: Decimal, expected_destination: str,
                       expected_asset_code: str, expected_asset_issuer: str) -> bool:
    """
    Verify that a Stellar transaction contains the expected USDC payment

    Checks:
    - Transaction contains payment operation
    - Payment destination matches our address
    - Payment asset is USDC (correct code and issuer)
    - Payment amount >= expected amount (allowing small tolerance for rounding)

    Args:
        stellar_tx: Transaction object from Horizon API
        expected_amount: Decimal amount of USDC expected
        expected_destination: Our Stellar address expecting payment
        expected_asset_code: "USDC"
        expected_asset_issuer: Circle's USDC issuer address

    Returns:
        True if payment verified, False otherwise
    """
    try:
        # Get transaction hash for logging
        tx_hash = stellar_tx.get('id', 'unknown')

        # Fetch operations for this transaction
        server = Server(horizon_url=settings.HORIZON_URL)
        operations = server.operations().for_transaction(tx_hash).call()

        # Look for payment operation
        for op in operations.get('_embedded', {}).get('records', []):
            if op.get('type') != 'payment':
                continue

            # Check destination
            if op.get('to') != expected_destination:
                logger.warning(
                    f"Payment destination mismatch. Expected: {expected_destination}, "
                    f"Got: {op.get('to')}"
                )
                continue

            # Check if it's USDC (native XLM won't have asset_code)
            if op.get('asset_type') == 'native':
                logger.warning("Found XLM payment, not USDC")
                continue

            # Check asset code and issuer
            asset_code = op.get('asset_code')
            asset_issuer = op.get('asset_issuer')

            if asset_code != expected_asset_code:
                logger.warning(
                    f"Asset code mismatch. Expected: {expected_asset_code}, Got: {asset_code}"
                )
                continue

            if asset_issuer != expected_asset_issuer:
                logger.warning(
                    f"Asset issuer mismatch. Expected: {expected_asset_issuer}, Got: {asset_issuer}"
                )
                continue

            # Check amount (allow 0.01 tolerance for rounding)
            actual_amount = Decimal(op.get('amount', '0'))
            tolerance = Decimal('0.01')

            if actual_amount < (expected_amount - tolerance):
                logger.warning(
                    f"Amount mismatch. Expected: {expected_amount}, "
                    f"Got: {actual_amount}"
                )
                continue

            # All checks passed!
            logger.info(
                f"USDC payment verified - TX: {tx_hash}, "
                f"Amount: {actual_amount}, Destination: {expected_destination}"
            )
            return True

        # No matching payment found
        logger.error(f"No matching USDC payment found in transaction {tx_hash}")
        return False

    except Exception as e:
        logger.error(f"Error verifying USDC payment: {e}", exc_info=True)
        return False


def process_withdrawal(transaction_id: str, stellar_transaction_id: str) -> bool:
    """
    Called after admin verifies USDC received on Stellar blockchain

    Steps:
    1. Verify USDC payment on Stellar blockchain
    2. Update status to pending_anchor (waiting for fiat payout)
    3. Log success/failure

    Note: Fiat payout is processed manually, and Node.js server will update
    status to 'completed' after payout is done.

    Args:
        transaction_id: The withdrawal transaction ID
        stellar_transaction_id: The Stellar transaction hash to verify

    Returns:
        True if USDC verified successfully, False otherwise
    """
    try:
        # 1. Fetch and validate transaction
        transaction = Transaction.objects.get(id=transaction_id, kind=Transaction.KIND.withdrawal)

        if transaction.status != Transaction.STATUS.pending_user_transfer_start:
            logger.error(
                f"Transaction {transaction_id} is in invalid status: {transaction.status}. "
                f"Expected pending_user_transfer_start"
            )
            return False

        logger.info(
            f"Processing withdrawal verification for transaction {transaction_id}, "
            f"Stellar TX: {stellar_transaction_id}"
        )

        # 2. Fetch Stellar transaction from Horizon
        server = Server(horizon_url=settings.HORIZON_URL)
        stellar_tx = server.transactions().transaction(stellar_transaction_id).call()

        # 3. Verify USDC payment
        verified = verify_usdc_payment(
            stellar_tx=stellar_tx,
            expected_amount=transaction.amount_in,
            expected_destination=transaction.receiving_anchor_account,
            expected_asset_code="USDC",
            expected_asset_issuer=settings.USDC_ISSUER
        )

        if not verified:
            logger.error(
                f"USDC payment verification failed for transaction {transaction_id}. "
                f"Stellar TX: {stellar_transaction_id}"
            )
            transaction.status = Transaction.STATUS.error
            transaction.status_message = f"USDC payment verification failed"
            transaction.save()
            return False

        # 4. Update transaction status to pending_anchor (waiting for fiat payout)
        transaction.status = Transaction.STATUS.pending_anchor
        transaction.stellar_transaction_id = stellar_transaction_id
        transaction.save()

        logger.info(
            f"Withdrawal USDC verified successfully for transaction {transaction_id}. "
            f"Status updated to pending_anchor. "
            f"Admin should now process fiat payout of {transaction.amount_out} to {transaction.to_address}"
        )

        # TODO: Send email notification to admin to process fiat payout
        # Should include: transaction ID, bank details, fiat amount, currency

        return True

    except Transaction.DoesNotExist:
        logger.error(f"Transaction {transaction_id} not found")
        return False

    except BaseHorizonError as e:
        logger.error(
            f"Stellar network error while verifying withdrawal {transaction_id}: {e}"
        )
        transaction.status = Transaction.STATUS.error
        transaction.status_message = f"Stellar error: {str(e)}"
        transaction.save()
        return False

    except Exception as e:
        logger.error(
            f"Unexpected error while processing withdrawal {transaction_id}: {e}",
            exc_info=True
        )
        transaction.status = Transaction.STATUS.error
        transaction.status_message = f"Error: {str(e)}"
        transaction.save()
        return False
