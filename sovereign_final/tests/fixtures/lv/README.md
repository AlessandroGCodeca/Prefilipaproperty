# LV fixtures

Each `<name>.txt` is the plain text of an LV report (as
`kataster_scraper.fetch_lv_text` returns it) and `<name>.expected.json` is what
the screen must make of it:

```json
{"status": "PASS", "flags": [], "soft": ["vecné bremeno"], "_checked_against_the_vypis": true}
```

- `status`: `PASS` or `REJECT` (`modules/debt_bot._parse_lv`)
- `flags`: the blocking encumbrances; `soft`: the soft flags
- `no_part_c`: set when the text has no ČASŤ C heading
- `_checked_against_the_vypis`: `true` only once someone compared the verdict
  with the paper výpis

`tests/test_lv_tiers.py::test_fixture_lv` runs every pair.

## The synthetic ones

`synthetic_*` files are **made up** in the layout the screen expects (parts A,
B, C; entries numbered `V 1234/2015`). They only keep the harness honest. They
say nothing about what the cadastre really prints — which is the open question
from the October 2026 audit (A9).

## Adding a real one

From a Slovak IP, in `sovereign_final/`:

```
python3 dev/capture_lv_fixture.py --lv 4321 --area Petržalka --name petrzalka_bank_lien \
    --redact "Novák,Hlavná 12"
```

It blanks birth numbers and birth dates and every string you list in
`--redact` (owner names, addresses — the script cannot find names on its own),
then writes the pair with the screen's current verdict. Read both files, correct
the expected verdict against the výpis, set `_checked_against_the_vypis` to
`true`, and only then commit. Useful ones to collect: a clean LV, a bank
mortgage, a private lien, an exekúcia note, a utility easement, a lifetime
right of use, a municipality's pre-emption right, and an LV shared by a whole
building.
