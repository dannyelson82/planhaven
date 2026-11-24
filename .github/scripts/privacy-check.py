#!/usr/bin/env python3
"""Fail if new commits would make personal infrastructure details public.

Usage: privacy-check.py BASE [HEAD] [--exclude REF ...]
Checks each non-merge commit in BASE..HEAD (skipping commits reachable from any
--exclude REF, e.g. the upstream project's main) and the lines it adds.

Checks, using generic patterns only (the real values are never written here):
- author/committer emails that are a computer's local address (user@host.local,
  .lan, .home, .localdomain): use the GitHub noreply address instead;
- private IPv4 addresses (10/8, 172.16/12, 192.168/16) other than the example
  ones below, and Tailscale addresses (100.64.0.0/10) outside 100.64.x.x;
- Tailscale MagicDNS names (*.ts.net) unless they're placeholders.

Allowed: example addresses 192.168.1.x, 10.0.0.x, 172.17.0.x (Docker), 100.64.x.x;
the range base addresses 10.0.0.0, 172.16.0.0, 192.168.0.0, 100.64.0.0; anything
listed (one address or CIDR per line) in a .privacy-allow file at the repository
root; ts.net names with a <placeholder>, "example", or only one label before
.ts.net. A line containing "privacy-check: allow" is skipped.
"""

import ipaddress
import re
import subprocess
import sys

LOCAL_EMAIL = re.compile(r"@[^@\s]+\.(local|lan|home|localdomain|internal)$", re.I)
IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
TS_NET = re.compile(r"(?<![<>\w.-])[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+\.ts\.net\b")
CHECKED_NETS = [ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",  # private + Tailscale
)]
ALLOWED_NETS = [ipaddress.ip_network(n) for n in (
    "192.168.1.0/24", "10.0.0.0/24", "172.17.0.0/24", "100.64.0.0/16",
    "10.0.0.0/32", "172.16.0.0/32", "192.168.0.0/32", "100.64.0.0/32",
)]


def load_allow_file() -> None:
    try:
        root = git("rev-parse", "--show-toplevel").strip()
        with open(f"{root}/.privacy-allow", encoding="utf-8") as fh:
            for raw in fh:
                entry = raw.split("#", 1)[0].strip()
                if entry:
                    ALLOWED_NETS.append(ipaddress.ip_network(entry, strict=False))
    except FileNotFoundError:
        pass
ALLOW_MARK = "privacy-check: allow"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def bad_ip(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return False
    return any(ip in n for n in CHECKED_NETS) and not any(ip in n for n in ALLOWED_NETS)


def bad_ts_name(name: str) -> bool:
    # A real MagicDNS name is machine.<tailnet>.ts.net; one label (ft.ts.net) is a stand-in.
    return "example" not in name.lower()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    load_allow_file()
    args = sys.argv[1:]
    exclude = [args[i + 1] for i, a in enumerate(args) if a == "--exclude" and i + 1 < len(args)]
    pos = [a for i, a in enumerate(args) if a != "--exclude" and (i == 0 or args[i - 1] != "--exclude")]
    base, head = pos[0], pos[1] if len(pos) > 1 else "HEAD"
    problems: list[str] = []

    log = git("log", "-p", "-U0", "--no-merges", "--no-color", "--no-ext-diff",
              "--format=@@commit %h %ae %ce", f"{base}..{head}", *[f"^{r}" for r in exclude])
    sha, path = "?", "?"
    for line in log.splitlines():
        if line.startswith("@@commit "):
            sha, *emails = line.split()[1:]
            for email in set(emails):
                if LOCAL_EMAIL.search(email):
                    problems.append(f"commit {sha}: email is a computer's local address "
                                    f"({email.split('@')[1]}); set git config user.email to "
                                    "your GitHub noreply address")
            continue
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
            continue
        if not line.startswith("+") or ALLOW_MARK in line:
            continue
        for ip in IPV4.findall(line):
            if bad_ip(ip):
                problems.append(f"{path} ({sha}): private or Tailscale address {ip} "
                                "(use 192.168.1.x / 100.64.x.x examples)")
        for name in TS_NET.findall(line):
            if bad_ts_name(name):
                problems.append(f"{path} ({sha}): Tailscale name {name} (use tower.<your-tailnet>.ts.net)")

    for p in dict.fromkeys(problems):
        print(f"::error::{p}")
    if problems:
        print(f"{len(set(problems))} privacy problem(s). See the privacy rules in CLAUDE.md.")
        return 1
    print("privacy check: nothing personal found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
