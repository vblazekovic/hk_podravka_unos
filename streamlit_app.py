# streamlit_app.py
# HK Podravka — Unos članova + fotografije + brisanje + uvoz/izvoz
import io
import os
import json
import sqlite3
from datetime import date
from typing import List

import pandas as pd
import streamlit as st

# -------------------- osnovno --------------------
st.set_page_config(page_title="HK Podravka — Sustav", page_icon="🥇", layout="wide")

DB_PATH = "data/rezultati_knjiga1.sqlite"
UPLOAD_ROOT = "data/uploads"      # root za sve uploadove
MEMBER_PHOTOS_DIR = os.path.join(UPLOAD_ROOT, "members")  # fotke članova

# -------------------- pomoćne --------------------
def ensure_dirs():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(UPLOAD_ROOT, exist_ok=True)
    os.makedirs(MEMBER_PHOTOS_DIR, exist_ok=True)

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

def save_uploads(files, subfolder: str) -> list:
    """Spremi uploadane datoteke u podmapu; vrati listu putanja."""
    ensure_dirs()
    saved = []
    if not files:
        return saved
    dest_dir = os.path.join(UPLOAD_ROOT, subfolder)
    os.makedirs(dest_dir, exist_ok=True)
    for f in files:
        name = f.name.replace("/", "_").replace("\\", "_")
        path = os.path.join(dest_dir, name)
        with open(path, "wb") as out:
            out.write(f.read())
        saved.append(path)
    return saved

# -------------------- DB init --------------------
def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript("""
    PRAGMA foreign_keys=ON;

    -- minimalne tablice koje trebaju appu
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

    -- prisustvo (opcionalno; FK na members)
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
        datum TEXT NOT NULL,
        termin TEXT,            -- npr. 18:30-20:00
        grupa TEXT,             -- redund. radi brzog filtra
        prisutan INTEGER NOT NULL DEFAULT 1,
        trajanje_min INTEGER DEFAULT 90,
        created_at TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    conn.close()

init_db()

# -------------------- brisanje članova --------------------
def delete_member(member_id: int, delete_photo: bool = True) -> bool:
    """Obriši člana + (opcionalno) njegovu fotografiju s diska.
    Attendance zapisi se brišu automatski (FK ON DELETE CASCADE)."""
    try:
        # nađi foto putanju
        dfp = df_from_sql("SELECT foto_path FROM members WHERE id=?", (member_id,))
        if delete_photo and not dfp.empty:
            fp = str(dfp.iloc[0]["foto_path"] or "").strip()
            if fp and os.path.isfile(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass  # ne ruši app ako se fajl ne može obrisati

        # obriši člana
        exec_sql("DELETE FROM members WHERE id=?", (member_id,))
        return True
    except Exception:
        return False

# -------------------- UI --------------------
st.title("🥇 HK Podravka — Sustav")

page = st.sidebar.radio(
    "Navigacija",
    [
        "👤 Članovi",
        "📅 Prisustvo",
        "⚙️ Dijagnostika",
    ],
)

# -------------------- ČLANOVI --------------------
if page == "👤 Članovi":
    tab_add, tab_edit, tab_list, tab_import = st.tabs(
        ["➕ Dodaj člana", "🛠 Uredi/obriši", "📋 Popis & izvoz", "⬆️ Uvoz članova (Excel)"]
    )

    # -------- Dodaj člana --------
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

    # -------- Uredi / obriši --------
    with tab_edit:
        dfm = df_from_sql("SELECT * FROM members ORDER BY prezime, ime")
        if dfm.empty:
            st.info("Nema članova.")
        else:
            labels = dfm.apply(lambda r: f"{r['prezime']} {r['ime']} — {r.get('grupa_trening','')}", axis=1).tolist()
            idx = st.selectbox("Odaberi člana", list(range(len(labels))), format_func=lambda i: labels[i])
            r = dfm.iloc[idx]

            cols = st.columns([1,1])
            with cols[0]:
                # prikaz fotografije (ako postoji)
                fp = str(r.get("foto_path") or "").strip()
                if fp and os.path.isfile(fp):
                    st.image(fp, width=220, caption="Fotografija člana")
                else:
                    st.info("Nema fotografije za ovog člana.")

            with st.form("frm_member_edit"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    ime = st.text_input("Ime *", value=str(r["ime"] or ""))
                    prezime = st.text_input("Prezime *", value=str(r["prezime"] or ""))
                    # datum
                    try:
                        init_date = pd.to_datetime(r["datum_rodjenja"]).date() if r["datum_rodjenja"] else date(2010,1,1)
                    except Exception:
                        init_date = date(2010,1,1)
                    datum_rod = st.date_input("Datum rođenja", value=init_date)

                with c2:
                    val = pd.to_numeric(r.get("godina_rodjenja"), errors="coerce")
                    init_god = int(val) if pd.notna(val) else 2010
                    godina_rod = st.number_input("Godina rođenja", min_value=1900, max_value=2100, value=init_god, step=1)
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

            st.divider()
            # ----- Brisanje odabranog člana -----
            st.subheader("🗑️ Brisanje ovog člana")
            col_del_a, col_del_b, col_del_c = st.columns([1,1,2])
            with col_del_a:
                del_photo = st.checkbox("Obriši i fotografiju", value=True)
            with col_del_b:
                confirm_del = st.checkbox("Potvrđujem brisanje")
            with col_del_c:
                if st.button("🗑️ Obriši člana", disabled=not confirm_del, type="primary"):
                    ok = delete_member(int(r["id"]), delete_photo=del_photo)
                    if ok:
                        st.success(f"Član **{r['prezime']} {r['ime']}** obrisan.")
                        st.experimental_rerun()
                    else:
                        st.error("Brisanje nije uspjelo.")

    # -------- Popis & izvoz --------
    with tab_list:
        dfm = df_from_sql("""
            SELECT id, ime, prezime, grupa_trening, datum_rodjenja, godina_rodjenja,
                   email_sportas, email_roditelj, telefon_sportas, telefon_roditelj,
                   clanski_broj, oib, adresa, foto_path
            FROM members ORDER BY prezime, ime
        """)
        st.dataframe(dfm.drop(columns=["id"]), use_container_width=True)
        if not dfm.empty:
            # izvoz
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine="openpyxl") as writer:
                dfm.drop(columns=["id"]).to_excel(writer, index=False, sheet_name="Clanovi")
            st.download_button(
                "⬇️ Izvezi članove u Excel",
                data=out.getvalue(),
                file_name="clanovi.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            # grupno brisanje
            st.markdown("### 🗑️ Grupno brisanje")
            id_to_label = {
                int(row["id"]): f"{row['prezime']} {row['ime']} ({row.get('grupa_trening','')})"
                for _, row in dfm.iterrows()
            }
            selected_ids = st.multiselect(
                "Odaberi članove",
                options=list(id_to_label.keys()),
                format_func=lambda mid: id_to_label.get(mid, str(mid))
            )
            del_photo_multi = st.checkbox("Obriši i fotografije odabranih", value=True)
            confirm_multi = st.checkbox("Potvrđujem grupno brisanje")
            if st.button("🗑️ Obriši odabrane", disabled=not (selected_ids and confirm_multi), type="primary"):
                n_ok = 0
                for mid in selected_ids:
                    if delete_member(int(mid), delete_photo=del_photo_multi):
                        n_ok += 1
                st.success(f"Obrisano članova: **{n_ok}**")
                st.experimental_rerun()

    # -------- Uvoz članova (Excel) --------
    with tab_import:
        st.caption(
            "Očekivana zaglavlja: Ime, Prezime, Datum rođenja, Godina rođenja, "
            "E-mail sportaša, E-mail roditelja, Kontakt sportaša, Kontakt roditelja, "
            "Članski broj, OIB, Adresa prebivališta, Grupa treninga"
        )
        up = st.file_uploader("Excel (.xlsx)", type=["xlsx"])
        if up:
            xls = pd.ExcelFile(io.BytesIO(up.getvalue()))
            sheet = st.selectbox("Sheet", xls.sheet_names)
            df = xls.parse(sheet)
            st.dataframe(df.head(20), use_container_width=True)

            # tolerantni mapping naziva
            def find_col(df, target_names):
                cols = list(df.columns)
                norm = {i: str(c).strip().lower() for i, c in enumerate(cols)}
                # točno
                for t in target_names:
                    tnorm = str(t).strip().lower()
                    for i, c in norm.items():
                        if c == tnorm:
                            return cols[i]
                # djelomično
                for t in target_names:
                    tnorm = str(t).strip().lower()
                    for i, c in norm.items():
                        if tnorm in c:
                            return cols[i]
                return None

            want = {
                "Ime": ["ime"],
                "Prezime": ["prezime"],
                "Datum rođenja": ["datum rođenja", "datum rodjenja", "datum"],
                "Godina rođenja": ["godina rođenja", "godina rodjenja", "godina"],
                "E-mail sportaša": ["e-mail sportaša", "email sportaša", "email sportas", "email"],
                "E-mail roditelja": ["e-mail roditelja", "email roditelja"],
                "Kontakt sportaša": ["kontakt sportaša", "telefon sportaša", "telefon"],
                "Kontakt roditelja": ["kontakt roditelja", "telefon roditelja", "telefon"],
                "Članski broj": ["članski broj", "clanski broj"],
                "OIB": ["oib"],
                "Adresa prebivališta": ["adresa", "adresa prebivališta"],
                "Grupa treninga": ["grupa treninga", "grupa"],
                # podrži i "Ime i prezime"
                "ImePrezime": ["ime i prezime", "prezime i ime", "ime prezime", "prezime ime"],
            }

            mapping = {k: find_col(df, v) for k, v in want.items()}

            # Ako postoji "Ime i prezime" a nema odvojenih - razdvoji ("Prezime Ime" -> Ime, Prezime)
            if (mapping.get("Ime") is None or mapping.get("Prezime") is None) and mapping.get("ImePrezime"):
                col_full = mapping["ImePrezime"]
                def split_name(s):
                    s = str(s).strip() if pd.notna(s) else ""
                    if not s: return "", ""
                    parts = s.split()
                    if len(parts) >= 2:
                        prez = parts[0]; ime = " ".join(parts[1:])
                        return ime, prez
                    return s, ""
                df["_Ime"], df["_Prezime"] = zip(*df[col_full].map(split_name))
                mapping["Ime"] = "_Ime"
                mapping["Prezime"] = "_Prezime"

            required = ["Ime","Prezime"]
            miss = [k for k in required if mapping.get(k) is None]
            if miss:
                st.error("Nedostaju obavezne kolone: " + ", ".join(miss))
            else:
                if st.button("🚀 Uvezi članove iz Excela"):
                    rows = []
                    for _, rr in df.iterrows():
                        def val(key, default=""):
                            col = mapping.get(key)
                            if col is None: return default
                            v = rr[col]
                            return str(v) if pd.notna(v) else default

                        # datum
                        dat = ""
                        if mapping.get("Datum rođenja"):
                            v = rr[mapping["Datum rođenja"]]
                            if pd.notna(v):
                                dat = pd.to_datetime(v, dayfirst=True, errors="coerce")
                                dat = dat.date().isoformat() if pd.notna(dat) else ""

                        # godina
                        god = None
                        if mapping.get("Godina rođenja"):
                            god = pd.to_numeric(rr[mapping["Godina rođenja"]], errors="coerce")
                            god = int(god) if pd.notna(god) else None

                        rows.append((
                            val("Ime"), val("Prezime"), dat, god,
                            val("E-mail sportaša"), val("E-mail roditelja"),
                            val("Kontakt sportaša"), val("Kontakt roditelja"),
                            val("Članski broj"), val("OIB"),
                            val("Adresa prebivališta"), val("Grupa treninga"),
                            None  # foto_path
                        ))

                    if rows:
                        exec_many("""
                            INSERT INTO members
                            (ime, prezime, datum_rodjenja, godina_rodjenja, email_sportas, email_roditelj,
                             telefon_sportas, telefon_roditelj, clanski_broj, oib, adresa, grupa_trening, foto_path)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, rows)
                    st.success(f"Uvezeno članova: {len(rows)}")

# -------------------- PRISUSTVO (osnovno) --------------------
elif page == "📅 Prisustvo":
    st.subheader("📅 Evidencija prisustva (osnovno)")

    # izbor datuma, termina, grupe
    d = st.date_input("Datum", value=date.today())
    termin = st.selectbox("Termin", ["18:30-20:00", "20:00-22:00", "Upiši ručno…"])
    if termin == "Upiši ručno…":
        termin = st.text_input("Termin (npr. 09:00-10:30)")

    # grupe iz baze
    df_groups = df_from_sql("SELECT DISTINCT grupa_trening FROM members WHERE grupa_trening IS NOT NULL AND grupa_trening<>'' ORDER BY 1")
    grupe = df_groups["grupa_trening"].dropna().astype(str).tolist()
    grupa = st.selectbox("Grupa", ["(sve)"] + grupe)
    # popis članova
    if grupa == "(sve)":
        dfm = df_from_sql("SELECT id, ime, prezime, grupa_trening FROM members ORDER BY prezime, ime")
    else:
        dfm = df_from_sql("SELECT id, ime, prezime, grupa_trening FROM members WHERE grupa_trening=? ORDER BY prezime, ime", (grupa,))

    if dfm.empty:
        st.info("Nema članova u odabranoj grupi.")
    else:
        ids = dfm["id"].tolist()
        labels = dfm.apply(lambda r: f"{r['prezime']} {r['ime']} ({r.get('grupa_trening','')})", axis=1).tolist()
        checked = st.multiselect("Označi prisutne", options=ids, format_func=lambda mid: labels[ids.index(mid)])

        trajanje = st.number_input("Trajanje treninga (minute)", min_value=30, max_value=180, value=90, step=5)

        if st.button("💾 Spremi prisustvo"):
            rows = [(int(mid), str(d), termin.strip(), grupa if grupa != "(sve)" else "", 1, int(trajanje)) for mid in checked]
            if rows:
                exec_many("""
                    INSERT INTO attendance (member_id, datum, termin, grupa, prisutan, trajanje_min)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, rows)
            st.success(f"Spremljeno prisutnih: {len(rows)}")

    st.divider()
    st.subheader("📈 Brzi pregled")
    q = """
        SELECT a.datum, a.termin, m.prezime || ' ' || m.ime AS clan, COALESCE(a.grupa, m.grupa_trening) AS grupa, a.trajanje_min
        FROM attendance a JOIN members m ON m.id=a.member_id
        ORDER BY a.datum DESC, clan
        LIMIT 200
    """
    dfa = df_from_sql(q)
    st.dataframe(dfa, use_container_width=True)

# -------------------- DIJAGNOSTIKA --------------------
else:
    st.subheader("⚙️ Dijagnostika")
    st.write("🗃️ Put do baze:", os.path.abspath(DB_PATH))
    st.write("📁 Upload root:", os.path.abspath(UPLOAD_ROOT))
    st.write("📁 Fotke članova:", os.path.abspath(MEMBER_PHOTOS_DIR))

    # popis tablica
    conn = get_conn()
    tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name", conn)
    conn.close()
    st.write("Tablice u bazi:", tables)

    if st.button("🔧 Inicijaliziraj/kreiraj bazu (ponovno)"):
        init_db()
        st.success("Baza inicijalizirana.")

