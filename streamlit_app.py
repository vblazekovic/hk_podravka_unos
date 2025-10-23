# streamlit_app.py — HK Podravka • Sustav (s uvoz/izvoz Excel)
# (skraćena verzija + nova stranica "📝 Online upis" i UI kozmetika s logom)
import io, os, json, sqlite3
from io import BytesIO
from urllib.parse import quote_plus
from datetime import datetime, date
from typing import List, Optional, Tuple
import pandas as pd
import streamlit as st

# ------------------------- Osnovno / Branding -------------------------
ASSETS_DIR = "assets"
LOGO_PATH = os.path.join(ASSETS_DIR, "logo.jpg")
st.set_page_config(page_title="HK Podravka — Sustav", page_icon=LOGO_PATH if os.path.isfile(LOGO_PATH) else "🥇", layout="wide", initial_sidebar_state="collapsed")

BRAND_BAR = """
<style>
/* Mobile tweaks */
@media (max-width: 640px) {
  html, body { font-size: 16px; }
  section.main > div { padding-top: 0.5rem !important; }
  h1, h2, h3 { margin: 0.5rem 0 0.35rem 0; }
}
/* Buttons/inputs */
.stButton button { padding: 0.9rem 1.15rem; border-radius: 12px; font-weight: 600; }
.stTextInput input, .stNumberInput input, .stDateInput input, .stTimeInput input,
.stSelectbox [data-baseweb="select"] > div, .stMultiSelect [data-baseweb="select"] > div {
  min-height: 44px; font-size: 1rem;
}
[data-testid="stDataFrame"] div[role="grid"] { overflow-x: auto !important; }
.stFileUploader > section div { word-break: break-word; }
header { border-bottom: 1px solid #eee;}
</style>
"""
st.markdown(BRAND_BAR, unsafe_allow_html=True)

left, mid = st.columns([1,6])
with left:
    if os.path.isfile(LOGO_PATH):
        st.image(LOGO_PATH, width=88)
with mid:
    st.title("HK Podravka — Sustav")
    st.caption("Sve na jednom mjestu: natjecanja, rezultati, članovi, prisustvo, obavijesti i online upis.")

DB_PATH = "data/rezultati_knjiga1.sqlite"
UPLOAD_ROOT = "data/uploads"
UPLOADS = {
    "members": os.path.join(UPLOAD_ROOT, "members"),
    "competitions": os.path.join(UPLOAD_ROOT, "competitions"),
    "trainers": os.path.join(UPLOAD_ROOT, "trainers"),
    "veterans": os.path.join(UPLOAD_ROOT, "veterans"),
    "club": os.path.join(UPLOAD_ROOT, "club"),
}
CLUB_EMAIL = "hsk.podravka@gmail.com"
ADMIN_EMAIL = "vblazekovic76@gmail.com"

# ------------------------- Helperi (DB / I/O) -------------------------
def ensure_dirs():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    for p in UPLOADS.values(): os.makedirs(p, exist_ok=True)

def get_conn():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def df_from_sql(q: str, params: tuple = ()):
    conn = get_conn(); df = pd.read_sql(q, conn, params=params); conn.close(); return df

def exec_sql(q: str, params: tuple = ()):
    conn = get_conn(); cur = conn.cursor(); cur.execute(q, params); conn.commit(); lid = cur.lastrowid; conn.close(); return lid

def exec_many(q: str, rows: List[tuple]):
    conn = get_conn(); cur = conn.cursor(); cur.executemany(q, rows); conn.commit(); conn.close()

def save_upload(file, subfolder: str) -> Optional[str]:
    if not file: return None
    ensure_dirs(); safe = file.name.replace("/", "_").replace("\\", "_")
    path = os.path.join(UPLOADS[subfolder], safe)
    with open(path, "wb") as out: out.write(file.read())
    return path

def simulate_email(to_list: List[str], subject: str, body: str) -> tuple[bool, str]:
    if not to_list: return False, "Nema primatelja."
    return True, f"SIMULACIJA — e-mail bi bio poslan na: {', '.join(sorted(set(to_list)))}"

def _normalize_dates(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            try: df[c] = pd.to_datetime(df[c]).dt.date.astype(str)
            except Exception: df[c] = df[c].astype(str)
    return df

# ------------------------- DB init (pojednostavljena) -------------------------
def init_db():
    conn = get_conn(); cur = conn.cursor()
    cur.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ime TEXT, prezime TEXT, datum_rodjenja TEXT, godina_rodjenja INTEGER,
        email_sportas TEXT, email_roditelj TEXT,
        telefon_sportas TEXT, telefon_roditelj TEXT,
        clanski_broj TEXT, oib TEXT, adresa TEXT, grupa_trening TEXT, foto_path TEXT,
        zdr_potvrda_path TEXT, zdr_valjan_do TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS trainers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ime TEXT, prezime TEXT, datum_rodjenja TEXT, oib TEXT,
        osobna_broj TEXT, iban TEXT, telefon TEXT, email TEXT,
        foto_path TEXT, ugovor_path TEXT, ugovor_valjan_do TEXT,
        napomena TEXT, created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS competitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        redni_broj INTEGER UNIQUE, godina INTEGER, datum TEXT, datum_kraj TEXT,
        natjecanje TEXT, ime_natjecanja TEXT, stil_hrvanja TEXT,
        mjesto TEXT, drzava TEXT, kratica_drzave TEXT,
        nastupilo_podravke INTEGER, ekipno TEXT, trener TEXT,
        napomena TEXT, link_rezultati TEXT, galerija_json TEXT, vijest TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competition_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
        ime_prezime TEXT, spol TEXT, plasman TEXT, kategorija TEXT, uzrast TEXT,
        borbi INTEGER, pobjeda INTEGER, izgubljenih INTEGER,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
        datum TEXT NOT NULL, termin TEXT, grupa TEXT, prisutan INTEGER NOT NULL DEFAULT 1, trajanje_min INTEGER DEFAULT 90,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS trainer_attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trainer_id INTEGER NOT NULL REFERENCES trainers(id) ON DELETE CASCADE,
        datum TEXT NOT NULL, grupa TEXT, vrijeme_od TEXT, vrijeme_do TEXT, trajanje_min INTEGER, napomena TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS club_info (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        naziv TEXT, adresa TEXT, grad TEXT, oib TEXT, iban TEXT, email TEXT, telefon TEXT, web TEXT, logo_path TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS club_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, file_path TEXT, uploaded_at TEXT DEFAULT (datetime('now'))
    );
    """); conn.commit()
    # default 1 row in club_info
    cur.execute("SELECT COUNT(*) FROM club_info")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO club_info (id, naziv, email, logo_path, updated_at) VALUES (1, 'HK Podravka', ?, ?, datetime('now'))",
                    ("hsk.podravka@gmail.com", LOGO_PATH if os.path.isfile(LOGO_PATH) else None,))
        conn.commit()
    conn.close()
init_db()

# ------------------------- Navigacija -------------------------
page = st.sidebar.radio("Navigacija", [
    "📝 Online upis", "➕ Natjecanja", "🧾 Rezultati", "👤 Članovi", "📅 Prisustvo",
    "📘 Prisustvo trenera", "🏋️ Treneri", "🎖️ Veterani", "📣 Obavijesti", "🏛️ Klub", "⚙️ Dijagnostika"
])

# ------------------------- 📝 Online upis -------------------------
if page == "📝 Online upis":
    st.subheader("📝 Online upis — Pristupnica i GDPR privola")
    st.caption("Ulogiraj se OIB-om djeteta, ispuni podatke, potvrdi privolu i preuzmi PDF.")
    if "oib" not in st.session_state: st.session_state.oib = ""
    with st.form("login"):
        oib_in = st.text_input("OIB djeteta", value=st.session_state.oib, max_chars=20)
        if st.form_submit_button("Nastavi →"):
            oib_in = (oib_in or "").strip().replace(" ", "")
            if len(oib_in) < 8: st.error("Unesite ispravan OIB (minimalno 8 znakova).")
            else: st.session_state.oib = oib_in
    if not st.session_state.oib: st.stop()

    st.success(f"Ulogirani OIB: {st.session_state.oib}")
    GDPR_TEXT = """
Sukladno Zakonu o zaštiti osobnih podataka i Općoj uredbi (EU) 2016/679 (GDPR) ...
(tekst možete urediti u kodu)
"""
    with st.form("upis"):
        c1, c2 = st.columns(2)
        with c1:
            ime = st.text_input("Ime djeteta *"); prezime = st.text_input("Prezime djeteta *")
            datum_rod = st.date_input("Datum rođenja", value=date(2012,1,1))
            adresa = st.text_input("Adresa stanovanja"); skola = st.text_input("Škola / Fakultet")
            dokument_br = st.text_input("Broj osobne iskaznice / putovnice")
        with c2:
            roditelj = st.text_input("Ime i prezime roditelja/staratelja *")
            tel_roditelj = st.text_input("Telefon/mobitel roditelja *")
            email_roditelj = st.text_input("E-mail roditelja *")
            zdrav_potvrda = st.selectbox("Potvrda o zdravstvenoj sposobnosti", ["NE", "DA"], index=1)
            med_stanja = st.text_area("Specifična medicinska stanja (opcionalno)")
            foto_suglasnost = st.selectbox("Suglasnost za foto/video objave", ["NE", "DA"], index=1)
        with st.expander("Prikaži tekst privole", expanded=False): st.write(GDPR_TEXT)
        prihvacam = st.checkbox("Prihvaćam izjavu/privolu i točno sam naveo/la podatke *", value=False)
        submitted = st.form_submit_button("💾 Generiraj pristupnicu (PDF)")

    def _req(x): return bool((x or '').strip())
    if submitted:
        if not (_req(ime) and _req(prezime) and _req(roditelj) and _req(tel_roditelj) and _req(email_roditelj)):
            st.error("Molimo ispunite sva obavezna polja (*)."); st.stop()
        if not prihvacam: st.error("Za nastavak morate potvrditi privolu."); st.stop()

        # PDF build (reportlab)
        PDF_OK=True
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import mm
            from reportlab.pdfgen import canvas
            from reportlab.lib.utils import ImageReader
        except Exception:
            PDF_OK=False
        from io import BytesIO
        today = date.today().strftime("%Y-%m-%d")
        pdf_name = f"Pristupnica_{prezime}_{ime}_{st.session_state.oib}_{today}.pdf"
        if PDF_OK:
            bio = BytesIO(); c = canvas.Canvas(bio, pagesize=A4); W,H = A4; y = H - 30*mm
            try:
                if os.path.isfile(LOGO_PATH):
                    c.drawImage(ImageReader(LOGO_PATH), 20*mm, y-20*mm, width=30*mm, height=20*mm, preserveAspectRatio=True, mask='auto')
            except Exception: pass
            c.setFont("Helvetica-Bold", 16); c.drawString(60*mm, y-8*mm, "HK Podravka — Pristupnica i izjava")
            c.setFont("Helvetica", 10); c.drawString(60*mm, y-14*mm, f"Datum: {today} | OIB: {st.session_state.oib}")
            y -= 28*mm
            def line(lbl,val):
                nonlocal y
                c.setFont("Helvetica-Bold", 11); c.drawString(20*mm, y, lbl)
                c.setFont("Helvetica", 11); c.drawString(65*mm, y, str(val or '')); y -= 7*mm
            line("Ime i prezime djeteta:", f"{ime} {prezime}")
            line("Datum rođenja:", datum_rod.strftime("%d.%m.%Y."))
            line("Adresa:", adresa)
            line("Škola / Fakultet:", skola)
            line("Broj osobne/putovnice:", dokument_br)
            line("Roditelj/staratelj:", roditelj)
            line("Telefon roditelja:", tel_roditelj)
            line("E-mail roditelja:", email_roditelj)
            line("Zdravstvena potvrda:", zdrav_potvrda)
            line("Specifična medicinska stanja:", med_stanja)
            line("Foto/video suglasnost:", foto_suglasnost)
            y -= 3*mm; c.setFont("Helvetica-Bold", 12); c.drawString(20*mm, y, "Privola (sažetak):")
            y -= 6*mm; c.setFont("Helvetica", 9)
            from textwrap import wrap
            for para in GDPR_TEXT.splitlines():
                for ln in wrap(para, width=95):
                    c.drawString(20*mm, y, ln); y -= 5*mm
                    if y < 30*mm: c.showPage(); y = H - 20*mm; c.setFont("Helvetica", 9)
                y -= 3*mm
            y = max(y, 40*mm); c.setFont("Helvetica", 11)
            c.drawString(20*mm, 35*mm, "U _____________________________ ; ________________ g.")
            c.line(30*mm, 25*mm, 90*mm, 25*mm); c.drawString(35*mm, 22*mm, "Član kluba — potpis")
            c.line(110*mm, 25*mm, 180*mm, 25*mm); c.drawString(120*mm, 22*mm, "Roditelj/staratelj — potpis")
            c.showPage(); c.save(); pdf_bytes = bio.getvalue(); bio.close()
            st.download_button("⬇️ Preuzmi pristupnicu (PDF)", data=pdf_bytes, file_name=pdf_name, mime="application/pdf")
            st.info(f"Pošalji e-mail klubu: mailto:{CLUB_EMAIL}")
        else:
            st.warning("PDF generator nije dostupan u okruženju.")

# ------------------------- Placeholderi za ostale originale -------------------------
elif page == "➕ Natjecanja":
    st.info("Ovdje ide tvoj postojeći modul za Natjecanja (iz tvoje verzije).")
elif page == "🧾 Rezultati":
    st.info("Ovdje ide tvoj postojeći modul za Rezultate.")
elif page == "👤 Članovi":
    st.info("Ovdje ide tvoj postojeći modul za Članove (uz zdrav. potvrde).")
elif page == "📅 Prisustvo":
    st.info("Ovdje ide tvoja evidencija prisustva.")
elif page == "📘 Prisustvo trenera":
    st.info("Ovdje ide evidencija prisustva trenera.")
elif page == "🏋️ Treneri":
    st.info("Ovdje ide modul Treneri (ugovori + isteci).")
elif page == "🎖️ Veterani":
    st.info("Ovdje ide modul Veterani.")
elif page == "📣 Obavijesti":
    st.info("Ovdje ide slanje obavijesti (simulacija e-mail, WhatsApp linkovi, SMS Twilio).")
elif page == "🏛️ Klub":
    st.info("Ovdje ide upravljanje podacima o klubu + dokumenti.")
else:
    st.write("Dijagnostika / info okruženja.")
