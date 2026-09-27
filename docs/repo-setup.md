# GitHub repository setup and hardening

Do these once when creating the repository, before the first code is pushed.
Replace `dannyelson82` with your GitHub username everywhere.

## 1. Account

- [ ] Enable two-factor authentication on your GitHub account (a passkey or hardware key is best).
- [ ] Use a signing key for commits (SSH or GPG) and add it to GitHub.

## 2. Create and push

```bash
unzip planhaven.zip && cd planhaven
git init -b main
git add .
git commit -S -m "docs: initial architecture and security design"
git remote add origin git@github.com:dannyelson82/planhaven.git
git push -u origin main
```

Create the repository on GitHub first (empty, no README/license), public or private.
Tip: keep it **private** until v0.1 passes the SECURITY.md §11 checklist.

## 3. Settings → General

- [ ] Default branch: `main`
- [ ] Pull requests: allow squash merging only; auto-delete head branches
- [ ] Disable wiki (docs live in the repo) unless you want it

## 4. Settings → Rules (branch ruleset for `main`)

- [ ] Require a pull request before merging
- [ ] Require status checks to pass (add CI and security workflows once they exist)
- [ ] Require signed commits
- [ ] Require linear history
- [ ] Block force pushes and deletions
- [ ] Include administrators (you), so you can't bypass by accident

## 5. Settings → Code security

- [ ] Private vulnerability reporting: **on**
- [ ] Dependency graph: on
- [ ] Dependabot alerts and security updates: on
- [ ] Secret scanning and **push protection**: on
- [ ] Custom secret-scanning pattern for Planhaven tokens (where available):
      regex `phv_(sync|ics|pat|oat|ort|inv)_[A-Za-z0-9_-]{32,}`
- [ ] Code scanning (CodeQL): enable once code exists

## 6. Settings → Actions

- [ ] Workflow permissions: **read repository contents** by default
- [ ] Do not allow Actions to create or approve pull requests
- [ ] Allow only GitHub-owned and verified-creator actions (or an explicit allowlist)
- [ ] Require approval for workflows from outside contributors

## 7. Packages (GHCR)

- [ ] Image will publish to `ghcr.io/dannyelson82/planhaven`
- [ ] After the first publish, set the package visibility and link it to the repository

## 8. Placeholders to replace

- [ ] `dannyelson82` in `.github/ISSUE_TEMPLATE/config.yml` and this file
