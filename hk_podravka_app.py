
# -*- coding: utf-8 -*-
"""
HK Podravka – klupska web-admin aplikacija (Streamlit, 1-file .py)
Autor: ChatGPT (GPT-5 Thinking)

▶ Pokretanje lokalno:
    pip install -r requirements.txt
    streamlit run hk_podravka_app.py

Napomena:
- Aplikacija je responzivna (Streamlit) i prilagođena za korištenje na mobitelima.
- Boje kluba: crvena, bijela, zlatna.
"""

import os
import io
import base64
import sqlite3
from datetime import datetime, date, timedelta
from typing import Optional, List

import pandas as pd
import streamlit as st

# ==========================
# KONSTANTE KLUBA I STIL
# ==========================
PRIMARY_RED = "#c1121f"   # klupska crvena
GOLD        = "#d4af37"   # zlatna
WHITE       = "#ffffff"
LIGHT_BG    = "#fffaf8"

KLUB_NAZIV  = "Hrvački klub Podravka"
KLUB_EMAIL  = "hsk-podravka@gmail.com"
KLUB_ADRESA = "Miklinovec 6a, 48000 Koprivnica"
KLUB_OIB    = "60911784858"
KLUB_WEB    = "https://hk-podravka.com"
KLUB_IBAN   = "HR6923860021100518154"

DB_PATH     = "hk_podravka.db"
UPLOAD_DIR  = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ==========================
# POMOĆNE FUNKCIJE
# ==========================
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # Osnovni podaci o klubu
    cur.execute("""
        CREATE TABLE IF NOT EXISTS club_info (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT, street TEXT, city_zip TEXT,
            email TEXT, address TEXT, oib TEXT, web TEXT, iban TEXT,
            president TEXT, secretary TEXT,
            instagram TEXT, facebook TEXT, tiktok TEXT,
            created_at TEXT, updated_at TEXT
        )
    """)

    # Članovi tijela (predsjedništvo & nadzorni)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS board_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT CHECK(kind IN ('board','supervisory')),
            full_name TEXT, phone TEXT, email TEXT
        )
    """)

    # Dokumenti kluba
    cur.execute("""
        CREATE TABLE IF NOT EXISTS club_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT,             -- npr. 'statut', 'pravilnik', 'ostalo'
            filename TEXT,
            path TEXT,
            uploaded_at TEXT
        )
    """)

    # Grupe
    cur.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
    """)

    # Članovi
    cur.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT,
            dob TEXT,
            gender TEXT CHECK (gender IN ('M','Ž','')),
            oib TEXT,
            residence TEXT,
            athlete_email TEXT,
            parent_email TEXT,
            id_card_number TEXT, id_card_issuer TEXT, id_card_valid_until TEXT,
            passport_number TEXT, passport_issuer TEXT, passport_valid_until TEXT,
            active_competitor INTEGER DEFAULT 0,
            veteran INTEGER DEFAULT 0,
            other_flag INTEGER DEFAULT 0,
            membership_fee_eur REAL DEFAULT 0,
            group_id INTEGER,
            photo_path TEXT,
            consent_path TEXT,       -- pristupnica/privola
            application_path TEXT,   -- dodatni dokument
            medical_path TEXT,
            medical_valid_until TEXT,
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE SET NULL
        )
    """)

    # Treneri
    cur.execute("""
        CREATE TABLE IF NOT EXISTS coaches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT,
            dob TEXT,
            oib TEXT,
            email TEXT,
            iban TEXT,
            photo_path TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS coach_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coach_id INTEGER,
            kind TEXT, filename TEXT, path TEXT, uploaded_at TEXT,
            FOREIGN KEY(coach_id) REFERENCES coaches(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS coach_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coach_id INTEGER,
            group_id INTEGER,
            assigned_at TEXT,
            FOREIGN KEY(coach_id) REFERENCES coaches(id) ON DELETE CASCADE,
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
    """)

    # Natjecanja
    cur.execute("""
        CREATE TABLE IF NOT EXISTS competitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT,          -- kategorija natjecanja
            custom_kind TEXT,   -- ako je "ostalo"
            name TEXT,          -- ime natjecanja
            date_from TEXT,
            date_to TEXT,
            place TEXT,
            style TEXT,         -- GR, FS, WW, BW, MODIFICIRANO
            age_group TEXT,     -- POČETNICI, U11, U13, U15, U17, U20, U23, SENIORI
            country TEXT,       -- puna država
            country_code TEXT,  -- ISO3
            team_rank TEXT,
            club_competitors INTEGER,     -- broj nastupajućih iz kluba
            total_competitors INTEGER,    -- ukupan broj natjecatelja
            total_clubs INTEGER,
            total_countries INTEGER,
            coaches_text TEXT,
            notes TEXT,         -- zapažanja trenera (za objave)
            bulletin_link TEXT,
            results_link TEXT,
            gallery_link TEXT
        )
    """)

    # Rezultati natjecanja po sportašu
    cur.execute("""
        CREATE TABLE IF NOT EXISTS competition_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competition_id INTEGER,
            member_id INTEGER,
            weight_category TEXT,
            style TEXT,
            bouts_total INTEGER,
            wins INTEGER,
            losses INTEGER,
            placement INTEGER,
            opponent_list TEXT,    -- JSON: [{name,club,win/lose}...]
            notes TEXT,
            FOREIGN KEY(competition_id) REFERENCES competitions(id) ON DELETE CASCADE,
            FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE SET NULL
        )
    """)

    # Slike s natjecanja (više datoteka)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS competition_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competition_id INTEGER,
            filename TEXT, path TEXT, uploaded_at TEXT,
            FOREIGN KEY(competition_id) REFERENCES competitions(id) ON DELETE CASCADE
        )
    """)

    # Prisustvo: treneri (sesije) i članovi (dolazak)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coach_id INTEGER,
            group_id INTEGER,
            start_ts TEXT,
            end_ts TEXT,
            location TEXT,
            remark TEXT,
            FOREIGN KEY(coach_id) REFERENCES coaches(id) ON DELETE SET NULL,
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE SET NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            member_id INTEGER,
            present INTEGER DEFAULT 1,
            minutes INTEGER DEFAULT 0,
            FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE
        )
    """)

    # Zadani zapis o klubu
    cur.execute("SELECT COUNT(*) FROM club_info WHERE id=1")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO club_info(id,name,street,city_zip,email,address,oib,web,iban,
                                  president,secretary,instagram,facebook,tiktok,created_at,updated_at)
            VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (KLUB_NAZIV, "Miklinovec 6a", "48000 Koprivnica",
              KLUB_EMAIL, KLUB_ADRESA, KLUB_OIB, KLUB_WEB, KLUB_IBAN,
              "", "", "", "", "", datetime.now().isoformat(), datetime.now().isoformat()))
    conn.commit()
    conn.close()


def css_style():
    st.markdown(f"""
        <style>
        :root {{
            --hk-red: {PRIMARY_RED};
            --hk-gold:{GOLD};
            --hk-white:{WHITE};
        }}
        .hk-header {{
            background: linear-gradient(90deg, var(--hk-red), #9b0d17);
            color: white;
            padding: 12px 16px;
            border-radius: 12px;
        }}
        .hk-pill {{
            background: {GOLD}22;
            border: 1px solid {GOLD}66;
            color: #333;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 12px;
        }}
        .stButton>button {{
            background-color: {PRIMARY_RED};
            color: white;
            border-radius: 10px;
            border: 0;
        }}
        .stDownloadButton>button {{
            border: 1px solid {GOLD};
            border-radius: 10px;
        }}
        .hk-danger {{
            background: #ffefef;
            border-left: 4px solid #d11;
            padding: 8px 12px;
            border-radius: 8px;
        }}
        </style>
    """, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = ""):
    st.markdown(f"<div class='hk-header'><h3 style='margin:0'>{title}</h3>"
                f"<div>{subtitle}</div></div>", unsafe_allow_html=True)


def save_upload(file, subdir: str) -> str:
    """Spremi upload u uploads/subdir i vrati relativnu putanju."""
    if not file:
        return ""
    sd = os.path.join(UPLOAD_DIR, subdir)
    os.makedirs(sd, exist_ok=True)
    path = os.path.join(sd, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.name}")
    with open(path, "wb") as f:
        f.write(file.getbuffer())
    return path


def excel_bytes_from_df(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()


def members_template_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "ime_prezime":"", "datum_rođenja":"", "spol(M/Ž)":"",
        "oib":"", "mjesto_prebivališta":"",
        "email_sportaša":"", "email_roditelja":"",
        "osobna_broj":"", "osobna_izdavatelj":"", "osobna_vrijedi_do":"",
        "putovnica_broj":"", "putovnica_izdavatelj":"", "putovnica_vrijedi_do":"",
        "aktivni_natjecatelj(0/1)":"", "veteran(0/1)":"", "ostalo(0/1)":"",
        "članarina_EUR":"30", "grupa":"", "napomena":""
    }])


def comp_results_template_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "natjecanje_id":"", "clan(ime_prezime)":"",
        "kategorija":"", "stil":"", "ukupno_borbi":"",
        "pobjede":"", "porazi":"", "plasman(1-100)":"",
        "protivnici(JSON)":"[{'name':'Ime Prezime','club':'Klub','result':'win/lose'}]",
        "napomena":""
    }])


# ==========================
# ODJELJAK: KLUB
# ==========================
def section_club():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM club_info WHERE id=1", conn)

    page_header("Osnovni podaci o klubu",
                "Postavite podatke kluba, tijela upravljanja i dokumente.")
    st.caption("Logo i boje: crvena • bijela • zlatna")

    with st.container():
        c1, c2 = st.columns(2)
        with c1:
            st.image("https://hk-podravka.com/wp-content/uploads/2021/08/cropped-HK-Podravka-logo.png",
                     caption=KLUB_NAZIV, use_column_width=True)
            logo_upload = st.file_uploader("Učitaj vlastiti logo (opcionalno)", type=["png","jpg","jpeg"])
            logo_path = save_upload(logo_upload, "logo") if logo_upload else ""

        with c2:
            st.markdown("**Društvene mreže**")
            instagram = st.text_input("Instagram URL", df.loc[0, "instagram"] if "instagram" in df.columns else "")
            facebook  = st.text_input("Facebook URL",  df.loc[0, "facebook"] if "facebook" in df.columns else "")
            tiktok    = st.text_input("TikTok URL",    df.loc[0, "tiktok"] if "tiktok" in df.columns else "")

    with st.form("club_form"):
        st.subheader("Osnovni podaci")
        a1, a2 = st.columns(2)
        name = a1.text_input("KLUB (IME)", df.loc[0, "name"] if "name" in df.columns else KLUB_NAZIV)
        street = a1.text_input("Ulica i kućni broj", df.loc[0, "street"] if "street" in df.columns else "Miklinovec 6a")
        city_zip = a1.text_input("Grad i poštanski broj", df.loc[0, "city_zip"] if "city_zip" in df.columns else "48000 Koprivnica")
        email = a2.text_input("E-mail", df.loc[0, "email"] if "email" in df.columns else KLUB_EMAIL)
        web = a2.text_input("Web stranica", df.loc[0, "web"] if "web" in df.columns else KLUB_WEB)
        iban = a2.text_input("IBAN račun", df.loc[0, "iban"] if "iban" in df.columns else KLUB_IBAN)
        oib = a2.text_input("OIB", df.loc[0, "oib"] if "oib" in df.columns else KLUB_OIB)

        st.subheader("Tijela upravljanja")
        president = st.text_input("Predsjednik kluba", df.loc[0, "president"] if "president" in df.columns else "")
        secretary = st.text_input("Tajnik kluba", df.loc[0, "secretary"] if "secretary" in df.columns else "")

        st.markdown("**Članovi predsjedništva**")
        board_df = st.experimental_data_editor(pd.DataFrame(columns=["ime_prezime","telefon","email"]), num_rows=1)
        st.markdown("**Nadzorni odbor**")
        superv_df = st.experimental_data_editor(pd.DataFrame(columns=["ime_prezime","telefon","email"]), num_rows=1)

        st.subheader("Dokumenti kluba")
        d1, d2, d3 = st.columns(3)
        statut = d1.file_uploader("Statut", type=["pdf","doc","docx"])
        pravilnik = d2.file_uploader("Pravilnik/Opći akt", type=["pdf","doc","docx"])
        doc_ostalo = d3.file_uploader("Ostali dokument", type=["pdf","doc","docx","png","jpg","jpeg"])

        submitted = st.form_submit_button("Spremi podatke kluba")

    if submitted:
        now = datetime.now().isoformat()
        conn.execute("""UPDATE club_info SET
                        name=?, street=?, city_zip=?, email=?, address=?, oib=?, web=?, iban=?,
                        president=?, secretary=?, instagram=?, facebook=?, tiktok=?, updated_at=?
                        WHERE id=1""",
                     (name, street, city_zip, email, f"{street}, {city_zip}", oib, web, iban,
                      president, secretary, instagram, facebook, tiktok, now))
        # Pohrana članova tijela (jednostavno: najprije obriši pa ubaci unesene)
        conn.execute("DELETE FROM board_members WHERE kind='board'")
        conn.execute("DELETE FROM board_members WHERE kind='supervisory'")
        for _, r in board_df.dropna(how="all").iterrows():
            conn.execute("INSERT INTO board_members(kind,full_name,phone,email) VALUES (?,?,?,?)",
                         ("board", r.get("ime_prezime",""), r.get("telefon",""), r.get("email","")))
        for _, r in superv_df.dropna(how="all").iterrows():
            conn.execute("INSERT INTO board_members(kind,full_name,phone,email) VALUES (?,?,?,?)",
                         ("supervisory", r.get("ime_prezime",""), r.get("telefon",""), r.get("email","")))

        # Dokumenti
        for label, f in [("statut", statut), ("pravilnik", pravilnik), ("ostalo", doc_ostalo)]:
            if f:
                p = save_upload(f, "club_docs")
                conn.execute("INSERT INTO club_docs(kind,filename,path,uploaded_at) VALUES (?,?,?,?)",
                             (label, f.name, p, now))
        conn.commit()
        st.success("Podaci kluba spremljeni.")

    # Pregled dokumenata
    doc_df = pd.read_sql_query("SELECT id, kind AS vrsta, filename AS datoteka, uploaded_at AS datum FROM club_docs ORDER BY id DESC", conn)
    st.dataframe(doc_df, use_container_width=True)
    conn.close()


# ==========================
# ODJELJAK: ČLANOVI
# ==========================
def section_members():
    page_header("Članovi", "Uvoz/izvoz, osobni podaci, dokumenti i liječničke potvrde")

    st.download_button("Skini predložak članova (Excel)",
                       data=excel_bytes_from_df(members_template_df(), "ClanoviPredlozak"),
                       file_name="clanovi_predlozak.xlsx")

    st.download_button("Skini predložak rezultata (Excel)",
                       data=excel_bytes_from_df(comp_results_template_df(), "RezultatiPredlozak"),
                       file_name="rezultati_predlozak.xlsx")

    conn = get_conn()

    # Upload članova iz Excela
    upl = st.file_uploader("Učitaj članove iz Excel tablice (po predlošku)", type=["xlsx"])
    if upl:
        try:
            df = pd.read_excel(upl)
            for _, r in df.fillna("").iterrows():
                # pokušaj mapiranja grupe
                gid = None
                if r.get("grupa",""):
                    g = conn.execute("SELECT id FROM groups WHERE name=?", (r["grupa"],)).fetchone()
                    if g: gid = g[0]
                conn.execute("""INSERT INTO members
                    (full_name,dob,gender,oib,residence,athlete_email,parent_email,
                     id_card_number,id_card_issuer,id_card_valid_until,
                     passport_number,passport_issuer,passport_valid_until,
                     active_competitor,veteran,other_flag,membership_fee_eur,group_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get("ime_prezime",""), r.get("datum_rođenja",""), r.get("spol(M/Ž)",""),
                     r.get("oib",""), r.get("mjesto_prebivališta",""), r.get("email_sportaša",""),
                     r.get("email_roditelja",""), r.get("osobna_broj",""), r.get("osobna_izdavatelj",""),
                     r.get("osobna_vrijedi_do",""), r.get("putovnica_broj",""), r.get("putovnica_izdavatelj",""),
                     r.get("putovnica_vrijedi_do",""),
                     int(r.get("aktivni_natjecatelj(0/1)",0) or 0),
                     int(r.get("veteran(0/1)",0) or 0),
                     int(r.get("ostalo(0/1)",0) or 0),
                     float(r.get("članarina_EUR", 0) or 0), gid))
            conn.commit()
            st.success("Članovi su uvezeni.")
        except Exception as e:
            st.error(f"Greška pri uvozu: {e}")

    st.markdown("---")
    st.subheader("Upis novog člana")
    with st.form("new_member"):
        c1, c2 = st.columns(2)
        full_name = c1.text_input("Ime i prezime")
        dob = c1.date_input("Datum rođenja", value=None)
        gender = c1.selectbox("Spol", ["", "M", "Ž"])
        oib = c1.text_input("OIB")
        residence = c1.text_input("Mjesto prebivališta")

        athlete_email = c2.text_input("E-mail sportaša")
        parent_email  = c2.text_input("E-mail roditelja")

        st.markdown("**Osobna iskaznica**")
        id_card_number = st.text_input("Broj osobne iskaznice")
        id_card_issuer = st.text_input("Izdavatelj osobne")
        id_card_valid_until = st.date_input("Vrijedi do (osobna)", value=None)

        st.markdown("**Putovnica**")
        passport_number = st.text_input("Broj putovnice")
        passport_issuer = st.text_input("Izdavatelj putovnice")
        passport_valid_until = st.date_input("Vrijedi do (putovnica)", value=None)

        st.markdown("**Status**")
        colA, colB, colC = st.columns(3)
        active_competitor = colA.checkbox("Aktivni natjecatelj/ica", value=False)
        veteran = colB.checkbox("Veteran", value=False)
        other_flag = colC.checkbox("Ostalo", value=False)

        fee_default = 30.0 if active_competitor else 0.0
        fee = st.number_input("Članarina (EUR)", min_value=0.0, value=float(fee_default), step=5.0)

        # Slika člana
        photo = st.file_uploader("Slika člana (jpg/png)", type=["png","jpg","jpeg"])

        # Grupa
        groups = [r[0] for r in conn.execute("SELECT name FROM groups ORDER BY name").fetchall()]
        group_name = st.selectbox("Grupa", [""] + groups)

        # Dokumenti: privola/pristupnica i liječničko
        consent = st.file_uploader("Privola / Pristupnica (pdf/jpg/png)", type=["pdf","jpg","jpeg","png"])
        application = st.file_uploader("Dodatna pristupnica ili dokument", type=["pdf","jpg","jpeg","png"])
        medical = st.file_uploader("Liječnička potvrda (pdf/jpg/png)", type=["pdf","jpg","jpeg","png"])
        medical_valid = st.date_input("Liječnička vrijedi do", value=None, help="Obavezno upišite datum isteka potvrde.")

        submit_member = st.form_submit_button("Spremi člana")

    if submit_member:
        gid = None
        if group_name:
            r = conn.execute("SELECT id FROM groups WHERE name=?", (group_name,)).fetchone()
            if r: gid = r[0]
        now = datetime.now().isoformat()
        photo_p = save_upload(photo, "members/photos")
        consent_p = save_upload(consent, "members/consent")
        application_p = save_upload(application, "members/application")
        medical_p = save_upload(medical, "members/medical")

        conn.execute("""INSERT INTO members
            (full_name,dob,gender,oib,residence,athlete_email,parent_email,
             id_card_number,id_card_issuer,id_card_valid_until,
             passport_number,passport_issuer,passport_valid_until,
             active_competitor,veteran,other_flag,membership_fee_eur,
             group_id,photo_path,consent_path,application_path,medical_path,medical_valid_until)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (full_name, str(dob) if dob else "", gender, oib, residence, athlete_email, parent_email,
             id_card_number, id_card_issuer, str(id_card_valid_until) if id_card_valid_until else "",
             passport_number, passport_issuer, str(passport_valid_until) if passport_valid_until else "",
             int(active_competitor), int(veteran), int(other_flag), float(fee),
             gid, photo_p, consent_p, application_p, medical_p, str(medical_valid) if medical_valid else ""))
        conn.commit()
        st.success("Član je spremljen.")

    # Popis članova + oznaka isteka liječničke
    st.markdown("---")
    st.subheader("Popis članova")
    mdf = pd.read_sql_query("""
        SELECT m.id, m.full_name AS ime_prezime, m.dob, m.gender AS spol, m.oib, m.residence AS prebivalište,
               m.athlete_email, m.parent_email, m.active_competitor AS aktivni, m.veteran,
               m.membership_fee_eur AS članarina, m.medical_valid_until AS liječnička_do,
               g.name AS grupa
        FROM members m LEFT JOIN groups g ON m.group_id=g.id
        ORDER BY m.full_name
    """, conn)
    st.dataframe(mdf, use_container_width=True)

    # Upozorenja o liječničkoj potvrdi
    if not mdf.empty:
        today = date.today()
        warn_ids = []
        for _, row in mdf.iterrows():
            if row["liječnička_do"]:
                try:
                    exp = datetime.fromisoformat(row["liječnička_do"]).date()
                except Exception:
                    try:
                        exp = datetime.strptime(row["liječnička_do"], "%Y-%m-%d").date()
                    except Exception:
                        continue
                days = (exp - today).days
                if days <= 14:
                    warn_ids.append((row["ime_prezime"], days))
        if warn_ids:
            st.markdown("<div class='hk-danger'><b>Upozorenje:</b> Slijedećim članovima istječe liječnička u roku 14 dana:</div>", unsafe_allow_html=True)
            for nm, d in warn_ids:
                st.write(f"- {nm}: {d} dana")

    conn.close()


# ==========================
# ODJELJAK: TRENERI
# ==========================
def section_coaches():
    page_header("Treneri", "Upis trenera, ugovori i dokumenti")

    conn = get_conn()
    with st.form("coach_form"):
        c1, c2 = st.columns(2)
        full_name = c1.text_input("Ime i prezime")
        dob = c1.date_input("Datum rođenja", value=None)
        oib = c1.text_input("OIB")
        email = c2.text_input("E-mail")
        iban = c2.text_input("IBAN račun")
        photo = st.file_uploader("Slika (jpg/png)", type=["jpg","jpeg","png"])
        submit = st.form_submit_button("Spremi trenera")

    if submit:
        photo_p = save_upload(photo, "coaches/photos")
        conn.execute("""INSERT INTO coaches (full_name,dob,oib,email,iban,photo_path)
                        VALUES (?,?,?,?,?,?)""",
                     (full_name, str(dob) if dob else "", oib, email, iban, photo_p))
        conn.commit()
        st.success("Trener spremljen.")

    # Povezivanje s grupama
    st.subheader("Dodjela trenera u grupe")
    coaches = conn.execute("SELECT id, full_name FROM coaches").fetchall()
    groups = conn.execute("SELECT id, name FROM groups").fetchall()
    if coaches and groups:
        cc = st.selectbox("Trener", [f"{c[0]} – {c[1]}" for c in coaches])
        gg = st.selectbox("Grupa", [f"{g[0]} – {g[1]}" for g in groups])
        if st.button("Dodijeli"):
            cid = int(cc.split(" – ")[0]); gid = int(gg.split(" – ")[0])
            conn.execute("INSERT INTO coach_groups (coach_id,group_id,assigned_at) VALUES (?,?,?)",
                         (cid, gid, datetime.now().isoformat()))
            conn.commit()
            st.success("Dodano.")
    else:
        st.info("Najprije unesite trenere i grupe.")

    # Ugovori/dokumenti
    st.subheader("Učitavanje ugovora i drugih dokumenata")
    if coaches:
        csel = st.selectbox("Trener (dokumenti)", [f"{c[0]} – {c[1]}" for c in coaches], key="docs_coach")
        doc1 = st.file_uploader("Ugovor (pdf/doc)", type=["pdf","doc","docx"], key="c_doc1")
        doc2 = st.file_uploader("Drugi dokument", type=["pdf","doc","docx","jpg","jpeg","png"], key="c_doc2")
        if st.button("Spremi dokumente"):
            cid = int(csel.split(" – ")[0])
            for f, k in [(doc1, "ugovor"), (doc2, "ostalo")]:
                if f:
                    p = save_upload(f, "coaches/docs")
                    conn.execute("INSERT INTO coach_docs (coach_id,kind,filename,path,uploaded_at) VALUES (?,?,?,?,?)",
                                 (cid, k, f.name, p, datetime.now().isoformat()))
            conn.commit()
            st.success("Dokumenti spremljeni.")

    # Popis trenera
    tdf = pd.read_sql_query("SELECT id, full_name AS ime_prezime, dob, email, iban FROM coaches", conn)
    st.dataframe(tdf, use_container_width=True)
    conn.close()


# ==========================
# ODJELJAK: NATJECANJA I REZULTATI
# ==========================
def section_competitions():
    page_header("Natjecanja i rezultati", "Unos natjecanja, slike, rezultati po članovima")

    # Definirane opcije
    KINDS = [
        "PRVENSTVO HRVATSKE","MEĐUNARODNI TURNIR","REPREZENTATIVNI NASTUP",
        "HRVAČKA LIGA ZA SENIORE","MEĐUNARODNA HRVAČKA LIGA ZA KADETE",
        "REGIONALNO PRVENSTVO","LIGA ZA DJEVOJČICE","OSTALO"
    ]
    REP_SUB = ["PRVENSTVO EUROPE","PRVENSTVO SVIJETA","PRVENSTVO BALKANA","UWW TURNIR"]
    STYLES = ["GR","FS","WW","BW","MODIFICIRANO"]
    AGES = ["POČETNICI","U11","U13","U15","U17","U20","U23","SENIORI"]

    conn = get_conn()

    with st.form("comp_form"):
        kind = st.selectbox("Vrsta natjecanja", KINDS)
        rep_sub = st.selectbox("Podvrsta reprezentativnog nastupa", REP_SUB, disabled=(kind!="REPREZENTATIVNI NASTUP"))
        custom_kind = st.text_input("Upiši vrstu (ako 'OSTALO')", disabled=(kind!="OSTALO"))
        name = st.text_input("Ime natjecanja (ako postoji naziv)")
        c1, c2 = st.columns(2)
        date_from = c1.date_input("Datum od", value=date.today())
        date_to = c2.date_input("Datum do (ako 1 dan, ostavi isti)",
                                value=date.today())
        place = st.text_input("Mjesto")
        style = st.selectbox("Hrvački stil", STYLES)
        age_group = st.selectbox("Uzrast", AGES)
        country = st.text_input("Država (puni naziv)")
        country_code = st.text_input("ISO3 kratica države (npr. HRV)")
        c3, c4, c5 = st.columns(3)
        team_rank = c3.text_input("Ekipni poredak (npr. 1., 5., 10.)")
        club_competitors = c4.number_input("Broj naših natjecatelja", min_value=0, step=1)
        total_competitors = c5.number_input("Ukupan broj natjecatelja", min_value=0, step=1)
        c6, c7 = st.columns(2)
        total_clubs = c6.number_input("Broj klubova", min_value=0, step=1)
        total_countries = c7.number_input("Broj zemalja", min_value=0, step=1)

        # Treneri koji su vodili
        coach_text = st.text_input("Trener(i) (odvoji zarezima)")

        # Linkovi i bilješke
        notes = st.text_area("Zapažanje trenera (za objave)")
        bulletin_link = st.text_input("Link na bilten/rezultate")
        results_link = st.text_input("Link na službene rezultate")
        gallery_link = st.text_input("Link na objavu na webu (galerija)")

        # Slike
        photos = st.file_uploader("Slike s natjecanja (više datoteka)", type=["jpg","jpeg","png"], accept_multiple_files=True)

        submit = st.form_submit_button("Spremi natjecanje")

    if submit:
        conn.execute("""INSERT INTO competitions
            (kind,custom_kind,name,date_from,date_to,place,style,age_group,country,country_code,
             team_rank,club_competitors,total_competitors,total_clubs,total_countries,
             coaches_text,notes,bulletin_link,results_link,gallery_link)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (kind, rep_sub if kind=="REPREZENTATIVNI NASTUP" else custom_kind, name,
             str(date_from), str(date_to), place, style, age_group, country, country_code,
             team_rank, int(club_competitors), int(total_competitors), int(total_clubs), int(total_countries),
             coach_text, notes, bulletin_link, results_link, gallery_link))
        comp_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for ph in photos or []:
            p = save_upload(ph, "competitions/photos")
            conn.execute("INSERT INTO competition_photos (competition_id,filename,path,uploaded_at) VALUES (?,?,?,?)",
                         (comp_id, ph.name, p, datetime.now().isoformat()))
        conn.commit()
        st.success("Natjecanje spremljeno.")

    # Dodavanje rezultata po sportašu
    st.markdown("---")
    st.subheader("Rezultati sportaša")
    comps = conn.execute("SELECT id, name, date_from FROM competitions ORDER BY date_from DESC").fetchall()
    members = conn.execute("SELECT id, full_name FROM members ORDER BY full_name").fetchall()
    if comps and members:
        comp_sel = st.selectbox("Natjecanje", [f"{c[0]} – {c[1]} ({c[2]})" for c in comps])
        mem_sel = st.multiselect("Odaberi sportaše (iz baze)", [f"{m[0]} – {m[1]}" for m in members])
        with st.form("add_results"):
            for idx, ms in enumerate(mem_sel):
                st.markdown(f"**#{idx+1} – {ms}**")
                weight = st.text_input("Kategorija", key=f"k_{idx}")
                style2 = st.selectbox("Stil", STYLES, key=f"s_{idx}")
                bouts_total = st.number_input("Ukupno borbi", min_value=0, step=1, key=f"bt_{idx}")
                wins = st.number_input("Pobjede", min_value=0, step=1, key=f"w_{idx}")
                losses = st.number_input("Porazi", min_value=0, step=1, key=f"l_{idx}")
                placement = st.number_input("Plasman (1-100)", min_value=1, max_value=100, step=1, key=f"p_{idx}")
                opponents_json = st.text_area("Protivnici (JSON lista objekata name/club/result)", key=f"o_{idx}")
                note = st.text_area("Napomena", key=f"n_{idx}")
            sres = st.form_submit_button("Spremi rezultate")
        if sres:
            cid = int(comp_sel.split(" – ")[0])
            for idx, ms in enumerate(mem_sel):
                mid = int(ms.split(" – ")[0])
                conn.execute("""INSERT INTO competition_results
                                (competition_id,member_id,weight_category,style,bouts_total,wins,losses,placement,opponent_list,notes)
                                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                             (cid, mid, st.session_state[f"k_{idx}"], st.session_state[f"s_{idx}"],
                              int(st.session_state[f"bt_{idx}"]), int(st.session_state[f"w_{idx}"]),
                              int(st.session_state[f"l_{idx}"]), int(st.session_state[f"p_{idx}"]),
                              st.session_state[f"o_{idx}"], st.session_state[f"n_{idx}"]))
            conn.commit()
            st.success("Rezultati spremljeni.")
    else:
        st.info("Za unos rezultata potreban je barem jedan član i jedno natjecanje.")

    # Uvoz rezultata iz Excela
    upl = st.file_uploader("Učitaj rezultate (Excel po predlošku)", type=["xlsx"], key="upl_res")
    if upl:
        try:
            df = pd.read_excel(upl).fillna("")
            for _, r in df.iterrows():
                cid = int(r.get("natjecanje_id","") or 0)
                # pokušaj naći člana po imenu
                mrow = conn.execute("SELECT id FROM members WHERE full_name=?", (r.get("clan(ime_prezime)",""),)).fetchone()
                mid = mrow[0] if mrow else None
                if cid and mid:
                    conn.execute("""INSERT INTO competition_results
                                    (competition_id,member_id,weight_category,style,bouts_total,wins,losses,placement,opponent_list,notes)
                                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                                 (cid, mid, r.get("kategorija",""), r.get("stil",""),
                                  int(r.get("ukupno_borbi",0) or 0), int(r.get("pobjede",0) or 0),
                                  int(r.get("porazi",0) or 0), int(r.get("plasman(1-100)",0) or 0),
                                  str(r.get("protivnici(JSON)","")), r.get("napomena","")))
            conn.commit()
            st.success("Rezultati uvezeni.")
        except Exception as e:
            st.error(f"Greška pri uvozu: {e}")

    # Pregled
    st.markdown("---")
    st.subheader("Pregled natjecanja")
    cdf = pd.read_sql_query("""
        SELECT id, name AS ime, kind AS vrsta, date_from AS od, date_to AS do, place AS mjesto, age_group AS uzrast
        FROM competitions ORDER BY date_from DESC
    """, conn)
    st.dataframe(cdf, use_container_width=True)
    conn.close()


# ==========================
# ODJELJAK: STATISTIKA
# ==========================
def section_stats():
    page_header("Statistika", "Filtri po godini, mjesecu, kategoriji, stilu i sportašu")

    conn = get_conn()
    year = st.selectbox("Godina", ["Sve"] + sorted(list(set([d[0][:4] for d in conn.execute("SELECT date_from FROM competitions").fetchall() if d[0]]))))
    member = st.text_input("Filtriraj po sportašu (dio imena)")
    kind = st.text_input("Vrsta natjecanja (dio naziva)")
    if st.button("Izračunaj"):
        q = """
            SELECT c.kind, c.age_group, c.style,
                   COUNT(DISTINCT c.id) AS broj_natjecanja,
                   SUM(cr.wins) AS pobjede, SUM(cr.losses) AS porazi,
                   SUM(cr.bouts_total) AS ukupno_borbi,
                   SUM(CASE WHEN cr.placement=1 THEN 1 ELSE 0 END) AS zlato,
                   SUM(CASE WHEN cr.placement=2 THEN 1 ELSE 0 END) AS srebro,
                   SUM(CASE WHEN cr.placement=3 THEN 1 ELSE 0 END) AS bronca
            FROM competitions c
            LEFT JOIN competition_results cr ON c.id=cr.competition_id
            LEFT JOIN members m ON m.id=cr.member_id
            WHERE 1=1
        """
        params: List[str] = []
        if year != "Sve":
            q += " AND c.date_from LIKE ?"; params.append(f"{year}%")
        if member.strip():
            q += " AND (m.full_name LIKE ?)"; params.append(f"%{member}%")
        if kind.strip():
            q += " AND (c.kind LIKE ?)"; params.append(f"%{kind}%")
        q += " GROUP BY c.kind, c.age_group, c.style ORDER BY broj_natjecanja DESC"
        sdf = pd.read_sql_query(q, conn, params=params)
        st.dataframe(sdf, use_container_width=True)
    conn.close()


# ==========================
# ODJELJAK: GRUPE
# ==========================
def section_groups():
    page_header("Grupe", "Dodavanje/brisanje grupa i raspored članova")

    conn = get_conn()
    with st.form("add_group"):
        gname = st.text_input("Naziv grupe")
        if st.form_submit_button("Dodaj grupu") and gname:
            try:
                conn.execute("INSERT INTO groups(name) VALUES (?)", (gname,))
                conn.commit(); st.success("Grupa dodana.")
            except sqlite3.IntegrityError:
                st.warning("Grupa već postoji.")

    # Popis grupa i članova
    groups = conn.execute("SELECT id, name FROM groups ORDER BY name").fetchall()
    for gid, gname in groups:
        st.markdown(f"### {gname}")
        gdf = pd.read_sql_query("""
            SELECT m.id, m.full_name AS član, m.active_competitor AS aktivni, m.veteran
            FROM members m WHERE m.group_id=? ORDER BY m.full_name
        """, conn, params=(gid,))
        st.dataframe(gdf, use_container_width=True)
        # Premještanje člana
        mems = conn.execute("SELECT id, full_name FROM members WHERE group_id IS NOT ? OR group_id!=? OR group_id IS NULL",
                            (gid, gid)).fetchall()
        if mems:
            sel = st.selectbox(f"Premjesti člana u '{gname}'", [f"{m[0]} – {m[1]}" for m in mems], key=f"mv_{gid}")
            if st.button("Premjesti", key=f"btnmv_{gid}"):
                mid = int(sel.split(" – ")[0])
                conn.execute("UPDATE members SET group_id=? WHERE id=?", (gid, mid))
                conn.commit(); st.success("Premješten.")

    # Uvoz/izvoz (Excel)
    st.markdown("---")
    st.subheader("Excel import/export")
    exp = pd.read_sql_query("SELECT id, name FROM groups", conn)
    st.download_button("Skini popis grupa (Excel)",
                       data=excel_bytes_from_df(exp, "Grupe"),
                       file_name="grupe.xlsx")
    upl = st.file_uploader("Učitaj grupe (Excel s kolonom 'name')", type=["xlsx"])
    if upl:
        try:
            df = pd.read_excel(upl).fillna("")
            for _, r in df.iterrows():
                if r.get("name",""):
                    try:
                        conn.execute("INSERT INTO groups(name) VALUES (?)", (r["name"],))
                    except sqlite3.IntegrityError:
                        pass
            conn.commit(); st.success("Grupe uvezene.")
        except Exception as e:
            st.error(f"Greška: {e}")
    conn.close()


# ==========================
# ODJELJAK: VETERANI
# ==========================
def section_veterans():
    page_header("Veterani", "Popis, uređivanje i komunikacija")

    conn = get_conn()
    vdf = pd.read_sql_query("""
        SELECT id, full_name AS ime_prezime, athlete_email, parent_email, residence
        FROM members WHERE veteran=1 ORDER BY full_name
    """, conn)
    st.dataframe(vdf, use_container_width=True)

    # WhatsApp link generacija (ručni odabir člana)
    if not vdf.empty:
        sel = st.selectbox("Pošalji obavijest (kopiraj link)", [f"{r['id']} – {r['ime_prezime']}" for _, r in vdf.iterrows()])
        msg = st.text_area("Poruka", "Pozdrav! Obavijest za veterane HK Podravka...")
        if st.button("Generiraj WhatsApp link"):
            member_name = sel.split(" – ")[1]
            link = f"https://wa.me/?text={member_name}%0A{msg.replace(' ', '%20')}"
            st.write("Kopiraj i zalijepi u preglednik / WhatsApp:")
            st.code(link)

    # Brisanje/mijenjanje
    st.markdown("---")
    del_id = st.number_input("ID člana za brisanje (veteran)", min_value=0, step=1)
    if st.button("Obriši"):
        conn.execute("DELETE FROM members WHERE id=? AND veteran=1", (int(del_id),))
        conn.commit(); st.success("Obrisano (ako je postojalo).")
    conn.close()


# ==========================
# ODJELJAK: PRISUSTVO
# ==========================
def section_attendance():
    page_header("Prisustvo", "Evidencija prisustva trenera i sportaša, statistika")

    LOCATIONS = ["DVORANA SJEVER", "IGRALIŠTE ANG", "IGRALIŠTE SREDNJA", "Drugo (upiši)"]

    conn = get_conn()

    st.subheader("Upis prisustva trenera (sesija)")
    coaches = conn.execute("SELECT id, full_name FROM coaches ORDER BY full_name").fetchall()
    groups = conn.execute("SELECT id, name FROM groups ORDER BY name").fetchall()

    if coaches and groups:
        csel = st.selectbox("Trener", [f"{c[0]} – {c[1]}" for c in coaches])
        gsel = st.selectbox("Grupa", [f"{g[0]} – {g[1]}" for g in groups])
        t1, t2 = st.columns(2)
        start_ts = t1.text_input("Početak (YYYY-MM-DD HH:MM)", value=datetime.now().strftime("%Y-%m-%d 18:00"))
        end_ts   = t2.text_input("Kraj (YYYY-MM-DD HH:MM)", value=datetime.now().strftime("%Y-%m-%d 19:30"))
        loc = st.selectbox("Mjesto", LOCATIONS)
        if loc == "Drugo (upiši)":
            loc = st.text_input("Upiši mjesto")
        remark = st.text_input("Napomena")
        if st.button("Spremi sesiju"):
            conn.execute("""INSERT INTO sessions (coach_id,group_id,start_ts,end_ts,location,remark)
                            VALUES (?,?,?,?,?,?)""",
                         (int(csel.split(" – ")[0]), int(gsel.split(" – ")[0]), start_ts, end_ts, loc, remark))
            conn.commit(); st.success("Sesija spremljena.")
    else:
        st.info("Dodajte trenere i grupe.")

    st.subheader("Prisustvo sportaša")
    sessions = conn.execute("""SELECT s.id, s.start_ts, g.name, c.full_name
                               FROM sessions s LEFT JOIN groups g ON g.id=s.group_id
                               LEFT JOIN coaches c ON c.id=s.coach_id ORDER BY s.start_ts DESC""").fetchall()
    if sessions:
        ssel = st.selectbox("Sesija", [f"{s[0]} – {s[1]} – {s[2]} – {s[3]}" for s in sessions])
        sid = int(ssel.split(" – ")[0])
        # predložena grupa članova
        gid = conn.execute("SELECT group_id FROM sessions WHERE id=?", (sid,)).fetchone()[0]
        if gid:
            mems = conn.execute("SELECT id, full_name FROM members WHERE group_id=? ORDER BY full_name", (gid,)).fetchall()
        else:
            mems = conn.execute("SELECT id, full_name FROM members ORDER BY full_name").fetchall()
        picks = st.multiselect("Prisustvovali", [f"{m[0]} – {m[1]}" for m in mems])
        minutes = st.number_input("Trajanje treninga (minute po sportašu)", min_value=0, step=15, value=90)
        if st.button("Spremi prisustvo"):
            for p in picks:
                mid = int(p.split(" – ")[0])
                conn.execute("INSERT INTO attendance (session_id,member_id,present,minutes) VALUES (?,?,?,?)",
                             (sid, mid, 1, int(minutes)))
            conn.commit(); st.success("Prisustvo spremljeno.")
    else:
        st.info("Najprije unesite sesiju.")

    # Statistika za mjesec
    st.markdown("---")
    st.subheader("Statistika prisustva (mjesec)")
    month = st.selectbox("Mjesec (YYYY-MM)", sorted(list(set([s[0][:7] for s in conn.execute("SELECT start_ts FROM sessions").fetchall() if s[0]]))))
    if month:
        s_count = conn.execute("SELECT COUNT(*), COALESCE(SUM((julianday(end_ts)-julianday(start_ts))*24*60),0) FROM sessions WHERE start_ts LIKE ?",
                               (f"{month}%",)).fetchone()
        st.write(f"- Broj treninga: **{int(s_count[0])}**")
        st.write(f"- Ukupno minuta (treneri): **{int(s_count[1])}**")
        a_count = conn.execute("SELECT COUNT(*), COALESCE(SUM(minutes),0) FROM attendance a JOIN sessions s ON s.id=a.session_id WHERE s.start_ts LIKE ?",
                               (f"{month}%",)).fetchone()
        st.write(f"- Prisustava (sportaši): **{int(a_count[0])}**")
        st.write(f"- Ukupno minuta (sportaši): **{int(a_count[1])}**")
    conn.close()


# ==========================
# NAVIGACIJA I APLIKACIJA
# ==========================
def main():
    st.set_page_config(page_title="HK Podravka – Admin", page_icon="🤼", layout="wide")
    css_style()
    init_db()

    with st.sidebar:
        st.image("https://hk-podravka.com/wp-content/uploads/2021/08/cropped-HK-Podravka-logo.png", width=120)
        st.markdown(f"### {KLUB_NAZIV}")
        st.markdown(f"**E-mail:** {KLUB_EMAIL}")
        st.markdown(f"**Adresa:** {KLUB_ADRESA}")
        st.markdown(f"**OIB:** {KLUB_OIB}")
        st.markdown(f"**IBAN:** {KLUB_IBAN}")
        st.markdown(f"[Web]({KLUB_WEB})")

        section = st.radio("Navigacija", [
            "Klub", "Članovi", "Treneri", "Natjecanja i rezultati",
            "Statistika", "Grupe", "Veterani", "Prisustvo"
        ])

    if section == "Klub":
        section_club()
    elif section == "Članovi":
        section_members()
    elif section == "Treneri":
        section_coaches()
    elif section == "Natjecanja i rezultati":
        section_competitions()
    elif section == "Statistika":
        section_stats()
    elif section == "Grupe":
        section_groups()
    elif section == "Veterani":
        section_veterans()
    elif section == "Prisustvo":
        section_attendance()


if __name__ == "__main__":
    main()
