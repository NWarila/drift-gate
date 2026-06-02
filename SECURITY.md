# Security Policy

## Reporting a Vulnerability

Use **GitHub's private vulnerability-reporting channel** to disclose security
issues in this repository. In the Security tab, click **Report a vulnerability**,
fill in the template, and submit. This creates a private advisory visible only to
the repository maintainer.

Do not open a public issue for a vulnerability. Public disclosure before a fix is
available puts all consumers of this action at risk.

Expected response time: acknowledgement within 5 business days.

## Scope

| In scope | Out of scope |
| --- | --- |
| Code-execution or credential-exfiltration paths in `action.yml` or `tools/baseline/` | Theoretical issues with no exploitable path |
| Manifest parsing that could bypass the drift check silently | Actions runner infrastructure (report to GitHub) |
| Unsafe use of GitHub API responses in the Check Runs output | Dependency vulnerabilities not exploitable in this action's context |

## Supported Versions

Only the current `main` branch receives security fixes. This action is pinned by
SHA in consuming repos; update the pin after a fix lands.

## Disclosure Policy

Once a fix is merged to `main`, the maintainer will publish the GitHub Security
Advisory and reference the fixing commit. Credit to the reporter will be included
unless they request otherwise.
