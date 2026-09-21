# Security

This app runs a local HTTP server on 127.0.0.1 only and talks to a laser over USB.
It never listens on the network and sends nothing anywhere except one request to
api.github.com on start to look for a newer release.

If you find a way to make it fire the laser without the operator's confirmation, reach
outside the local machine, or execute untrusted input, please report it privately through
GitHub's "Report a vulnerability" on the Security tab rather than a public issue.
