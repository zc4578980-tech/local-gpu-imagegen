## Summary

Describe the user-visible or engineering change.

## Verification

- [ ] `python -m unittest discover -s tests -v`
- [ ] `python scripts/verify_mcp.py`
- [ ] No model, dependency, or network download was added without explicit opt-in.
- [ ] No credentials, private images, local endpoints, or personal absolute paths are included.

## Scope

- Backend(s): protocol only / WebUI / ComfyUI / Diffusers
- Documentation updated when behavior or limitations changed: yes / not applicable
- Public claims are backed by retained, publishable evidence: yes / not applicable
