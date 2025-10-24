
# streamlit_app.py — HK Podravka • Sustav
# Članovi (liječnička, pristupnica, privola) • Prisustvo • Treneri • Veterani • Natjecanja
# Statistika & Pretraga • E-mail podsjetnici • Excel uvoz/izvoz + predlošci

import os, re, json, sqlite3
from io import BytesIO
from datetime import datetime, date, timedelta
from typing import List, Tuple, Optional

import numpy as np
import pandas as pd
import streamlit as st

# ========================== Setup ==========================
st.set_page_config(page_title="HK Podravka — Sustav", page_icon="🥇", layout="wide", initial_sidebar_state="collapsed")

# Logo u sidebaru (iz settings) + fallback
_lp = get_setting("logo_path", "logo.jpg")
try:
    st.sidebar.image(_lp, use_column_width=True)
except Exception:
    pass


# Logo u sidebaru
        try:
            st.sidebar.image("logo.jpg", use_column_width=True)
        except Exception:
            pass

CSS = """
@media (max-width: 640px){ html,body{font-size:16px} section.main>div{padding-top:.5rem!important} }
.stButton button{padding:.9rem 1.1rem;border-radius:12px;font-weight:600}
[data-testid="stDataFrame"] div[role="grid"]{overflow-x:auto!important}
.badge{padding:.2rem .5rem;border-radius:.5rem;font-weight:700;color:#fff}
.badge.green{background:#16a34a}.badge.yellow{background:#f59e0b}.badge.red{background:#dc2626}
"""
st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)

DB_PATH = "data/hk_podravka.sqlite"
UPLOAD_ROOT = "data/uploads"
UPLOADS = {
    "members": os.path.join(UPLOAD_ROOT, "members"),
    "trainers": os.path.join(UPLOAD_ROOT, "trainers"),
    "veterans": os.path.join(UPLOAD_ROOT, "veterans"),
    "medical": os.path.join(UPLOAD_ROOT, "medical"),
    "pristupnice": os.path.join(UPLOAD_ROOT, "pristupnice"),
    "privole": os.path.join(UPLOAD_ROOT, "privole"),
    "competitions": os.path.join(UPLOAD_ROOT, "competitions"),
}

# SMTP za e-mail podsjetnike (ako nije postavljeno -> simulacija)
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
SMTP_FROM = os.environ.get("SMTP_FROM", "noreply@hk-podravka.local")

AUTO_EMAIL_REMINDERS = True
REMINDER_DAY_GUARD = "data/last_reminder.txt"

def ensure_dirs():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    for p in UPLOADS.values(): os.makedirs(p, exist_ok=True)
    os.makedirs("data", exist_ok=True)

def get_conn():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

# ======================= Helpers =======================

def get_setting(key: str, default: str|None=None):
    try:
        df = df_from_sql("SELECT value FROM settings WHERE key=?", (key,))
        if not df.empty: return df["value"].iloc[0]
    except Exception: pass
    return default
def set_setting(key: str, value: str):
    try:
        exec_sql("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    except Exception: pass


def status_dot(expiry_str: str|None, warn_days: int = 30) -> str:
    from datetime import datetime as _dt
    if not expiry_str: return "⚪"
    try:
        d = _dt.fromisoformat(str(expiry_str)).date()
    except Exception:
        return "⚪"
    today = date.today()
    if d < today: return "🔴"
    if (d - today).days <= warn_days: return "🟠"
    return "🟢"

def sanitize_filename(name: str) -> str:
    base = os.path.basename(str(name))
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base)

def save_upload(file, subfolder: str) -> Optional[str]:
    if not file: return None
    ensure_dirs()
    safe = sanitize_filename(file.name)
    path = os.path.join(UPLOADS[subfolder], safe)
    with open(path, "wb") as out:
        out.write(file.read())
    return path

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

def df_mobile(df: pd.DataFrame, height: int = 420):
    st.dataframe(df, use_container_width=True, height=height)

from datetime import datetime as _dt, date as _date
def safe_date(v, default: _date = _date(2010, 1, 1)) -> _date:
    try:
        if isinstance(v, (list, tuple)): v = v[0] if v else None
        if hasattr(v, "iloc"): v = v.iloc[0] if len(v) else None
        elif isinstance(v, np.ndarray): v = v[0] if v.size else None
        if isinstance(v, str) and v.strip().lower() in {"", "nat", "nan", "none"}: v = None
        if isinstance(v, _date) and not isinstance(v, _dt): return v
        ts = pd.to_datetime(v, errors="coerce")
        if pd.isna(ts): return default
        if not isinstance(ts, _dt): ts = pd.Timestamp(ts).to_pydatetime()
        return ts.date()
    except Exception:
        return default

# ======================= DB init =======================
def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS members(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ime TEXT, prezime TEXT,
        datum_rodjenja TEXT, godina_rodjenja INTEGER,
        email_sportas TEXT, email_roditelj TEXT,
        telefon_sportas TEXT, telefon_roditelj TEXT,
        clanski_broj TEXT, oib TEXT, adresa TEXT, grupa_trening TEXT,
        foto_path TEXT,
        medical_valid_until TEXT, medical_path TEXT,
        pristupnica_date TEXT, pristupnica_path TEXT,
        privola_date TEXT, privola_path TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS trainers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ime TEXT, prezime TEXT, datum_rodjenja TEXT,
        oib TEXT, osobna_broj TEXT, iban TEXT,
        telefon TEXT, email TEXT, foto_path TEXT, ugovor_path TEXT, napomena TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS veterans(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ime TEXT, prezime TEXT, datum_rodjenja TEXT,
        oib TEXT, osobna_broj TEXT, telefon TEXT, email TEXT,
        foto_path TEXT, ugovor_path TEXT, napomena TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS attendance(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
        datum TEXT NOT NULL, termin TEXT, grupa TEXT,
        prisutan INTEGER NOT NULL DEFAULT 1, trajanje_min INTEGER DEFAULT 90,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS competitions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        redni_broj INTEGER UNIQUE,
        godina INTEGER,
        datum TEXT, datum_kraj TEXT,
        natjecanje TEXT, ime_natjecanja TEXT, stil_hrvanja TEXT,
        mjesto TEXT, drzava TEXT, kratica_drzave TEXT,
        nastupilo_podravke INTEGER,
        ekipno TEXT, trener TEXT,
        napomena TEXT, link_rezultati TEXT, galerija_json TEXT, vijest TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
""")
    
    # dodatne migracije — members passport & extra docs
    cols = pd.read_sql("PRAGMA table_info(members)", conn)["name"].tolist()
    for col, ddl in [
        ("passport_number","TEXT"),
        ("passport_expiry","TEXT")
    ]:
        if col not in cols:
            cur.execute(f"ALTER TABLE members ADD COLUMN {col} {ddl}")
# migracije
    cols = pd.read_sql("PRAGMA table_info(members)", conn)["name"].tolist()
    for col, ddl in [
        ("medical_valid_until","TEXT"),
        ("medical_path","TEXT"),
        ("pristupnica_date","TEXT"),
        ("pristupnica_path","TEXT"),
        ("privola_date","TEXT"),
        ("privola_path","TEXT"),
    ]:
        if col not in cols:
            cur.execute(f"ALTER TABLE members ADD COLUMN {col} {ddl}")
    conn.commit(); conn.close()
init_db()


# ---- Dodatne tablice: rezultati natjecanja i prisustvo trenera ----
def _ensure_extra_tables():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS competition_results(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competition_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
        member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
        sportas TEXT,
        kategorija TEXT,
        ukupno_borbi INTEGER DEFAULT 0,
        pobjeda INTEGER DEFAULT 0,
        poraza INTEGER DEFAULT 0,
        pobjede_nad TEXT,   -- JSON lista stringova "Ime Prezime (Klub)"
        izgubljeno_od TEXT, -- JSON lista stringova "Ime Prezime (Klub)"
        napomena TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS coach_attendance(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trener_id INTEGER REFERENCES trainers(id) ON DELETE SET NULL,
        trener TEXT,
        datum TEXT NOT NULL,
        grupa TEXT,
        vrijeme_od TEXT,
        vrijeme_do TEXT,
        trajanje_min INTEGER,
        created_at TEXT DEFAULT (datetime('now'))
    )
    """)
    
        # Dodaj nove stupce ako nedostaju
    try:
        cols = pd.read_sql("PRAGMA table_info(competition_results)", get_conn())["name"].tolist()
    except Exception:
        cols = []
    if "medalja" not in cols:
        conn2 = get_conn(); conn2.execute("ALTER TABLE competition_results ADD COLUMN medalja TEXT"); conn2.commit(); conn2.close()
    if "plasman" not in cols:
        conn2 = get_conn(); conn2.execute("ALTER TABLE competition_results ADD COLUMN plasman TEXT"); conn2.commit(); conn2.close()

    conn.commit(); conn.close()

_ensure_extra_tables()


# ======================= Excel I/O =======================
ALLOWED_COLS = {
    "members": ["ime","prezime","datum_rodjenja","godina_rodjenja","email_sportas","email_roditelj",
                "telefon_sportas","telefon_roditelj","clanski_broj","oib","adresa","grupa_trening","foto_path",
                "medical_valid_until","medical_path","pristupnica_date","pristupnica_path","privola_date","privola_path"],
    "trainers": ["ime","prezime","datum_rodjenja","oib","osobna_broj","iban","telefon","email","foto_path","ugovor_path","napomena"],
    "veterans": ["ime","prezime","datum_rodjenja","oib","osobna_broj","telefon","email","foto_path","ugovor_path","napomena"],
    "attendance": ["member_id","datum","termin","grupa","prisutan","trajanje_min"],
    "competitions": ["redni_broj","godina","datum","datum_kraj","natjecanje","ime_natjecanja","stil_hrvanja","mjesto","drzava","kratica_drzave",
                     "nastupilo_podravke","ekipno","trener","napomena","link_rezultati","galerija_json","vijest"],
}

def _normalize_dates(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            try: df[c] = pd.to_datetime(df[c]).dt.date.astype(str)
            except Exception: df[c] = df[c].astype(str)
    return df

def export_table_to_excel(table_name: str, use_allowed_cols: bool = False) -> bytes:
    if use_allowed_cols and table_name in ALLOWED_COLS:
        cols = ", ".join(ALLOWED_COLS[table_name])
        q = f"SELECT {cols} FROM {table_name}"
    else:
        q = f"SELECT * FROM {table_name}"
    df = df_from_sql(q)
    if table_name == "members":
        df = _normalize_dates(df, ["datum_rodjenja","medical_valid_until","pristupnica_date","privola_date"])
    elif table_name in ("trainers","veterans"):
        df = _normalize_dates(df, ["datum_rodjenja"])
    elif table_name == "attendance":
        df = _normalize_dates(df, ["datum"])
    elif table_name == "competitions":
        df = _normalize_dates(df, ["datum","datum_kraj"])
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=table_name)
    return bio.getvalue()

def _cast_types_for_table(table: str, df: pd.DataFrame) -> pd.DataFrame:
    dfx = df.copy()
    if table == "attendance":
        for c in ["member_id","prisutan","trajanje_min"]:
            if c in dfx.columns: dfx[c] = pd.to_numeric(dfx[c], errors="coerce").astype("Int64")
        dfx = _normalize_dates(dfx, ["datum"])
    elif table == "members":
        dfx = _normalize_dates(dfx, ["datum_rodjenja","medical_valid_until","pristupnica_date","privola_date"])
    elif table == "competitions":
        dfx = _normalize_dates(dfx, ["datum","datum_kraj"])
    else:
        dfx = _normalize_dates(dfx, ["datum_rodjenja"])
    return dfx

def import_table_from_excel(file, table_name: str) -> Tuple[int, List[str]]:
    try: df_new = pd.read_excel(file)
    except Exception as e: raise ValueError(f"Ne mogu pročitati Excel: {e}")
    if table_name not in ALLOWED_COLS: raise ValueError("Uvoz nije podržan za ovu tablicu.")
    keep = [c for c in df_new.columns if c in ALLOWED_COLS[table_name]]
    dropped = [c for c in df_new.columns if c not in ALLOWED_COLS[table_name]]
    df_new = df_new[keep].copy()
    df_new = _cast_types_for_table(table_name, df_new)
    conn = get_conn()
    try: df_new.to_sql(table_name, conn, if_exists="append", index=False)
    finally: conn.close()
    warns = []
    if dropped: warns.append("Izostavljene kolone: " + ", ".join(map(str, dropped)))
    return len(df_new), warns

def template_bytes(columns: List[str]) -> Tuple[bytes, str]:
    df = pd.DataFrame(columns=columns)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="predlozak")
    return bio.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# ======================= E-mail podsjetnici =======================
def _send_email(to_list: List[str], subject: str, body: str) -> tuple[bool, str]:
    to_list = [t for t in {t.strip() for t in to_list} if t]
    if not to_list: return False, "Nema primatelja."
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS):
        return True, f"SIMULACIJA — {', '.join(to_list)}"
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = ", ".join(to_list)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.sendmail(SMTP_FROM, to_list, msg.as_string())
        return True, "OK"
    except Exception as e:
        return False, f"Greška: {e}"

def members_needing_medical(days_before=14) -> pd.DataFrame:
    df = df_from_sql("SELECT id, ime, prezime, email_sportas, email_roditelj, medical_valid_until FROM members WHERE medical_valid_until IS NOT NULL")
    if df.empty: return df
    today = date.today()
    def status(d):
        dt = safe_date(d, None)
        if dt is None: return "N/A"
        diff = (dt - today).days
        if diff < 0: return "expired"
        if diff <= days_before: return "soon"
        return "ok"
    df["status"] = df["medical_valid_until"].apply(status)
    return df[df["status"].isin(["expired","soon"])].copy()

def run_daily_reminders(days_before=14) -> Tuple[int,int]:
    today_str = date.today().isoformat()
    try:
        if os.path.isfile(REMINDER_DAY_GUARD):
            if open(REMINDER_DAY_GUARD).read().strip() == today_str:
                return (0,0)
    except Exception: pass
    df = members_needing_medical(days_before)
    sent = skipped = 0
    for _, r in df.iterrows():
        tos = []
        if str(r.get("email_sportas") or "").strip(): tos.append(str(r["email_sportas"]).strip())
        if str(r.get("email_roditelj") or "").strip(): tos.append(str(r["email_roditelj"]).strip())
        if not tos: skipped += 1; continue
        m_until = safe_date(r.get("medical_valid_until"), None)
        status = "ISTEKAO" if (m_until and m_until < date.today()) else "ISTJEČE USKORO"
        subj = f"[HK Podravka] Podsjetnik — Liječnička potvrda ({status})"
        body = f"Poštovani,\n\nZa {r['ime']} {r['prezime']} liječnička potvrda {status.lower()}.\nVrijedi do: {m_until.isoformat() if m_until else '-'}\n\nLP,\nHK Podravka"
        ok, _ = _send_email(tos, subj, body)
        sent += 1 if ok else 0
        skipped += 0 if ok else 1
    try: open(REMINDER_DAY_GUARD,"w").write(today_str)
    except Exception: pass
    return (sent, skipped)

# ======================= UI routing =======================
st.title("🥇 HK Podravka — Sustav")
page = st.sidebar.radio("Navigacija", [
    "👤 Članovi","📅 Prisustvo","🏋️ Treneri","🎖️ Veterani",
    "🏆 Natjecanja","📑 Pristupnice & Privole","👥 Svi članovi",
    "📊 Statistika & Pretraga","📧 Podsjetnici",
    "🥇 Rezultati",
    "🧑‍🏫 Prisustvo trenera",
    "📊 Rezultati — Statistika & Izvoz",
    "⚙️ Postavke",
    "🔁 Uvoz starih rezultata"
])

# ---------------------- ČLANOVI ----------------------
if page == "👤 Članovi":
    tab_add, tab_list, tab_bulk = st.tabs(["➕ Dodaj","📥/📤 Excel & Popis","🗑️ Grupno brisanje"])
    with tab_add:
        with st.form("add_m"):
            c1,c2,c3 = st.columns(3)
            with c1:
                ime=st.text_input("Ime *"); prezime=st.text_input("Prezime *")
                datum_rod=st.date_input("Datum rođenja", value=date(2010,1,1))
            with c2:
                god=st.number_input("Godina rođenja",1900,2100,2010,1)
                email_s=st.text_input("E-mail sportaša"); email_r=st.text_input("E-mail roditelja")
            with c3:
                tel_s=st.text_input("Mobitel sportaša"); tel_r=st.text_input("Mobitel roditelja")
                cl_br=st.text_input("Članski broj")
            c4,c5 = st.columns(2)
            with c4:
                oib=st.text_input("OIB"); adresa=st.text_input("Adresa"); grupa=st.text_input("Grupa treninga (npr. U13)")
            with c5:
                foto=st.file_uploader("Fotografija", type=["png","jpg","jpeg","webp"])
                st.caption("🩺 Liječnička potvrda")
                med_until=st.date_input("Vrijedi do", value=date.today()+timedelta(days=365))
                med_file=st.file_uploader("Potvrda (PDF/JPG/PNG)", type=["pdf","jpg","jpeg","png"])
                st.caption("📑 Pristupnica / Privola")
                pris_date=st.date_input("Datum pristupnice", value=date.today())
                pris_file=st.file_uploader("Pristupnica (PDF/JPG/PNG)", type=["pdf","jpg","jpeg","png"])
                priv_date=st.date_input("Datum privole", value=date.today())
                priv_file=st.file_uploader("Privola (PDF/JPG/PNG)", type=["pdf","jpg","jpeg","png"])
            if st.form_submit_button("Spremi člana"):
                fp = save_upload(foto,"members") if foto else None
                mp = save_upload(med_file,"medical") if med_file else None
                psp = save_upload(pris_file,"pristupnice") if pris_file else None
                pvp = save_upload(priv_file,"privole") if priv_file else None
                exec_sql("""INSERT INTO members
                    (ime,prezime,datum_rodjenja,godina_rodjenja,email_sportas,email_roditelj,telefon_sportas,telefon_roditelj,
                     clanski_broj,oib,adresa,grupa_trening,foto_path,medical_valid_until,medical_path,pristupnica_date,pristupnica_path,privola_date,privola_path)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (ime.strip(),prezime.strip(),str(datum_rod),int(god),email_s.strip(),email_r.strip(),tel_s.strip(),tel_r.strip(),cl_br.strip(),
                     oib.strip(),adresa.strip(),grupa.strip(),fp,str(med_until),mp,str(pris_date),psp,str(priv_date),pvp))
                st.success("✅ Član dodan.")

    with tab_list:
        df = df_from_sql("""SELECT id, ime, prezime, grupa_trening, datum_rodjenja, godina_rodjenja, email_sportas, email_roditelj,
                                   telefon_sportas, telefon_roditelj, clanski_broj, oib, adresa,
                                   medical_valid_until, pristupnica_date, privola_date
                            FROM members ORDER BY prezime, ime""")
        def med_label(s):
            d=safe_date(s,None)
            if d is None: return "—"
            diff=(d-date.today()).days
            if diff<0: return "🟥 istekao"
            if diff<=30: return "🟨 uskoro"
            return "🟩 vrijedi"
        if not df.empty: df["Liječnička"]=df["medical_valid_until"].apply(med_label)
        df_mobile(df)
        st.markdown("### 📤 Izvoz / 📥 Uvoz — Članovi")
        st.download_button("⬇️ Preuzmi članove (Excel)", data=export_table_to_excel("members", True),
                           file_name="clanovi.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        upl=st.file_uploader("📥 Uvezi članove (.xlsx)", type=["xlsx"], key="upl_m")
        if upl:
            try:
                n, warns = import_table_from_excel(upl,"members")
                st.success(f"✅ Uvezeno {n} članova."); [st.info(w) for w in warns]; st.experimental_rerun()
            except Exception as e: st.error(f"❌ Uvoz nije uspio: {e}")
        tpl,mime=template_bytes(ALLOWED_COLS["members"])
        st.download_button("⬇️ Predložak (Članovi)", data=tpl, file_name="predlozak_clanovi.xlsx", mime=mime)

        st.markdown("---")
        st.subheader("🗑️ Pojedinačno brisanje")
        if not df.empty:
            ids = df["id"].tolist()
            opts = df.apply(lambda r: f"{r['prezime']} {r['ime']} ({r.get('grupa_trening','')})", axis=1).tolist()
            to_del = st.selectbox("Član", options=ids, format_func=lambda i: opts[ids.index(i)])
            if st.button("🗑️ Obriši", type="primary"):
                exec_sql("DELETE FROM members WHERE id=?", (int(to_del),))
                st.success("Obrisan."); st.experimental_rerun()

    with tab_bulk:
        dfx=df_from_sql("SELECT id, prezime||' '||ime AS label, grupa_trening FROM members ORDER BY prezime, ime")
        if dfx.empty: st.info("Nema članova.")
        else:
            ids=dfx["id"].tolist(); labels=dfx.apply(lambda r:f"{r['label']} ({r['grupa_trening'] or ''})", axis=1).tolist()
            sel=st.multiselect("Odaberi članove", options=ids, format_func=lambda i: labels[ids.index(i)])
            if st.button("🗑️ Obriši odabrane", type="primary", disabled=not sel):
                exec_many("DELETE FROM members WHERE id=?", [(int(i),) for i in sel])
                st.success(f"Obrisano: {len(sel)}"); st.experimental_rerun()


st.markdown("---")
st.subheader("📎 Dokumenti člana (upload)")
dfl = df_from_sql("SELECT id, prezime||' '||ime AS label FROM members ORDER BY prezime, ime")
if dfl.empty:
    st.info("Nema članova.")
else:
    sel_mid = st.selectbox("Član", options=dfl["id"].tolist(), format_func=lambda i: dfl.loc[dfl['id']==i,'label'].iloc[0], key="doc_member")
    c1,c2 = st.columns(2)
    with c1:
        med_file = st.file_uploader("Liječnička potvrda — upload (PDF/JPG)", type=["pdf","jpg","jpeg","png"], key="med_upl")
        med_until = st.date_input("Vrijedi do", value=None, key="med_until")
    with c2:
        pri_file = st.file_uploader("Pristupnica — upload (PDF/JPG)", type=["pdf","jpg","jpeg","png"], key="pri_upl")
        pass_no = st.text_input("Broj putovnice", value="", key="pass_no")
        pass_until = st.date_input("Putovnica vrijedi do", value=None, key="pass_until")
    if st.button("💾 Spremi dokumente", type="primary", key="save_docs"):
        updates = {}
        Path("data/uploads").mkdir(parents=True, exist_ok=True)
        if med_file is not None:
            mp = f"data/uploads/med_{sel_mid}_{int(datetime.now().timestamp())}.{med_file.name.split('.')[-1]}"
            with open(mp, "wb") as f: f.write(med_file.read())
            updates["medical_path"] = mp
        if med_until:
            updates["medical_valid_until"] = str(med_until)
        if pri_file is not None:
            pp = f"data/uploads/pristupnica_{sel_mid}_{int(datetime.now().timestamp())}.{pri_file.name.split('.')[-1]}"
            with open(pp, "wb") as f: f.write(pri_file.read())
            updates["pristupnica_path"] = pp
            updates["pristupnica_date"] = str(date.today())
        if pass_no.strip():
            updates["passport_number"] = pass_no.strip()
        if pass_until:
            updates["passport_expiry"] = str(pass_until)
        if updates:
            sets = ", ".join([f"{k}=?" for k in updates.keys()])
            params = list(updates.values()) + [int(sel_mid)]
            exec_sql(f"UPDATE members SET {sets} WHERE id=?", tuple(params))
            st.success("Spremljeno.")
# ---------------------- PRISUSTVO ----------------------
elif page == "📅 Prisustvo":
    st.subheader("📅 Evidencija prisustva članova")
    d = st.date_input("Datum", value=date.today())
    termin = st.text_input("Termin (npr. 18:30-20:00)", value="18:30-20:00")
    df_groups = df_from_sql("SELECT DISTINCT grupa_trening FROM members WHERE COALESCE(grupa_trening,'')<>'' ORDER BY 1")
    groups = ["(sve)"] + df_groups["grupa_trening"].astype(str).tolist()
    grupa = st.selectbox("Grupa", groups)
    if grupa == "(sve)":
        dfm = df_from_sql("SELECT id, ime, prezime, grupa_trening FROM members ORDER BY prezime, ime")
    else:
        dfm = df_from_sql("SELECT id, ime, prezime, grupa_trening FROM members WHERE grupa_trening=? ORDER BY prezime, ime",(grupa,))
    if dfm.empty:
        st.info("Nema članova u grupi.")
    else:
        ids=dfm["id"].tolist(); labels=dfm.apply(lambda r: f"{r['prezime']} {r['ime']} ({r.get('grupa_trening','')})", axis=1).tolist()
        checked=st.multiselect("Označi prisutne", options=ids, format_func=lambda i: labels[ids.index(i)])
        trajanje=st.number_input("Trajanje (min)", 30, 180, 90, 5)
        if st.button("💾 Spremi prisustvo"):
            rows=[(int(mid), str(d), termin.strip(), "" if grupa=="(sve)" else grupa, 1, int(trajanje)) for mid in checked]
            if rows: exec_many("INSERT INTO attendance (member_id, datum, termin, grupa, prisutan, trajanje_min) VALUES (?,?,?,?,?,?)", rows)
            st.success(f"Spremljeno prisutnih: {len(rows)}")

    st.divider()
    st.subheader("📈 Zadnjih 200")
    q = """SELECT a.datum, a.termin, m.prezime||' '||m.ime AS clan,
                  COALESCE(a.grupa, m.grupa_trening) AS grupa, a.trajanje_min
           FROM attendance a JOIN members m ON m.id=a.member_id
           ORDER BY a.datum DESC, m.prezime ASC LIMIT 200"""
    df_last = df_from_sql(q); df_mobile(df_last)

    st.markdown("---"); st.markdown("### 📤 Izvoz / 📥 Uvoz — Prisustvo")
    st.download_button("⬇️ Preuzmi prisustvo (Excel)", data=export_table_to_excel("attendance", True),
                       file_name="prisustvo.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    upl=st.file_uploader("📥 Uvezi prisustvo (.xlsx)", type=["xlsx"], key="upl_att")
    if upl:
        try:
            n, warns = import_table_from_excel(upl, "attendance")
            st.success(f"✅ Uvezeno {n} zapisa."); [st.info(w) for w in warns]; st.experimental_rerun()
        except Exception as e: st.error(f"❌ Uvoz nije uspio: {e}")
    tpl,mime=template_bytes(ALLOWED_COLS["attendance"])
    st.download_button("⬇️ Predložak (Prisustvo)", data=tpl, file_name="predlozak_prisustvo.xlsx", mime=mime)

# ---------------------- TRENERI ----------------------
elif page == "🏋️ Treneri":
    tab_add, tab_list = st.tabs(["➕ Dodaj","📥/📤 Excel & Popis"])
    with tab_add:
        with st.form("add_t"):
            c1,c2,c3 = st.columns(3)
            with c1:
                ime=st.text_input("Ime *"); prezime=st.text_input("Prezime *")
                datum_rod=st.date_input("Datum rođenja", value=date(1990,1,1))
            with c2:
                osobna=st.text_input("Broj osobne"); iban=st.text_input("IBAN"); telefon=st.text_input("Mobitel")
            with c3:
                email=st.text_input("E-mail"); oib=st.text_input("OIB"); napomena=st.text_area("Napomena", height=80)
            foto=st.file_uploader("Fotografija", type=["png","jpg","jpeg","webp"])
            ugovor=st.file_uploader("Ugovor (PDF/DOC/DOCX)", type=["pdf","doc","docx"])
            if st.form_submit_button("Spremi trenera"):
                fp=save_upload(foto,"trainers") if foto else None
                up=save_upload(ugovor,"trainers") if ugovor else None
                exec_sql("""INSERT INTO trainers (ime,prezime,datum_rodjenja,oib,osobna_broj,iban,telefon,email,foto_path,ugovor_path,napomena)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                         (ime.strip(),prezime.strip(),str(datum_rod),oib.strip(),osobna.strip(),iban.strip(),telefon.strip(),email.strip(),fp,up,napomena.strip()))
                st.success("✅ Trener dodan.")
    with tab_list:
        dft=df_from_sql("SELECT ime, prezime, datum_rodjenja, osobna_broj, iban, telefon, email, oib, foto_path, ugovor_path, napomena FROM trainers ORDER BY prezime, ime")
        df_mobile(dft)
        st.markdown("### 📤 Izvoz / 📥 Uvoz — Treneri")
        st.download_button("⬇️ Preuzmi trenere (Excel)", data=export_table_to_excel("trainers", True), file_name="treneri.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        upl=st.file_uploader("📥 Uvezi trenere (.xlsx)", type=["xlsx"], key="upl_t")
        if upl:
            try:
                n,w=import_table_from_excel(upl,"trainers"); st.success(f"✅ Uvezeno {n} trenera."); [st.info(i) for i in w]; st.experimental_rerun()
            except Exception as e: st.error(f"❌ Uvoz nije uspio: {e}")
        tpl,mime=template_bytes(ALLOWED_COLS["trainers"])
        st.download_button("⬇️ Predložak (Treneri)", data=tpl, file_name="predlozak_treneri.xlsx", mime=mime)

# ---------------------- VETERANI ----------------------
elif page == "🎖️ Veterani":
    tab_add, tab_list = st.tabs(["➕ Dodaj","📥/📤 Excel & Popis"])
    with tab_add:
        with st.form("add_v"):
            c1,c2,c3=st.columns(3)
            with c1:
                ime=st.text_input("Ime *"); prezime=st.text_input("Prezime *")
                datum_rod=st.date_input("Datum rođenja", value=date(1980,1,1))
            with c2:
                osobna=st.text_input("Broj osobne"); telefon=st.text_input("Mobitel"); email=st.text_input("E-mail")
            with c3:
                oib=st.text_input("OIB"); napomena=st.text_area("Napomena", height=80)
            foto=st.file_uploader("Fotografija", type=["png","jpg","jpeg","webp"])
            ugovor=st.file_uploader("Dokument (PDF/DOC/DOCX)", type=["pdf","doc","docx"])
            if st.form_submit_button("Spremi veterana"):
                fp=save_upload(foto,"veterans") if foto else None
                up=save_upload(ugovor,"veterans") if ugovor else None
                exec_sql("""INSERT INTO veterans (ime,prezime,datum_rodjenja,oib,osobna_broj,telefon,email,foto_path,ugovor_path,napomena)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""",
                         (ime.strip(),prezime.strip(),str(datum_rod),oib.strip(),osobna.strip(),telefon.strip(),email.strip(),fp,up,napomena.strip()))
                st.success("✅ Veteran dodan.")
    with tab_list:
        dfv=df_from_sql("SELECT ime, prezime, datum_rodjenja, osobna_broj, telefon, email, oib, foto_path, ugovor_path, napomena FROM veterans ORDER BY prezime, ime")
        df_mobile(dfv)
        st.markdown("### 📤 Izvoz / 📥 Uvoz — Veterani")
        st.download_button("⬇️ Preuzmi veterane (Excel)", data=export_table_to_excel("veterans", True), file_name="veterani.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        upl=st.file_uploader("📥 Uvezi veterane (.xlsx)", type=["xlsx"], key="upl_v")
        if upl:
            try:
                n,w=import_table_from_excel(upl,"veterans"); st.success(f"✅ Uvezeno {n} veterana."); [st.info(i) for i in w]; st.experimental_rerun()
            except Exception as e: st.error(f"❌ Uvoz nije uspio: {e}")
        tpl,mime=template_bytes(ALLOWED_COLS["veterans"])
        st.download_button("⬇️ Predložak (Veterani)", data=tpl, file_name="predlozak_veterani.xlsx", mime=mime)

# ---------------------- NATJECANJA ----------------------
elif page == "🏆 Natjecanja":
    st.subheader("➕ Unos natjecanja")
    with st.form("frm_comp"):
        dfl = df_from_sql("SELECT MAX(redni_broj) AS mx FROM competitions")
        next_rb = 1 if dfl.empty or dfl.iloc[0,0] is None else int(dfl.iloc[0,0])+1
        st.caption(f"Redni broj (auto): **{next_rb}**")
        c1,c2,c3 = st.columns(3)
        with c1:
            godina = st.number_input("Godina", 1990, 2100, date.today().year, 1)
            datum = st.date_input("Datum (početak)", value=date.today())
            datum_kraj = st.date_input("Datum (kraj)", value=date.today())
        with c2:
            natjecanje = st.selectbox("Tip natjecanja", ["PRVENSTVO HRVATSKE","REPREZENTATIVNI NASTUP","MEĐUNARODNI TURNIR","KUP","LIGA","REGIONALNO","KVALIFIKACIJE","ŠKOLSKO","OSTALO"], index=0)
            ime_natjecanja = st.text_input("Ime natjecanja (opcionalno)")
            stil = st.selectbox("Stil", ["GR","FS","WW","BW","MODIFICIRANI"], index=0)
        with c3:
            mjesto = st.text_input("Mjesto")
            drzava = st.text_input("Država")
            kratica = st.text_input("Kratica (CRO/ITA...)", value="CRO")
        c4,c5 = st.columns(2)
        with c4:
            nastupilo = st.number_input("Nastupilo hrvača Podravke", 0, 1000, 0, 1)
            ekipno = st.text_input("Ekipno (npr. ekipni poredak)")
        with c5:
            trener = st.text_input("Trener")
        link_rez = st.text_input("Link na rezultate (URL)")
        napomena = st.text_area("Napomena", height=80)
        vijest = st.text_area("Tekst vijesti (za web objavu)", height=120)
        imgs = st.file_uploader("Slike (više datoteka)", type=["png","jpg","jpeg","webp"], accept_multiple_files=True)
        if st.form_submit_button("Spremi natjecanje"):
            cid = exec_sql("""INSERT INTO competitions
                    (redni_broj,godina,datum,datum_kraj,natjecanje,ime_natjecanja,stil_hrvanja,mjesto,drzava,kratica_drzave,
                     nastupilo_podravke,ekipno,trener,napomena,link_rezultati,galerija_json,vijest)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (next_rb,int(godina),str(datum),str(datum_kraj),natjecanje.strip(),ime_natjecanja.strip(),stil.strip(),
                 mjesto.strip(),drzava.strip(),kratica.strip(),int(nastupilo),ekipno.strip(),trener.strip(),
                 napomena.strip(),link_rez.strip(),None,vijest.strip()))
            paths=[]
            if imgs:
                for f in imgs:
                    p = save_upload(f,"competitions")
                    if p: paths.append(p)
            if paths:
                exec_sql("UPDATE competitions SET galerija_json=? WHERE id=?", (json.dumps(paths, ensure_ascii=False), cid))
            st.success("✅ Natjecanje spremljeno.")

    st.divider()
    st.subheader("📋 Popis natjecanja")
    dfc = df_from_sql("SELECT id, redni_broj, godina, datum, ime_natjecanja, mjesto, drzava FROM competitions ORDER BY godina DESC, datum DESC")
    df_mobile(dfc)
    st.markdown("### 📤 Izvoz / 📥 Uvoz — Natjecanja")
    st.download_button("⬇️ Preuzmi (Excel)", data=export_table_to_excel("competitions", True),
                       file_name="natjecanja.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    upl=st.file_uploader("📥 Uvezi natjecanja (.xlsx)", type=["xlsx"], key="upl_comp")
    if upl:
        try:
            n,w=import_table_from_excel(upl,"competitions"); st.success(f"✅ Uvezeno {n} natjecanja."); [st.info(i) for i in w]; st.experimental_rerun()
        except Exception as e: st.error(f"❌ Uvoz nije uspio: {e}")
    tpl,mime=template_bytes(ALLOWED_COLS["competitions"])
    st.download_button("⬇️ Predložak (Natjecanja)", data=tpl, file_name="predlozak_natjecanja.xlsx", mime=mime)

# ---------------------- PRISTUPNICE/PRIVOLE ----------------------
elif page == "📑 Pristupnice & Privole":
    st.subheader("Upravljanje dokumentima po članu")
    dfm = df_from_sql("SELECT id, prezime||' '||ime AS naziv, medical_valid_until, pristupnica_date, privola_date FROM members ORDER BY prezime, ime")
    if dfm.empty:
        st.info("Nema članova.")
    else:
        ids=dfm["id"].tolist(); labels=dfm["naziv"].tolist()
        mid = st.selectbox("Član", options=ids, format_func=lambda i: labels[ids.index(i)])
        c1,c2,c3 = st.columns(3)
        with c1:
            med_until = st.date_input("Liječnička vrijedi do", value=safe_date(dfm[dfm["id"]==mid]["medical_valid_until"], date.today()+timedelta(days=365)))
            med_file = st.file_uploader("Liječnička (PDF/JPG/PNG)", type=["pdf","jpg","jpeg","png"], key="med_up")
        with c2:
            pris_date = st.date_input("Datum pristupnice", value=safe_date(dfm[dfm["id"]==mid]["pristupnica_date"], date.today()))
            pris_file = st.file_uploader("Pristupnica (PDF/JPG/PNG)", type=["pdf","jpg","jpeg","png"], key="pris_up")
        with c3:
            priv_date = st.date_input("Datum privole", value=safe_date(dfm[dfm["id"]==mid]["privola_date"], date.today()))
            priv_file = st.file_uploader("Privola (PDF/JPG/PNG)", type=["pdf","jpg","jpeg","png"], key="priv_up")
        if st.button("💾 Spremi dokumente"):
            mp = save_upload(med_file,"medical") if med_file else None
            psp = save_upload(pris_file,"pristupnice") if pris_file else None
            pvp = save_upload(priv_file,"privole") if priv_file else None
            old = df_from_sql("SELECT medical_path,pristupnica_path,privola_path FROM members WHERE id=?", (int(mid),))
            old_med, old_pris, old_priv = (old.iloc[0][c] if not old.empty else None for c in ["medical_path","pristupnica_path","privola_path"])
            exec_sql("""UPDATE members SET medical_valid_until=?, medical_path=?, pristupnica_date=?, pristupnica_path=?, privola_date=?, privola_path=? WHERE id=?""",
                     (str(med_until), mp or old_med, str(pris_date), psp or old_pris, str(priv_date), pvp or old_priv, int(mid)))
            st.success("Spremljeno.")

    st.divider()
    st.subheader("📊 Popis i status")
    df = df_from_sql("SELECT prezime||' '||ime AS član, grupa_trening, medical_valid_until, pristupnica_date, privola_date FROM members ORDER BY prezime, ime")
    df_mobile(df)

# ---------------------- SVI ČLANOVI ----------------------
elif page == "👥 Svi članovi":
    st.subheader("Kompletan popis članova")
    df = df_from_sql("SELECT * FROM members ORDER BY prezime, ime")
    if df.empty: st.info("Nema članova u bazi.")
    else:
        def med_color(x):
            d = safe_date(x, None)
            if d is None: return '<span class="badge red">nema</span>'
            days = (d - date.today()).days
            if days < 0: cls="red"
            elif days <= 30: cls="yellow"
            else: cls="green"
            return f'<span class="badge {cls}">{d.isoformat()}</span>'
        show=df.copy()
        show["Liječnička"]=show["medical_valid_until"].apply(med_color)
        st.write(show.to_html(escape=False, index=False), unsafe_allow_html=True)

# ---------------------- STATISTIKA ----------------------
elif page == "📊 Statistika & Pretraga":
    tabs = st.tabs(["Članovi","Treneri","Veterani","Prisustvo"])
    with tabs[0]:
        c1,c2,c3 = st.columns(3)
        ime = c1.text_input("Ime sadrži")
        prez = c2.text_input("Prezime sadrži")
        grp = c3.text_input("Grupa (točno)")
        q = "SELECT ime, prezime, grupa_trening, godina_rodjenja, medical_valid_until, pristupnica_date, privola_date FROM members WHERE 1=1"
        params = []
        if ime: q += " AND ime LIKE ?"; params.append(f"%{ime}%")
        if prez: q += " AND prezime LIKE ?"; params.append(f"%{prez}%")
        if grp: q += " AND grupa_trening = ?"; params.append(grp.strip())
        q += " ORDER BY prezime, ime"
        df = df_from_sql(q, tuple(params)); df_mobile(df)
    with tabs[1]:
        txt = st.text_input("Traži (ime/prezime/telefon/email) — Treneri")
        df = df_from_sql("SELECT ime, prezime, telefon, email, iban FROM trainers")
        if txt:
            t = txt.lower()
            df = df[df.apply(lambda r, term=t: term in str(r.values).lower(), axis=1)]
        df_mobile(df)
    with tabs[2]:
        txt = st.text_input("Traži (ime/prezime/telefon/email) — Veterani")
        df = df_from_sql("SELECT ime, prezime, telefon, email FROM veterans")
        if txt:
            t = txt.lower()
            df = df[df.apply(lambda r, term=t: term in str(r.values).lower(), axis=1)]
        df_mobile(df)
    with tabs[3]:
        c1,c2,c3 = st.columns(3)
        od=c1.date_input("Od", value=date.today()-timedelta(days=30))
        do=c2.date_input("Do", value=date.today())
        grp=c3.text_input("Grupa")
        q = """SELECT a.datum, a.termin, a.grupa, m.prezime||' '||m.ime AS clan, a.trajanje_min
               FROM attendance a JOIN members m ON m.id=a.member_id
               WHERE date(a.datum) BETWEEN ? AND ?"""
        params=[str(od), str(do)]
        if grp: q += " AND COALESCE(a.grupa, m.grupa_trening) = ?"; params.append(grp.strip())
        q += " ORDER BY a.datum DESC, clan ASC"
        df=df_from_sql(q, tuple(params))
        if not df.empty:
            mins=df["trajanje_min"].fillna(0).sum()
            st.caption(f"Zapisa: {len(df)} · Ukupno: {mins} min ({mins/60.0:.2f} h)")
        df_mobile(df)

# ---------------------- PODSJETNICI ----------------------
else:
    st.subheader("📧 E-mail podsjetnici (liječnička potvrda)")
    days = st.number_input("Podsjeti kad je ostalo (dana) ili je isteklo", 1, 120, 14, 1)
    df_need = members_needing_medical(days)
    if df_need.empty:
        st.success("Nema članova za podsjetnik.")
    else:
        st.info(f"Za slanje: {len(df_need)}")
        df_mobile(df_need)
        if st.button("📨 Pošalji podsjetnike sada"):
            sent = skipped = 0
            for _, r in df_need.iterrows():
                tos = []
                if str(r.get("email_sportas") or "").strip(): tos.append(str(r["email_sportas"]).strip())
                if str(r.get("email_roditelj") or "").strip(): tos.append(str(r["email_roditelj"]).strip())
                if not tos: skipped += 1; continue
                m_until = safe_date(r.get("medical_valid_until"), None)
                status = "ISTEKAO" if (m_until and m_until < date.today()) else "ISTJEČE USKORO"
                subj = f"[HK Podravka] Podsjetnik — Liječnička potvrda ({status})"
                body = (f"Poštovani,\n\nZa {r['ime']} {r['prezime']} liječnička potvrda {status.lower()}.\n"
                        f"Vrijedi do: {m_until.isoformat() if m_until else '-'}\n\nMolimo obnovu potvrde.\n\nLP,\nHK Podravka")
                ok, _ = _send_email(tos, subj, body)
                sent += 1 if ok else 0; skipped += 0 if ok else 1
            st.success(f"Poslano: {sent}, preskočeno: {skipped}")
    if AUTO_EMAIL_REMINDERS:
        s,k = run_daily_reminders(days)
        if s or k: st.info(f"Automatski ciklus: poslano {s}, preskočeno {k}.")
        else: st.caption("Automatski ciklus danas je već odrađen ili nema primatelja.")




# ---- Predložak za Excel (rezultati natjecanja) ----
def get_results_template_excel(df_members=None) -> bytes:
    import pandas as pd
    from io import BytesIO
    cols = ["sportas","member_id","kategorija","ukupno_borbi","pobjeda","poraza","pobjede_nad","izgubljeno_od","napomena","medalja","plasman"]
    rows = []
        if df_members is not None and not df_members.empty:
            for _, rr in df_members.iterrows():
                rows.append({"sportas": f"{rr.prezime} {rr.ime}", "member_id": int(rr.id), "kategorija": "", "ukupno_borbi": "", "pobjeda": "", "poraza": "", "pobjede_nad": "", "izgubljeno_od": "", "napomena": "", "medalja": "—", "plasman": ""})
        example = rows if rows else [{
        "sportas": "Prezime Ime",
        "member_id": "",
        "kategorija": "U15 52kg",
        "ukupno_borbi": 3,
        "pobjeda": 2,
        "poraza": 1,
        "pobjede_nad": "Novak Luka (Klub A)\nHorvat Marko (Klub B)",
        "izgubljeno_od": "Ivić Ivan (Klub C)",
        "napomena": "",
        "medalja": "🥈",
        "plasman": "2."
    }]
    df = pd.DataFrame(example, columns=cols)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Rezultati")
        ws = writer.sheets["Rezultati"]
        # malo šire kolone
        for i, w in enumerate([22,10,18,14,10,10,28,28,18,10,10]):
            ws.set_column(i, i, w)
    return bio.getvalue()


# ---- Validacija uvoza rezultata ----
def _validate_results_import(dfu, members_df):
    import pandas as pd, json
    allowed_medals = {"—","🥇","🥈","🥉","",None,pd.NA}
    valid_member_ids = set(members_df["id"].astype(int).tolist()) if not members_df.empty else set()
    dfu = dfu.copy()
    dfu.columns = [str(c).strip().lower() for c in dfu.columns]
    for c in ["sportas","member_id","kategorija","ukupno_borbi","pobjeda","poraza","pobjede_nad","izgubljeno_od","napomena","medalja","plasman"]:
        if c not in dfu.columns: dfu[c] = None
    statuses = []; parsed_rows = []
    for _, rr in (good if not suhi_test else prev[0:0]).iterrows():
        errs = []
        mid = None
        if pd.notna(rr.get("member_id")) and str(rr.get("member_id")).strip() != "":
            try:
                mid = int(rr.get("member_id"))
                if mid not in valid_member_ids: errs.append(f"member_id {mid} ne postoji")
            except Exception:
                errs.append("member_id nije broj")
        sportas = str(rr.get("sportas")).strip() if pd.notna(rr.get("sportas")) else ""
        if not sportas and not mid:
            errs.append("nedostaje 'sportas' ili 'member_id'")
        def to_int(x, name):
            if pd.isna(x) or str(x).strip()=="": return 0
            try: return int(x)
            except Exception: errs.append(f"{name} nije broj"); return 0
        ukupno = to_int(rr.get("ukupno_borbi"), "ukupno_borbi")
        pobjeda = to_int(rr.get("pobjeda"), "pobjeda")
        poraza = to_int(rr.get("poraza"), "poraza")
        if ukupno and (pobjeda+poraza)!=ukupno: errs.append("pobjeda+poraza != ukupno_borbi")
        pobjede_list = [str(x).strip() for x in str(rr.get("pobjede_nad") or "").splitlines() if str(x).strip()]
        izgubljeno_list = [str(x).strip() for x in str(rr.get("izgubljeno_od") or "").splitlines() if str(x).strip()]
        med = str(rr.get("medalja")).strip() if pd.notna(rr.get("medalja")) else ""
        if med not in allowed_medals: errs.append("medalja mora biti —/🥇/🥈/🥉 ili prazno")
        med = None if med in {"","—"} else med
        plas = str(rr.get("plasman")).strip() if pd.notna(rr.get("plasman")) else None
        parsed_rows.append({
            "member_id": mid, "sportas": sportas or None, "kategorija": (str(rr.get("kategorija")).strip() if pd.notna(rr.get("kategorija")) else None),
            "ukupno_borbi": ukupno, "pobjeda": pobjeda, "poraza": poraza,
            "pobjede_nad": json.dumps(pobjede_list), "izgubljeno_od": json.dumps(izgubljeno_list),
            "napomena": (str(rr.get("napomena")).strip() if pd.notna(rr.get("napomena")) else None),
            "medalja": med, "plasman": plas
        })
        statuses.append("; ".join(errs) if errs else "OK")
    out = pd.DataFrame(parsed_rows); out["status"] = statuses
    return out

# ---------------------- REZULTATI ----------------------
if page == "🥇 Rezultati":
    st.header("🥇 Rezultati natjecanja")
    # Odabir natjecanja koje je već uneseno
    df_comp = df_from_sql("SELECT id, godina, datum, datum_kraj, natjecanje, ime_natjecanja, stil_hrvanja, mjesto, drzava, kratica_drzave, nastupilo_podravke, ekipno, trener, napomena FROM competitions ORDER BY godina DESC, datum DESC, redni_broj DESC")
    if df_comp.empty:
        st.info("Prvo unesite natjecanje u odjeljku **🏆 Natjecanja**.")
    else:
        opt = st.selectbox("Natjecanje", options=df_comp["id"].tolist(),
                           format_func=lambda i: f"{df_comp.loc[df_comp['id']==i,'godina'].iloc[0]} — {df_comp.loc[df_comp['id']==i,'ime_natjecanja'].iloc[0]} ({df_comp.loc[df_comp['id']==i,'mjesto'].iloc[0]})")
        sel = df_comp[df_comp["id"]==opt].iloc[0].to_dict()
        with st.expander("Detalji odabranog natjecanja", expanded=True):
            c1,c2,c3 = st.columns(3)
            with c1:
                st.write("**Godina:**", sel.get("godina"))
                st.write("**Datum:**", sel.get("datum"))
                st.write("**Datum kraj:**", sel.get("datum_kraj"))
                st.write("**Stil hrvanja:**", sel.get("stil_hrvanja"))
            with c2:
                st.write("**Naziv:**", sel.get("ime_natjecanja"))
                st.write("**Natjecanje:**", sel.get("natjecanje"))
                st.write("**Mjesto:**", sel.get("mjesto"))
                st.write("**Država:**", sel.get("drzava"))
            with c3:
                st.write("**Ekipno:**", sel.get("ekipno"))
                st.write("**Trener:**", sel.get("trener"))
                st.write("**Nastupilo Podravke:**", sel.get("nastupilo_podravke"))
                st.write("**Napomena:**", sel.get("napomena"))
        st.markdown("---")

        # Unos rezultata po sportašu
        st.subheader("➕ Unos rezultata sportaša")

# Predložak i uvoz
with st.expander("📥 Uvoz iz Excela / 📄 Preuzmi predložak", expanded=False):
    colt1, colt2 = st.columns([1,1])
    with colt1:
        if st.button("📄 Preuzmi Excel predložak", use_container_width=True):
            content = get_results_template_excel()
            fname_t = f"/mnt/data/rezultati_predlozak.xlsx"
            with open(fname_t, "wb") as f: f.write(content)
            st.success(f"[Preuzmi predložak]({fname_t})")
    with colt2:
        upl = st.file_uploader("Učitaj Excel s rezultatima (sheet 'Rezultati')", type=["xlsx"])
                    suhi_test = st.checkbox("Suhi test (bez spremanja u bazu)", value=True)
        if upl is not None:
            import pandas as pd, json
            try:
                dfu = pd.read_excel(upl, sheet_name=0)
                            df_members = df_from_sql("SELECT id FROM members")
                            prev = _validate_results_import(dfu, df_members)
                            st.markdown("**Pregled validacije**")
                            st.dataframe(prev, use_container_width=True)
                            good = prev[prev["status"]=="OK"]
                            bad = prev[prev["status"]!="OK"]
                            st.success(f"Ispravnih redaka: {len(good)}")
                            st.warning(f"Redaka s greškom: {len(bad)}")
                # Normaliziraj nazive kolona
                dfu.columns = [str(c).strip().lower() for c in dfu.columns]
                needed = ["sportas","member_id","kategorija","ukupno_borbi","pobjeda","poraza","pobjede_nad","izgubljeno_od","napomena","medalja","plasman"]
                for c in needed:
                    if c not in dfu.columns: dfu[c] = None
                # Insert svaki red
                inserted = 0; skipped = 0
                for _, rr in (good if not suhi_test else prev[0:0]).iterrows():
                    pobjede_list = []
                    if pd.notna(rr.get("pobjede_nad")):
                        pobjede_list = [str(x).strip() for x in str(rr["pobjede_nad"]).splitlines() if str(x).strip()]
                    izgubljeno_list = []
                    if pd.notna(rr.get("izgubljeno_od")):
                        izgubljeno_list = [str(x).strip() for x in str(rr["izgubljeno_od"]).splitlines() if str(x).strip()]
                    # member_id opcionalan
                    mid = rr.get("member_id")
                    try:
                        mid = int(mid) if pd.notna(mid) and str(mid).strip() != "" else None
                    except Exception:
                        mid = None
                    try:
                        exec_sql("""
                            INSERT INTO competition_results(competition_id, member_id, sportas, kategorija, ukupno_borbi, pobjeda, poraza, pobjede_nad, izgubljeno_od, napomena, medalja, plasman)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (int(sel["id"]), mid, (str(rr.get("sportas")).strip() if pd.notna(rr.get("sportas")) else None),
                                (str(rr.get("kategorija")).strip() if pd.notna(rr.get("kategorija")) else None),
                                int(rr.get("ukupno_borbi") or 0), int(rr.get("pobjeda") or 0), int(rr.get("poraza") or 0),
                                json.dumps(pobjede_list), json.dumps(izgubljeno_list),
                                (str(rr.get("napomena")).strip() if pd.notna(rr.get("napomena")) else None),
                                (str(rr.get("medalja")).strip() if pd.notna(rr.get("medalja")) and str(rr.get("medalja")).strip() != "—" else None),
                                (str(rr.get("plasman")).strip() if pd.notna(rr.get("plasman")) else None)))
                        inserted += 1
                    except Exception:
                        skipped += 1
                st.success(f"Uvezeno redaka: {inserted}, preskočeno: {skipped}")
                st.info("Napomena: 'member_id' je opcionalan. Ako je ispunjen i postoji u bazi, sportaš se veže na člana.")
            except Exception as e:
                st.error(f"Greška pri čitanju Excela: {e}")

        df_m = df_from_sql("SELECT id, ime, prezime, grupa_trening FROM members ORDER BY prezime, ime")
        member_map = {int(r.id): f"{r.prezime} {r.ime} ({r.grupa_trening or ''})" for _,r in df_m.iterrows()} if not df_m.empty else {}
        colA, colB = st.columns([2,1])
        with colA:
            member_id = st.selectbox("Sportaš (opcionalno)", options=[None]+list(member_map.keys()), format_func=lambda i: "—" if i is None else member_map[i])
            sportas = st.text_input("Ime i prezime (ako nije iz baze)", value=(member_map[member_id].split(' (')[0] if member_id else ""))
            kategorija = st.text_input("Kategorija (npr. U15 52kg)")
        with colB:
            ukupno = st.number_input("Ukupno borbi", min_value=0, value=0, step=1)
            pobjeda = st.number_input("Pobjeda", min_value=0, value=0, step=1)
            poraza = st.number_input("Poraza", min_value=0, value=0, step=1)
        c1, c2 = st.columns(2)
        with c1:
            pobjede_nad_raw = st.text_area("Pobjede nad (po jedan red):", placeholder="Ime Prezime (Klub)\n...")
        with c2:
            izgubljeno_od_raw = st.text_area("Izgubljeno od (po jedan red):", placeholder="Ime Prezime (Klub)\n...")
        
colm1, colm2 = st.columns(2)
with colm1:
    napomena = st.text_area("Napomena (opcionalno)", placeholder="...")
with colm2:
    medalja = st.selectbox("Medalja", options=["—","🥇","🥈","🥉"], index=0)
    plasman = st.text_input("Plasman (npr. 5.)", value="")


        if st.button("💾 Spremi rezultat", type="primary", use_container_width=True):
            pobjede_list = [x.strip() for x in (pobjede_nad_raw or "").splitlines() if x.strip()]
            izgubljeno_list = [x.strip() for x in (izgubljeno_od_raw or "").splitlines() if x.strip()]
            exec_sql("""
                INSERT INTO competition_results(competition_id, member_id, sportas, kategorija, ukupno_borbi, pobjeda, poraza, pobjede_nad, izgubljeno_od, napomena, medalja, plasman)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (int(sel["id"]), int(member_id) if member_id else None, sportas.strip() or None, kategorija.strip() or None, int(ukupno), int(pobjeda), int(poraza), json.dumps(pobjede_list), json.dumps(izgubljeno_list), (napomena.strip() or None), (medalja if medalja!='—' else None), (plasman.strip() or None)))
            st.success("Rezultat spremljen.")

        # Popis rezultata za odabrano natjecanje
        st.subheader("📋 Rezultati — popis")
        dfr = df_from_sql("""
            SELECT r.id, COALESCE(r.sportas, m.prezime||' '||m.ime) AS sportas, r.kategorija, r.ukupno_borbi, r.pobjeda, r.poraza, r.pobjede_nad, r.izgubljeno_od, r.napomena
            FROM competition_results r
            LEFT JOIN members m ON m.id = r.member_id
            WHERE r.competition_id=?
            ORDER BY sportas
        """, (int(sel["id"]),))
        if dfr.empty:
            st.caption("Nema unesenih rezultata.")
        else:
            # Pretvori JSON polja u čitljiv tekst
            def _join_json(col):
                try:
                    arr = json.loads(col) if col else []
                    return "\\n".join(arr)
                except Exception:
                    return str(col or "")
            dfr["Pobjede nad"] = dfr["pobjede_nad"].apply(_join_json)
            dfr["Izgubljeno od"] = dfr["izgubljeno_od"].apply(_join_json)
            dfr = dfr.drop(columns=["pobjede_nad","izgubljeno_od"])
                if "medalja" in dfr.columns: dfr.rename(columns={"medalja":"Medalja"}, inplace=True)
                if "plasman" in dfr.columns: dfr.rename(columns={"plasman":"Plasman"}, inplace=True)
            st.dataframe(dfr, use_container_width=True)
            # Brisanje pojedinog rezultata
            rid = st.selectbox("Brisanje rezultata (odaberi ID)", options=[None]+dfr["id"].astype(int).tolist())
            if rid and st.button("🗑️ Obriši odabrani rezultat"):
                exec_sql("DELETE FROM competition_results WHERE id=?", (int(rid),))
                st.success("Obrisano."); st.experimental_rerun()

# ------------------ PRISUSTVO TRENERA ------------------
if page == "🧑‍🏫 Prisustvo trenera":
    st.header("🧑‍🏫 Prisustvo trenera")
    tab_unos, tab_stat = st.tabs(["➕ Unos prisustva","📈 Statistika"])

    with tab_unos:
        df_t = df_from_sql("SELECT id, ime, prezime FROM trainers ORDER BY prezime, ime")
        trener_map = {int(r.id): f"{r.prezime} {r.ime}" for _,r in df_t.iterrows()} if not df_t.empty else {}
        trener_id = st.selectbox("Trener", options=[None]+list(trener_map.keys()), format_func=lambda i: "—" if i is None else trener_map[i])
        trener_name = st.text_input("Ime i prezime (ako nije iz baze)", value=(trener_map[trener_id] if trener_id else ""))

        col1, col2 = st.columns(2)
        with col1:
            datum = st.date_input("Datum", value=date.today())
            grupa_opts = df_from_sql("SELECT DISTINCT COALESCE(grupa_trening,'') AS g FROM members ORDER BY g")["g"].tolist()
            grupa = st.selectbox("Grupa", options=[""] + [g for g in grupa_opts if g], index=0)
        with col2:
            izbor = st.radio("Vrijeme", options=["18:30–20:00","20:15–22:00","Ručno"], horizontal=True)
            if izbor == "18:30–20:00":
                vrijeme_od, vrijeme_do = "18:30","20:00"
            elif izbor == "20:15–22:00":
                vrijeme_od, vrijeme_do = "20:15","22:00"
            else:
                t1 = st.time_input("Od", value=datetime.strptime("18:30","%H:%M").time())
                t2 = st.time_input("Do", value=datetime.strptime("20:00","%H:%M").time())
                vrijeme_od, vrijeme_do = t1.strftime("%H:%M"), t2.strftime("%H:%M")
        # izračun trajanja u minutama
        try:
            h1,m1 = map(int, vrijeme_od.split(":")); h2,m2 = map(int, vrijeme_do.split(":"))
            trajanje_min = max(0, (h2*60+m2) - (h1*60+m1))
        except Exception:
            trajanje_min = None
        st.caption(f"Trajanje: {trajanje_min/60:.2f} h" if trajanje_min is not None else "Trajanje nije izračunato.")

        if st.button("💾 Spremi prisustvo", type="primary"):
            exec_sql("""
                INSERT INTO coach_attendance(trener_id, trener, datum, grupa, vrijeme_od, vrijeme_do, trajanje_min)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (int(trener_id) if trener_id else None, trener_name.strip() or None, str(datum), grupa or None, vrijeme_od, vrijeme_do, trajanje_min))
            st.success("Spremljeno.")

        st.markdown("---")
        st.subheader("Zadnji unosi")
        dfa = df_from_sql("""
            SELECT ca.id, COALESCE(t.prezime||' '||t.ime, ca.trener) AS trener,
                   ca.datum, ca.grupa, ca.vrijeme_od||'–'||ca.vrijeme_do AS termin,
                   ROUND(COALESCE(ca.trajanje_min,0)/60.0,2) AS sati
            FROM coach_attendance ca
            LEFT JOIN trainers t ON t.id=ca.trener_id
            ORDER BY ca.datum DESC, ca.id DESC
            LIMIT 50
        """)
        st.dataframe(dfa, use_container_width=True)

    with tab_stat:
        c1,c2,c3 = st.columns(3)
        with c1:
            god = st.number_input("Godina", min_value=2020, max_value=date.today().year+1, value=date.today().year, step=1)
        with c2:
            mjesec = st.selectbox("Mjesec", options=[0]+list(range(1,13)), format_func=lambda m: "Svi" if m==0 else f"{m:02d}")
        with c3:
            trener_filter = st.text_input("Filter trenera (ime/prezime)", value="")

        # Filtriranje
        q = "SELECT COALESCE(t.prezime||' '||t.ime, ca.trener) AS trener, ca.datum, ca.grupa, ca.trajanje_min FROM coach_attendance ca LEFT JOIN trainers t ON t.id=ca.trener_id WHERE 1=1"
        params = []
        if god:
            q += " AND substr(ca.datum,1,4)=?"; params.append(str(int(god)))
        if mjesec and int(mjesec)>0:
            q += " AND substr(ca.datum,6,2)=?"; params.append(f"{int(mjesec):02d}")
        dfa = df_from_sql(q, tuple(params))

        if trener_filter.strip():
            dfa = dfa[dfa["trener"].str.contains(trener_filter.strip(), case=False, na=False)]

        if dfa.empty:
            st.info("Nema podataka za odabrani period.")
        else:
            dfa["sati"] = dfa["trajanje_min"].fillna(0)/60.0
            # mjesečni i godišnji zbrojevi
            total_hours = round(dfa["sati"].sum(), 2)
            st.metric("Ukupno sati", f"{total_hours:.2f}")
            # Po treneru
            grp = dfa.groupby("trener", dropna=False)["sati"].sum().sort_values(ascending=False).reset_index()
            st.subheader("Po treneru (sati)")
            st.dataframe(grp, use_container_width=True)
            # Po mjesecu u godini (ako odabrana godina bez mjeseca)
            if mjesec == 0:
                dfa["m"] = dfa["datum"].str.slice(0,7)
                by_m = dfa.groupby("m")["sati"].sum().reset_index().rename(columns={"m":"Mjesec","sati":"Sati"})
                st.subheader("Po mjesecima")
                st.bar_chart(by_m.set_index("Mjesec"))



# ------------- REZULTATI — STATISTIKA & IZVOZ -------------
if page == "📊 Rezultati — Statistika & Izvoz":
    st.header("📊 Rezultati — Statistika & Izvoz")

    colf1, colf2, colf3, colf4 = st.columns(4)
    with colf1:
        god = st.number_input("Godina", min_value=2010, max_value=date.today().year, value=date.today().year, step=1)
    with colf2:
        samo_ph = st.checkbox("Samo Prvenstvo Hrvatske")
    with colf3:
        sportas_filter = st.text_input("Sportaš (ime ili prezime)", value="")
    with colf4:
        natjec_filter = st.text_input("Filter naziva natjecanja", value="")

    q = """
        SELECT r.*, COALESCE(r.sportas, m.prezime||' '||m.ime) AS sportas_label,
               c.ime_natjecanja, c.natjecanje, c.godina, c.datum, c.mjesto, c.drzava
        FROM competition_results r
        JOIN competitions c ON c.id = r.competition_id
        LEFT JOIN members m ON m.id = r.member_id
        WHERE c.godina = ?
    """
    params = [int(god)]
    dfr = df_from_sql(q, tuple(params))

    if samo_ph:
        dfr = dfr[dfr["ime_natjecanja"].fillna("").str.lower().str.contains("prvenstvo hrvatske") | dfr["natjecanje"].fillna("").str.lower().str.contains("prvenstvo hrvatske")]
    if sportas_filter.strip():
        dfr = dfr[dfr["sportas_label"].fillna("").str.contains(sportas_filter.strip(), case=False, na=False)]
    if natjec_filter.strip():
        dfr = dfr[dfr["ime_natjecanja"].fillna("").str.contains(natjec_filter.strip(), case=False, na=False) | dfr["natjecanje"].fillna("").str.contains(natjec_filter.strip(), case=False, na=False)]

    if dfr.empty:
        st.info("Nema rezultata za zadane filtre.")
    else:
        total_entries = len(dfr)
        total_competitions = dfr["competition_id"].nunique()
        wins = dfr["pobjeda"].fillna(0).astype(int).sum()
        losses = dfr["poraza"].fillna(0).astype(int).sum()
        win_rate = (wins / max(1, wins + losses)) * 100.0

        dfr_ph = dfr[dfr["ime_natjecanja"].fillna("").str.lower().str.contains("prvenstvo hrvatske") | dfr["natjecanje"].fillna("").str.lower().str.contains("prvenstvo hrvatske")]
        ph_entries = len(dfr_ph)

        colm = st.columns(5)
        colm[0].metric("Unosa rezultata", f"{total_entries}")
        colm[1].metric("Različitih natjecanja", f"{total_competitions}")
        colm[2].metric("Pobjede", f"{wins}")
        colm[3].metric("Porazi", f"{losses}")
        colm[4].metric("Win rate", f"{win_rate:.1f}%")

        medal_counts = dfr["medalja"].value_counts(dropna=True) if "medalja" in dfr.columns else pd.Series(dtype=int)
        c1,c2,c3 = st.columns(3)
        c1.metric("🥇", int(medal_counts.get("🥇", 0)))
        c2.metric("🥈", int(medal_counts.get("🥈", 0)))
        c3.metric("🥉", int(medal_counts.get("🥉", 0)))

        st.caption(f"**Nastupa na Prvenstvu Hrvatske:** {ph_entries}")

        st.markdown("### Rezultati (filtrirani)")
        view_cols = ["sportas_label","kategorija","ime_natjecanja","mjesto","pobjeda","poraza","medalja","plasman","napomena"]
        view_cols = [c for c in view_cols if c in dfr.columns]
        st.dataframe(dfr[view_cols].sort_values(["ime_natjecanja","sportas_label"]), use_container_width=True)

        # Excel export
        from io import BytesIO
        import pandas as pd
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            dfr.rename(columns={"sportas_label":"Sportaš","kategorija":"Kategorija","ime_natjecanja":"Natjecanje","mjesto":"Mjesto","pobjeda":"Pobjede","poraza":"Porazi","medalja":"Medalja","plasman":"Plasman","napomena":"Napomena"}).to_excel(writer, sheet_name="Rezultati", index=False)
            summary = pd.DataFrame({
                "Pokazatelj": ["Unosa rezultata","Natjecanja","Pobjede","Porazi","Win rate %","Nastupa na PH","🥇","🥈","🥉"],
                "Vrijednost": [total_entries,total_competitions,wins,losses,round(win_rate,1),ph_entries,int(medal_counts.get("🥇",0)),int(medal_counts.get("🥈",0)),int(medal_counts.get("🥉",0))]
            })
            summary.to_excel(writer, sheet_name="Sažetak", index=False)
        fname = f"/mnt/data/rezultati_izvoz_{int(datetime.now().timestamp())}.xlsx"
        with open(fname, "wb") as f: f.write(output.getvalue())
        st.success(f"[Preuzmi Excel izvoz]({fname})")

    st.markdown("---")
    st.subheader("👤 Statistika jednog sportaša")
    df_m = df_from_sql("SELECT id, ime, prezime FROM members ORDER BY prezime, ime")
    member_map = {int(r.id): f"{r.prezime} {r.ime}" for _,r in df_m.iterrows()} if not df_m.empty else {}
    colp1, colp2 = st.columns(2)
    with colp1:
        member_pick = st.selectbox("Sportaš (iz baze)", options=[None]+list(member_map.keys()), format_func=lambda i: "—" if i is None else member_map[i])
    with colp2:
        godina_sportas = st.number_input("Godina (sportaš)", min_value=2010, max_value=date.today().year, value=date.today().year, step=1)

    if member_pick:
        q2 = """
            SELECT r.*, COALESCE(r.sportas, m.prezime||' '||m.ime) AS sportas_label,
                   c.ime_natjecanja, c.natjecanje, c.godina, c.datum, c.mjesto
            FROM competition_results r
            JOIN competitions c ON c.id = r.competition_id
            LEFT JOIN members m ON m.id = r.member_id
            WHERE c.godina = ? AND (r.member_id = ? OR r.sportas = ?)
        """
        sportas_name = member_map.get(int(member_pick))
        dfa = df_from_sql(q2, (int(godina_sportas), int(member_pick), sportas_name))
        if dfa.empty:
            st.info("Nema rezultata za odabranog sportaša u toj godini.")
        else:
            wins_s = dfa["pobjeda"].fillna(0).astype(int).sum()
            losses_s = dfa["poraza"].fillna(0).astype(int).sum()
            win_rate_s = (wins_s / max(1, wins_s + losses_s)) * 100.0
            medal_counts_s = dfa["medalja"].value_counts(dropna=True) if "medalja" in dfa.columns else pd.Series(dtype=int)
            cm = st.columns(5)
            cm[0].metric("Unosa", len(dfa))
            cm[1].metric("Pobjede", wins_s)
            cm[2].metric("Porazi", losses_s)
            cm[3].metric("Win rate", f"{win_rate_s:.1f}%")
            cm[4].metric("Medalje", int(medal_counts_s.sum()) if not medal_counts_s.empty else 0)
            show_cols = ["ime_natjecanja","kategorija","pobjeda","poraza","medalja","plasman","napomena"]
            show_cols = [c for c in show_cols if c in dfa.columns]
            st.dataframe(dfa[show_cols].sort_values("ime_natjecanja"), use_container_width=True)

            # Export for athlete
            from io import BytesIO
            output2 = BytesIO()
            with pd.ExcelWriter(output2, engine="xlsxwriter") as writer:
                dfa.rename(columns={"ime_natjecanja":"Natjecanje","kategorija":"Kategorija","pobjeda":"Pobjede","poraza":"Porazi","medalja":"Medalja","plasman":"Plasman","napomena":"Napomena"}).to_excel(writer, sheet_name="Rezultati", index=False)
                summary2 = pd.DataFrame({
                    "Pokazatelj": ["Unosa","Pobjede","Porazi","Win rate %","🥇","🥈","🥉"],
                    "Vrijednost": [len(dfa), wins_s, losses_s, round(win_rate_s,1), int(medal_counts_s.get("🥇",0)), int(medal_counts_s.get("🥈",0)), int(medal_counts_s.get("🥉",0))]
                })
                summary2.to_excel(writer, sheet_name="Sažetak", index=False)
            fname2 = f"/mnt/data/rezultati_sportas_{int(datetime.now().timestamp())}.xlsx"
            with open(fname2, "wb") as f: f.write(output2.getvalue())
            st.success(f"[Preuzmi Excel (sportaš)]({fname2})")

# ---------------------- POSTAVKE ----------------------
if page == "⚙️ Postavke":
    st.header("⚙️ Postavke")
    st.subheader("Logo kluba")
    upl = st.file_uploader("Učitaj logo (.jpg/.png)", type=["jpg","jpeg","png"], key="logo_upl")
    if upl is not None:
        Path("data").mkdir(parents=True, exist_ok=True)
        lp = f"data/logo_uploaded_{int(datetime.now().timestamp())}.{upl.name.split('.')[-1]}"
        with open(lp, "wb") as f: f.write(upl.read())
        set_setting("logo_path", lp)
        st.success("Logo spremljen.")
        st.experimental_rerun()
    st.caption(f"Aktualni logo: {get_setting('logo_path','logo.jpg')}")


# ------------- UVOZ STARIH REZULTATA (auto-migracija) -------------
if page == "🔁 Uvoz starih rezultata":
    st.header("🔁 Uvoz starih rezultata")
    st.caption("Automatski detektira tablice poput 'results' ili 'rezultati' i pokušava ih prebaciti u 'competition_results'.")

    # Prikaži postojeće tablice
    try:
        df_tables = df_from_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        st.write("Tablice u bazi:", ", ".join(df_tables["name"].tolist()))
    except Exception as e:
        st.error(f"Greška pri čitanju tablica: {e}")
        df_tables = None

    legacy_tables = []
    if df_tables is not None and not df_tables.empty:
        for t in df_tables["name"].tolist():
            if t.lower() in ("results","rezultati","competition_results_old","old_results"):
                legacy_tables.append(t)

    if not legacy_tables:
        st.info("Nije pronađena stara tablica rezultata ('results', 'rezultati', ...). Ako imaš Excel/CSV, uvezi kroz sekciju 🥇 Rezultati.")
    else:
        pick = st.selectbox("Stara tablica", options=legacy_tables)
        df_legacy = df_from_sql(f"SELECT * FROM {pick} LIMIT 5")
        st.subheader("Primjer podataka (prvih 5 redaka)")
        st.dataframe(df_legacy, use_container_width=True)

        st.markdown("#### Mapiranje polja (pokušaj automatskog mapiranja)")
        # heuristično mapiranje naziva
        def guess(cols, *cands):
            s = {c.lower():c for c in cols}
            for c in cands:
                for k in s:
                    if c in k: return s[k]
            return None

        cols = df_from_sql(f"PRAGMA table_info({pick})")["name"].tolist()
        map_cfg = {}
        map_cfg["competition_id"] = guess(cols, "competition_id","natjecanje_id","comp_id","cid")
        map_cfg["member_id"] = guess(cols, "member_id","clan_id","mid","sportas_id")
        map_cfg["sportas"] = guess(cols, "sportas","ime","prezime","sportaš","athlete","competitor")
        map_cfg["kategorija"] = guess(cols, "kategorija","kat","category","weight")
        map_cfg["ukupno_borbi"] = guess(cols, "ukupno","borbi","meceva","mečeva","bouts","fights","matches")
        map_cfg["pobjeda"] = guess(cols, "pobjeda","wins","win")
        map_cfg["poraza"] = guess(cols, "poraz","losses","loss")
        map_cfg["pobjede_nad"] = guess(cols, "pobjede_nad","wins_over","pobjede-protiv")
        map_cfg["izgubljeno_od"] = guess(cols, "izgubljeno_od","lost_to","porazi-od")
        map_cfg["napomena"] = guess(cols, "napomena","note","biljeska","bilješka","remark")
        map_cfg["medalja"] = guess(cols, "medalja","medal","med")
        map_cfg["plasman"] = guess(cols, "plasman","rank","place","poredak")

        st.json(map_cfg)

        dry = st.checkbox("Suhi test (bez spremanja)", value=True)
        if st.button("🚚 Pokreni migraciju"):
            import pandas as pd, json as _json
            dfl = df_from_sql(f"SELECT * FROM {pick}")
            inserted = 0; skipped = 0
            for _, r in dfl.iterrows():
                def val(key):
                    col = map_cfg.get(key)
                    return (r[col] if (col and col in r.index) else None)
                try:
                    comp_id = int(val("competition_id")) if pd.notna(val("competition_id")) else None
                except Exception:
                    comp_id = None
                # preskoči bez competition_id
                if not comp_id:
                    skipped += 1; continue
                try:
                    pobjede_list = []
                    if pd.notna(val("pobjede_nad")):
                        pobjede_list = [str(x).strip() for x in str(val("pobjede_nad")).splitlines() if str(x).strip()]
                    izgubljeno_list = []
                    if pd.notna(val("izgubljeno_od")):
                        izgubljeno_list = [str(x).strip() for x in str(val("izgubljeno_od")).splitlines() if str(x).strip()]
                    params = (
                        comp_id,
                        int(val("member_id")) if pd.notna(val("member_id")) else None,
                        str(val("sportas")).strip() if pd.notna(val("sportas")) else None,
                        str(val("kategorija")).strip() if pd.notna(val("kategorija")) else None,
                        int(val("ukupno_borbi") or 0) if pd.notna(val("ukupno_borbi")) else 0,
                        int(val("pobjeda") or 0) if pd.notna(val("pobjeda")) else 0,
                        int(val("poraza") or 0) if pd.notna(val("poraza")) else 0,
                        _json.dumps(pobjede_list), _json.dumps(izgubljeno_list),
                        str(val("napomena")).strip() if pd.notna(val("napomena")) else None,
                        str(val("medalja")).strip() if pd.notna(val("medalja")) else None,
                        str(val("plasman")).strip() if pd.notna(val("plasman")) else None
                    )
                    if dry:
                        inserted += 1  # simulacija
                    else:
                        exec_sql("""
                            INSERT INTO competition_results(competition_id, member_id, sportas, kategorija, ukupno_borbi, pobjeda, poraza, pobjede_nad, izgubljeno_od, napomena, medalja, plasman)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, params)
                        inserted += 1
                except Exception:
                    skipped += 1
            if dry:
                st.warning(f"Suhi test: migriralo bi se {inserted} redaka, preskočeno: {skipped}.")
            else:
                st.success(f"Migrirano: {inserted}, preskočeno: {skipped}")
