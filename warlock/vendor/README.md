# Vendored third-party code

Code here is **not ours**. Do not refactor it to match house style — keeping it
close to upstream makes it possible to diff against a newer release later.

## `pn532/`

Waveshare PN532 NFC HAT control library.

- **Authors:** Yehui (Waveshare), Tony DiCola (Adafruit)
- **License:** MIT — Copyright (c) 2019 Waveshare, (c) 2015–2018 Adafruit Industries
  (full text retained in the file headers)
- **Why vendored:** it is not published on PyPI under this name, and V1 carried
  its own copy. v2 keeps its own so the package is self-contained rather than
  importing out of `Warlock Table V1/MagicTarot/` — a legacy folder whose name
  contains spaces and which should stay frozen as reference material.
- **Wiring in this table:** SPI, `cs=4`, `reset=20` (carried over from V1 and
  confirmed working — PN532 firmware 1.6).
