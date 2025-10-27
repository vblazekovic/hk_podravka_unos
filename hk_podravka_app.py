
# hk_podravka_app.py
# -----------------------------------------------------------------------------
# Streamlit app for HK Podravka — klub & evidencije
# Colors: red/white/gold brand styling. Mobile-friendly by Streamlit defaults.
# -----------------------------------------------------------------------------

import os, json, sqlite3, re, hashlib
from io import BytesIO
from datetime import date, datetime
from typing import Optional, Tuple, List

import pandas as pd
import streamlit as st

# ===================== APP CONFIG / THEME =====================
st.set_page_config(page_title="HK Podravka – klub & evidencije", layout="wide")
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "app.db")

# Brand colors
CLR_RED = "#c1121f"
CLR_GOLD = "#d4af37"
CLR_WHITE = "#ffffff"

# ===================== DEFAULT CLUB INFO =====================
CLUB_DEFAULTS = {
    "club_name": "Hrvački klub Podravka",
    "club_email": "hsk-podravka@gmail.com",
    "club_phone": "091/456-23-21",
    "club_addr_street": "Miklinovec 6a",
    "club_addr_cityzip": "48000 Koprivnica",
    "club_oib": "60911784858",
    "club_iban": "HR6923860021100518154",
    "club_web": "https://hk-podravka.com",
    "social_instagram": "",
    "social_facebook": "",
    "social_tiktok": "",
}

COUNTRIES = [
    "Hrvatska","Slovenija","Srbija","Bosna i Hercegovina","Crna Gora","Sjeverna Makedonija","Albanija",
    "Austrija","Mađarska","Italija","Njemačka","Švicarska","Francuska","Španjolska","Belgija",
    "Nizozemska","Poljska","Češka","Slovačka","Rumunjska","Bugarska","Grčka","Turska",
    "Ujedinjeno Kraljevstvo","Irska","Portugal","Norveška","Švedska","Finska","Danska","Island",
    "SAD","Kanada"
]

CITY_TO_COUNTRY = {
    "Zagreb":"Hrvatska","Split":"Hrvatska","Rijeka":"Hrvatska","Osijek":"Hrvatska","Koprivnica":"Hrvatska",
    "Ljubljana":"Slovenija","Maribor":"Slovenija","Beograd":"Srbija","Novi Sad":"Srbija",
    "Sarajevo":"Bosna i Hercegovina","Mostar":"Bosna i Hercegovina","Tuzla":"Bosna i Hercegovina"
}

ISO3 = {
    "Hrvatska":"HRV","Slovenija":"SVN","Srbija":"SRB","Bosna i Hercegovina":"BIH","Crna Gora":"MNE",
    "Sjeverna Makedonija":"MKD","Albanija":"ALB","Austrija":"AUT","Mađarska":"HUN","Italija":"ITA",
    "Njemačka":"DEU","Švicarska":"CHE","Francuska":"FRA","Španjolska":"ESP","Belgija":"BEL","Nizozemska":"NLD",
    "Poljska":"POL","Češka":"CZE","Slovačka":"SVK","Rumunjska":"ROU","Bugarska":"BGR","Grčka":"GRC","Turska":"TUR",
    "Ujedinjeno Kraljevstvo":"GBR","Irska":"IRL","Portugal":"PRT","Norveška":"NOR","Švedska":"SWE","Finska":"FIN",
    "Danska":"DNK","Island":"ISL","SAD":"USA","Kanada":"CAN"
}

# ===================== STYLE =====================
st.markdown(f"""
<style>
:root {{
  --brand-red: {CLR_RED};
  --brand-gold: {CLR_GOLD};
  --brand-white: {CLR_WHITE};
}}
/* headings */
h1, h2, h3, h4, h5, h6 {{ color: var(--brand-red) !important; }}
/* buttons */
.stButton>button {{ background: var(--brand-red); color: white; border-radius: 10px; }}
.stButton>button:hover {{ background: #9c0e18; }}
/* tables */
[data-testid="stTable"] thead th {{ background: var(--brand-gold); color:black; }}
/* badges */
.badge {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; margin-left:6px; }}
.badge-green {{ background:#e8f5e9; color:#1b5e20; }}
.badge-orange {{ background:#fff3e0; color:#e65100; }}
.badge-red {{ background:#ffebee; color:#b71c1c; }}
/* cards */
.section {{ border:1px solid #eee; border-left:6px solid var(--brand-red);
           border-radius:10px; padding:16px; margin-bottom:14px; background:white; }}
.preview {{ max-height:160px; border-radius:8px; border:1px solid #eee; }}
</style>
""", unsafe_allow_html=True)

# ===================== HELPERS =====================
def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def exec_sql(q, params=()):
    with get_conn() as c:
        c.execute(q, params); c.commit()

def df_from_sql(q, params=()):
    with get_conn() as c:
        return pd.read_sql_query(q, c, params=params)

def _safe_int(x, default=None):
    try: return int(x)
    except Exception: return default

def _nz(x, default=""):
    return x if (x is not None and str(x).strip()!="") else default

def guess_country_for_city(city):
    if not city: return None
    for k,v in CITY_TO_COUNTRY.items():
        if str(city).strip().lower()==k.lower(): return v
    return None

def iso3(country:str) -> str:
    return ISO3.get(country, (country or "XXX")[:3].upper())

def status_badge(expiry: Optional[str], warn_days:int=30) -> str:
    if not expiry: return "⚪"
    try: d = datetime.fromisoformat(str(expiry)).date()
    except Exception: return "⚪"
    days = (d - date.today()).days
    if days < 0: return "🔴 isteklo"
    if days <= warn_days: return f"🟠 {days} dana"
    return f"🟢 {days} dana"

def get_setting(key, default=None):
    try:
        df = df_from_sql("SELECT value FROM settings WHERE key=?", (key,))
        if not df.empty: return df["value"].iloc[0]
    except Exception:
        pass
    return default

def set_setting(key, value):
    exec_sql("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,value))

def ensure_defaults():
    for k,v in CLUB_DEFAULTS.items():
        if get_setting(k) is None:
            set_setting(k, v)

def save_uploaded(prefix:str, file) -> Optional[str]:
    if not file: return None
    ext = file.name.split(".")[-1].lower()
    path = os.path.join(UPLOAD_DIR, f"{prefix}_{int(datetime.now().timestamp())}.{ext}")
    with open(path, "wb") as f: f.write(file.read())
    return path

def try_make_pdf(filename:str, title:str, body:str) -> str:
    """Generate a simple PDF (uses reportlab if available, else .txt)."""
    path_pdf = os.path.join(DATA_DIR, filename)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import cm
        c = canvas.Canvas(path_pdf, pagesize=A4)
        width, height = A4
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2*cm, height-2*cm, title)
        c.setFont("Helvetica", 10)
        y = height-3*cm
        for line in body.splitlines():
            chunks = re.findall(".{1,95}", line) or [""]
            for chunk in chunks:
                c.drawString(2*cm, y, chunk)
                y -= 14
                if y < 2*cm:
                    c.showPage(); c.setFont("Helvetica", 10); y = height-2*cm
        c.showPage(); c.save()
        return path_pdf
    except Exception:
        fallback = path_pdf.replace(".pdf",".txt")
        with open(fallback,"w",encoding="utf-8") as f:
            f.write(title+"\n\n"+body)
        return fallback

def make_token(email:str, oib:str) -> str:
    m = hashlib.sha256()
    m.update((email.strip().lower()+"|"+oib.strip()).encode("utf-8"))
    return m.hexdigest()[:16]

# ===================== DB INIT =====================
def init_db():
    ensure_dirs()
    with get_conn() as c:
        cur = c.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);

        /* Club personnel */
        CREATE TABLE IF NOT EXISTS club_persons(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT, -- predsjednik, tajnik, predsjednistvo, nadzorni
            ime TEXT, prezime TEXT, kontakt TEXT, email TEXT
        );

        /* Club docs */
        CREATE TABLE IF NOT EXISTS club_docs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naziv TEXT, opis TEXT, path TEXT, kategorija TEXT, uploaded_at TEXT DEFAULT (datetime('now'))
        );

        /* Members */
        CREATE TABLE IF NOT EXISTS members(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ime TEXT, prezime TEXT, datum_rodjenja TEXT,
            spol TEXT, oib TEXT, prebivaliste TEXT,
            email_sportas TEXT, email_roditelj TEXT,
            osobna_broj TEXT, osobna_izdavatelj TEXT, osobna_vrijedi_do TEXT,
            passport_number TEXT, passport_issuer TEXT, passport_expiry TEXT,
            aktivni INTEGER DEFAULT 0, veteran INTEGER DEFAULT 0, ostalo INTEGER DEFAULT 0,
            placa_clanarinu INTEGER DEFAULT 0, iznos_clanarine_eur REAL DEFAULT 30.0,
            grupa_trening TEXT,
            slika_path TEXT,
            medical_path TEXT, medical_valid_until TEXT,
            pristupnica_path TEXT, pristupnica_date TEXT,
            privola_path TEXT, privola_date TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        /* Trainers */
        CREATE TABLE IF NOT EXISTS trainers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ime TEXT, prezime TEXT, datum_rodjenja TEXT,
            oib TEXT, email TEXT, iban TEXT,
            grupa TEXT,
            slika_path TEXT
        );
        CREATE TABLE IF NOT EXISTS trainer_docs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trener_id INTEGER REFERENCES trainers(id) ON DELETE CASCADE,
            naziv TEXT, path TEXT, uploaded_at TEXT DEFAULT (datetime('now'))
        );

        /* Groups */
        CREATE TABLE IF NOT EXISTS groups(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naziv TEXT UNIQUE,
            trener TEXT
        );

        /* Competitions */
        CREATE TABLE IF NOT EXISTS competitions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            godina INTEGER,
            datum TEXT, datum_kraj TEXT,
            tip TEXT,
            podtip TEXT,
            ime_natjecanja TEXT,
            stil_hrvanja TEXT,
            uzrast TEXT,
            mjesto TEXT, drzava TEXT, kratica_drzave TEXT,
            ekipni_poredak TEXT,
            broj_natjecatelja_klub INTEGER,
            broj_natjecatelja_ukupno INTEGER,
            broj_klubova INTEGER, broj_zemalja INTEGER,
            treneri TEXT,
            zapazanja TEXT,
            link_bilten TEXT,
            link_objava TEXT,
            images_json TEXT
        );

        /* Competition results */
        CREATE TABLE IF NOT EXISTS competition_results(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competition_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
            member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
            sportas TEXT,
            kategorija TEXT,
            stil TEXT,
            ukupno_borbi INTEGER DEFAULT 0,
            pobjeda INTEGER DEFAULT 0,
            poraza INTEGER DEFAULT 0,
            pobjede_nad TEXT,
            izgubljeno_od TEXT,
            plasman TEXT,
            napomena TEXT,
            medalja TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        /* Attendance */
        CREATE TABLE IF NOT EXISTS coach_attendance(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trener TEXT, grupa TEXT, lokacija TEXT,
            datum TEXT, vrijeme_od TEXT, vrijeme_do TEXT,
            trajanje_min INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS attendance(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
            grupa TEXT, datum TEXT, prisutan INTEGER DEFAULT 1
        );

        /* Fees */
        CREATE TABLE IF NOT EXISTS fees(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
            mjesec INTEGER, godina INTEGER,
            iznos REAL, poziv TEXT, iban TEXT,
            roditelj TEXT, adresa TEXT,
            status TEXT DEFAULT 'neplaćeno',
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)
        c.commit()
    ensure_defaults()

init_db()

# ===================== SIDEBAR (logo + nav) =====================
logo_path = get_setting("logo_path", "")
if logo_path and os.path.exists(logo_path):
    st.sidebar.image(logo_path, use_column_width=True)
else:
    st.sidebar.caption("Dodaj logo u ⚙️ Postavke")

NAV = st.sidebar.radio("Navigacija", [
    "🏠 Klub (osnovno)","👤 Članovi","🧑‍🏫 Treneri","🏆 Natjecanja & Rezultati",
    "📊 Statistika","👥 Grupe","🧓 Veterani","🗓️ Prisustvo","💶 Članarine","✉️ Komunikacije","⚙️ Postavke"
])

# ===================== PAGES =====================
# ---- CLUB BASIC ----
if NAV == "🏠 Klub (osnovno)":
    st.header("🏠 Osnovni podaci o klubu")
    with st.form("club_basic"):
        c = st.columns(2)
        with c[0]:
            club_name = st.text_input("KLUB (IME)", value=get_setting("club_name"))
            street = st.text_input("ULICA I KUĆNI BROJ", value=get_setting("club_addr_street"))
            cityzip = st.text_input("GRAD I POŠTANSKI BROJ", value=get_setting("club_addr_cityzip"))
            iban = st.text_input("IBAN RAČUN", value=get_setting("club_iban"))
            oib = st.text_input("OIB", value=get_setting("club_oib"))
            web = st.text_input("Web stranica", value=get_setting("club_web"))
        with c[1]:
            email = st.text_input("E-mail", value=get_setting("club_email"))
            phone = st.text_input("Telefon/Mobitel", value=get_setting("club_phone"))
            insta = st.text_input("Instagram (link)", value=get_setting("social_instagram"))
            fb = st.text_input("Facebook (link)", value=get_setting("social_facebook"))
            tiktok = st.text_input("TikTok (link)", value=get_setting("social_tiktok"))
        sub = st.form_submit_button("💾 Spremi osnovne podatke")
        if sub:
            set_setting("club_name", club_name); set_setting("club_addr_street", street)
            set_setting("club_addr_cityzip", cityzip); set_setting("club_iban", iban)
            set_setting("club_oib", oib); set_setting("club_web", web)
            set_setting("club_email", email); set_setting("club_phone", phone)
            set_setting("social_instagram", insta); set_setting("social_facebook", fb); set_setting("social_tiktok", tiktok)
            st.success("Spremljeno.")
    st.divider()
    st.subheader("👥 Vodstvo kluba")
    col = st.columns(4)
    role = col[0].selectbox("Uloga", ["predsjednik","tajnik","predsjednistvo","nadzorni"])
    ime = col[1].text_input("Ime")
    prezime = col[2].text_input("Prezime")
    kontakt = col[3].text_input("Kontakt broj")
    emailp = st.text_input("E-mail adresa")
    if st.button("➕ Dodaj osobu"):
        exec_sql("INSERT INTO club_persons(role,ime,prezime,kontakt,email) VALUES(?,?,?,?,?)",(role, ime, prezime, kontakt, emailp))
        st.success("Dodano.")
    dfp = df_from_sql("SELECT role, ime||' '||prezime AS osoba, kontakt, email FROM club_persons ORDER BY role, osoba")
    st.dataframe(dfp, use_container_width=True)
    st.divider()
    st.subheader("📎 Dokumenti kluba")
    c1,c2 = st.columns([1,2])
    with c1:
        naziv = st.text_input("Naziv dokumenta")
        opis = st.text_input("Opis (opcionalno)")
        kategorija = st.text_input("Kategorija (npr. Statut, Odluke...)")
        upl = st.file_uploader("Datoteka", type=["pdf","doc","docx","xls","xlsx","jpg","png"])
        if st.button("📤 Učitaj dokument", type="primary"):
            if upl is None: st.error("Nema datoteke.")
            else:
                path = save_uploaded("club", upl)
                exec_sql("INSERT INTO club_docs(naziv,opis,path,kategorija) VALUES(?,?,?,?)",(naziv or upl.name, opis, path, kategorija))
                st.success("Spremljeno.")
    with c2:
        dfc = df_from_sql("SELECT uploaded_at, kategorija, naziv, opis, path FROM club_docs ORDER BY id DESC")
        if dfc.empty: st.info("Nema dokumenata.")
        else:
            dfc["Link"] = dfc["path"].apply(lambda p: f"[Preuzmi]({p})")
            st.dataframe(dfc[["uploaded_at","kategorija","naziv","opis","Link"]], use_container_width=True)

# ---- MEMBERS ----
def template_members() -> bytes:
    cols = ["ime","prezime","datum_rodjenja","spol","oib","prebivaliste","email_sportas","email_roditelj",
            "osobna_broj","osobna_izdavatelj","osobna_vrijedi_do","passport_number","passport_issuer","passport_expiry",
            "aktivni","veteran","ostalo","placa_clanarinu","iznos_clanarine_eur","grupa_trening"]
    df = pd.DataFrame(columns=cols)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name="Clanovi")
    return bio.getvalue()

def import_members_from_excel(file) -> Tuple[int,List[str]]:
    warns=[]; n=0
    df = pd.read_excel(file, sheet_name=0)
    df.columns = [str(c).strip().lower() for c in df.columns]
    need = ["ime","prezime"]
    for c in need:
        if c not in df.columns: df[c]=None; warns.append(f"Kolona '{c}' nedostajala – postavljena prazno")
    for _,r in df.iterrows():
        try:
            exec_sql("""
                INSERT INTO members(ime,prezime,datum_rodjenja,spol,oib,prebivaliste,email_sportas,email_roditelj,
                    osobna_broj,osobna_izdavatelj,osobna_vrijedi_do,passport_number,passport_issuer,passport_expiry,
                    aktivni,veteran,ostalo,placa_clanarinu,iznos_clanarine_eur,grupa_trening)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (_nz(r.get("ime")), _nz(r.get("prezime")), _nz(r.get("datum_rodjenja")), _nz(r.get("spol")), _nz(r.get("oib")),
                  _nz(r.get("prebivaliste")), _nz(r.get("email_sportas")), _nz(r.get("email_roditelj")), _nz(r.get("osobna_broj")),
                  _nz(r.get("osobna_izdavatelj")), _nz(r.get("osobna_vrijedi_do")), _nz(r.get("passport_number")), _nz(r.get("passport_issuer")),
                  _nz(r.get("passport_expiry")), _safe_int(r.get("aktivni"),0), _safe_int(r.get("veteran"),0), _safe_int(r.get("ostalo"),0),
                  _safe_int(r.get("placa_clanarinu"),0), float(r.get("iznos_clanarine_eur") or 30.0), _nz(r.get("grupa_trening")) ))
            n+=1
        except Exception as e:
            warns.append(f"Preskočeno: {e}")
    return n, warns

if NAV == "👤 Članovi":
    st.header("👤 Članovi")
    tab_add, tab_list, tab_import = st.tabs(["➕ Dodaj/uredi","📋 Popis","📥 Uvoz/Izvoz"])
    with tab_add:
        c1,c2,c3 = st.columns(3)
        with c1:
            ime = st.text_input("Ime")
            prezime = st.text_input("Prezime")
            datum_rod = st.date_input("Datum rođenja", value=None)
            spol = st.selectbox("Spol", ["","m","ž"])
            oib = st.text_input("OIB")
            preb = st.text_input("Mjesto prebivališta / adresa")
            grupa = st.text_input("Grupa (npr. U13, djevojčice, veterani...)")
        with c2:
            email_s = st.text_input("E-mail sportaša")
            email_r = st.text_input("E-mail roditelja")
            osobna_b = st.text_input("Broj osobne iskaznice")
            osobna_iz = st.text_input("Izdavatelj osobne")
            osobna_do = st.date_input("Osobna vrijedi do", value=None)
            pass_no = st.text_input("Broj putovnice")
            pass_iz = st.text_input("Izdavatelj putovnice")
            pass_do = st.date_input("Putovnica vrijedi do", value=None)
        with c3:
            aktivni = st.checkbox("Aktivni natjecatelj/ica", value=False)
            veteran = st.checkbox("Veteran", value=False)
            ostalo = st.checkbox("Ostalo", value=False)
            placa = st.checkbox("Plaća članarinu", value=False)
            iznos = st.number_input("Iznos članarine (EUR)", min_value=0.0, step=5.0, value=30.0, help="Može se mijenjati (npr. više članova obitelji)")
            slika = st.file_uploader("Slika člana (JPG/PNG)", type=["jpg","jpeg","png"])
            grupa_pick = st.text_input("Smjesti u grupu", value=grupa)
        if st.button("💾 Spremi člana", type="primary"):
            slika_path = save_uploaded("clan_slika", slika) if slika else None
            exec_sql("""
                INSERT INTO members(ime,prezime,datum_rodjenja,spol,oib,prebivaliste,email_sportas,email_roditelj,
                    osobna_broj,osobna_izdavatelj,osobna_vrijedi_do,passport_number,passport_issuer,passport_expiry,
                    aktivni,veteran,ostalo,placa_clanarinu,iznos_clanarine_eur,grupa_trening,slika_path)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (ime or None, prezime or None, str(datum_rod) if datum_rod else None, spol or None, oib or None, preb or None,
                  email_s or None, email_r or None, osobna_b or None, osobna_iz or None, str(osobna_do) if osobna_do else None,
                  pass_no or None, pass_iz or None, str(pass_do) if pass_do else None, 1 if aktivni else 0, 1 if veteran else 0,
                  1 if ostalo else 0, 1 if placa else 0, float(iznos or 0.0), grupa_pick or None, slika_path))
            st.success("Član spremljen.")
            # auto-generate pristupnica & privola (sažeto)
            header = f"""{get_setting('club_name')} — {get_setting('club_addr_cityzip')}, {get_setting('club_addr_street')}
mob:{get_setting('club_phone')} web:{get_setting('club_web')} e-mail:{get_setting('club_email')}
OIB:{get_setting('club_oib')} IBAN:{get_setting('club_iban')}"""
            pristup_title = f"PRISTUPNICA — {ime} {prezime} | {oib} | {str(datum_rod) if datum_rod else ''}"
            pristup_text = header + "\n\n" + "Pristupnica (sažetak Statuta). Cijeli Statut: www.hk-podravka.hr/o-klubu\n\n" + \
                           "Izjava o odgovornosti i suglasnosti za fotografiranje.\n\n" + \
                           "Potpisi: član __________________  roditelj/staratelj __________________"
            p_path = try_make_pdf(f"pristupnica_{int(datetime.now().timestamp())}.pdf", pristup_title, pristup_text)
            exec_sql("UPDATE members SET pristupnica_path=?, pristupnica_date=datetime('now') WHERE rowid=last_insert_rowid()", (p_path,))
            privola_text = "Privola za obradu osobnih podataka (sažetak sukladan GDPR-u). Vrijedi do opoziva."
            v_path = try_make_pdf(f"privola_{int(datetime.now().timestamp())}.pdf", f"PRIVOLA — {ime} {prezime}", privola_text)
            exec_sql("UPDATE members SET privola_path=?, privola_date=datetime('now') WHERE rowid=last_insert_rowid()", (v_path,))
            st.info(f"Generirane datoteke: [Pristupnica]({p_path}) • [Privola]({v_path})")

    with tab_list:
        df = df_from_sql("SELECT id, prezime||' '||ime AS Ime, grupa_trening, aktivni, veteran, medical_valid_until, email_sportas, email_roditelj FROM members ORDER BY prezime, ime")
        if df.empty: st.info("Nema članova.")
        else:
            df["Liječnička"] = df["medical_valid_until"].apply(lambda x: status_badge(x))
            df["Aktivni"] = df["aktivni"].apply(lambda x: "Da" if x==1 else "Ne")
            df["Veteran"] = df["veteran"].apply(lambda x: "Da" if x==1 else "Ne")
            st.dataframe(df[["Ime","grupa_trening","Aktivni","Veteran","Liječnička","email_sportas","email_roditelj"]], use_container_width=True)
        st.subheader("Uredi dokumente/validacije")
        dfl = df_from_sql("SELECT id, prezime||' '||ime AS label FROM members ORDER BY prezime, ime")
        if not dfl.empty:
            sel = st.selectbox("Član", dfl["id"].tolist(), format_func=lambda i: dfl.loc[dfl['id']==i,'label'].iloc[0])
            c1,c2 = st.columns(2)
            with c1:
                prist = st.file_uploader("Pristupnica (PDF/JPG)", type=["pdf","jpg","jpeg","png"])
                priv = st.file_uploader("Privola (PDF/JPG)", type=["pdf","jpg","jpeg","png"])
                med = st.file_uploader("Liječnička potvrda (PDF/JPG)", type=["pdf","jpg","jpeg","png"])
                med_until = st.date_input("Liječnička vrijedi do", value=None)
            with c2:
                pass_no = st.text_input("Broj putovnice (izmjena)")
                pass_issuer = st.text_input("Izdavatelj putovnice (izmjena)")
                pass_until = st.date_input("Putovnica vrijedi do (izmjena)", value=None)
            if st.button("💾 Spremi dokumente", type="primary"):
                sets=[]; vals=[]
                p1=save_uploaded("pristupnica", prist); p2=save_uploaded("privola", priv); p3=save_uploaded("lijecnicka", med)
                if p1: sets+=["pristupnica_path=?", "pristupnica_date=datetime('now')"]; vals+=[p1]
                if p2: sets+=["privola_path=?", "privola_date=datetime('now')"]; vals+=[p2]
                if p3: sets+=["medical_path=?"]; vals+=[p3]
                if med_until: sets+=["medical_valid_until=?"]; vals+=[str(med_until)]
                if pass_no: sets+=["passport_number=?"]; vals+=[pass_no]
                if pass_issuer: sets+=["passport_issuer=?"]; vals+=[pass_issuer]
                if pass_until: sets+=["passport_expiry=?"]; vals+=[str(pass_until)]
                if sets:
                    q="UPDATE members SET "+", ".join(sets)+" WHERE id=?"; vals.append(int(sel)); exec_sql(q, tuple(vals)); st.success("Spremljeno.")

    with tab_import:
        col1,col2,col3 = st.columns(3)
        with col1:
            if st.button("📄 Predložak (Članovi)"):
                fn=os.path.join(DATA_DIR,"predlozak_clanovi.xlsx"); open(fn,"wb").write(template_members()); st.success(f"[Preuzmi]({fn})")
        with col2:
            upl = st.file_uploader("Učitaj Excel (Članovi)", type=["xlsx"], key="upl_members")
            if upl:
                n,w = import_members_from_excel(upl); st.success(f"✅ Uvezeno {n} članova."); [st.info(i) for i in w]
        with col3:
            dfe = df_from_sql("SELECT * FROM members ORDER BY prezime, ime")
            if not dfe.empty and st.button("⬇️ Izvoz (Članovi)"):
                bio = BytesIO(); dfe.to_excel(bio, index=False); fn=os.path.join(DATA_DIR,"clanovi_izvoz.xlsx"); open(fn,"wb").write(bio.getvalue()); st.success(f"[Preuzmi]({fn})")

# ---- TRAINERS ----
if NAV == "🧑‍🏫 Treneri":
    st.header("🧑‍🏫 Treneri")
    t1,t2 = st.columns([1,2])
    with t1:
        ime = st.text_input("Ime trenera"); prezime = st.text_input("Prezime trenera")
        drod = st.date_input("Datum rođenja", value=None)
        toib = st.text_input("OIB")
        temail = st.text_input("E-mail")
        tiban = st.text_input("IBAN broj računa")
        tgrupa = st.text_input("Grupa koju trenira")
        tslika = st.file_uploader("Slika (opcionalno)", type=["jpg","jpeg","png"])
        if st.button("Spremi trenera"):
            path = save_uploaded("trener_slika", tslika) if tslika else None
            exec_sql("INSERT INTO trainers(ime,prezime,datum_rodjenja,oib,email,iban,grupa,slika_path) VALUES(?,?,?,?,?,?,?,?)",
                     (ime, prezime, str(drod) if drod else None, toib, temail, tiban, tgrupa, path))
            st.success("Trener spremljen.")
    with t2:
        dft = df_from_sql("SELECT id, prezime||' '||ime AS trener, email, grupa FROM trainers ORDER BY prezime, ime")
        st.dataframe(dft, use_container_width=True)
        st.subheader("📎 Dokumenti trenera")
        dfl = df_from_sql("SELECT id, prezime||' '||ime AS label FROM trainers ORDER BY prezime, ime")
        if not dfl.empty:
            tid = st.selectbox("Trener", dfl["id"].tolist(), format_func=lambda i: dfl.loc[dfl['id']==i,'label'].iloc[0])
            doc = st.file_uploader("Ugovor ili drugi dokument", type=["pdf","jpg","jpeg","png","doc","docx"])
            naziv = st.text_input("Naziv dokumenta", value="Ugovor")
            if st.button("📤 Učitaj", type="primary"):
                p = save_uploaded("trener_doc", doc); exec_sql("INSERT INTO trainer_docs(trener_id,naziv,path) VALUES(?,?,?)",(int(tid), naziv, p)); st.success("Učitano.")
            ddocs = df_from_sql("SELECT naziv, uploaded_at, path FROM trainer_docs WHERE trener_id=? ORDER BY id DESC",(int(tid),))
            if not ddocs.empty:
                ddocs["Link"]=ddocs["path"].apply(lambda p: f"[Preuzmi]({p})"); st.dataframe(ddocs[["uploaded_at","naziv","Link"]], use_container_width=True)

# ---- COMPETITIONS & RESULTS ----
def template_results() -> bytes:
    cols = ["sportas","member_id","kategorija","stil","ukupno_borbi","pobjeda","poraza","pobjede_nad","izgubljeno_od","plasman","napomena","medalja"]
    df = pd.DataFrame(columns=cols)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name="Rezultati")
    return bio.getvalue()

if NAV == "🏆 Natjecanja & Rezultati":
    st.header("🏆 Natjecanja & Rezultati")
    with st.expander("➕ Dodaj natjecanje", expanded=False):
        c1,c2,c3 = st.columns(3)
        with c1:
            godina = st.number_input("Godina", min_value=2010, max_value=date.today().year+1, value=date.today().year, step=1)
            datum = st.date_input("Datum početka", value=None)
            datum_kraj = st.date_input("Datum završetka", value=None)
            tip = st.selectbox("TIP", ["PRVENSTVO HRVATSKE","MEĐUNARODNI TURNIR","REPREZENTATIVNI NASTUP","HRVAČKA LIGA ZA SENIORE","MEĐUNARODNA HRVAČKA LIGA ZA KADETE","REGIONALNO PRVENSTVO","LIGA ZA DJEVOJČICE","OSTALO"])
            podtip = st.selectbox("Podtip (za reprezentativni nastup)", ["—","PRVENSTVO EUROPE","PRVENSTVO SVIJETA","PRVENSTVO BALKANA","UWW TURNIR"])
        with c2:
            ime_nat = st.text_input("Ime natjecanja (ako postoji)")
            stil = st.selectbox("Stil hrvanja", ["GR","FS","WW","BW","MODIFICIRANO"])
            uzrast = st.selectbox("Uzrast", ["POČETNICI","U11","U13","U15","U17","U20","U23","SENIORI"])
            mjesto = st.text_input("Mjesto")
            pred = guess_country_for_city(mjesto) if mjesto else None
            drzava = st.selectbox("Država", options=COUNTRIES, index=(COUNTRIES.index(pred) if pred in COUNTRIES else 0))
            krr = st.text_input("Kratica države", value=iso3(drzava))
        with c3:
            ekipni = st.text_input("Ekipni poredak")
            br_klub = st.number_input("Broj natjecatelja (klub)", min_value=0, step=1)
            br_uk = st.number_input("Broj natjecatelja (ukupno)", min_value=0, step=1)
            brk = st.number_input("Broj klubova", min_value=0, step=1)
            brz = st.number_input("Broj zemalja", min_value=0, step=1)
            treneri = st.text_input("Trener(i)")
        zapa = st.text_area("Zapažanja (za objavu)")
        link_b = st.text_input("Link rezultata / biltena")
        link_o = st.text_input("Link klupske objave")
        img_files = st.file_uploader("Fotografije s natjecanja", accept_multiple_files=True, type=["jpg","jpeg","png"])
        imgs = []
        if img_files:
            for f in img_files:
                p = save_uploaded("natjecanje_img", f); imgs.append(p)
        if st.button("💾 Spremi natjecanje", type="primary"):
            exec_sql("""
                INSERT INTO competitions(godina, datum, datum_kraj, tip, podtip, ime_natjecanja, stil_hrvanja, uzrast, mjesto, drzava, kratica_drzave,
                    ekipni_poredak, broj_natjecatelja_klub, broj_natjecatelja_ukupno, broj_klubova, broj_zemalja, treneri, zapazanja, link_bilten, link_objava, images_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (int(godina), str(datum) if datum else None, str(datum_kraj) if datum_kraj else None, tip, (podtip if podtip!="—" else None),
                  ime_nat or None, stil, uzrast, mjesto or None, drzava or None, krr or None, ekipni or None, int(br_klub), int(br_uk), int(brk), int(brz),
                  treneri or None, zapa or None, link_b or None, link_o or None, json.dumps(imgs)))
            st.success("Natjecanje spremljeno.")

    dfc = df_from_sql("SELECT id, godina, datum, ime_natjecanja, tip, mjesto, drzava FROM competitions ORDER BY godina DESC, datum DESC, id DESC")
    if dfc.empty: st.info("Nema natjecanja.")
    else:
        comp_id = st.selectbox("Odaberi natjecanje", options=dfc["id"].tolist(),
            format_func=lambda i: f"{dfc.loc[dfc['id']==i,'godina'].iloc[0]} — {dfc.loc[dfc['id']==i,'ime_natjecanja'].iloc[0]} ({dfc.loc[dfc['id']==i,'mjesto'].iloc[0]}, {dfc.loc[dfc['id']==i,'drzava'].iloc[0]})")

        with st.expander("➕ Rezultati za odabrano natjecanje", expanded=False):
            df_m = df_from_sql("SELECT id, ime, prezime, grupa_trening FROM members ORDER BY prezime, ime")
            members_map = {int(r.id): f"{r.prezime} {r.ime} ({_nz(r.grupa_trening)})" for _,r in df_m.iterrows()} if not df_m.empty else {}
            use_member = st.toggle("Odaberi sportaša iz baze", value=True)
            if use_member and members_map:
                member_id = st.selectbox("Sportaš (baza)", options=list(members_map.keys()), format_func=lambda i: members_map[i])
                sportas_txt = st.text_input("Ime i prezime (ručno, opcionalno)", value="")
            else:
                member_id = None
                sportas_txt = st.text_input("Ime i prezime (ručno)")
            kategorija = st.text_input("Kategorija")
            stilr = st.selectbox("Stil", ["GR","FS","WW","BW","MODIFICIRANO"], index=0)
            colx1,colx2,colx3 = st.columns(3)
            with colx1:
                ukupno = st.number_input("Ukupno borbi", min_value=0, step=1)
            with colx2:
                pobjeda = st.number_input("Pobjeda", min_value=0, step=1)
            with colx3:
                poraza = st.number_input("Poraza", min_value=0, step=1)
            c1,c2 = st.columns(2)
            with c1: pobjede_nad_raw = st.text_area("Pobjede nad (Ime Prezime – Klub) — svaki u novi red")
            with c2: izgubljeno_od_raw = st.text_area("Izgubljeno od (Ime Prezime – Klub) — svaki u novi red")
            colm1, colm2 = st.columns(2)
            with colm1: napomena = st.text_area("Napomena (opcionalno)")
            with colm2:
                medalja = st.selectbox("Medalja", options=["—","🥇","🥈","🥉"], index=0)
                plasman = st.text_input("Plasman (npr. 5.)", value="")
            if st.button("💾 Spremi rezultat", type="primary"):
                pobjede_list = [x.strip() for x in (pobjede_nad_raw or "").splitlines() if x.strip()]
                izgubljeno_list = [x.strip() for x in (izgubljeno_od_raw or "").splitlines() if x.strip()]
                exec_sql("""
                    INSERT INTO competition_results(competition_id, member_id, sportas, kategorija, stil, ukupno_borbi, pobjeda, poraza, pobjede_nad, izgubljeno_od, napomena, medalja, plasman)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (int(comp_id), int(member_id) if member_id else None, (sportas_txt.strip() or None),
                      (kategorija.strip() or None), stilr, int(ukupno), int(pobjeda), int(poraza),
                      json.dumps(pobjede_list), json.dumps(izgubljeno_list), (napomena.strip() or None),
                      (medalja if medalja!='—' else None), (plasman.strip() or None)))
                st.success("Rezultat spremljen.")

        st.markdown("### 📋 Rezultati — popis")
        dfr = df_from_sql("""
            SELECT r.id, COALESCE(r.sportas, m.prezime||' '||m.ime) AS Sportaš, r.kategorija, r.stil,
                   r.ukupno_borbi AS Ukupno, r.pobjeda AS Pobjede, r.poraza AS Porazi, r.medalja, r.plasman, r.napomena
            FROM competition_results r LEFT JOIN members m ON m.id=r.member_id
            WHERE r.competition_id=? ORDER BY Sportaš
        """, (int(comp_id),))
        if dfr.empty: st.info("Nema rezultata.")
        else: st.dataframe(dfr.drop(columns=["id"]), use_container_width=True)

        st.markdown("### 📥 Uvoz / 📄 Predložak / ⬇️ Izvoz")
        colr1,colr2,colr3 = st.columns(3)
        with colr1:
            if st.button("📄 Predložak (Rezultati)"):
                fn=os.path.join(DATA_DIR,"predlozak_rezultati.xlsx"); open(fn,"wb").write(template_results()); st.success(f"[Preuzmi]({fn})")
        with colr2:
            uplr = st.file_uploader("Učitaj Excel (Rezultati)", type=["xlsx"], key="upl_res")
            if uplr:
                warns=[]; n=0
                df = pd.read_excel(uplr, sheet_name=0); df.columns=[str(c).strip().lower() for c in df.columns]
                need = ["sportas","member_id","kategorija","stil","ukupno_borbi","pobjeda","poraza","pobjede_nad","izgubljeno_od","plasman","napomena","medalja"]
                for ccc in need:
                    if ccc not in df.columns: df[ccc]=None; warns.append(f"Kolona '{ccc}' nedostajala – postavljena prazno")
                for _, r in df.iterrows():
                    try:
                        exec_sql("""
                            INSERT INTO competition_results(competition_id, member_id, sportas, kategorija, stil, ukupno_borbi, pobjeda, poraza, pobjede_nad, izgubljeno_od, napomena, medalja, plasman)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """, (int(comp_id), _safe_int(r.get("member_id")), _nz(r.get("sportas")), _nz(r.get("kategorija")), _nz(r.get("stil")),
                              _safe_int(r.get("ukupno_borbi"),0), _safe_int(r.get("pobjeda"),0), _safe_int(r.get("poraza"),0),
                              json.dumps([s.strip() for s in str(_nz(r.get("pobjede_nad"))).splitlines() if s.strip()]),
                              json.dumps([s.strip() for s in str(_nz(r.get("izgubljeno_od"))).splitlines() if s.strip()]),
                              _nz(r.get("napomena")), (r.get("medalja") if str(r.get("medalja")) in {"🥇","🥈","🥉"} else None), _nz(r.get("plasman"))))
                        n+=1
                    except Exception as e:
                        warns.append(f"Preskočeno: {e}")
                st.success(f"✅ Uvezeno {n} rezultata."); [st.info(i) for i in warns]
        with colr3:
            dfr_all = df_from_sql("""
                SELECT COALESCE(r.sportas, m.prezime||' '||m.ime) AS Sportaš, r.kategorija AS Kategorija, r.stil AS Stil,
                       r.ukupno_borbi AS Ukupno_borbi, r.pobjeda AS Pobjede, r.poraza AS Porazi,
                       r.medalja AS Medalja, r.plasman AS Plasman, r.napomena AS Napomena
                FROM competition_results r
                LEFT JOIN members m ON m.id=r.member_id
                WHERE r.competition_id=?
            """, (int(comp_id),))
            if not dfr_all.empty and st.button("⬇️ Izvoz (Rezultati)"):
                bio = BytesIO(); dfr_all.to_excel(bio, index=False); fn=os.path.join(DATA_DIR,"rezultati_izvoz.xlsx"); open(fn,"wb").write(bio.getvalue()); st.success(f"[Preuzmi]({fn})")

# ---- STATISTICS ----
if NAV == "📊 Statistika":
    st.header("📊 Statistika")
    god_options = [0] + sorted(df_from_sql("SELECT DISTINCT godina FROM competitions WHERE godina IS NOT NULL ORDER BY godina").get("godina", pd.Series(dtype=int)).tolist())
    god = st.selectbox("Godina", options=god_options, format_func=lambda x: "Sve" if x==0 else str(x))
    sportas = st.text_input("Sportaš (opcionalno)"); nat = st.text_input("Natjecanje (opcionalno)")
    q = """
        SELECT r.*, COALESCE(r.sportas, m.prezime||' '||m.ime) AS sportas_label,
               c.ime_natjecanja, c.tip, c.uzrast, c.stil_hrvanja, c.godina, c.datum, c.mjesto, c.drzava
        FROM competition_results r
        JOIN competitions c ON c.id = r.competition_id
        LEFT JOIN members m ON m.id = r.member_id
        WHERE 1=1
    """
    params = []
    if god != 0: q += " AND c.godina=?"; params.append(int(god))
    dfr = df_from_sql(q, tuple(params))
    if sportas.strip(): dfr = dfr[dfr["sportas_label"].fillna("").str.contains(sportas.strip(), case=False, na=False)]
    if nat.strip(): dfr = dfr[dfr["ime_natjecanja"].fillna("").str.contains(nat.strip(), case=False, na=False) | dfr["tip"].fillna("").str.contains(nat.strip(), case=False, na=False)]
    if dfr.empty: st.info("Nema podataka.")
    else:
        total_comp = dfr["competition_id"].nunique()
        bouts = dfr["ukupno_borbi"].fillna(0).astype(int).sum()
        wins = dfr["pobjeda"].fillna(0).astype(int).sum()
        losses = dfr["poraza"].fillna(0).astype(int).sum()
        colm = st.columns(4)
        colm[0].metric("Natjecanja", total_comp)
        colm[1].metric("Borbi", bouts)
        colm[2].metric("Pobjede", wins)
        colm[3].metric("Porazi", losses)
        by_year = dfr.groupby("godina")[["ukupno_borbi","pobjeda","poraza"]].sum().reset_index()
        st.subheader("Po godinama"); st.dataframe(by_year, use_container_width=True)
        by_ath = dfr.groupby("sportas_label")[["ukupno_borbi","pobjeda","poraza"]].sum().reset_index().sort_values("pobjeda", ascending=False)
        st.subheader("Po sportašima"); st.dataframe(by_ath, use_container_width=True)

# ---- GROUPS ----
if NAV == "👥 Grupe":
    st.header("👥 Grupe")
    c1,c2 = st.columns([1,2])
    with c1:
        g_name = st.text_input("Naziv grupe")
        g_trainer = st.text_input("Trener (ime/prezime)")
        if st.button("Spremi grupu"):
            if g_name.strip():
                exec_sql("INSERT INTO groups(naziv,trener) VALUES(?,?) ON CONFLICT(naziv) DO UPDATE SET trener=excluded.trener", (g_name.strip(), g_trainer.strip() or None))
                st.success("Grupa spremljena.")
    with c2:
        dfg = df_from_sql("SELECT id, naziv, trener FROM groups ORDER BY naziv")
        st.dataframe(dfg, use_container_width=True)
    st.subheader("Članovi po grupama")
    dfl = df_from_sql("SELECT prezime||' '||ime AS Ime, COALESCE(grupa_trening,'') AS Grupa FROM members ORDER BY Grupa, Ime")
    if dfl.empty: st.info("Nema članova.")
    else: st.dataframe(dfl, use_container_width=True)

# ---- VETERANS ----
if NAV == "🧓 Veterani":
    st.header("🧓 Veterani")
    dfv = df_from_sql("SELECT prezime||' '||ime AS Ime, grupa_trening, medical_valid_until, passport_expiry FROM members WHERE veteran=1 ORDER BY Ime")
    if dfv.empty: st.info("Nema označenih veterana.")
    else:
        dfv["Liječnička"] = dfv["medical_valid_until"].apply(lambda x: status_badge(x))
        dfv["Putovnica"] = dfv["passport_expiry"].apply(lambda x: status_badge(x))
        st.dataframe(dfv[["Ime","grupa_trening","Liječnička","Putovnica"]], use_container_width=True)

# ---- ATTENDANCE ----
if NAV == "🗓️ Prisustvo":
    st.header("🗓️ Prisustvo trenera")
    trener = st.text_input("Trener (ime/prezime)")
    grupa = st.text_input("Grupa")
    izbor = st.selectbox("Lokacija", ["DVORANA SJEVER","IGRALIŠTE ANG","IGRALIŠTE SREDNJA","(ručno)"])
    lok = st.text_input("Lokacija (ručno)", value="" if izbor!="(ručno)" else "")
    lokacija = (lok if izbor=="(ručno)" else izbor)
    t1 = st.time_input("Od", value=datetime.strptime("18:30","%H:%M").time())
    t2 = st.time_input("Do", value=datetime.strptime("20:00","%H:%M").time())
    datum = st.date_input("Datum", value=date.today())
    h1,m1 = map(int, t1.strftime("%H:%M").split(":")); h2,m2 = map(int, t2.strftime("%H:%M").split(":"))
    trajanje_min = max(0, (h2*60+m2)-(h1*60+m1))
    st.caption(f"Trajanje: {trajanje_min/60:.2f} h")
    if st.button("💾 Spremi prisustvo trenera", type="primary"):
        exec_sql("""INSERT INTO coach_attendance(trener, grupa, lokacija, datum, vrijeme_od, vrijeme_do, trajanje_min) VALUES (?,?,?,?,?,?,?)""",
                 (trener or None, grupa or None, lokacija or None, str(datum), t1.strftime("%H:%M"), t2.strftime("%H:%M"), int(trajanje_min)))
        st.success("Spremljeno.")
    st.subheader("📈 Statistika sati (treneri)")
    god = st.number_input("Godina", min_value=2020, max_value=date.today().year+1, value=date.today().year, step=1)
    mjesec = st.selectbox("Mjesec", options=[0]+list(range(1,13)), format_func=lambda m: "Svi" if m==0 else f"{m:02d}")
    dfa = df_from_sql("SELECT trener, datum, trajanje_min FROM coach_attendance WHERE substr(datum,1,4)=?", (str(int(god)),))
    if int(mjesec)>0: dfa = dfa[dfa["datum"].str.slice(5,7)==f"{int(mjesec):02d}"]
    if dfa.empty: st.info("Nema podataka.")
    else:
        dfa["sati"]=dfa["trajanje_min"].fillna(0)/60.0
        st.metric("Ukupno sati", f"{dfa['sati'].sum():.2f}")
        by_tr = dfa.groupby("trener")["sati"].sum().sort_values(ascending=False).reset_index()
        st.subheader("Po treneru"); st.dataframe(by_tr, use_container_width=True)

    st.divider()
    st.header("🗓️ Prisustvo sportaša")
    dfm = df_from_sql("SELECT id, prezime||' '||ime AS label, grupa_trening FROM members ORDER BY prezime, ime")
    datum2 = st.date_input("Datum (sportaši)", value=date.today(), key="d2")
    prisutni = st.multiselect("Označi prisutne", options=dfm["id"].tolist(), format_func=lambda i: dfm.loc[dfm['id']==i,'label'].iloc[0])
    if st.button("💾 Spremi prisustvo sportaša", type="primary"):
        exec_sql("DELETE FROM attendance WHERE datum=?", (str(datum2),))
        for mid in prisutni:
            g = dfm.loc[dfm['id']==mid,'grupa_trening'].iloc[0]
            exec_sql("INSERT INTO attendance(member_id, grupa, datum, prisutan) VALUES (?,?,?,1)", (int(mid), g, str(datum2)))
        st.success("Prisustvo spremljeno.")
    st.subheader("📋 Pregled prisustva")
    dfp = df_from_sql("""
        SELECT a.datum, m.prezime||' '||m.ime AS sportaš, COALESCE(a.grupa,m.grupa_trening) AS grupa, a.prisutan FROM attendance a
        JOIN members m ON m.id=a.member_id ORDER BY a.datum DESC, sportaš""")
    st.dataframe(dfp, use_container_width=True)

# ---- FEES ----
if NAV == "💶 Članarine":
    st.header("💶 Članarine")
    dfl = df_from_sql("SELECT id, prezime||' '||ime AS label, placa_clanarinu, iznos_clanarine_eur, prebivaliste, email_roditelj, oib FROM members ORDER BY prezime, ime")
    izbor = st.selectbox("Član", options=["SVI"]+dfl["label"].tolist())
    mjesec = st.selectbox("Mjesec", list(range(1,13)))
    godina = st.number_input("Godina", min_value=2020, max_value=2100, value=date.today().year, step=1)
    if st.button("🧾 Kreiraj članarine"):
        created=0
        def make_poziv(mid:int, oib:str): return f"{oib}-{mid}-{mjesec}/{godina}"
        if izbor=="SVI":
            for _,r in dfl.iterrows():
                mid = int(r["id"]); iznos = float(r["iznos_clanarine_eur"] or 30.0)
                poziv = make_poziv(mid, r.get("oib") or "")
                exec_sql("""INSERT INTO fees(member_id,mjesec,godina,iznos,poziv,iban,roditelj,adresa) VALUES (?,?,?,?,?,?,?,?)""",
                         (mid, int(mjesec), int(godina), iznos, poziv, get_setting("club_iban"), r["label"], r.get("prebivaliste")))
                created+=1
        else:
            mid = int(dfl.loc[dfl["label"]==izbor,"id"].iloc[0])
            iznos = float(dfl.loc[dfl["label"]==izbor,"iznos_clanarine_eur"].iloc[0] or 30.0)
            oib = dfl.loc[dfl["label"]==izbor,"oib"].iloc[0] or ""
            poziv = make_poziv(mid, oib)
            exec_sql("""INSERT INTO fees(member_id,mjesec,godina,iznos,poziv,iban,roditelj,adresa) VALUES (?,?,?,?,?,?,?,?)""",
                     (mid, int(mjesec), int(godina), iznos, poziv, get_setting("club_iban"), izbor, dfl.loc[dfl["label"]==izbor,"prebivaliste"].iloc[0]))
            created=1
        st.success(f"Kreirano {created} članarina.")
    st.subheader("📋 Evidencija članarina")
    dff = df_from_sql("""
        SELECT f.id, m.prezime||' '||m.ime AS Član, f.mjesec AS Mjesec, f.godina AS Godina, f.iznos AS Iznos,
               f.poziv AS Poziv, f.status AS Status
        FROM fees f JOIN members m ON m.id=f.member_id ORDER BY f.godina DESC, f.mjesec DESC, Član
    """)
    if not dff.empty:
        st.dataframe(dff, use_container_width=True)
        sel = st.selectbox("Označi plaćeno (odaberi ID retka)", options=[None]+dff["id"].astype(int).tolist())
        if sel and st.button("Označi kao plaćeno"):
            exec_sql("UPDATE fees SET status='plaćeno' WHERE id=?", (int(sel),)); st.success("Ažurirano.")
        if st.button("⬇️ Izvoz (Excel)"):
            bio=BytesIO(); dff.to_excel(bio, index=False); fn=os.path.join(DATA_DIR,"clanarine.xlsx"); open(fn,"wb").write(bio.getvalue()); st.success(f"[Preuzmi]({fn})")
    else:
        st.info("Nema evidencije.")

# ---- COMMUNICATIONS ----
if NAV == "✉️ Komunikacije":
    st.header("✉️ Komunikacije (e-mail popisi & CSV)")
    dfm = df_from_sql("SELECT prezime||' '||ime AS Ime, email_sportas AS Email_sportas, email_roditelj AS Email_roditelj FROM members ORDER BY Ime")
    if dfm.empty: st.info("Nema članova.")
    else:
        st.dataframe(dfm, use_container_width=True)
        if st.button("⬇️ Preuzmi CSV e-mailova"):
            bio=BytesIO(); dfm.to_csv(bio, index=False); fn=os.path.join(DATA_DIR,"emails.csv"); open(fn,"wb").write(bio.getvalue()); st.success(f"[Preuzmi]({fn})")
    st.divider()
    st.subheader("Portal roditelja (demo)")
    email = st.text_input("E-mail roditelja")
    oib = st.text_input("OIB člana")
    if st.button("Generiraj pristup (token)"):
        token = make_token(email, oib)
        st.info(f"Privremeni token: {token}. (Za produkciju potreban je vanjski mini-portal za upload dokumenata.)")

# ---- SETTINGS ----
if NAV == "⚙️ Postavke":
    st.header("⚙️ Postavke")
    st.subheader("Logo kluba")
    upl = st.file_uploader("Učitaj logo (.jpg/.png)", type=["jpg","jpeg","png"])
    if upl is not None:
        lp = os.path.join(DATA_DIR, f"logo_{int(datetime.now().timestamp())}.{upl.name.split('.')[-1].lower()}")
        open(lp, "wb").write(upl.read())
        set_setting("logo_path", lp)
        st.success("Logo spremljen. Osvježite stranicu.")
    st.caption(f"Aktualni logo: {get_setting('logo_path','(nije postavljen)')}")
