# Renderer receipt

**Renderer:** `rsvg-convert version 2.62.3`.

The source diagram is `profile-evolution-claude-code-front-door.svg` with a
fixed 1600 by 900 view box. The checked-in PNG was reproduced byte-for-byte
from that source with:

```bash
rsvg-convert --width 1600 --height 900 \
  profile-evolution-claude-code-front-door.svg \
  --output profile-evolution-claude-code-front-door.png
```

The SVG is the editable source; the PNG is the portable rendered copy.

## Portable source/render binding

| Source / render | Source SHA-256 | Render SHA-256 |
|---|---|---|
| `profile-evolution-claude-code-front-door.svg` / `profile-evolution-claude-code-front-door.png` | `8cd185d2c255b6b63a02069af4287c0c372390abc79dc9bb87dc73d66183d072` | `384688475265c1051009369ec6d0ea05896af7aeff0adffd52a7a444c925c56e` |

Any source or render change requires rerendering, visual inspection, and new
digests.
