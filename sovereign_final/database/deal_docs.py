"""
database/deal_docs.py — a deal's due-diligence checklist and its documents
(DEAL PIPELINE → the picked deal): what you have checked before buying, and
the files that show it — the LV, the správca's confirmation that nothing is
owed, the energy certificate, the bank's offer, each version of the contract.

The files are kept in the database itself, so the daily backup carries them
with everything else. One file is at most MAX_FILE_MB.
"""

import uuid
from datetime import datetime, timezone

import database as _db

MAX_FILE_MB = 15

# The checks, in the order a purchase meets them: (key, Slovak deal, Czech deal).
CHECKLIST = (
    ("rents",      "Three live rental ads nearby compared with the card's rent",
                   "Tři aktuální inzeráty na pronájem v okolí porovnané s nájmem na kartě"),
    ("viewing",    "Viewing done: roof, façade, lift, risers, damp, windows",
                   "Prohlídka: střecha, fasáda, výtah, stoupačky, vlhkost, okna"),
    ("lv_read",    "Part C of the LV read by you and your lawyer",
                   "Části C a D výpisu z LV přečteny vámi a advokátem"),
    ("bezdlznost", "Správca's potvrdenie o bezdlžnosti: the flat owes nothing",
                   "Potvrzení SVJ / správce o bezdlužnosti jednotky"),
    ("fond",       "Fond opráv balance, the building's loans and planned works",
                   "Zůstatek fondu oprav, úvěry domu a plánované opravy"),
    ("revisions",  "Building revision reports: lift, gas, electrics",
                   "Revizní zprávy domu: výtah, plyn, elektro"),
    ("energy",     "Energy certificate (energetický certifikát)",
                   "Průkaz energetické náročnosti budovy (PENB)"),
    ("seller",     "Seller checked: insolvency register and executions (CRE)",
                   "Prodávající prověřen: insolvenční rejstřík (ISIR) a exekuce (CEE)"),
    ("bank",       "Bank's loan offer and the valuation (znalecký posudok)",
                   "Nabídka banky a odhad ceny nemovitosti"),
    ("contract",   "Contract reviewed by a lawyer or notary; escrow (úschova) agreed",
                   "Smlouva prověřena advokátem; advokátní / notářská úschova"),
    ("lv_48h",     "LV re-read within 48 hours of signing (RE-VERIFY LV)",
                   "Výpis z LV ověřen do 48 hodin před podpisem"),
    ("meters",     "Meter readings at handover: water, gas, electricity, heat",
                   "Stavy měřidel při předání: voda, plyn, elektřina, teplo"),
)
CHECK_KEYS = tuple(k for k, _sk, _cz in CHECKLIST)
FILE_KINDS = ("LV", "Potvrdenie o bezdlžnosti", "Energy certificate", "Bank offer",
              "Valuation", "Contract", "Photo", "Other")


def _ensure_tables(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS deal_checklist (
            listing_id TEXT NOT NULL,
            item       TEXT NOT NULL,
            done       INTEGER NOT NULL DEFAULT 0,
            note       TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (listing_id, item)
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS deal_files (
            id          TEXT PRIMARY KEY,
            listing_id  TEXT NOT NULL,
            kind        TEXT NOT NULL,
            name        TEXT NOT NULL,
            mime        TEXT,
            size        INTEGER NOT NULL,
            data        BLOB NOT NULL,
            uploaded_at TEXT NOT NULL
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_deal_files_listing ON deal_files(listing_id)")


def get_checklist(listing_id: str) -> dict[str, dict]:
    """{item: {"done", "note", "updated_at"}} for the items ticked or noted."""
    conn = _db.get_conn()
    try:
        _ensure_tables(conn)
        rows = conn.execute("SELECT item, done, note, updated_at FROM deal_checklist "
                            "WHERE listing_id=?", (listing_id,)).fetchall()
    finally:
        conn.close()
    return {r["item"]: {"done": bool(r["done"]), "note": r["note"] or "",
                        "updated_at": r["updated_at"]} for r in rows}


def set_checklist(listing_id: str, items: dict[str, tuple[bool, str]]) -> int:
    """Store {item: (done, note)} for a deal; unknown items are ignored.
    Returns how many were stored."""
    now = datetime.now(timezone.utc).isoformat()
    rows = [(listing_id, k, 1 if done else 0, (note or "").strip()[:300] or None, now)
            for k, (done, note) in items.items() if k in CHECK_KEYS]
    conn = _db.get_conn()
    try:
        _ensure_tables(conn)
        conn.executemany("INSERT OR REPLACE INTO deal_checklist "
                         "(listing_id, item, done, note, updated_at) VALUES (?,?,?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def add_deal_file(listing_id: str, kind: str, name: str, data: bytes,
                  mime: str | None = None) -> str:
    """Keep a document for a deal; returns its id. A file over MAX_FILE_MB,
    or an empty one, is refused (ValueError)."""
    if not data:
        raise ValueError("the file is empty")
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise ValueError(f"the file is over {MAX_FILE_MB} MB")
    file_id = str(uuid.uuid4())
    conn = _db.get_conn()
    try:
        _ensure_tables(conn)
        conn.execute("INSERT INTO deal_files (id, listing_id, kind, name, mime, size, data, "
                     "uploaded_at) VALUES (?,?,?,?,?,?,?,?)",
                     (file_id, listing_id, kind if kind in FILE_KINDS else "Other",
                      (name or "document")[:120], mime, len(data), data,
                      datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()
    return file_id


def list_deal_files(listing_id: str) -> list[dict]:
    """The deal's documents without their contents, newest first."""
    conn = _db.get_conn()
    try:
        _ensure_tables(conn)
        rows = conn.execute("SELECT id, kind, name, mime, size, uploaded_at FROM deal_files "
                            "WHERE listing_id=? ORDER BY uploaded_at DESC", (listing_id,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_deal_file(file_id: str) -> dict | None:
    """One document with its contents ("data"), or None."""
    conn = _db.get_conn()
    try:
        _ensure_tables(conn)
        row = conn.execute("SELECT id, listing_id, kind, name, mime, size, data, uploaded_at "
                           "FROM deal_files WHERE id=?", (file_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def delete_deal_file(file_id: str) -> bool:
    conn = _db.get_conn()
    try:
        _ensure_tables(conn)
        n = conn.execute("DELETE FROM deal_files WHERE id=?", (file_id,)).rowcount
        conn.commit()
    finally:
        conn.close()
    return n > 0
