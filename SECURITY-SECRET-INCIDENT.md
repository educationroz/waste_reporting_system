# Secret exposure response

If an `.env` file containing real values was ever committed, treat every value in
that file as compromised. Removing the file from the current branch prevents a
new checkout from receiving it, but it **does not revoke a copied credential**
or remove it from existing clones, forks, caches, pull requests, or Git history.

## Immediate actions

1. **Rotate Django `SECRET_KEY`** in the deployment secret store. This invalidates
   signed sessions, password-reset tokens, and other Django signatures created
   with the old key; deploy the replacement promptly.
2. **Change the database password**, update the application deployment secret,
   and revoke/disable the old database role or password. Do not reuse
   `admin123`; use a unique, randomly generated application account password.
3. **Revoke the Gmail app password** in the Google Account security settings,
   create a new app password only if SMTP is still required, and update
   `EMAIL_HOST_PASSWORD` in the deployment secret store.
4. **Rotate the Google OAuth client secret if one was exposed.** A Google OAuth
   *client ID* is intended to be public and normally does not need rotation,
   but review the OAuth consent screen, authorized redirect URIs, and authorized
   JavaScript origins. Never expose a client secret to browser code.
5. Review database, mail, application, and OAuth audit logs from the first
   public commit through the rotation time. Invalidate suspicious user sessions
   and investigate unexpected access.

## Repository hygiene

- `.env` and local variants are ignored by Git. Use the tracked
  [`.env.example`](.env.example) as the safe setup template.
- Store production values in the platform's secret manager or injected runtime
  environment variables, not in a repository, image layer, issue, or log.
- Enable repository secret scanning and push protection. If GitHub identifies
  a historical secret, follow its remediation link after rotating the secret.
- If the secret is present in reachable Git history, coordinate a history
  rewrite with repository administrators using `git filter-repo` or GitHub's
  documented sensitive-data removal process. Force-pushing rewritten history
  is disruptive and does not replace credential rotation.

## Verification before deployment

```bash
# must show no tracked environment file
 git ls-files | grep -E '(^|/)\.env($|\.)' || true

# production must provide a real secret key
DEBUG=False SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')" \
  python manage.py check --deploy
```

The application now refuses to start with a missing or placeholder Django
secret key when `DEBUG=False`.
