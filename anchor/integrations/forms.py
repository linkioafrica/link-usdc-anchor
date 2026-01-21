from django import forms

from polaris.integrations.forms import TransactionForm

class ContactForm(forms.Form):
    first_name = forms.CharField()
    last_name = forms.CharField()
    email = forms.EmailField()

class AddressForm(forms.Form):
    address_1 = forms.CharField()
    address_2 = forms.CharField()
    city = forms.CharField()
    zip_code = forms.CharField()

class BankAccount(forms.Form):
    account_number = forms.CharField()
    routing_number = forms.CharField()

class WithdrawForm(TransactionForm):
    """This form accepts the amount to withdraw from the user."""

    Link_Tag = forms.CharField(
        label=("Link Tag"),
        help_text=("Enter the link-Tag"),
    )

class DepositForm(TransactionForm):
    """This form accepts the amount to withdraw from the user."""

    Amount = forms.CharField(
        label=("Amount in words"),
    )
    stellar_address = forms.CharField(
        label=("Stellar address or Federation account to be credited"),
        help_text=("Enter stellar address"),
    )
    Link_Tag = forms.CharField(
        label=("Link Tag"),
        help_text=("Enter the link-Tag"),
    )

class KYCForm(forms.Form):
    first_name = forms.CharField(
        max_length=254,
        widget=forms.TextInput(attrs={"class": "input", "test-value": "Albert"}),
        label=("First Name"),
    )
    last_name = forms.CharField(
        max_length=254,
        widget=forms.TextInput(attrs={"class": "input", "test-value": "Einstein"}),
        label=("Last Name"),
    )
    email = forms.EmailField(
        widget=forms.TextInput(
            attrs={"class": "input", "test-value": "clerk@patentoffice.gov"}
        ),
        label=("Email"),
    )

class ConfirmationForm(forms.Form):
    pass
