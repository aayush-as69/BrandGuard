# BrandGuard documentation

Use this folder as the technical reference for operating and validating BrandGuard.

| Guide | Covers |
|---|---|
| [Deployment](DEPLOYMENT.md) | Environment modes, first deployment, proxy setup, health checks, migrations, monitoring, backups, and restore |
| [Testing](TESTING.md) | Automated and live-provider tests, smoke testing, accessibility checks, and restore drills |
| [Security](SECURITY.md) | Accounts, sessions, roles, source access, request protections, upload limits, and known boundaries |
| [Privacy](PRIVACY.md) | Stored data, AI provider disclosure, masking, logging, retention, and deletion |

## Before using real brand data

1. Read the deployment guide and configure production mode with a long random secret.
2. Use real accounts; do not expose demo sign-in on a production deployment.
3. Review the security and privacy boundaries with the brand owner.
4. Decide whether sending content to an AI provider is permitted. The AI judge is optional and can be disabled.
5. Use encrypted storage and protected backups. The application does not encrypt the live SQLite database itself.
6. Run the automated suite, public deployment smoke test, and a restore drill.

Demo records in the repository are synthetic and describe the fictional Brewline Coffee brand.
