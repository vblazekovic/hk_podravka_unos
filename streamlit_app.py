import io
import os
import json
import sqlite3
from datetime import datetime, date
from typing import List

import pandas as pd
import streamlit as st

st.set_page_config(page_title="HK Podravka — Sustav (prazno)", page_icon="🥇", layout="wide")

DB_PATH = "data/rezultati_knjiga1.sqlite"  # prazna baza, kreira se automatski
UPLOAD_ROOT = "data/uploads"               # slike natjecanja i fotografije članova

# -------------------- pomoćne liste --------------------
COMP_TYPES_DEFAULT = [
    "PRVENSTVO HRVATSKE",
    "REPREZENTATIVNI NASTUP",
    "MEĐUNARODNI TURNIR",
    "KUP",
    "LIGA",
    "REGIONALNO",
    "KVALIFIKACIJE",
    "ŠKOLSKO",
    "OSTALO",
]
STYLES = ["GR", "FS", "WW", "BW", "MODIFICIRANI"]
AGE_GROUPS = ["početnici", "početnice", "U11", "U13", "U15", "U17", "U20", "U23", "seniori", "seniorke"]

# HR nazivi + dvoslovne kratice (ostavljeno radi kompatibilnosti)
COUNTRIES = {
    "Albanija": "AL", "Austrija": "AT", "Belgija": "BE", "Bosna i Hercegovina": "BA",
    "Bugarska": "BG", "Crna Gora": "ME", "Češka": "CZ", "Danska": "DK", "Egipat": "EG",
    "Finska": "FI", "Francuska": "FR", "Grčka": "GR", "Hrvatska": "HR", "Irska": "IE",
    "Italija": "IT", "Kosovo": "XK", "Mađarska": "HU", "Makedonija": "MK", "Njemačka": "DE",
    "Nizozemska": "NL", "Norveška": "NO", "Poljska": "PL", "Portugal": "PT", "Rumunjska": "RO",
    "SAD": "US", "Srbija": "RS", "Slovačka": "SK", "Slovenija": "SI", "Španjolska": "ES",
    "Švedska": "SE", "Švicarska": "CH", "Turska": "TR", "Ujedinjeno Kraljevstvo": "GB",
}

# 3-slovne kratice (prijedlozi) — ručni unos je moguć
COUNTRY_3_SUGGEST = {
    "Hrvatska": "CRO", "Srbija": "SRB", "Italija": "ITA", "Slovenija": "SLO", "Bosna i Hercegovina": "BIH",
    "Mađarska": "HUN", "Austrija": "AUT", "Njemačka": "GER", "Španjolska": "ESP", "Francuska": "FRA",
    "Poljska": "POL", "Češka": "CZE", "Slovačka": "SVK", "Crna Gora": "MNE", "Rumunjska": "ROU",
    "Bugarska": "BUL", "Grčka": "GRE", "Turska": "TUR", "Norveška": "NOR", "Švedska": "SWE",
    "Finska": "FIN", "Švicarska": "SUI", "Nizozemska": "NED", "Belgija": "BEL",
    "Ujedinjeno Kraljevstvo": "GBR", "Irska": "IRL", "SAD": "USA", "Kanada": "CAN",
    "Brazil": "BRA", "Argentina": "ARG", "Meksiko": "MEX", "Japan": "JPN", "Kina": "CHN",
    "Indija": "IND", "J. Koreja": "KOR", "Australija": "AUS", "Novi Zeland": "NZL"
}

# -------------------- DB utils --------------------
def ensure_dirs():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(UPLOAD_ROOT, exist_ok=True)

def get_conn():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def df_from_sql(q: str, params: tuple = ()):
    conn = get_conn()
    df = pd.read_sql(q, conn, params=params)
    conn.close()
    return df

def exec_sql(q: str, params: tuple = ()):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(q, params)
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    return lid

def exec_many(q: str, rows: List[tuple]):
    conn = get_conn()
    cur = conn.cursor()
    cur.executemany(q, rows)
    conn.commit()
    conn.close()

def init_db():
    """Kreira praznu bazu + tablice za prisustvo."""
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript(
        """
        PRAGMA foreign_keys=ON;

        -- NATJECANJA
        CREATE TABLE IF NOT EXISTS competitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            redni_broj INTEGER UNIQUE,
            godina INTEGER,
            datum TEXT,
            datum_kraj TEXT,
            natjecanje TEXT,
            ime_natjecanja TEXT,
            stil_hrvanja TEXT,
            mjesto TEXT,
            drzava TEXT,
            kratica_drzave TEXT,
            nastupilo_podravke INTEGER,
            ekipno TEXT,
            trener TEXT,
            napomena TEXT,
            link_rezultati TEXT,
            galerija_json TEXT,
            vijest TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- REZULTATI
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competition_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
            ime_prezime TEXT,
            spol TEXT,
            plasman TEXT,
            kategorija TEXT,
            uzrast TEXT,
            borbi INTEGER,
            pobjeda INTEGER,
            izgubljenih INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- CLANOVI
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ime TEXT,
            prezime TEXT,
            datum_rodjenja TEXT,
            godina_rodjenja INTEGER,
            email_sportas TEXT,
            email_roditelj TEXT,
            telefon_sportas TEXT,
            telefon_roditelj TEXT,
            clanski_broj TEXT,
            oib TEXT,
            adresa TEXT,
            grupa_trening TEXT,
            foto_path TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- TRENING TERMINI
        CREATE TABLE IF NOT EXISTS trainings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum TEXT NOT NULL,
            dan_u_tjednu TEXT,
            grupa TEXT NOT NULL,
            vrijeme TEXT NOT NULL,            -- izvorni string, npr. 18:30-20:00
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            napomena TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- PRISUSTVO
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            training_id INTEGER NOT NULL REFERENCES trainings(id) ON DELETE CASCADE,
            member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            present INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    conn.commit()
    conn.close()

def next_redni_broj() -> int:
    try:
        d = df_from_sql("SELECT MAX(redni_broj) AS mx FROM competitions")
        if d.empty or d.iloc[0, 0] is None:
            return 1
        return int(d.iloc[0, 0]) + 1
    except Exception:
        return 1

def save_uploads(files, folder: str) -> list:
    """Spremi uploadane datoteke u podmapu; vrati listu putanja."""
    ensure_dirs()
    saved = []
    if not files:
        return saved
    dest_dir = os.path.join(UPLOAD_ROOT, folder)
    os.makedirs(dest_dir, exist_ok=True)
    for f in files:
        name = f.name.replace("/", "_").replace("\\", "_")
        path = os.path.join(dest_dir, name)
        with open(path, "wb") as out:
            out.write(f.read())
        saved.append(path)
    return saved

# Inicijalizacija prazne baze
init_db()

# -------------------- UI --------------------
st.title("🥇 HK Podravka — Sustav (prazno)")

page = st.sidebar.radio(
    "Navigacija",
    [
        "➕ Unos natjecanja",
        "🛠 Uredi natjecanje",
        "🧾 Unos rezultata",
        "📊 Pregled & izvoz",
        "📅 Prisustvo",
        "👤 Članovi",
    ],
)

# --- Sidebar dijagnostika ---
with st.sidebar.expander("⚙️ Dijagnostika"):
    st.write("Radni direktorij:", os.getcwd())
    st.write("DB putanja:", os.path.abspath(DB_PATH))
    data_dir = os.path.dirname(DB_PATH) or "."
    st.write("Data direktorij:", os.path.abspath(data_dir))
    try:
        ensure_dirs()
        ok_write = os.access(data_dir, os.W_OK)
        st.write("Write permission:", ok_write)
        conn = get_conn()
        tabs = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", conn)
        conn.close()
        st.write("Tablice u bazi:", ", ".join(tabs["name"].tolist()) if not tabs.empty else "(nema)")
        if st.button("💾 Inicijaliziraj/kreiraj bazu"):
            init_db()
            st.success("Baza inicijalizirana.")
    except Exception as e:
        st.error(f"Greška s bazom: {e}")

# ---------- helpers za UI ----------
def select_or_new(label: str, options: List[str], key: str) -> str:
    opts = sorted(list(set([o for o in options if o])))
    opts = ["➕ Upiši novo…"] + opts
    sel = st.selectbox(label, opts, key=key)
    if sel == "➕ Upiši novo…":
        return st.text_input(f"{label} (upiši)", key=f"{key}_new").strip()
    return sel

def name_select(label: str, names: List[str], key: str) -> str:
    opts = sorted(list(set([n for n in names if n])))
    opts = ["➕ Upiši novo ime/prezime…"] + opts
    sel = st.selectbox(label, opts, key=key)
    if sel.startswith("➕"):
        return st.text_input(f"{label} (upiši)", key=f"{key}_new").strip()
    return sel

# ----------------------- ➕ Unos natjecanja -----------------------
if page == "➕ Unos natjecanja":
    st.subheader("➕ Dodaj natjecanje")

    with st.form("frm_comp_add"):
        rb = next_redni_broj()
        st.write(f"Redni broj (auto): **{rb}**")

        col1, col2, col3 = st.columns(3)
        with col1:
            godina = st.number_input("Godina", min_value=1990, max_value=2100, value=datetime.now().year, step=1)
            datum = st.date_input("Datum (početak)")
            datum_kraj = st.date_input("Datum (kraj)", value=datum)
        with col2:
            natjecanje = select_or_new("Tip natjecanja", COMP_TYPES_DEFAULT, "comp_type")
            ime_natjecanja = st.text_input("Ime natjecanja (opcionalno)")
            stil = st.selectbox("Stil", STYLES, index=0)
        with col3:
            df_c = df_from_sql("SELECT DISTINCT mjesto FROM competitions WHERE mjesto IS NOT NULL AND mjesto<>''")
            grad_postojece = df_c["mjesto"].tolist() if not df_c.empty else []
            mjesto = select_or_new("Mjesto", grad_postojece, "grad_sel")

            drzave_opts = sorted(list(COUNTRIES.keys()))
            drzava = st.selectbox("Država (HR nazivi)", drzave_opts, index=drzave_opts.index("Hrvatska") if "Hrvatska" in drzave_opts else 0)
            kratica3 = st.text_input("Kratica države (3 slova, npr. CRO/ITA/SRB)", value=COUNTRY_3_SUGGEST.get(drzava, ""))
            kratica = (kratica3.strip().upper() or COUNTRIES.get(drzava, "")).strip()

        col4, col5 = st.columns(2)
        with col4:
            nastupilo = st.number_input("Nastupilo hrvača Podravke", min_value=0, step=1, value=0)
            ekipno = st.text_input("Ekipno (npr. ekipni poredak)")
        with col5:
            trener = st.text_input("Trener")

        st.markdown("**Dodatno**")
        link_rez = st.text_input("Link na rezultate (URL)")
        napomena = st.text_area("Napomena", height=80)
        vijest = st.text_area("Tekst vijesti (za web objavu)", height=200)
        imgs = st.file_uploader("Slike s natjecanja (može više)", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True)

        submit = st.form_submit_button("Spremi natjecanje")
        if submit:
            comp_id = exec_sql(
                """
                INSERT INTO competitions
                (redni_broj, godina, datum, datum_kraj, natjecanje, ime_natjecanja, stil_hrvanja,
                 mjesto, drzava, kratica_drzave, nastupilo_podravke, ekipno, trener,
                 napomena, link_rezultati, galerija_json, vijest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rb, int(godina), str(datum), str(datum_kraj), natjecanje.strip(), ime_natjecanja.strip(),
                    stil.strip(), mjesto.strip(), drzava.strip(), kratica, int(nastupilo), ekipno.strip(),
                    trener.strip(), napomena.strip(), link_rez.strip(), None, vijest.strip()
                ),
            )
            paths = save_uploads(imgs, f"comp_{comp_id}") if imgs else []
            if paths:
                exec_sql("UPDATE competitions SET galerija_json=? WHERE id=?", (json.dumps(paths, ensure_ascii=False), comp_id))
            st.success(f"✅ Natjecanje spremljeno. Redni broj: {rb}")

    st.divider()
    st.subheader("📋 Popis natjecanja")
    dfc = df_from_sql("""
        SELECT id, redni_broj, godina, datum, datum_kraj, natjecanje, ime_natjecanja, stil_hrvanja, mjesto, drzava, kratica_drzave
        FROM competitions ORDER BY godina DESC, datum DESC
    """)
    st.dataframe(dfc, use_container_width=True)

# ----------------------- 🛠 Uredi natjecanje -----------------------
elif page == "🛠 Uredi natjecanje":
    st.subheader("🛠 Uredi postojeće natjecanje")
    dfc_all = df_from_sql("SELECT * FROM competitions ORDER BY godina DESC, datum DESC")
    if dfc_all.empty:
        st.info("Nema natjecanja za urediti.")
        st.stop()

    labels = dfc_all.apply(lambda r: f"#{int(r['redni_broj'])} — {r['datum']} — {r['ime_natjecanja'] or ''}", axis=1).tolist()
    idx = st.selectbox("Odaberi", list(range(len(labels))), format_func=lambda i: labels[i])
    row = dfc_all.iloc[idx]

    with st.form("frm_edit"):
        col1, col2, col3 = st.columns(3)
        with col1:
            godina = st.number_input("Godina", min_value=1990, max_value=2100, value=int(row["godina"] or datetime.now().year), step=1)
            datum = st.date_input("Datum (početak)", value=pd.to_datetime(row["datum"]).date() if row["datum"] else date.today())
            datum_kraj = st.date_input("Datum (kraj)", value=pd.to_datetime(row["datum_kraj"]).date() if row["datum_kraj"] else pd.to_datetime(row["datum"]).date())
        with col2:
            natjecanje = select_or_new("Tip natjecanja", COMP_TYPES_DEFAULT + [str(row["natjecanje"] or "")], "comp_type_edit")
            ime_natjecanja = st.text_input("Ime natjecanja (opcionalno)", value=str(row["ime_natjecanja"] or ""))
            stil = st.selectbox("Stil", STYLES, index=(STYLES.index(row["stil_hrvanja"]) if row["stil_hrvanja"] in STYLES else 0))
        with col3:
            df_c = df_from_sql("SELECT DISTINCT mjesto FROM competitions WHERE mjesto IS NOT NULL AND mjesto<>''")
            grad_postojece = df_c["mjesto"].tolist() if not df_c.empty else []
            mjesto = select_or_new("Mjesto", grad_postojece + [str(row["mjesto"] or "")], "grad_edit")
            drzave_opts = sorted(list(COUNTRIES.keys()))
            default_country = str(row["drzava"] or "Hrvatska")
            drzava = st.selectbox("Država (HR nazivi)", drzave_opts, index=(drzave_opts.index(default_country) if default_country in drzave_opts else 0))
            kratica3 = st.text_input("Kratica države (3 slova)", value=str(row.get("kratica_drzave") or COUNTRY_3_SUGGEST.get(drzava, "")))
            kratica = (kratica3.strip().upper() or COUNTRIES.get(drzava, "")).strip()

        col4, col5 = st.columns(2)
        with col4:
            nastupilo = st.number_input("Nastupilo hrvača Podravke", min_value=0, step=1, value=int(row["nastupilo_podravke"] or 0))
            ekipno = st.text_input("Ekipno", value=str(row["ekipno"] or ""))
        with col5:
            trener = st.text_input("Trener", value=str(row["trener"] or ""))

        st.markdown("**Dodatno**")
        link_rez = st.text_input("Link na rezultate (URL)", value=str(row.get("link_rezultati", "") or ""))
        napomena = st.text_area("Napomena", value=str(row.get("napomena", "") or ""), height=80)
        vijest = st.text_area("Tekst vijesti (za web objavu)", value=str(row.get("vijest", "") or ""), height=200)
        nove_slike = st.file_uploader("Dodaj još slika (opcionalno)", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True)

        gal_list = []
        try:
            if row["galerija_json"]:
                gal_list = json.loads(row["galerija_json"])
        except Exception:
            gal_list = []
        if gal_list:
            st.caption("Postojeće slike:")
            for p in gal_list[:12]:
                st.image(p, width=150)

        if st.form_submit_button("Spremi izmjene"):
            add_paths = save_uploads(nove_slike, f"comp_{int(row['id'])}") if nove_slike else []
            all_paths = gal_list + add_paths if add_paths else gal_list
            exec_sql(
                """
                UPDATE competitions SET
                    godina=?, datum=?, datum_kraj=?, natjecanje=?, ime_natjecanja=?,
                    stil_hrvanja=?, mjesto=?, drzava=?, kratica_drzave=?, nastupilo_podravke=?,
                    ekipno=?, trener=?, napomena=?, link_rezultati=?, galerija_json=?, vijest=?
                WHERE id=?
                """,
                (
                    int(godina), str(datum), str(datum_kraj), natjecanje.strip(), ime_natjecanja.strip(),
                    stil.strip(), mjesto.strip(), drzava.strip(), kratica, int(nastupilo),
                    ekipno.strip(), trener.strip(), napomena.strip(), link_rez.strip(),
                    (json.dumps(all_paths, ensure_ascii=False) if all_paths else None),
                    vijest.strip(), int(row["id"])
                ),
            )
            st.success("✅ Izmjene spremljene.")
            st.experimental_rerun()

# ----------------------- 🧾 Unos rezultata -----------------------
elif page == "🧾 Unos rezultata":
    st.subheader("🧾 Unos rezultata po natjecanju")

    dfc = df_from_sql("SELECT id, redni_broj, datum, ime_natjecanja FROM competitions ORDER BY godina DESC, datum DESC")
    if dfc.empty:
        st.info("Prvo dodaj natjecanje u ➕ Unos natjecanja.")
        st.stop()

    comp_labels = dfc.apply(lambda r: f"#{int(r['redni_broj'])} — {r['datum']} — {r['ime_natjecanja'] or ''}", axis=1).tolist()
    comp_map = {comp_labels[i]: int(dfc.iloc[i]["id"]) for i in range(len(comp_labels))}
    sel = st.selectbox("Natjecanje", comp_labels)
    competition_id = comp_map[sel]

    known_names = df_from_sql("SELECT DISTINCT ime_prezime FROM results WHERE ime_prezime IS NOT NULL AND ime_prezime<>''")["ime_prezime"].tolist()

    with st.form("frm_res"):
        col1, col2, col3 = st.columns(3)
        with col1:
            ime_prezime = name_select("Ime i prezime", known_names, "ath_name")
            spol = st.selectbox("Spol", ["M", "Ž"])
            kategorija = st.text_input("Kategorija")
            uzrast = st.selectbox("Uzrast", AGE_GROUPS, index=(AGE_GROUPS.index("U15") if "U15" in AGE_GROUPS else 0))
        with col2:
            borbi = st.number_input("Broj borbi", min_value=0, step=1, value=0)
            pobjeda = st.number_input("Pobjeda", min_value=0, step=1, value=0)
            izgubljenih = st.number_input("Poraza", min_value=0, step=1, value=0)
        with col3:
            plasman = st.text_input("Plasman (1/2/3/...)")

        if st.form_submit_button("Spremi rezultat"):
            if not ime_prezime.strip():
                st.error("Ime i prezime je obavezno.")
            else:
                exec_sql(
                    """
                    INSERT INTO results
                    (competition_id, ime_prezime, spol, plasman, kategorija, uzrast, borbi, pobjeda, izgubljenih)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        competition_id, ime_prezime.strip(), spol, plasman.strip(),
                        kategorija.strip(), uzrast.strip(), int(borbi), int(pobjeda), int(izgubljenih)
                    ),
                )
                st.success("✅ Rezultat spremljen.")
                st.experimental_rerun()

    st.divider()
    st.subheader("📋 Zadnjih 200 rezultata")
    dfr = df_from_sql("""
        SELECT r.id,
               c.redni_broj, c.ime_natjecanja, c.datum,
               r.ime_prezime, r.spol, r.kategorija, r.uzrast,
               r.borbi, r.pobjeda, r.izgubljenih, r.plasman
        FROM results r JOIN competitions c ON c.id = r.competition_id
        ORDER BY r.id DESC
        LIMIT 200
    """)
    st.dataframe(dfr, use_container_width=True)

# ----------------------- 📊 Pregled & izvoz -----------------------
elif page == "📊 Pregled & izvoz":
    st.subheader("📊 Pregled, filtriranje i izvoz")

    dfr = df_from_sql("""
        SELECT r.*, c.redni_broj, c.godina, c.ime_natjecanja, c.datum,
               c.mjesto, c.drzava, c.stil_hrvanja, c.natjecanje, c.kratica_drzave
        FROM results r JOIN competitions c ON c.id = r.competition_id
    """)
    if dfr.empty:
        st.info("Nema podataka.")
        st.stop()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        god_opts = sorted(dfr["godina"].dropna().astype(int).unique().tolist())
        f_god = st.multiselect("Godina", god_opts, default=god_opts)
    with c2:
        nat_opts = sorted(dfr["ime_natjecanja"].dropna().astype(str).unique().tolist())
        f_nat = st.multiselect("Ime natjecanja", nat_opts, default=[])
    with c3:
        tip_opts = sorted(dfr["natjecanje"].dropna().astype(str).unique().tolist())
        f_tip = st.multiselect("Tip natjecanja", tip_opts, default=[])
    with c4:
        stil_opts = sorted(dfr["stil_hrvanja"].dropna().astype(str).unique().tolist())
        f_stil = st.multiselect("Stil", stil_opts, default=[])

    c5, c6, c7, c8 = st.columns(4)
    with c5:
        kat_opts = sorted(dfr["kategorija"].dropna().astype(str).unique().tolist())
        f_kat = st.multiselect("Kategorija", kat_opts, default=[])
    with c6:
        uzr_opts = sorted(dfr["uzrast"].dropna().astype(str).unique().tolist())
        f_uzr = st.multiselect("Uzrast", uzr_opts, default=[])
    with c7:
        spol_opts = sorted(dfr["spol"].dropna().astype(str).unique().tolist())
        f_spol = st.multiselect("Spol", spol_opts, default=[])
    with c8:
        grad_opts = sorted(dfr["mjesto"].dropna().astype(str).unique().tolist())
        f_grad = st.multiselect("Grad", grad_opts, default=[])

    f = dfr.copy()
    if f_god:  f = f[f["godina"].astype(int).isin(f_god)]
    if f_nat:  f = f[f["ime_natjecanja"].astype(str).isin(f_nat)]
    if f_tip:  f = f[f["natjecanje"].astype(str).isin(f_tip)]
    if f_stil: f = f[f["stil_hrvanja"].astype(str).isin(f_stil)]
    if f_kat:  f = f[f["kategorija"].astype(str).isin(f_kat)]
    if f_uzr:  f = f[f["uzrast"].astype(str).isin(f_uzr)]
    if f_spol: f = f[f["spol"].astype(str).isin(f_spol)]
    if f_grad: f = f[f["mjesto"].astype(str).isin(f_grad)]

    st.write(f"🔎 Zapisa: **{len(f)}**")
    view_cols = [
        "redni_broj","godina","datum","ime_natjecanja","natjecanje","stil_hrvanja",
        "mjesto","drzava","kratica_drzave","ime_prezime","spol","kategorija","uzrast",
        "borbi","pobjeda","izgubljenih","plasman"
    ]
    st.dataframe(f[view_cols], use_container_width=True)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        f[view_cols].to_excel(writer, index=False, sheet_name="Filtrirano")
    st.download_button(
        "⬇️ Izvezi filtrirane rezultate u Excel",
        data=output.getvalue(),
        file_name="rezultati_filtrirano.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    with st.expander("📈 Brza statistika"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Natjecanja", f["redni_broj"].nunique())
        c2.metric("Rezultata", len(f))
        c3.metric("Ukupno borbi", int(f["borbi"].fillna(0).sum()))
        c4.metric("Pobjede", int(f["pobjeda"].fillna(0).sum()))

# ----------------------- 📅 Prisustvo -----------------------
elif page == "📅 Prisustvo":
    st.subheader("📅 Unos prisustva na treningu")

    datum = st.date_input("Datum", value=date.today())

    df_groups = df_from_sql("SELECT DISTINCT grupa_trening FROM members WHERE grupa_trening IS NOT NULL AND grupa_trening<>'' ORDER BY 1")
    grp_opts = df_groups["grupa_trening"].dropna().astype(str).tolist() if not df_groups.empty else []
    grupa = st.selectbox("Grupa", ["(odaberi)"] + grp_opts, index=0)

    slot = st.selectbox("Vrijeme treninga", ["18:30-20:00", "20:00-22:00", "➕ Napiši vrijeme…"])
    if slot.startswith("➕"):
        slot = st.text_input("Upiši vrijeme (HH:MM-HH:MM)", value="18:30-20:00")

    napomena = st.text_input("Napomena (opcionalno)")

    def parse_slot(s: str):
        try:
            a,b = s.replace(" ","").split("-")
            return a,b
        except Exception:
            return "18:30","20:00"

    if grupa != "(odaberi)":
        dfm = df_from_sql("SELECT id, ime, prezime FROM members WHERE grupa_trening=? ORDER BY prezime, ime", (grupa,))
        if dfm.empty:
            st.info("Nema članova u toj grupi.")
        else:
            names = dfm.apply(lambda r: f"{r['prezime']} {r['ime']}", axis=1).tolist()
            present = st.multiselect("Prisustvovali", options=names)

            if st.button("💾 Spremi prisustvo"):
                start, end = parse_slot(slot)
                try:
                    dan = pd.to_datetime(str(datum)).day_name(locale='hr_HR')
                except Exception:
                    dan = ""
                tid = exec_sql(
                    """
                    INSERT INTO trainings (datum, dan_u_tjednu, grupa, vrijeme, start_time, end_time, napomena)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (str(datum), dan, grupa, slot, start, end, napomena.strip())
                )
                selected_ids = set(
                    dfm[dfm.apply(lambda r: f"{r['prezime']} {r['ime']}", axis=1).isin(present)]["id"].astype(int).tolist()
                )
                rows = [(tid, mid, 1) for mid in selected_ids]
                if rows:
                    exec_many("INSERT INTO attendance (training_id, member_id, present) VALUES (?, ?, ?)", rows)
                st.success("✅ Prisustvo spremljeno.")

    st.markdown("---")
    st.subheader("📈 Statistika prisustva")

    colA, colB, colC = st.columns(3)
    with colA:
        scope = st.selectbox("Razdoblje", ["Tjedan", "Mjesec", "Godina"])
    with colB:
        anchor = st.date_input("Referentni datum", value=date.today())
    with colC:
        mod = st.radio("Pregled", ["Po grupi", "Po članu"], horizontal=True)

    start_date = pd.to_datetime(anchor)
    if scope == "Tjedan":
        start_date = start_date - pd.to_timedelta(start_date.weekday(), unit='D')
        end_date = start_date + pd.Timedelta(days=7)
    elif scope == "Mjesec":
        start_date = start_date.replace(day=1)
        end_date = (start_date + pd.offsets.MonthEnd(1)) + pd.Timedelta(days=1)
    else:
        start_date = start_date.replace(month=1, day=1)
        end_date = start_date.replace(year=start_date.year + 1)

    if mod == "Po grupi":
        grp = st.selectbox("Grupa", grp_opts if grp_opts else [""], index=0 if grp_opts else 0)
        if grp:
            dft = df_from_sql(
                """
                SELECT * FROM trainings WHERE grupa=? AND datum>=? AND datum<? ORDER BY datum DESC
                """, (grp, str(start_date.date()), str(end_date.date()))
            )
            if dft.empty:
                st.info("Nema treninga u odabranom razdoblju.")
            else:
                total_trainings = len(dft)
                dfm_grp = df_from_sql("SELECT id, ime, prezime FROM members WHERE grupa_trening=? ORDER BY prezime, ime", (grp,))
                recs = []
                for _, m in dfm_grp.iterrows():
                    att = df_from_sql(
                        """
                        SELECT a.* , t.start_time, t.end_time FROM attendance a
                        JOIN trainings t ON t.id=a.training_id
                        WHERE a.member_id=? AND t.grupa=? AND t.datum>=? AND t.datum<?
                        """,
                        (int(m['id']), grp, str(start_date.date()), str(end_date.date()))
                    )
                    attended = len(att.index)
                    hours = att.apply(lambda r: (pd.to_datetime(r['end_time']) - pd.to_datetime(r['start_time'])).seconds/3600, axis=1).sum() if not att.empty else 0
                    pct = (attended/total_trainings*100) if total_trainings>0 else 0
                    recs.append({
                        'Član': f"{m['prezime']} {m['ime']}",
                        'Prisustava': attended,
                        'Ukupno treninga': total_trainings,
                        '% Prisustva': round(pct,1),
                        'Sati': round(hours,2)
                    })
                df_out = pd.DataFrame(recs)
                st.dataframe(df_out, use_container_width=True)
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine="openpyxl") as writer:
                    df_out.to_excel(writer, index=False, sheet_name="Prisustvo grupa")
                st.download_button("⬇️ Izvezi statistiku (Excel)", data=out.getvalue(), file_name="prisustvo_grupa.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        dfm_all = df_from_sql("SELECT id, ime, prezime, grupa_trening FROM members ORDER BY prezime, ime")
        if dfm_all.empty:
            st.info("Nema članova.")
        else:
            labels = dfm_all.apply(lambda r: f"{r['prezime']} {r['ime']} ({r['grupa_trening']})", axis=1).tolist()
            idx = st.selectbox("Član", list(range(len(labels))), format_func=lambda i: labels[i])
            mem = dfm_all.iloc[idx]
            dft = df_from_sql(
                """
                SELECT * FROM trainings WHERE grupa=? AND datum>=? AND datum<? ORDER BY datum DESC
                """, (str(mem['grupa_trening'] or ''), str(start_date.date()), str(end_date.date()))
            )
            total_trainings = len(dft)
            att = df_from_sql(
                """
                SELECT a.* , t.datum, t.vrijeme, t.start_time, t.end_time FROM attendance a
                JOIN trainings t ON t.id=a.training_id
                WHERE a.member_id=? AND t.datum>=? AND t.datum<?
                ORDER BY t.datum DESC
                """,
                (int(mem['id']), str(start_date.date()), str(end_date.date()))
            )
            if att.empty:
                st.info("Nema prisustava u razdoblju.")
            else:
                att['Sati'] = att.apply(lambda r: (pd.to_datetime(r['end_time']) - pd.to_datetime(r['start_time'])).seconds/3600, axis=1)
                st.dataframe(att[["datum","vrijeme","Sati"]], use_container_width=True)
                hours = round(float(att['Sati'].sum()),2)
                pct = round((len(att)/total_trainings*100),1) if total_trainings>0 else 0
                c1,c2,c3 = st.columns(3)
                c1.metric("Prisustava", len(att))
                c2.metric("Ukupno treninga", total_trainings)
                c3.metric("% prisustva", pct)
                st.caption(f"Ukupno sati: **{hours} h**")
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine="openpyxl") as writer:
                    att[["datum","vrijeme","Sati"]].to_excel(writer, index=False, sheet_name="Prisustvo člana")
                st.download_button("⬇️ Izvezi (Excel)", data=out.getvalue(), file_name="prisustvo_clan.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ----------------------- 👤 Članovi -----------------------
elif page == "👤 Članovi":
    st.subheader("👤 Baza članova (Excel uvoz/izvoz + rezultati člana)")

    tab_add, tab_edit, tab_list, tab_import = st.tabs(["➕ Dodaj", "🛠 Uredi/rezultati", "📋 Popis/izvoz", "⬆️ Uvoz članova (Excel)"])

    # Dodaj člana
    with tab_add:
        with st.form("frm_member_add"):
            c1, c2, c3 = st.columns(3)
            with c1:
                ime = st.text_input("Ime *")
                prezime = st.text_input("Prezime *")
                datum_rod = st.date_input("Datum rođenja", value=date(2010, 1, 1))
            with c2:
                godina_rod = st.number_input("Godina rođenja", min_value=1900, max_value=2100, value=2010, step=1)
                email_s = st.text_input("E-mail sportaša")
                email_r = st.text_input("E-mail roditelja")
            with c3:
                tel_s = st.text_input("Kontakt sportaša")
                tel_r = st.text_input("Kontakt roditelja")
                cl_br = st.text_input("Članski broj")

            c4, c5 = st.columns(2)
            with c4:
                oib = st.text_input("OIB")
                adresa = st.text_input("Adresa prebivališta")
            with c5:
                grupa = st.text_input("Grupa treninga (npr. U13, U15, rekreacija...)")
                foto = st.file_uploader("Fotografija (opcionalno)", type=["png", "jpg", "jpeg", "webp"])

            if st.form_submit_button("Spremi člana"):
                foto_path = None
                if foto is not None:
                    saved = save_uploads([foto], "members")
                    foto_path = saved[0] if saved else None

                exec_sql("""
                    INSERT INTO members
                    (ime, prezime, datum_rodjenja, godina_rodjenja, email_sportas, email_roditelj,
                     telefon_sportas, telefon_roditelj, clanski_broj, oib, adresa, grupa_trening, foto_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ime.strip(), prezime.strip(), str(datum_rod), int(godina_rod), email_s.strip(), email_r.strip(),
                    tel_s.strip(), tel_r.strip(), cl_br.strip(), oib.strip(), adresa.strip(), grupa.strip(), foto_path
                ))
                st.success("✅ Član dodan.")

    # Uredi + rezultati člana
    with tab_edit:
        dfm = df_from_sql("SELECT * FROM members ORDER BY prezime, ime")
        if dfm.empty:
            st.info("Nema članova.")
        else:
            labels = dfm.apply(lambda r: f"{r['prezime']} {r['ime']} — {r.get('clanski_broj', '')}", axis=1).tolist()
            idx = st.selectbox("Odaberi člana", list(range(len(labels))), format_func=lambda i: labels[i])
            r = dfm.iloc[idx]

            with st.form("frm_member_edit"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    ime = st.text_input("Ime *", value=str(r["ime"] or ""))
                    prezime = st.text_input("Prezime *", value=str(r["prezime"] or ""))
                    datum_rod = st.date_input("Datum rođenja", value=pd.to_datetime(r["datum_rodjenja"]).date() if r["datum_rodjenja"] else date(2010, 1, 1))
                with c2:
                    godina_rod = st.number_input("Godina rođenja", min_value=1900, max_value=2100, value=int(r["godina_rodjenja"] or 2010), step=1)
                    email_s = st.text_input("E-mail sportaša", value=str(r["email_sportas"] or ""))
                    email_r = st.text_input("E-mail roditelja", value=str(r["email_roditelj"] or ""))
                with c3:
                    tel_s = st.text_input("Kontakt sportaša", value=str(r["telefon_sportas"] or ""))
                    tel_r = st.text_input("Kontakt roditelja", value=str(r["telefon_roditelj"] or ""))
                    cl_br = st.text_input("Članski broj", value=str(r["clanski_broj"] or ""))

                c4, c5 = st.columns(2)
                with c4:
                    oib = st.text_input("OIB", value=str(r["oib"] or ""))
                    adresa = st.text_input("Adresa prebivališta", value=str(r["adresa"] or ""))
                with c5:
                    grupa = st.text_input("Grupa treninga", value=str(r["grupa_trening"] or ""))
                    nova_foto = st.file_uploader("Zamijeni/učitaj fotografiju", type=["png", "jpg", "jpeg", "webp"])

                if st.form_submit_button("Spremi izmjene"):
                    foto_path = r.get("foto_path")
                    if nova_foto is not None:
                        saved = save_uploads([nova_foto], "members")
                        foto_path = saved[0] if saved else foto_path

                    exec_sql("""
                        UPDATE members SET
                        ime=?, prezime=?, datum_rodjenja=?, godina_rodjenja=?, email_sportas=?, email_roditelj=?,
                        telefon_sportas=?, telefon_roditelj=?, clanski_broj=?, oib=?, adresa=?, grupa_trening=?, foto_path=?
                        WHERE id=?
                    """, (
                        ime.strip(), prezime.strip(), str(datum_rod), int(godina_rod), email_s.strip(), email_r.strip(),
                        tel_s.strip(), tel_r.strip(), cl_br.strip(), oib.strip(), adresa.strip(), grupa.strip(),
                        foto_path, int(r["id"])
                    ))
                    st.success("✅ Izmjene spremljene.")
                    st.experimental_rerun()

            st.markdown("---")
            st.subheader("📑 Rezultati odabranog člana")
            full_name = f"{r['ime']} {r['prezime']}".strip()
            dfr_mem = df_from_sql(
                """
                SELECT c.redni_broj, c.godina, c.datum, c.ime_natjecanja, c.mjesto, c.drzava,
                       r.kategorija, r.uzrast, r.spol, r.borbi, r.pobjeda, r.izgubljenih, r.plasman
                FROM results r
                JOIN competitions c ON c.id = r.competition_id
                WHERE r.ime_prezime = ?
                ORDER BY c.godina DESC, c.datum DESC
                """,
                (full_name,),
            )
            if dfr_mem.empty:
                st.info("Ovaj član još nema upisanih rezultata.")
            else:
                st.dataframe(dfr_mem, use_container_width=True)
                out_mem = io.BytesIO()
                with pd.ExcelWriter(out_mem, engine="openpyxl") as writer:
                    dfr_mem.to_excel(writer, index=False, sheet_name="Rezultati člana")
                st.download_button(
                    "⬇️ Izvezi rezultate člana u Excel",
                    data=out_mem.getvalue(),
                    file_name=f"rezultati_{r['prezime']}_{r['ime']}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

    # Popis/izvoz članova
    with tab_list:
        dfm = df_from_sql(
            """
            SELECT ime, prezime, datum_rodjenja, godina_rodjenja, email_sportas, email_roditelj,
                   telefon_sportas, telefon_roditelj, clanski_broj, oib, adresa, grupa_trening, foto_path
            FROM members ORDER BY prezime, ime
            """
        )
        st.dataframe(dfm, use_container_width=True)
        if not dfm.empty:
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine="openpyxl") as writer:
                dfm.to_excel(writer, index=False, sheet_name="Clanovi")
            st.download_button(
                "⬇️ Izvezi članove u Excel",
                data=out.getvalue(),
                file_name="clanovi.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    # Uvoz članova
    with tab_import:
        st.caption("Učitaj .xlsx s glavnim kolumnama. Zaglavlja mogu varirati (prepoznajemo ih bez obzira na velika/mala slova).")
        st.markdown("**Preporučena zaglavlja:** Ime, Prezime, Datum rođenja, Godina rođenja, E-mail sportaša, E-mail roditelja, Kontakt sportaša, Kontakt roditelja, Članski broj, OIB, Adresa, Grupa treninga")
        up = st.file_uploader("Excel (.xlsx)", type=["xlsx"], key="member_import")
        if up:
            xls = pd.ExcelFile(io.BytesIO(up.getvalue()))
            sheet = st.selectbox("Sheet", xls.sheet_names)
            df = xls.parse(sheet)
            st.dataframe(df.head(20), use_container_width=True)

            def find_col(df, target_names: List[str]):
                lower_map = {str(c).strip().lower(): c for c in df.columns}
                for name in target_names:
                    key = name.strip().lower()
                    if key in lower_map:
                        return lower_map[key]
                return None

            want = {
                "ime": ["ime"],
                "prezime": ["prezime"],
                "datum_rodjenja": ["datum rođenja", "datum rodjenja", "datum"],
                "godina_rodjenja": ["godina rođenja", "godina rodjenja", "godina"],
                "email_sportas": ["e-mail sportaša", "email sportaša", "email sportas", "email"],
                "email_roditelj": ["e-mail roditelja", "email roditelja"],
                "telefon_sportas": ["kontakt sportaša", "telefon sportaša", "telefon"],
                "telefon_roditelj": ["kontakt roditelja", "telefon roditelja"],
                "clanski_broj": ["članski broj", "clanski broj", "clanski_broj"],
                "oib": ["oib"],
                "adresa": ["adresa", "adresa prebivališta"],
                "grupa_trening": ["grupa treninga", "grupa"],
            }
            mapping = {k: find_col(df, v) for k, v in want.items()}

            required = ["ime", "prezime"]
            miss_req = [k for k in required if mapping[k] is None]
            if miss_req:
                st.error("Nedostaju obavezne kolone: " + ", ".join(miss_req))
            else:
                if st.button("🚀 Uvezi članove"):
                    rows = []
                    for _, r in df.iterrows():
                        def val(key, default=""):
                            col = mapping.get(key)
                            return (str(r[col]) if pd.notna(r[col]) else default) if col is not None else default

                        dat = None
                        if mapping.get("datum_rodjenja") and pd.notna(r[mapping["datum_rodjenja"]]):
                            try:
                                dat = pd.to_datetime(r[mapping["datum_rodjenja"]]).date()
                            except Exception:
                                dat = None
                        god = None
                        if mapping.get("godina_rodjenja") and pd.notna(r[mapping["godina_rodjenja"]]):
                            try:
                                god = int(pd.to_numeric(r[mapping["godina_rodjenja"]], errors="coerce") or 0)
                            except Exception:
                                god = None

                        rows.append((
                            val("ime"),
                            val("prezime"),
                            str(dat) if dat else "",
                            god if god else None,
                            val("email_sportas"),
                            val("email_roditelj"),
                            val("telefon_sportas"),
                            val("telefon_roditelj"),
                            val("clanski_broj"),
                            val("oib"),
                            val("adresa"),
                            val("grupa_trening"),
                            None,
                        ))

                    if rows:
                        exec_many(
                            """
                            INSERT INTO members
                            (ime, prezime, datum_rodjenja, godina_rodjenja, email_sportas, email_roditelj,
                             telefon_sportas, telefon_roditelj, clanski_broj, oib, adresa, grupa_trening, foto_path)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            rows,
                        )
                    st.success(f"Uvezeno članova: {len(rows)}")
