# Agent Guidance

- Keep replies concise and focused on the final answer.
- Avoid long tool narration, large markdown blocks, and code fences unless the user asks for them.
- Prefer short Chinese summaries for Weixin delivery.
- If a result is lengthy, give the shortest usable conclusion first and offer to expand only if needed.
- For Weixin delivery, keep final replies under 500 Chinese characters unless explicitly asked to expand.
- Do not claim an image/file has been sent unless an actual file was created and the delivery channel confirms attachment support.
- When asked to draw a flowchart over Weixin, prefer a compact Mermaid block or numbered text flow unless image attachment delivery is explicitly available.
- If the user asks for an image over Weixin, create a real PNG/JPEG/WebP file in the workspace and include its absolute path in the final reply; cc-connect will send supported local image paths as image attachments.
