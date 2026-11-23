# Fonts

IBM Plex Sans and IBM Plex Mono, normal style, weights 400, 500, 600 and 700,
in the Latin and Latin Extended subsets (WOFF2). Taken unchanged from the
Fontsource npm packages `@fontsource/ibm-plex-sans` and
`@fontsource/ibm-plex-mono` 5.3.0.

Copyright IBM Corp. Licensed under the SIL Open Font License 1.1: see
`OFL-IBM-Plex-Sans.txt` and `OFL-IBM-Plex-Mono.txt`. The licence allows
bundling and redistributing the fonts with software; the font files may not
be sold on their own.

The dashboard serves this folder itself (`.streamlit/config.toml`,
`enableStaticServing`), so `dashboard/style.py` loads them from
`app/static/fonts/` and no font server is asked. Everything in `static/` is
public without a login: keep only these files here.
