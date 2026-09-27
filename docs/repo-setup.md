# GitHub repository setup and hardening

The settings applied to `github.com/dannyelson82/planhaven`, and how to reproduce them on a
fork. Keep this file in sync with the real settings; review it when anything changes.

**Plan note:** GitHub enforces rulesets and branch protection on private repositories only on
paid plans. On a free account a private repo's rulesets do nothing, and secret scanning, push
protection and private vulnerability reporting are unavailable. This repository is therefore
public.

## 1. Account

- [x] Two-factor authentication on the GitHub account (passkey or hardware key preferred).
- [x] SSH signing key added under **Settings → SSH and GPG keys** with key type
      **Signing Key** (not Authentication Key).
- [ ] Vigilant mode: "Flag unsigned commits as unverified" (recommended).

Local git configuration for signing:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_signing -C "planhaven commit signing (<email>)"
git config gpg.format ssh
git config user.signingkey ~/.ssh/id_ed25519_signing.pub
git config commit.gpgsign true
git config tag.gpgsign true
# Optional: verify signatures locally
echo "<email> namespaces=\"git\" $(cat ~/.ssh/id_ed25519_signing.pub)" > ~/.ssh/allowed_signers
git config gpg.ssh.allowedSignersFile ~/.ssh/allowed_signers
```

`<email>` must be the commit email GitHub knows (e.g. the `noreply` address). Check with
`git log --show-signature -1`.

## 2. Access tokens

- Use a **fine-grained** personal access token limited to this one repository, with an
  expiry date (90 days or less).
- Grant only what the holder needs. An automation or AI agent that opens PRs and manages
  settings needs: Administration, Contents, Pull requests, Workflows, Actions, Issues, Code
  scanning alerts, Dependabot alerts (read and write); Commit statuses, Secret scanning
  alerts, Repository security advisories (read-only). Leave Secrets, Dependabot secrets and
  Webhooks at no access.
- A token with Administration can change the rules below. Treat it as a maintainer
  credential and revoke it if the machine holding it is compromised.

## 3. Settings → General

- [x] Default branch: `main`
- [x] Pull requests: squash merging only; automatically delete head branches
- [x] Wiki disabled (docs live in the repo)

## 4. Settings → Rules: ruleset "Protect main"

Target: default branch. Enforcement: active. **Bypass list: empty**, so the rules also apply
to admins and admin tokens.

- [x] Restrict deletions
- [x] Block force pushes
- [x] Require signed commits
- [x] Require linear history
- [x] Require a pull request before merging
  - Required approvals: **0**. GitHub doesn't let authors approve their own PRs, so a
    solo maintainer can't satisfy 1. Every change still goes through a visible PR.
    Raise to 1 when there is a second maintainer.
  - Dismiss stale approvals on new commits; require conversation resolution
  - Allowed merge method: squash
- [ ] Require status checks to pass: add the CI and security workflows once they exist
      (phase 0.1)

Squash merges done in the GitHub UI are signed by GitHub and show as Verified.

## 5. Settings → Advanced Security

- [x] Private vulnerability reporting
- [x] Dependency graph, Dependabot alerts, Dependabot security updates
- [x] Secret scanning and push protection
- [ ] Code scanning (CodeQL): enable once code exists (phase 0.1)

Not available on personal-account repos without paid Advanced Security, and covered instead
by Gitleaks in CI (`SECURITY.md` §8):

- Non-provider patterns (generic passwords and keys)
- Custom pattern for Planhaven tokens: `phv_(sync|ics|pat|oat|ort|inv)_[A-Za-z0-9_-]{32,}`

## 6. Settings → Actions

- [x] Allow only GitHub-owned and verified-creator actions
- [x] Require actions to be pinned to a full-length commit SHA
- [x] Workflow permissions: read repository contents by default
- [x] Actions may not create or approve pull requests
- [ ] Require approval for workflows from outside contributors (check when the first
      external PR arrives)

## 7. Packages (GHCR)

- [ ] Image will publish to `ghcr.io/dannyelson82/planhaven`
- [ ] After the first publish, set the package visibility and link it to the repository

## 8. Forking

Replace `dannyelson82` in `.github/ISSUE_TEMPLATE/config.yml` and in this file.
