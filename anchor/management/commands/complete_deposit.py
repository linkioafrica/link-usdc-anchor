"""
Django management command to complete a pending deposit transaction.

Usage:
    python manage.py complete_deposit <transaction_id>

Example:
    python manage.py complete_deposit abc123-def456-ghi789

This command should be run by an admin after manually verifying that the user's
fiat payment has been received. It will:
1. Check the hot wallet USDC balance
2. Send USDC from the hot wallet to the user's Stellar address
3. Update the transaction status to completed
"""

from django.core.management.base import BaseCommand, CommandError
from polaris.models import Transaction
from app.integrations.deposit import complete_deposit


class Command(BaseCommand):
    help = 'Complete a pending deposit by sending USDC from hot wallet'

    def add_arguments(self, parser):
        parser.add_argument(
            'transaction_id',
            type=str,
            help='The ID of the transaction to complete'
        )

    def handle(self, *args, **options):
        transaction_id = options['transaction_id']

        self.stdout.write(
            self.style.WARNING(f'Attempting to complete deposit for transaction: {transaction_id}')
        )

        # Verify transaction exists before attempting completion
        try:
            transaction = Transaction.objects.get(id=transaction_id, kind=Transaction.KIND.deposit)

            self.stdout.write(f'Transaction found:')
            self.stdout.write(f'  - ID: {transaction.id}')
            self.stdout.write(f'  - Status: {transaction.status}')
            self.stdout.write(f'  - Amount In: {transaction.amount_in}')
            self.stdout.write(f'  - Amount Out: {transaction.amount_out}')
            self.stdout.write(f'  - Stellar Account: {transaction.stellar_account}')
            self.stdout.write('')

        except Transaction.DoesNotExist:
            raise CommandError(f'Transaction "{transaction_id}" does not exist')

        # Attempt to complete the deposit
        success = complete_deposit(transaction_id)

        if success:
            # Reload transaction to get updated status
            transaction.refresh_from_db()

            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully completed deposit for transaction {transaction_id}'
                )
            )
            self.stdout.write(f'  - New Status: {transaction.status}')
            self.stdout.write(f'  - Stellar TX Hash: {transaction.stellar_transaction_id}')
            self.stdout.write(f'  - Amount Sent: {transaction.amount_out} USDC')
        else:
            # Reload to see if status changed to error
            transaction.refresh_from_db()

            self.stdout.write(
                self.style.ERROR(
                    f'Failed to complete deposit for transaction {transaction_id}'
                )
            )
            self.stdout.write(f'  - Current Status: {transaction.status}')
            if transaction.status_message:
                self.stdout.write(f'  - Error Message: {transaction.status_message}')
            self.stdout.write('')
            self.stdout.write('Check logs for more details.')

            raise CommandError('Deposit completion failed')
