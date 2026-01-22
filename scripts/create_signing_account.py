from stellar_sdk import Keypair

# Generate new keypair for anchor operations
keypair = Keypair.random()

print("=" * 60)
print("USDC ANCHOR SIGNING ACCOUNT")
print("=" * 60)
print(f"Public Key:  {keypair.public_key}")
print(f"Secret Key:  {keypair.secret}")
print("=" * 60)
print("⚠️  This is your SIGNING_SEED for the anchor")
print("⚠️  This is DIFFERENT from your hot wallet")
print("⚠️  Save the secret key securely!")
print()
print("Next steps:")
print("1. Fund this account with at least 1.5 XLM")
print("2. Add to .env as SIGNING_SEED")
print("=" * 60)
