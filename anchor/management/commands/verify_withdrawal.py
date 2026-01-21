"""
Django management command to verify USDC payment for a withdrawal transaction.

Usage:
    python manage.py verify_withdrawal <transaction_id> <stellar_tx_hash>

Example:
    python manage.py verify_withdrawal abc123-def456 a1b2c3d4e5f6...stellar_hash

This command should be run by an admin after verifying that the user has sent
USDC to our Stellar receiving address. It will:
1. Verify the USDC payment on the Stellar blockchain
2. Check that the payment matches expected amount and asset
3. Update the transaction status to pending_anchor (waiting for fiat payout)
4. Log success/failure

After this command succeeds, the admin should process the fiat payout manually,
and the Node.js server will update the status to 'completed' after payout.
"""

from django.core.management.base import BaseCommand, CommandError
from polaris.models import Transaction
from app.integrations.withdraw import process_withdrawal


class Command(BaseCommand):
    help = 'Verify USDC payment for a withdrawal transaction'

    def add_arguments(self, parser):
        parser.add_argument(
            'transaction_id',
            type=str,
            help='The ID of the withdrawal transaction'
        )
        parser.add_argument(
            'stellar_tx_id',
            type=str,
            help='The Stellar transaction hash containing the USDC payment'
        )

    def handle(self, *args, **options):
        transaction_id = options['transaction_id']
        stellar_tx_id = options['stellar_tx_id']

        self.stdout.write(
            self.style.WARNING(
                f'Attempting to verify USDC payment for withdrawal transaction: {transaction_id}'
            )
        )
        self.stdout.write(f'Stellar TX: {stellar_tx_id}')
        self.stdout.write('')

        # Verify transaction exists before attempting verification
        try:
            transaction = Transaction.objects.get(id=transaction_id, kind=Transaction.KIND.withdrawal)

            self.stdout.write(f'Transaction found:')
            self.stdout.write(f'  - ID: {transaction.id}')
            self.stdout.write(f'  - Status: {transaction.status}')
            self.stdout.write(f'  - USDC Amount In: {transaction.amount_in}')
            self.stdout.write(f'  - Fiat Amount Out: {transaction.amount_out}')
            self.stdout.write(f'  - Stellar Account: {transaction.stellar_account}')
            self.stdout.write(f'  - Bank Details: {transaction.to_address}')
            self.stdout.write(f'  - Receiving Address: {transaction.receiving_anchor_account}')
            self.stdout.write('')

        except Transaction.DoesNotExist:
            raise CommandError(f'Withdrawal transaction "{transaction_id}" does not exist')

        # Attempt to verify the withdrawal
        self.stdout.write('Verifying USDC payment on Stellar blockchain...')
        success = process_withdrawal(transaction_id, stellar_tx_id)

        if success:
            # Reload transaction to get updated status
            transaction.refresh_from_db()

            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully verified USDC payment for withdrawal {transaction_id}'
                )
            )
            self.stdout.write(f'  - New Status: {transaction.status}')
            self.stdout.write(f'  - Stellar TX Hash: {transaction.stellar_transaction_id}')
            self.stdout.write('')
            self.stdout.write(
                self.style.WARNING(
                    f'NEXT STEP: Process fiat payout of {transaction.amount_out} to bank account: {transaction.to_address}'
                )
            )
            self.stdout.write('After fiat payout is complete, Node.js server should update status to "completed"')
        else:
            # Reload to see if status changed to error
            transaction.refresh_from_db()

            self.stdout.write(
                self.style.ERROR(
                    f'Failed to verify USDC payment for withdrawal {transaction_id}'
                )
            )
            self.stdout.write(f'  - Current Status: {transaction.status}')
            if transaction.status_message:
                self.stdout.write(f'  - Error Message: {transaction.status_message}')
            self.stdout.write('')
            self.stdout.write('Check logs for more details.')
            self.stdout.write('Possible reasons:')
            self.stdout.write('  - Stellar transaction not found')
            self.stdout.write('  - Payment amount mismatch')
            self.stdout.write('  - Wrong asset (not USDC)')
            self.stdout.write('  - Wrong destination address')

            raise CommandError('Withdrawal verification failed')
