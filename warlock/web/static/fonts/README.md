# Fonts

Bundled and served locally, **not** loaded from the Google Fonts CDN.

The table is an appliance on a LAN. Depending on the internet to render its
own control panel would mean the panel degrades to fallback type exactly
when the network is having a bad day — which is when you are most likely to
be looking at it.

| File | Face | Licence |
|---|---|---|
| `Syne.ttf` | Display (variable, Regular→ExtraBold) | SIL OFL 1.1 — see `OFL-syne.txt` |
| `IBMPlexSans.ttf` | Body (variable) | SIL OFL 1.1 |
| `IBMPlexMono-Regular.ttf` | Utility | SIL OFL 1.1 |
| `IBMPlexMono-Medium.ttf` | Utility, emphasis | SIL OFL 1.1 |

Source: <https://github.com/google/fonts> (`ofl/syne`, `ofl/ibmplexsans`,
`ofl/ibmplexmono`).

These same files are read by `warlock/statusscreen.py` when rendering the TV
status screen, so the panel and the TV use identical type rather than the
TV falling back to whatever `apt` happened to install.
