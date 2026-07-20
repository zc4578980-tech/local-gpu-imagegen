# Stable Diffusion Image Generation Reference

This plugin folds in the practical capability areas from the public `stable-diffusion-image-generation` skill search result while keeping execution local to this plugin.

Referenced skill:

- `davila7/claude-code-templates@stable-diffusion-image-generation`
- Skills listing: `https://skills.sh/davila7/claude-code-templates/stable-diffusion-image-generation`
- Related upstream content observed under the repository's multimodal Stable Diffusion skill.

Integrated locally:

- Text-to-image generation.
- Image-to-image generation.
- Inpainting with source and mask images.
- Diffusers scheduler selection.
- Diffusers LoRA loading.
- VRAM controls: attention slicing, VAE slicing/tiling, and CPU offload.
- WebUI API fallback for AUTOMATIC1111-compatible servers.

Not copied verbatim:

- Large tutorial sections.
- Provider-specific cloud examples.
- Unrelated research workflow content.

The implementation lives in:

- `scripts/generate_image.py`
- `scripts/mcp_server.py`
- `skills/local-gpu-imagegen/SKILL.md`
