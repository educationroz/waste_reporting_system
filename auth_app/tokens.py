from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """
    Generates a token tied to the user's pk + current is_verified state.
    Once the account is verified, is_verified flips to True, which
    automatically invalidates any old/reused verification links.
    """
    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{timestamp}{user.is_verified}"


email_verification_token = EmailVerificationTokenGenerator()