
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
from typing import Optional, List, Tuple

import pandas as pd
import streamlit as st

# Za ISO3 kodove
try:
    import pycountry
except Exception:
    pycountry = None

# Za grafove u statistici
import matplotlib.pyplot as plt

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
            first_name TEXT,
            last_name TEXT,
            dob TEXT,
            gender TEXT CHECK (gender IN ('M','Ž','')),
            oib TEXT,
            street TEXT,
            city TEXT,
            postal_code TEXT,
            residence TEXT,
            athlete_email TEXT,
            parent_email TEXT,
            athlete_phone TEXT,
            parent_phone TEXT,
            id_card_number TEXT, id_card_issuer TEXT, id_card_valid_until TEXT,
            passport_number TEXT, passport_issuer TEXT, passport_valid_until TEXT,
            active_competitor INTEGER DEFAULT 0,
            veteran INTEGER DEFAULT 0,
            other_flag INTEGER DEFAULT 0,
            membership_fee_eur REAL DEFAULT 0,
            group_id INTEGER,
            photo_path TEXT,
            consent_path TEXT,       -- privola
            application_path TEXT,   -- pristupnica ili dodatni dokument
            medical_path TEXT,
            medical_valid_until TEXT,
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE SET NULL
        )
    """)
    # Backward compatible ALTERs
    def ensure_column(table: str, col: str, ddl: str):
        have = cur.execute(f"PRAGMA table_info({table})").fetchall()
        names = [r[1] for r in have]
        if col not in names:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

    ensure_column("members","first_name","TEXT")
    ensure_column("members","last_name","TEXT")
    ensure_column("members","street","TEXT")
    ensure_column("members","city","TEXT")
    ensure_column("members","postal_code","TEXT")
    ensure_column("members","athlete_phone","TEXT")
    ensure_column("members","parent_phone","TEXT")
    ensure_column("members","parent_name","TEXT")

    # Treneri
    cur.execute("""
        CREATE TABLE IF NOT EXISTS coaches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT,
            first_name TEXT,
            last_name TEXT,
            dob TEXT,
            oib TEXT,
            email TEXT,
            iban TEXT,
            photo_path TEXT
        )
    """)
    ensure_column("coaches","first_name","TEXT")
    ensure_column("coaches","last_name","TEXT")

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
            custom_kind TEXT,   -- ili podvrsta repre.
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
            gallery_link TEXT,
            bulletin_file TEXT,
            results_file TEXT
        )
    """)
    ensure_column("competitions","bulletin_file","TEXT")
    ensure_column("competitions","results_file","TEXT")

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

    # Pripreme reprezentacije
    cur.execute("""
        CREATE TABLE IF NOT EXISTS camps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            place TEXT,
            coach TEXT,
            start_date TEXT,
            end_date TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS camp_attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camp_id INTEGER,
            member_id INTEGER,
            trainings INTEGER DEFAULT 0,
            hours REAL DEFAULT 0.0,
            FOREIGN KEY(camp_id) REFERENCES camps(id) ON DELETE CASCADE,
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
        a.hk-btn {{
            text-decoration:none; padding:6px 10px; border-radius:8px; border:1px solid #ddd; margin-right:6px;
            display:inline-block;
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
        "ime":"", "prezime":"", "ime_prezime":"",
        "datum_rođenja":"", "spol(M/Ž)":"",
        "oib":"", "ulica":"", "grad":"", "poštanski_broj":"",
        "email_sportaša":"", "email_roditelja":"",
        "telefon_sportaša":"", "telefon_roditelja":"",
        "osobna_broj":"", "osobna_izdavatelj":"", "osobna_vrijedi_do":"",
        "putovnica_broj":"", "putovnica_izdavatelj":"", "putovnica_vrijedi_do":"",
        "aktivni_natjecatelj(0/1)":"", "veteran(0/1)":"", "ostalo(0/1)":"",
        "članarina_EUR":"30", "grupa":"", "napomena":""
    }])


def coaches_template_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "ime":"", "prezime":"", "ime_prezime":"",
        "datum_rođenja":"", "oib":"", "email":"", "iban":"", "grupa":""
    }])


def comp_results_template_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "natjecanje_id":"", "clan(ime_prezime)":"",
        "kategorija":"", "stil":"", "ukupno_borbi":"",
        "pobjede":"", "porazi":"", "plasman(1-100)":"",
        "protivnici(JSON)":"[{'name':'Ime Prezime','club':'Klub','result':'win/lose'}]",
        "napomena":""
    }])


def iso3(country_name: str) -> str:
    if not country_name:
        return ""
    if pycountry is None:
        return ""
    try:
        c = pycountry.countries.lookup(country_name)
        return getattr(c, "alpha_3", "") or ""
    except Exception:
        return ""


def mailto_link(address: str, subject: str = "", body: str = "") -> str:
    if not address:
        return ""
    from urllib.parse import quote
    return f"mailto:{address}?subject={quote(subject)}&body={quote(body)}"


def whatsapp_link(phone_or_text: str) -> str:
    # ako je broj, koristimo wa.me; inače samo text share
    s = str(phone_or_text).strip()
    base = "https://wa.me"
    if s and all(ch.isdigit() or ch in "+ " for ch in s):
        return f"{base}/{s.replace(' ', '')}"
    else:
        return f"{base}/?text={s.replace(' ', '%20')}"


# ==========================
# ODJELJAK: KLUB
# ==========================
def section_club():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM club_info WHERE id=1", conn)

    page_header("Osnovni podaci o klubu",
                "Unesite i spremite podatke kluba, vodstva i dokumente.")
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
    page_header("Članovi", "Unos, uvoz/izvoz, uređivanje, dokumenti i liječničke potvrde")

    # Predlošci
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
            df = pd.read_excel(upl).fillna("")
            for _, r in df.iterrows():
                gid = None
                if r.get("grupa",""):
                    g = conn.execute("SELECT id FROM groups WHERE name=?", (r["grupa"],)).fetchone()
                    if g: gid = g[0]
                full_name = r.get("ime_prezime","") or (r.get("ime","")+" "+r.get("prezime","")).strip()
                conn.execute("""INSERT INTO members
                    (full_name,first_name,last_name,dob,gender,oib,street,city,postal_code,residence,
                     athlete_email,parent_email,athlete_phone,parent_phone,parent_name,
                     id_card_number,id_card_issuer,id_card_valid_until,
                     passport_number,passport_issuer,passport_valid_until,
                     active_competitor,veteran,other_flag,membership_fee_eur,group_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (full_name, r.get("ime",""), r.get("prezime",""), r.get("datum_rođenja",""), r.get("spol(M/Ž)",""),
                     r.get("oib",""), r.get("ulica",""), r.get("grad",""), r.get("poštanski_broj",""),
                     f"{r.get('ulica','')}, {r.get('grad','')} {r.get('poštanski_broj','')}",
                     r.get("email_sportaša",""), r.get("email_roditelja",""),
                     r.get("telefon_sportaša",""), r.get("telefon_roditelja",""), r.get("roditelj_ime_prezime",""),
                     r.get("osobna_broj",""), r.get("osobna_izdavatelj",""), r.get("osobna_vrijedi_do",""),
                     r.get("putovnica_broj",""), r.get("putovnica_izdavatelj",""), r.get("putovnica_vrijedi_do",""),
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
        # Grupa – istaknuta na početku
        groups = [r[0] for r in conn.execute("SELECT name FROM groups ORDER BY name").fetchall()]
        group_name = st.selectbox("Grupa (odaberi)", [""] + groups)

        c1, c2 = st.columns(2)
        first_name = c1.text_input("Ime")
        last_name  = c1.text_input("Prezime")
        full_name  = f"{first_name} {last_name}".strip()

        # Datum rođenja i starost
        dob = c1.date_input("Datum rođenja", value=None, help="dan.mjesec.godina")
        if dob:
            # izračun starosti
            today = date.today()
            delta = today - dob
            years = delta.days // 365
            days_rem = delta.days - years * 365
            st.caption(f"Starost: **{years} godina, {days_rem} dana**")

        gender = c1.selectbox("Spol", ["", "M", "Ž"])
        oib = c1.text_input("OIB")

        # Adresa split u zasebne kolone
        street = c1.text_input("Ulica i kućni broj")
        city = c1.text_input("Mjesto/Grad")
        postal_code = c1.text_input("Poštanski broj")

        # Roditelji i kontakti
        parent_name  = c2.text_input("Ime i prezime roditelja/skrbnika")
        athlete_email = c2.text_input("E-mail sportaša")
        parent_email  = c2.text_input("E-mail roditelja")
        athlete_phone = c2.text_input("Telefon sportaša (za WhatsApp)")
        parent_phone  = c2.text_input("Telefon roditelja (za WhatsApp)")

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

        # Liječnički pregled – prvo datum, uz odbrojavanje
        st.markdown("**Liječnička potvrda**")
        colm1, colm2 = st.columns([2,1])
        medical_valid = colm1.date_input("Liječnička vrijedi do", value=None, help="dan.mjesec.godina")
        # countdown prikaz
        if medical_valid:
            days_left = (medical_valid - date.today()).days
            style = "color:#333;"
            if days_left <= 14:
                style = "color:#b00020; font-weight:600;"
            colm2.markdown(f"<div style='{style}'>Preostalo: {days_left} dana</div>", unsafe_allow_html=True)
        medical = st.file_uploader("Upload liječničke potvrde (pdf/jpg/png)", type=["pdf","jpg","jpeg","png"])

        # Privola i pristupnica
        consent = st.file_uploader("Privola (pdf/jpg/png)", type=["pdf","jpg","jpeg","png"])
        application = st.file_uploader("Pristupnica (pdf/jpg/png)", type=["pdf","jpg","jpeg","png"])

        submit_member = st.form_submit_button("Spremi člana")

    if submit_member:
        gid = None
        if group_name:
            r = conn.execute("SELECT id FROM groups WHERE name=?", (group_name,)).fetchone()
            if r: gid = r[0]
        photo_p = save_upload(photo, "members/photos")
        consent_p = save_upload(consent, "members/consent")
        application_p = save_upload(application, "members/application")
        medical_p = save_upload(medical, "members/medical")

        conn.execute("""INSERT INTO members
            (full_name,first_name,last_name,dob,gender,oib,street,city,postal_code,residence,
             athlete_email,parent_email,athlete_phone,parent_phone,parent_name,
             id_card_number,id_card_issuer,id_card_valid_until,
             passport_number,passport_issuer,passport_valid_until,
             active_competitor,veteran,other_flag,membership_fee_eur,
             group_id,photo_path,consent_path,application_path,medical_path,medical_valid_until)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (full_name, first_name, last_name, str(dob) if dob else "", gender, oib,
             street, city, postal_code, f"{street}, {city} {postal_code}",
             athlete_email, parent_email, athlete_phone, parent_phone, parent_name,
             id_card_number, id_card_issuer, str(id_card_valid_until) if id_card_valid_until else "",
             passport_number, passport_issuer, str(passport_valid_until) if passport_valid_until else "",
             int(active_competitor), int(veteran), int(other_flag), float(fee),
             gid, photo_p, consent_p, application_p, medical_p, str(medical_valid) if medical_valid else ""))
        conn.commit()
        st.success("Član je spremljen.")

    # Popis članova – format datuma dd.mm.yyyy, dob (godine,dani), R.br. od 1
    st.markdown("---")
    st.subheader("Popis članova")

    def fmt_date(s):
        if not s: return ""
        try:
            d = pd.to_datetime(s).date()
            return d.strftime("%d.%m.%Y.")
        except Exception:
            return str(s)

    mdf = pd.read_sql_query("""
        SELECT m.id, m.full_name AS ime_prezime, m.first_name AS ime, m.last_name AS prezime,
               m.gender AS spol, m.oib, m.street AS ulica, m.city AS grad, m.postal_code AS poštanski_broj,
               m.athlete_email, m.parent_email, m.athlete_phone, m.parent_phone, m.parent_name,
               m.active_competitor AS aktivni, m.veteran,
               m.membership_fee_eur AS članarina, m.medical_valid_until AS liječnička_do, m.dob,
               g.name AS grupa
        FROM members m LEFT JOIN groups g ON m.group_id=g.id
        ORDER BY m.full_name
    """, conn)

    if not mdf.empty:
        # izračun starosti kao tekst
        ages = []
        for _, r in mdf.iterrows():
            if r["dob"]:
                try:
                    dd = pd.to_datetime(r["dob"]).date()
                    delta = date.today() - dd
                    years = delta.days // 365
                    days_rem = delta.days - years * 365
                    ages.append(f"{years} godina, {days_rem} dana")
                except Exception:
                    ages.append("")
            else:
                ages.append("")
        mdf.insert(0, "R.br.", range(1, len(mdf) + 1))
        mdf["dob"] = mdf["dob"].apply(fmt_date)
        mdf["liječnička_do"] = mdf["liječnička_do"].apply(fmt_date)
        mdf.insert(3, "starost", ages)

    st.dataframe(mdf, use_container_width=True)

    # Export članova
    st.download_button("Skini sve članove (Excel)",
                       data=excel_bytes_from_df(mdf, "Clanovi"),
                       file_name="clanovi.xlsx")

    # Upozorenja o liječničkoj potvrdi
    if not mdf.empty:
        today = date.today()
        warn = []
        for _, row in mdf.iterrows():
            if row["liječnička_do"]:
                try:
                    exp = datetime.strptime(row["liječnička_do"], "%d.%m.%Y.").date()
                except Exception:
                    try:
                        exp = pd.to_datetime(row["liječnička_do"]).date()
                    except Exception:
                        continue
                days = (exp - today).days
                if days <= 14:
                    warn.append((row["ime_prezime"], days))
        if warn:
            st.markdown("<div class='hk-danger'><b>Upozorenje:</b> Slijedećim članovima istječe liječnička u roku 14 dana:</div>", unsafe_allow_html=True)
            for nm, d in warn:
                st.write(f"- {nm}: {d} dana")

    # Uređivanje/brisanje + kontakti i rezultati ostaju kao u prethodnoj verziji
    st.markdown("---")
    st.subheader("Uredi / obriši člana, kontakt i rezultati")
    ids = [r[0] for r in conn.execute("SELECT id FROM members ORDER BY full_name").fetchall()]
    if ids:
        sel_id = st.selectbox("Odaberi ID člana", ids)
        row = conn.execute("SELECT * FROM members WHERE id=?", (int(sel_id),)).fetchone()
        cols = [c[1] for c in conn.execute("PRAGMA table_info(members)")]
        data = dict(zip(cols, row))

        with st.form("edit_member"):
            # Grupa
            groups = [r[0] for r in conn.execute("SELECT name FROM groups ORDER BY name").fetchall()]
            current_group = conn.execute("SELECT name FROM groups WHERE id=?", (data.get("group_id"),)).fetchone()
            gsel = st.selectbox("Grupa", [""] + groups, index=([""]+groups).index(current_group[0]) if current_group else 0)

            e1, e2 = st.columns(2)
            data["first_name"] = e1.text_input("Ime", data.get("first_name",""))
            data["last_name"]  = e1.text_input("Prezime", data.get("last_name",""))
            data["gender"]     = e1.selectbox("Spol", ["","M","Ž"], index=["","M","Ž"].index(data.get("gender","") or ""))
            data["oib"]        = e1.text_input("OIB", data.get("oib",""))
            data["street"]     = e1.text_input("Ulica i broj", data.get("street",""))
            data["city"]       = e1.text_input("Grad", data.get("city",""))
            data["postal_code"]= e1.text_input("Poštanski broj", data.get("postal_code",""))

            data["parent_name"]  = e2.text_input("Ime i prezime roditelja/skrbnika", data.get("parent_name",""))
            data["athlete_email"] = e2.text_input("E-mail sportaša", data.get("athlete_email",""))
            data["parent_email"]  = e2.text_input("E-mail roditelja", data.get("parent_email",""))
            data["athlete_phone"] = e2.text_input("Telefon sportaša", data.get("athlete_phone",""))
            data["parent_phone"]  = e2.text_input("Telefon roditelja", data.get("parent_phone",""))
            data["membership_fee_eur"] = e2.number_input("Članarina (EUR)", min_value=0.0, step=5.0, value=float(data.get("membership_fee_eur") or 0))

            ch1, ch2, ch3 = st.columns(3)
            data["active_competitor"] = int(ch1.checkbox("Aktivni", bool(data.get("active_competitor"))))
            data["veteran"]           = int(ch2.checkbox("Veteran", bool(data.get("veteran"))))
            data["other_flag"]        = int(ch3.checkbox("Ostalo", bool(data.get("other_flag"))))

            # Liječnička datum s countdown prikazom
            med1, med2 = st.columns([2,1])
            med_valid = med1.date_input("Liječnička vrijedi do",
                                        value=pd.to_datetime(data.get("medical_valid_until")).date() if data.get("medical_valid_until") else None)
            if med_valid:
                days_left = (med_valid - date.today()).days
                style = "color:#333;"
                if days_left <= 14:
                    style = "color:#b00020; font-weight:600;"
                med2.markdown(f"<div style='{style}'>Preostalo: {days_left} dana</div>", unsafe_allow_html=True)

            if st.form_submit_button("Spremi izmjene"):
                full_name = f"{data['first_name']} {data['last_name']}".strip() or data.get("full_name","")
                data["full_name"] = full_name
                gid = None
                if gsel:
                    r = conn.execute("SELECT id FROM groups WHERE name=?", (gsel,)).fetchone()
                    gid = r[0] if r else None
                conn.execute("""UPDATE members SET
                    full_name=?, first_name=?, last_name=?, gender=?, oib=?, street=?, city=?, postal_code=?,
                    parent_name=?, athlete_email=?, parent_email=?, athlete_phone=?, parent_phone=?,
                    membership_fee_eur=?, active_competitor=?, veteran=?, other_flag=?, medical_valid_until=?, group_id=?
                    WHERE id=?""",
                    (data["full_name"], data["first_name"], data["last_name"], data["gender"], data["oib"],
                     data["street"], data["city"], data["postal_code"],
                     data["parent_name"], data["athlete_email"], data["parent_email"], data["athlete_phone"], data["parent_phone"],
                     float(data["membership_fee_eur"]), int(data["active_competitor"]), int(data["veteran"]), int(data["other_flag"]),
                     str(med_valid) if med_valid else "", gid, int(sel_id)))
                conn.commit()
                st.success("Izmjene spremljene.")

        # Kontakti + rezultati kao prije
        subject = "Obavijest HK Podravka"
        email_row = conn.execute("SELECT athlete_email, parent_email, athlete_phone, parent_phone FROM members WHERE id=?", (int(sel_id),)).fetchone()
        a_email, p_email, a_phone, p_phone = email_row if email_row else ("","","","")
        st.markdown(
            f"[📧 Sportaš]({mailto_link(a_email, subject)}) &nbsp; "
            f"[📧 Roditelj]({mailto_link(p_email, subject)}) &nbsp; "
            f"[🟢 WhatsApp sportaš]({whatsapp_link(a_phone)}) &nbsp; "
            f"[🟢 WhatsApp roditelj]({whatsapp_link(p_phone)})",
            unsafe_allow_html=True
        )

        # Rezultati člana
        st.markdown("**Rezultati ovog člana:**")
        rdf = pd.read_sql_query("""
            SELECT c.name AS natjecanje, c.date_from AS datum, cr.weight_category AS kategorija,
                   cr.style AS stil, cr.bouts_total AS borbi, cr.wins AS pobjede, cr.losses AS porazi, cr.placement AS plasman
            FROM competition_results cr
            JOIN competitions c ON c.id=cr.competition_id
            WHERE cr.member_id=? ORDER BY c.date_from DESC
        """, conn, params=(int(sel_id),))
        # formatiraj datum
        if not rdf.empty:
            rdf["datum"] = pd.to_datetime(rdf["datum"]).dt.strftime("%d.%m.%Y.")
        st.dataframe(rdf, use_container_width=True)

        colbtn1, colbtn2 = st.columns(2)
        if colbtn1.button("Obriši ovog člana"):
            conn.execute("DELETE FROM members WHERE id=?", (int(sel_id),))
            conn.commit()
            st.success("Član obrisan.")
    else:
        st.info("Nema članova u bazi.")

    conn.close()


# ==========================
# ODJELJAK: TRENERI
# ==========================
def section_coaches():
    page_header("Treneri", "Upis, uređivanje, dokumenti i Excel import/export")

    conn = get_conn()
    with st.form("coach_form"):
        c1, c2 = st.columns(2)
        first_name = c1.text_input("Ime")
        last_name  = c1.text_input("Prezime")
        full_name = f"{first_name} {last_name}".strip()
        dob = c1.date_input("Datum rođenja", value=None)
        oib = c1.text_input("OIB")
        email = c2.text_input("E-mail")
        iban = c2.text_input("IBAN račun")
        # Grupa pri upisu
        groups = [r[0] for r in conn.execute("SELECT name FROM groups ORDER BY name").fetchall()]
        group_name = c2.selectbox("Grupa", [""] + groups)
        photo = st.file_uploader("Slika (jpg/png)", type=["jpg","jpeg","png"])
        submit = st.form_submit_button("Spremi trenera")

    if submit:
        photo_p = save_upload(photo, "coaches/photos")
        conn.execute("""INSERT INTO coaches (full_name,first_name,last_name,dob,oib,email,iban,photo_path)
                        VALUES (?,?,?,?,?,?,?,?)""",
                     (full_name, first_name, last_name, str(dob) if dob else "", oib, email, iban, photo_p))
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        if group_name:
            gid = conn.execute("SELECT id FROM groups WHERE name=?", (group_name,)).fetchone()
            if gid:
                conn.execute("INSERT INTO coach_groups (coach_id,group_id,assigned_at) VALUES (?,?,?)",
                             (cid, gid[0], datetime.now().isoformat()))
        conn.commit()
        st.success("Trener spremljen.")

    # Uređivanje/brisanje trenera
    st.subheader("Uredi / obriši trenera")
    tdf = pd.read_sql_query("SELECT id, full_name AS ime_prezime, dob, email, iban FROM coaches", conn)
    st.dataframe(tdf, use_container_width=True)
    st.download_button("Skini trenere (Excel)",
                       data=excel_bytes_from_df(tdf, "Treneri"),
                       file_name="treneri.xlsx")

    uplc = st.file_uploader("Učitaj trenere (Excel po predlošku)", type=["xlsx"])
    if uplc:
        try:
            df = pd.read_excel(uplc).fillna("")
            for _, r in df.iterrows():
                full_name = r.get("ime_prezime","") or (r.get("ime","")+" "+r.get("prezime","")).strip()
                conn.execute("""INSERT INTO coaches (full_name,first_name,last_name,dob,oib,email,iban)
                                VALUES (?,?,?,?,?,?,?)""",
                             (full_name, r.get("ime",""), r.get("prezime",""),
                              r.get("datum_rođenja",""), r.get("oib",""), r.get("email",""), r.get("iban","")))
                cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                if r.get("grupa",""):
                    gid = conn.execute("SELECT id FROM groups WHERE name=?", (r["grupa"],)).fetchone()
                    if gid:
                        conn.execute("INSERT INTO coach_groups (coach_id,group_id,assigned_at) VALUES (?,?,?)",
                                     (cid, gid[0], datetime.now().isoformat()))
            conn.commit(); st.success("Treneri uvezeni.")
        except Exception as e:
            st.error(f"Greška pri uvozu: {e}")

    # Povezivanje s grupama (dodatno)
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
    conn.close()


# ==========================
# ODJELJAK: NATJECANJA I REZULTATI
# ==========================
def section_competitions():
    page_header("Natjecanja i rezultati", "Unos natjecanja, datoteka, rezultata i pretraga")

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
        date_to = c2.date_input("Datum do (ako 1 dan, ostavi isti)", value=date.today())
        place = st.text_input("Mjesto")
        country = st.text_input("Država (puni naziv)")
        auto_iso = iso3(country)
        style = st.selectbox("Hrvački stil", STYLES)
        age_group = st.selectbox("Uzrast", AGES)
        c3, c4, c5 = st.columns(3)
        team_rank = c3.text_input("Ekipni poredak (npr. 1., 5., 10.)")
        club_competitors = c4.number_input("Broj naših natjecatelja", min_value=0, step=1)
        total_competitors = c5.number_input("Ukupan broj natjecatelja", min_value=0, step=1)
        c6, c7 = st.columns(2)
        total_clubs = c6.number_input("Broj klubova", min_value=0, step=1)
        total_countries = c7.number_input("Broj zemalja", min_value=0, step=1)

        # Treneri koji su vodili
        coach_text = st.text_input("Trener(i) (odvoji zarezima)")

        # Opis i linkovi + upload
        notes = st.text_area("Zapažanje trenera (za objave)")
        bulletin_link = st.text_input("Link na bilten/rezultate")
        results_link = st.text_input("Link na službene rezultate")
        gallery_link = st.text_input("Link na objavu na webu (galerija)")
        bulletin_file = st.file_uploader("Učitaj bilten (pdf)", type=["pdf"])
        results_file = st.file_uploader("Učitaj rezultate (pdf/xlsx)", type=["pdf","xlsx"])

        # Slike
        photos = st.file_uploader("Slike s natjecanja (više datoteka)", type=["jpg","jpeg","png"], accept_multiple_files=True)

        submit = st.form_submit_button("Spremi natjecanje")

    if submit:
        bull_p = save_upload(bulletin_file, "competitions/docs") if bulletin_file else ""
        res_p = save_upload(results_file, "competitions/docs") if results_file else ""
        conn.execute("""INSERT INTO competitions
            (kind,custom_kind,name,date_from,date_to,place,style,age_group,country,country_code,
             team_rank,club_competitors,total_competitors,total_clubs,total_countries,
             coaches_text,notes,bulletin_link,results_link,gallery_link, bulletin_file, results_file)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (kind, rep_sub if kind=="REPREZENTATIVNI NASTUP" else custom_kind, name,
             str(date_from), str(date_to), f"{place}, {country}", style, age_group, country, auto_iso,
             team_rank, int(club_competitors), int(total_competitors), int(total_clubs), int(total_countries),
             coach_text, notes, bulletin_link, results_link, gallery_link, bull_p, res_p))
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
    STYLES = ["GR","FS","WW","BW","MODIFICIRANO"]
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

    # Uvoz/izvoz rezultata iz Excela
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
    # Export svih rezultata
    res_all = pd.read_sql_query("""
        SELECT cr.id, c.name AS natjecanje, c.date_from AS datum, m.full_name AS sportaš,
               cr.weight_category AS kategorija, cr.style AS stil,
               cr.bouts_total AS borbi, cr.wins AS pobjede, cr.losses AS porazi, cr.placement AS plasman
        FROM competition_results cr
        JOIN competitions c ON c.id=cr.competition_id
        LEFT JOIN members m ON m.id=cr.member_id
        ORDER BY c.date_from DESC
    """, conn)
    st.download_button("Skini sve rezultate (Excel)",
                       data=excel_bytes_from_df(res_all, "Rezultati"),
                       file_name="rezultati.xlsx")

    # Pretraga i pregled natjecanja
    st.markdown("---")
    st.subheader("Pregled i pretraga natjecanja")
    colf = st.columns(5)
    f_kind = colf[0].text_input("Vrsta (dio naziva)")
    f_year = colf[1].text_input("Godina (npr. 2025)")
    f_age  = colf[2].text_input("Uzrast (dio naziva)")
    f_style= colf[3].text_input("Stil (GR/FS/WW/BW/MOD)")
    f_country = colf[4].text_input("Država (dio naziva)")
    if st.button("Pretraži"):
        q = """
            SELECT id, name AS ime, kind AS vrsta, age_group AS uzrast, style AS stil,
                   date_from AS od, date_to AS do, place AS mjesto, country AS država, country_code AS ISO3,
                   team_rank AS ekipno, club_competitors AS naši, total_competitors AS natjecatelja,
                   total_clubs AS klubova, total_countries AS zemalja
            FROM competitions WHERE 1=1
        """
        params: List[str] = []
        if f_kind.strip(): q += " AND kind LIKE ?"; params.append(f"%{f_kind}%")
        if f_year.strip(): q += " AND date_from LIKE ?"; params.append(f"{f_year}%")
        if f_age.strip():  q += " AND age_group LIKE ?"; params.append(f"%{f_age}%")
        if f_style.strip():q += " AND style LIKE ?"; params.append(f"%{f_style}%")
        if f_country.strip(): q += " AND country LIKE ?"; params.append(f"%{f_country}%")
        q += " ORDER BY date_from DESC"
        cdf = pd.read_sql_query(q, conn, params=params)
    else:
        cdf = pd.read_sql_query("""
            SELECT id, name AS ime, kind AS vrsta, age_group AS uzrast, style AS stil,
                   date_from AS od, date_to AS do, place AS mjesto, country AS država, country_code AS ISO3
            FROM competitions ORDER BY date_from DESC
        """, conn)
    st.dataframe(cdf, use_container_width=True)

    conn.close()


# ==========================
# ODJELJAK: STATISTIKA
# ==========================
def section_stats():
    page_header("Statistika", "Filtri i grafički/tablični prikaz medalja, pobjeda/poraza i borbi")

    conn = get_conn()
    year_choices = sorted(list(set([d[0][:4] for d in conn.execute("SELECT date_from FROM competitions").fetchall() if d[0]])))
    year = st.selectbox("Godina", ["Sve"] + year_choices)
    member = st.text_input("Sportaš/ica (dio imena)")
    kind = st.text_input("Vrsta natjecanja (dio naziva)")
    if st.button("Izračunaj"):
        q = """
            SELECT c.kind, c.age_group, c.style,
                   COUNT(DISTINCT c.id) AS broj_natjecanja,
                   SUM(COALESCE(cr.wins,0)) AS pobjede, SUM(COALESCE(cr.losses,0)) AS porazi,
                   SUM(COALESCE(cr.bouts_total,0)) AS ukupno_borbi,
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

        # Grafovi
        if not sdf.empty:
            # Medalje
            medals = sdf[["zlato","srebro","bronca"]].sum()
            fig = plt.figure()
            plt.bar(["Zlato","Srebro","Bronca"], medals.values)
            plt.title("Medalje (ukupno)")
            st.pyplot(fig)

            # Omjer pobjeda/poraza
            wl = sdf[["pobjede","porazi"]].sum()
            fig2 = plt.figure()
            plt.bar(["Pobjede","Porazi"], wl.values)
            plt.title("Pobjede / Porazi (ukupno)")
            st.pyplot(fig2)

            # Ukupno borbi po vrsti natjecanja (top 10)
            top = sdf.groupby("kind")["ukupno_borbi"].sum().sort_values(ascending=False).head(10)
            fig3 = plt.figure()
            plt.bar(list(top.index), list(top.values))
            plt.title("Ukupno borbi po vrsti (top 10)")
            plt.xticks(rotation=45, ha="right")
            st.pyplot(fig3)
    conn.close()


# ==========================
# ODJELJAK: GRUPE
# ==========================
def section_groups():
    page_header("Grupe", "Dodavanje/uređivanje/brisanje i raspored članova + Excel import/export")

    conn = get_conn()
    # Dodavanje / uređivanje / brisanje
    with st.form("group_crud"):
        col = st.columns(3)
        gname = col[0].text_input("Naziv grupe (dodaj)")
        edit_id = col[1].number_input("ID za preimenovanje", min_value=0, step=1)
        new_name = col[1].text_input("Novo ime")
        del_id = col[2].number_input("ID za brisanje", min_value=0, step=1)
        submitted = st.form_submit_button("Primijeni")
    if submitted:
        if gname:
            try:
                conn.execute("INSERT INTO groups(name) VALUES (?)", (gname,))
                conn.commit(); st.success("Grupa dodana.")
            except sqlite3.IntegrityError:
                st.warning("Grupa već postoji.")
        if edit_id and new_name:
            conn.execute("UPDATE groups SET name=? WHERE id=?", (new_name, int(edit_id)))
            conn.commit(); st.success("Grupa preimenovana.")
        if del_id:
            conn.execute("DELETE FROM groups WHERE id=?", (int(del_id),))
            conn.commit(); st.success("Grupa obrisana.")

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
        mems = conn.execute("SELECT id, full_name FROM members ORDER BY full_name").fetchall()
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
    page_header("Veterani", "Popis, uređivanje/brisanje i komunikacija (e-mail/WhatsApp)")

    conn = get_conn()
    vdf = pd.read_sql_query("""
        SELECT id, full_name AS ime_prezime, athlete_email, parent_email, athlete_phone, parent_phone
        FROM members WHERE veteran=1 ORDER BY full_name
    """, conn)
    st.dataframe(vdf, use_container_width=True)

    if not vdf.empty:
        sel = st.selectbox("Odaberi veterana (ID – ime)", [f"{r['id']} – {r['ime_prezime']}" for _, r in vdf.iterrows()])
        vid = int(sel.split(" – ")[0])
        row = vdf[vdf["id"]==vid].iloc[0]
        subject = "Obavijest – Veterani HK Podravka"
        st.markdown(
            f"[📧 Sportaš]({mailto_link(row['athlete_email'], subject)}) &nbsp; "
            f"[📧 Roditelj]({mailto_link(row['parent_email'], subject)}) &nbsp; "
            f"[🟢 WhatsApp sportaš]({whatsapp_link(row['athlete_phone'])}) &nbsp; "
            f"[🟢 WhatsApp roditelj]({whatsapp_link(row['parent_phone'])})",
            unsafe_allow_html=True
        )

    # Brisanje/mijenjanje
    st.markdown("---")
    del_id = st.number_input("ID veterana za brisanje", min_value=0, step=1)
    if st.button("Obriši"):
        conn.execute("DELETE FROM members WHERE id=? AND veteran=1", (int(del_id),))
        conn.commit(); st.success("Obrisano (ako je postojalo).")
    conn.close()


# ==========================
# ODJELJAK: PRISUSTVO
# ==========================
def section_attendance():
    page_header("Prisustvo", "Evidencija prisustva trenera i sportaša, statistika i pripreme reprezentacije")

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

    # Pripreme reprezentacije
    st.markdown("---")
    st.subheader("Pripreme reprezentacije (evidencija)")
    with st.form("camp_form"):
        title = st.text_input("Naziv/Opis priprema")
        place = st.text_input("Mjesto")
        coach = st.text_input("Voditelj (trener)")
        c1, c2 = st.columns(2)
        sd = c1.date_input("Od", value=date.today())
        ed = c2.date_input("Do", value=date.today() + timedelta(days=7))
        submit = st.form_submit_button("Spremi pripreme")
    if submit:
        conn.execute("INSERT INTO camps (title,place,coach,start_date,end_date) VALUES (?,?,?,?,?)",
                     (title, place, coach, str(sd), str(ed)))
        conn.commit(); st.success("Pripreme spremljene.")

    camps = conn.execute("SELECT id, title, start_date, end_date FROM camps ORDER BY start_date DESC").fetchall()
    if camps:
        camp_sel = st.selectbox("Odaberi pripreme", [f"{c[0]} – {c[1]} ({c[2]}–{c[3]})" for c in camps])
        camp_id = int(camp_sel.split(" – ")[0])
        mems2 = conn.execute("SELECT id, full_name FROM members ORDER BY full_name").fetchall()
        picks2 = st.multiselect("Članovi na pripremama", [f"{m[0]} – {m[1]}" for m in mems2])
        tnum = st.number_input("Broj treninga", min_value=0, step=1)
        thrs = st.number_input("Sati", min_value=0.0, step=0.5)
        if st.button("Spremi sudjelovanje"):
            for p in picks2:
                mid = int(p.split(" – ")[0])
                conn.execute("""INSERT INTO camp_attendance (camp_id,member_id,trainings,hours)
                                VALUES (?,?,?,?)""", (camp_id, mid, int(tnum), float(thrs)))
            conn.commit(); st.success("Sudjelovanje spremljeno.")

    # Statistika za mjesec
    st.markdown("---")
    st.subheader("Statistika prisustva (mjesec)")
    months = sorted(list(set([s[0][:7] for s in conn.execute("SELECT start_ts FROM sessions").fetchall() if s[0]])))
    month = st.selectbox("Mjesec (YYYY-MM)", months if months else [])
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
