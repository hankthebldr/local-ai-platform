"""Static-markup regression for the canonical design-system token foundation.

Implements chat1's "semantic color expansion" from the claude.ai/design handoff:
the live :root must carry the canonical surface / accent-extension / status-ghost
/ node-tint / dataviz-series tokens + the radius and type scales. These also back
the redesign features (which reference var(--surface-card) etc.) — a regression
here re-breaks panels that were rendering transparent before the expansion.
"""

import re

# Tokens the canonical system defines and the features depend on. The earlier
# audit found var(--surface-card) used 11x with NO fallback while --surface-card
# was undefined → transparent panels. This guards that whole class.
REQUIRED = [
    # surfaces
    "--surface",
    "--surface-card",
    "--surface-raised",
    "--surface-overlay",
    "--surface-panel",
    "--surface-inset",
    "--bg-sunken",
    "--border-faint",
    # accent extensions
    "--accent-deep",
    "--accent-warm",
    "--accent-warm-dim",
    "--on-accent-2",
    # text + status ghosts
    "--text-strong",
    "--text-accent",
    "--success-ghost",
    "--warn-ghost",
    "--danger-ghost",
    "--info-ghost",
    # node category tints + dataviz series
    "--node-reasoning",
    "--node-coding",
    "--node-fast",
    "--node-general",
    "--node-uncensored",
    "--viz-1",
    "--viz-2",
    "--viz-3",
    "--viz-4",
    "--viz-5",
    # radii + type scale + extra elevation/glow
    "--radius-sm",
    "--radius-md",
    "--radius-lg",
    "--radius-pill",
    "--text-2xs",
    "--text-xs",
    "--text-sm",
    "--text-base",
    "--text-lg",
    "--elev-4",
    "--glow-emerald",
    "--glow-warm",
]


def test_canonical_tokens_defined(index_html_text):
    for tok in REQUIRED:
        assert re.search(rf"^\s*{re.escape(tok)}:", index_html_text, re.M), (
            f"canonical design token {tok} missing from :root — the design-system "
            "token expansion regressed"
        )


def test_surface_card_no_longer_undefined(index_html_text):
    """The specific bug the expansion fixed: --surface-card must resolve."""
    assert re.search(r"^\s*--surface-card:\s*#?\w", index_html_text, re.M)


def test_node_tints_match_role_palette(index_html_text):
    # Node tints encode the role palette (reasoning=teal, uncensored=ember).
    assert re.search(r"--node-reasoning:\s*#2BD4B4", index_html_text)
    assert re.search(r"--node-uncensored:\s*#E08A4C", index_html_text)


def test_light_scope_overrides_surfaces(index_html_text):
    # Light theme must flip surfaces to white, not inherit the charcoal.
    light = index_html_text[index_html_text.index('[data-theme="light"]') :]
    assert re.search(r"--surface-card:\s*#FFFFFF", light)
    assert re.search(r"--text-strong:\s*#060A09", light)
