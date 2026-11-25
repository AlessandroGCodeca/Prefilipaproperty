# Fonts for the PDF printouts

IBM Plex Sans, Regular and Bold, complete character set (WOFF), taken
unchanged from IBM's npm package `@ibm/plex-sans` 2.0.0
(`fonts/complete/woff/`). The investment memo and the offer sheet
(`modules/memo.py`, `modules/offer_sheet.py`) embed them, so a printout looks
like the dashboard (D15, D21) and prints Slovak and Czech letters and €
on any computer, whatever fonts it has.

Copyright IBM Corp. Licensed under the SIL Open Font License 1.1: see
`OFL-IBM-Plex-Sans.txt`. The licence allows bundling the fonts with software
and embedding them in documents; the font files may not be sold on their own.

They live here, not in `static/`, because only the server reads them:
`static/` is served to anyone without a login.
