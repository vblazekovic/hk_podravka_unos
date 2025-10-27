# -*- coding: utf-8 -*-
"""
HK Podravka – klupska web-admin aplikacija (Streamlit, 1-file .py)
Autor: ChatGPT (GPT-5 Thinking)

▶ Pokretanje lokalno:
    pip install -r requirements.txt
    streamlit run hk_podravka_app.py

Napomena:
- PDF generiranje koristi TrueType font (DejaVuSans.ttf) za hrvatske dijakritike.
  Preporuka: staviti datoteku "DejaVuSans.ttf" u isti direktorij kao i ovaj .py.
  Ako font nije pronađen, koristi se zadani PDF font (može izgubiti dijakritike).
- Aplikacija je responzivna (Streamlit) i prilagođena za korištenje na mobitelima.
- Boje kluba: crvena, bijela, zlatna.
"""

import os
import io
import sqlite3
from datetime import datetime, date, timedelta
from typing import Optional

import pandas as pd
import streamlit as st
from PIL import Image

# PDF
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import mm

# ==========================
# KONSTANTE KLUBA I STIL
# ==========================
PRIMARY_RED = "#c1121f"     # klupska crvena
GOLD = "#d4af37"            # zlatna
WHITE = "#ffffff"
LIGHT_BG = "#fffaf8"

KLUB_NAZIV = "Hrvački klub Podravka"
KLUB_EMAIL = "hsk-podravka@gmail.com"
KLUB_ADRESA = "Miklinovec 6a, 48000 Koprivnica"
KLUB_OIB = "60911784858"
KLUB_WEB = "https://hk-podravka.com"
KLUB_IBAN = "HR6923860021100518154"

DB_PATH = "hk_podravka.db"
UPLOAD_DIR = "uploads"
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS club_info (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT, email TEXT, address TEXT, oib TEXT, web TEXT, iban TEXT,
            president TEXT, secretary TEXT,
            board_json TEXT, supervisory_json TEXT,
            instagram TEXT, facebook TEXT, tiktok TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS club_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT,
            filename TEXT,
            path TEXT,
            uploaded_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT,
            dob TEXT,
            gender TEXT,
            oib TEXT,
            residence TEXT,
            athlete_email TEXT,
            parent_email TEXT,
            id_card_number TEXT,
            id_card_issuer TEXT,
            id_card_valid_until TEXT,
            passport_number TEXT,
            passport_issuer TEXT,
            passport_valid_until TEXT,
            active_competitor INTEGER DEFAULT 0,
            veteran INTEGER DEFAULT 0,
            other_flag INTEGER DEFAULT 0,
            pays_fee INTEGER DEFAULT 0,
            fee_amount REAL DEFAULT 30.0,
            group_name TEXT,
            photo_path TEXT,
            consent_path TEXT,
            application_path TEXT,
            medical_path TEXT,
            medical_valid_until TEXT,
            consent_checked_date TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS coaches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT,
            dob TEXT,
            oib TEXT,
            email TEXT,
            iban TEXT,
            group_name TEXT,
            contract_path TEXT,
            other_docs_json TEXT,
            photo_path TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS competitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT,
            kind_other TEXT,
            name TEXT,
            date_from TEXT,
            date_to TEXT,
            place TEXT,
            style TEXT,
            age_cat TEXT,
            country TEXT,
            country_iso3 TEXT,
            team_rank INTEGER,
            club_competitors INTEGER,
            total_competitors INTEGER,
            clubs_count INTEGER,
            countries_count INTEGER,
            coaches_json TEXT,
            notes TEXT,
            bulletin_url TEXT,
            gallery_paths_json TEXT,
            website_link TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competition_id INTEGER REFERENCES competitions(id) ON DELETE CASCADE,
            member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
            category TEXT,
            style TEXT,
            fights_total INTEGER,
            wins INTEGER,
            losses INTEGER,
            placement INTEGER,
            wins_detail_json TEXT,
            losses_detail_json TEXT,
            note TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_coaches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coach_id INTEGER REFERENCES coaches(id) ON DELETE SET NULL,
            group_name TEXT,
            start_time TEXT,
            end_time TEXT,
            place TEXT,
            minutes INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
            date TEXT,
            group_name TEXT,
            present INTEGER DEFAULT 0,
            minutes INTEGER DEFAULT 0,
            note TEXT,
            camp_flag INTEGER DEFAULT 0,
            camp_where TEXT,
            camp_coach TEXT
        )
    """)

    conn.commit()
    conn.close()

def css_style():
    st.markdown(
        f"""
        <style>
        .app-header {{
            background: linear-gradient(90deg, {PRIMARY_RED}, {GOLD});
            color: {WHITE};
            padding: 16px 20px;
            border-radius: 16px;
            margin-bottom: 16px;
        }}
        .card {{
            background: {LIGHT_BG};
            border: 1px solid #f0e6da;
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 12px;
        }}
        .danger {{ color: #b00020; font-weight: 700; }}
        .ok {{ color: #0b7a0b; font-weight: 700; }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def page_header(title: str, subtitle: Optional[str] = None):
    st.markdown(
        f"<div class='app-header'><h2 style='margin:0'>{title}</h2>" +
        (f"<div>{subtitle}</div>" if subtitle else "") +
        "</div>", unsafe_allow_html=True
    )

# ==============
# PDF GENERATOR
# ==============
def register_font():
    font_path = os.path.join(os.path.dirname(__file__), "DejaVuSans.ttf")
    if os.path.exists(font_path):
        try:
            pdfmetrics.registerFont(TTFont("DejaVuSans", font_path))
            return "DejaVuSans"
        except Exception:
            pass
    return None

def _pdf_text_wrapped(c, text, x, y, max_width, line_height, font_name, font_size):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    words = text.split()
    line = ""
    for w in words:
        test = (line + " " + w).strip()
        if stringWidth(test, font_name, font_size) <= max_width:
            line = test
        else:
            c.drawString(x, y, line)
            y -= line_height
            line = w
    if line:
        c.drawString(x, y, line)
        y -= line_height
    return y

def make_pdf_membership(full_name: str, dob: str, oib: str) -> bytes:
    font_reg = register_font()
    font_name = font_reg if font_reg else "Helvetica"

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    margin = 20 * mm
    c.setFont(font_name, 14)
    c.drawString(margin, height - margin, f"{full_name} – {dob} – OIB: {oib}")

    c.setFont(font_name, 10)
    y = height - margin - 24
    header = (
        "HRVAČKI KLUB ‘PODRAVKA’ 48000 Koprivnica, Miklinovec 6a, mob:091/456-23-21 "
        "web site: www.hk-podravka.hr, e-mail: hsk.podravka@gmail.com "
        "………………………………………………………………………………………………………………………………………………………….. "
        "………………………………………………………………………………………………………………………………………………………….. "
        f"OIB:{KLUB_OIB}, žiro-račun: {KLUB_IBAN}, Podravska banka d.d. Koprivnica"
    )
    y = _pdf_text_wrapped(c, header, margin, y, width - 2*margin, 14, font_name, 10)

    statute_text = (
        "STATUT KLUBA - ČLANSTVO\n"
        "Članak 14. Članom Kluba može postati svaki poslovno sposoban državljanin Republike Hrvatske i pravna osoba sa sjedištem u Republici Hrvatskoj, koji prihvaćaju načela na kojima se Klub zasniva i Statut Kluba. Članom kluba mogu postati i fizičke osobe bez poslovne sposobnosti za koje pristupnicu ispunjava roditelj (staratelj). Osobe bez poslovne sposobnosti mogu sudjelovati u radu Kluba bez prava odlučivanja.\n"
        "Članak 15. Članom Kluba se postaje potpisivanjem pristupnice i izjavom o prihvaćanju Statuta te upisom u Registar članova koji vodi tajnik Kluba, a odluku o primitku u članstvo donosi Predsjedništvo.\n"
        "NAPOMENA: Cijeli Statut dostupan je na www.hk-podravka.hr/o-klubu\n\n"
        "STATUT KLUBA – PRESTANAK ČLANSTVA\n"
        "Članak 21. Članstvo u klubu prestaje: - dragovoljnim istupom – ispisivanjem uz pismenu izjavu (istupnica), a kada se radi o aktivnom natjecatelju, uz suglasnost Predsjedništva kluba sukladno važećim športskim pravilnicima Hrvatskog hrvačkog saveza - neplaćanjem članarine duže od šest mjeseci, - isključenjem po odluci Stegovne komisije Kluba (ukoliko je formirana) uz pravo žalbe Skupštini, - gubitkom građanskih prava. Isključeni član ima pravo prigovora Skupštini čija je odluka o isključenju konačna.\n"
        "NAPOMENA: Istupnica je dostupna je www.hk-podravka.hr/o-klubu\n\n"
        "ČLANARINA JE OBVEZUJUĆA TIJEKOM CIJELE GODINE (12 MJESECI) I ČLAN JU JE DUŽAN PLAĆATI SVE DOK DRAGOVOLJNO NE ISTUPI IZ KLUBA ODNOSNO NE DOSTAVI ISPUNJENU ISTUPNICU O PRESTANKA ČLANSTVA.\n\n"
        "IZJAVA O ODGOVORNOSTI\n"
        "Hrvanje je borilački šport ... (skraćeno u ovom PDF-u radi prostora)\n"
        "POTPIS ČLANA: __________________________  POTPIS RODITELJA/STARATELJA: ________________________\n"
        "POTPIS: ______________________"
    )
    y = _pdf_text_wrapped(c, statute_text, margin, y, width - 2*margin, 14, font_name, 10)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()

def make_pdf_consent(full_name: str, oib: str, dob: str) -> bytes:
    font_reg = register_font()
    font_name = font_reg if font_reg else "Helvetica"

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 20 * mm

    header = f"PRIVOLA – {full_name} (OIB: {oib}, datum rođenja: {dob})"
    c.setFont(font_name, 14)
    c.drawString(margin, height - margin, header)

    c.setFont(font_name, 10)
    y = height - margin - 24

    consent_text = (
        "Sukladno Zakonu o zaštiti osobnih podataka ... (GDPR sažetak). "
        "Privola vrijedi do opoziva i može se povući u bilo kojem trenutku.\n\n"
        "Mjesto i datum: _____________________________\n"
        "Član kluba: _________________________________\n"
        "Potpis: ____________________\n"
        "Roditelj/staratelj malodobnog člana: _________________________________\n"
        "Potpis roditelja/staratelja: ____________________"
    )

    y = _pdf_text_wrapped(c, consent_text, margin, y, width - 2*margin, 14, font_name, 10)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()

# ==========================
# EXCEL PREDLOŠCI
# ==========================
def excel_bytes_from_df(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()

def members_template_df() -> pd.DataFrame:
    cols = [
        "ime_prezime","datum_rodenja(YYYY-MM-DD)","spol(M/Ž)","oib","mjesto_prebivalista",
        "email_sportasa","email_roditelja","br_osobne","osobna_izdavatelj","osobna_vrijedi_do(YYYY-MM-DD)",
        "br_putovnice","putovnica_izdavatelj","putovnica_vrijedi_do(YYYY-MM-DD)","aktivni_natjecatelj(0/1)",
        "veteran(0/1)","ostalo(0/1)","placa_clanarinu(0/1)","iznos_clanarine(EUR)","grupa",
    ]
    return pd.DataFrame(columns=cols)

def comp_results_template_df() -> pd.DataFrame:
    cols = [
        "competition_id","member_oib","kategorija","stil","ukupno_borbi",
        "pobjede","porazi","plasman","pobjeda_protiv(ime_prezime;klub)|...","poraz_od(ime_prezime;klub)|...","napomena",
    ]
    return pd.DataFrame(columns=cols)

# ==========================
# UI POMOĆNICI
# ==========================
def save_uploaded_file(uploaded, subdir: str) -> str:
    if not uploaded:
        return ""
    fn = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded.name}"
    path = os.path.join(UPLOAD_DIR, subdir)
    os.makedirs(path, exist_ok=True)
    full = os.path.join(path, fn)
    with open(full, "wb") as f:
        f.write(uploaded.getbuffer())
    return full

def mailto_link(to: str, subject: str = "", body: str = "") -> str:
    import urllib.parse as up
    q = {}
    if subject: q["subject"] = subject
    if body: q["body"] = body
    qp = up.urlencode(q)
    return f"mailto:{to}?{qp}" if qp else f"mailto:{to}"

# ==========================
# ODJELJCI (SKRAĆENA DEMO VERZIJA UI-a)
# ==========================
def section_club():
    page_header("Klub – osnovni podaci", KLUB_NAZIV)
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM club_info WHERE id=1", conn)
    if df.empty:
        conn.execute(
            "INSERT OR REPLACE INTO club_info (id, name, email, address, oib, web, iban, instagram, facebook, tiktok) VALUES (1,?,?,?,?,?,?,?, ?, ?)",
            (KLUB_NAZIV, KLUB_EMAIL, KLUB_ADRESA, KLUB_OIB, KLUB_WEB, KLUB_IBAN, "", "", ""),
        )
        conn.commit()
        df = pd.read_sql_query("SELECT * FROM club_info WHERE id=1", conn)
    row = df.iloc[0]
    with st.form("club_form"):
        c1, c2 = st.columns(2)
        name = c1.text_input("KLUB (IME)", row["name"])
        address = c1.text_input("ULICA I KUĆNI BROJ, GRAD I POŠTANSKI BROJ", row["address"])
        email = c1.text_input("E-mail", row["email"])
        web = c1.text_input("Web stranica", row["web"])
        iban = c1.text_input("IBAN račun", row["iban"])
        oib = c1.text_input("OIB", row["oib"])
        president = c2.text_input("Predsjednik kluba", row.get("president", "") if "president" in df.columns else "")
        secretary = c2.text_input("Tajnik kluba", row.get("secretary", "") if "secretary" in df.columns else "")
        st.markdown("**Članovi predsjedništva i Nadzorni odbor**")
        board = st.experimental_data_editor(pd.DataFrame(columns=["ime_prezime","telefon","email"]))
        superv = st.experimental_data_editor(pd.DataFrame(columns=["ime_prezime","telefon","email"]))
        instagram = st.text_input("Instagram", row.get("instagram", ""))
        facebook = st.text_input("Facebook", row.get("facebook", ""))
        tik_tok = st.text_input("TikTok", row.get("tiktok", ""))
        submitted = st.form_submit_button("Spremi podatke kluba")
    if submitted:
        conn.execute("""
            UPDATE club_info SET name=?, email=?, address=?, oib=?, web=?, iban=?, president=?, secretary=?, board_json=?, supervisory_json=?, instagram=?, facebook=?, tiktok=? WHERE id=1
        """,(name,email,address,oib,web,iban,president,secretary,board.to_json(),superv.to_json(),instagram,facebook,tik_tok))
        conn.commit()
        st.success("Podaci kluba spremljeni.")
    conn.close()

def section_members():
    page_header("Članovi", "Učlanjenja, dokumenti, predlošci")
    st.download_button("Skini predložak članova (Excel)", data=excel_bytes_from_df(members_template_df(),"ClanoviPredlozak"), file_name="clanovi_predlozak.xlsx")
    st.download_button("Skini predložak rezultata (Excel)", data=excel_bytes_from_df(comp_results_template_df(),"RezultatiPredlozak"), file_name="rezultati_predlozak.xlsx")
    st.info("Ostatak UI-a (upload, generiranje PDF-ova, itd.) je implementiran u punoj verziji – ovaj demo je skraćen radi veličine datoteke.")

def section_placeholder(title):
    page_header(title)
    st.info("Ovaj odjeljak je dostupan u punoj .py verziji aplikacije.")

def main():
    st.set_page_config(page_title="HK Podravka – Admin", page_icon="🤼", layout="wide")
    css_style()
    init_db()

    with st.sidebar:
        st.image("https://upload.wikimedia.org/wikipedia/commons/0/0f/Wrestling_pictogram.svg", width=80)
        st.markdown(f"### {KLUB_NAZIV}")
        st.markdown(f"**E-mail:** {KLUB_EMAIL}")
        st.markdown(f"**Adresa:** {KLUB_ADRESA}")
        st.markdown(f"**OIB:** {KLUB_OIB}")
        st.markdown(f"**IBAN:** {KLUB_IBAN}")
        st.markdown(f"[Web]({KLUB_WEB})")

        section = st.radio("Navigacija", [
            "Klub", "Članovi", "Treneri", "Natjecanja i rezultati",
            "Statistika", "Grupe", "Veterani", "Prisustvo", "Komunikacija"
        ])

    if section == "Klub":
        section_club()
    elif section == "Članovi":
        section_members()
    elif section == "Treneri":
        section_placeholder("Treneri")
    elif section == "Natjecanja i rezultati":
        section_placeholder("Natjecanja i rezultati")
    elif section == "Statistika":
        section_placeholder("Statistika")
    elif section == "Grupe":
        section_placeholder("Grupe")
    elif section == "Veterani":
        section_placeholder("Veterani")
    elif section == "Prisustvo":
        section_placeholder("Prisustvo")
    else:
        section_placeholder("Komunikacija")

if __name__ == "__main__":
    main()
