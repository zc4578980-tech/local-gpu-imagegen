# Contributing

Contributions should keep the project focused: a small, explainable local image-generation MCP service rather than a general agent platform.

## Development Setup

Protocol and mocked backend tests require only Python 3.11 or 3.12:

```powershell
python -m unittest discover -s tests -v
python .\scripts\verify_mcp.py
```

Do not download model weights or require a GPU in ordinary unit tests. Put real-backend checks behind an explicit integration-test marker and document their model, hardware, and network prerequisites.

## Pull Request Checklist

- Add or update tests for behavioral changes.
- Keep MCP transport concerns out of backend generation code.
- Preserve structured errors and request IDs.
- Do not introduce hidden package/model downloads.
- Update README or troubleshooting documentation when user-visible behavior changes.
- Avoid credentials, private images, machine-specific paths, and unverified performance claims.

## Reporting Bugs

Include the command or MCP method, sanitized JSON output, Python version, backend choice, and whether the issue reproduces with `scripts/verify_mcp.py`. Do not attach private source images or access tokens.
