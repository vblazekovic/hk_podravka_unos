
# streamlit_app.py — HK Podravka • Sustav (Excel uvoz/izvoz, brisanja, statistika, podsjetnici)
import os, re, sqlite3
from io import BytesIO
from datetime import datetime, date, timedelta
from typing import List, Tuple, Optional

import numpy as np
import pandas as pd
import streamlit as st

# ----------------------- Osnovno -----------------------
st.set_page_config(page_title="HK Podravka — Sustav", page_icon="🥇", layout="wide", initial_sidebar_state="collapsed")

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
UPLOADS = {k: os.path.join(UPLOAD_ROOT, k) for k in ["members", "trainers", "veterans", "medical"]}

# E-mail (SMTP) — ako ovo nije postavljeno, slanje će biti SIMULACIJA
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
SMTP_FROM = os.environ.get("SMTP_FROM", "noreply@hk-podravka.local")

# Auto podsjetnici (pokreću se kad netko otvori app taj dan, jednom dnevno)
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

# ----------------------- Helperi -----------------------
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

def sanitize_filename(name: str) -> str:
    base = os.path.basename(str(name))
    # dopusti slova, brojeve, točku, crticu i podvlaku — sve ostalo pretvori u "_"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base)

def save_upload(file, subfolder: str) -> Optional[str]:
    """Ispravno sanitizira nazive — NEMA problema s navodnicima/escape."""
    if not file: return None
    ensure_dirs()
    safe = sanitize_filename(file.name)
    path = os.path.join(UPLOADS[subfolder], safe)
    with open(path, "wb") as out:
        out.write(file.read())
    return path

def df_mobile(df: pd.DataFrame, height: int = 420):
    st.dataframe(df, use_container_width=True, height=height)

# Safe/date konverzije
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

# ----------------------- DB init -----------------------
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
    """)
    # migracije (ako su kolone dodane naknadno)
    cols = pd.read_sql("PRAGMA table_info(members)", conn)["name"].tolist()
    if "medical_valid_until" not in cols:
        cur.execute("ALTER TABLE members ADD COLUMN medical_valid_until TEXT")
    if "medical_path" not in cols:
        cur.execute("ALTER TABLE members ADD COLUMN medical_path TEXT")
    conn.commit()
    conn.close()
init_db()

# ----------------------- Excel I/O -----------------------
ALLOWED_COLS = {
    "members": ["ime","prezime","datum_rodjenja","godina_rodjenja","email_sportas","email_roditelj",
                "telefon_sportas","telefon_roditelj","clanski_broj","oib","adresa","grupa_trening","foto_path",
                "medical_valid_until","medical_path"],
    "trainers": ["ime","prezime","datum_rodjenja","oib","osobna_broj","iban","telefon","email","foto_path","ugovor_path","napomena"],
    "veterans": ["ime","prezime","datum_rodjenja","oib","osobna_broj","telefon","email","foto_path","ugovor_path","napomena"],
    "attendance": ["member_id","datum","termin","grupa","prisutan","trajanje_min"],
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
    if table_name == "members": df = _normalize_dates(df, ["datum_rodjenja","medical_valid_until"])
    elif table_name in ("trainers","veterans"): df = _normalize_dates(df, ["datum_rodjenja"])
    elif table_name == "attendance": df = _normalize_dates(df, ["datum"])
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=table_name)
    return bio.getvalue()

def _cast_types_for_table(table: str, df: pd.DataFrame) -> pd.DataFrame:
    dfx = df.copy()
    if table == "attendance":
        for c in ["member_id","prisutan","trajanje_min"]:
            if c in dfx.columns:
                dfx[c] = pd.to_numeric(dfx[c], errors="coerce").astype("Int64")
        dfx = _normalize_dates(dfx, ["datum"])
    elif table == "members":
        dfx = _normalize_dates(dfx, ["datum_rodjenja","medical_valid_until"])
    else:
        dfx = _normalize_dates(dfx, ["datum_rodjenja"])
    return dfx

def import_table_from_excel(file, table_name: str) -> Tuple[int, List[str]]:
    try:
        df_new = pd.read_excel(file)
    except Exception as e:
        raise ValueError(f"Ne mogu pročitati Excel: {e}")
    if table_name not in ALLOWED_COLS:
        raise ValueError("Uvoz nije podržan za ovu tablicu.")
    keep = [c for c in df_new.columns if c in ALLOWED_COLS[table_name]]
    dropped = [c for c in df_new.columns if c not in ALLOWED_COLS[table_name]]
    df_new = df_new[keep].copy()
    df_new = _cast_types_for_table(table_name, df_new)
    conn = get_conn()
    try:
        df_new.to_sql(table_name, conn, if_exists="append", index=False)
    finally:
        conn.close()
    warns = []
    if dropped:
        warns.append("Izostavljene kolone: " + ", ".join(map(str, dropped)))
    return len(df_new), warns

def template_bytes(columns: List[str]) -> Tuple[bytes, str]:
    df = pd.DataFrame(columns=columns)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="predlozak")
    return bio.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# ----------------------- Brisanje -----------------------
def delete_member(mid: int, del_photo=True, del_med=True) -> bool:
    try:
        r = df_from_sql("SELECT foto_path, medical_path FROM members WHERE id=?", (mid,))
        if not r.empty:
            if del_photo:
                p = str(r.iloc[0]["foto_path"] or "")
                if p and os.path.isfile(p):
                    try: os.remove(p)
                    except Exception: pass
            if del_med:
                m = str(r.iloc[0]["medical_path"] or "")
                if m and os.path.isfile(m):
                    try: os.remove(m)
                    except Exception: pass
        exec_sql("DELETE FROM members WHERE id=?", (mid,))
        return True
    except Exception:
        return False

def delete_trainer(tid: int, del_files=True) -> bool:
    try:
        r = df_from_sql("SELECT foto_path, ugovor_path FROM trainers WHERE id=?", (tid,))
        if del_files and not r.empty:
            for c in ("foto_path","ugovor_path"):
                p = str(r.iloc[0][c] or "")
                if p and os.path.isfile(p):
                    try: os.remove(p)
                    except Exception: pass
        exec_sql("DELETE FROM trainers WHERE id=?", (tid,))
        return True
    except Exception:
        return False

def delete_veteran(vid: int, del_files=True) -> bool:
    try:
        r = df_from_sql("SELECT foto_path, ugovor_path FROM veterans WHERE id=?", (vid,))
        if del_files and not r.empty:
            for c in ("foto_path","ugovor_path"):
                p = str(r.iloc[0][c] or "")
                if p and os.path.isfile(p):
                    try: os.remove(p)
                    except Exception: pass
        exec_sql("DELETE FROM veterans WHERE id=?", (vid,))
        return True
    except Exception:
        return False

# ----------------------- E-mail podsjetnici -----------------------
def _send_email(to_list: List[str], subject: str, body: str) -> tuple[bool, str]:
    """Ako SMTP_* postoji, šalje stvarno; inače simulira."""
    to_list = [t for t in {t.strip() for t in to_list} if t]
    if not to_list:
        return False, "Nema valjanih primatelja."
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS:
        # SIMULACIJA
        return True, f"SIMULACIJA — poslalo bi na: {', '.join(to_list)} | subject: {subject}"
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = ", ".join(to_list)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_FROM, to_list, msg.as_string())
        return True, f"Poslano na: {', '.join(to_list)}"
    except Exception as e:
        return False, f"Greška slanja: {e}"

def members_needing_medical(days_before: int = 14) -> pd.DataFrame:
    q = """SELECT id, ime, prezime, email_sportas, email_roditelj, medical_valid_until
           FROM members WHERE medical_valid_until IS NOT NULL"""
    df = df_from_sql(q)
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

def run_daily_reminders(days_before: int = 14) -> Tuple[int,int]:
    """Vraća: (poslano, preskočeno). Guard file sprečava ponavljanje tijekom dana."""
    today_str = date.today().isoformat()
    try:
        if os.path.isfile(REMINDER_DAY_GUARD):
            with open(REMINDER_DAY_GUARD, "r") as f:
                if f.read().strip() == today_str:
                    return (0,0)  # već slano danas
    except Exception:
        pass

    df = members_needing_medical(days_before)
    sent = skipped = 0
    if not df.empty:
        for _, r in df.iterrows():
            to_list = []
            if str(r.get("email_sportas") or "").strip(): to_list.append(str(r["email_sportas"]).strip())
            if str(r.get("email_roditelj") or "").strip(): to_list.append(str(r["email_roditelj"]).strip())
            if not to_list:
                skipped += 1
                continue
            m_until = safe_date(r.get("medical_valid_until"), None)
            status = "ISTEKAO" if (m_until and m_until < date.today()) else "ISTJEČE USKORO"
            subj = f"[HK Podravka] Podsjetnik — Liječnička potvrda ({status})"
            body = (
                f"Poštovani,\n\n"
                f"Za {r['ime']} {r['prezime']} liječnička potvrda {status.lower()}.\n"
                f"Vrijedi do: {m_until.isoformat() if m_until else '-'}\n\n"
                f"Molimo obnovite potvrdu i dostavite treneru.\n\n"
                f"LP,\nHK Podravka"
            )
            ok, _ = _send_email(to_list, subj, body)
            if ok: sent += 1
            else: skipped += 1

    try:
        with open(REMINDER_DAY_GUARD, "w") as f:
            f.write(today_str)
    except Exception:
        pass
    return (sent, skipped)

# ----------------------- UI -----------------------
st.title("🥇 HK Podravka — Sustav")
page = st.sidebar.radio(
    "Navigacija",
    ["👤 Članovi","🏋️ Treneri","🎖️ Veterani","📅 Prisustvo","👥 Svi članovi","📊 Statistika & Pretraga","📧 Podsjetnici"]
)

# ====== ČLANOVI ======
if page == "👤 Članovi":
    tab_add, tab_list, tab_bulk = st.tabs(["➕ Dodaj","📥/📤 Excel & Popis","🗑️ Grupno brisanje"])

    with tab_add:
        with st.form("add_m"):
            c1,c2,c3 = st.columns(3)
            with c1:
                ime = st.text_input("Ime *"); prezime = st.text_input("Prezime *")
                datum_rod = st.date_input("Datum rođenja", value=date(2010,1,1))
            with c2:
                god = st.number_input("Godina rođenja", 1900, 2100, 2010, 1)
                email_s = st.text_input("E-mail sportaša"); email_r = st.text_input("E-mail roditelja")
            with c3:
                tel_s = st.text_input("Mobitel sportaša"); tel_r = st.text_input("Mobitel roditelja")
                cl_br = st.text_input("Članski broj")
            c4,c5 = st.columns(2)
            with c4:
                oib = st.text_input("OIB"); adresa = st.text_input("Adresa"); grupa = st.text_input("Grupa treninga (npr. U13)")
            with c5:
                foto = st.file_uploader("Fotografija", type=["png","jpg","jpeg","webp"])
                st.caption("🩺 Liječnička potvrda")
                med_until = st.date_input("Vrijedi do", value=date.today() + timedelta(days=365))
                med_file = st.file_uploader("Potvrda (PDF/JPG/PNG)", type=["pdf","jpg","jpeg","png"])
            if st.form_submit_button("Spremi člana"):
                fp = save_upload(foto, "members") if foto else None
                mp = save_upload(med_file, "medical") if med_file else None
                exec_sql(
                    """INSERT INTO members
                       (ime,prezime,datum_rodjenja,godina_rodjenja,email_sportas,email_roditelj,telefon_sportas,telefon_roditelj,
                        clanski_broj,oib,adresa,grupa_trening,foto_path,medical_valid_until,medical_path)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (ime.strip(), prezime.strip(), str(datum_rod), int(god), email_s.strip(), email_r.strip(),
                     tel_s.strip(), tel_r.strip(), cl_br.strip(), oib.strip(), adresa.strip(), grupa.strip(),
                     fp, str(med_until), mp)
                )
                st.success("✅ Član dodan.")

    with tab_list:
        df = df_from_sql("""SELECT id, ime, prezime, grupa_trening, datum_rodjenja, godina_rodjenja, email_sportas, email_roditelj,
                                   telefon_sportas, telefon_roditelj, clanski_broj, oib, adresa, medical_valid_until,
                                   medical_path, foto_path
                            FROM members ORDER BY prezime, ime""")
        def med_label(s):
            d = safe_date(s, None)
            if d is None: return "—"
            diff = (d - date.today()).days
            if diff < 0: return "🟥 istekao"
            if diff <= 30: return "🟨 uskoro"
            return "🟩 vrijedi"
        if not df.empty: df["Liječnička"] = df["medical_valid_until"].apply(med_label)
        df_mobile(df)

        st.markdown("### 📤 Izvoz / 📥 Uvoz — Članovi")
        st.download_button("⬇️ Preuzmi članove (Excel)", data=export_table_to_excel("members", True),
                           file_name="clanovi.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        upl = st.file_uploader("📥 Uvezi članove (.xlsx)", type=["xlsx"], key="upl_members")
        if upl:
            try:
                n, warns = import_table_from_excel(upl, "members")
                st.success(f"✅ Uvezeno {n} članova.")
                for w in warns: st.info(w)
                st.experimental_rerun()
            except Exception as e:
                st.error(f"❌ Uvoz nije uspio: {e}")
        tpl, mime = template_bytes(ALLOWED_COLS["members"])
        st.download_button("⬇️ Predložak (Članovi)", data=tpl, file_name="predlozak_clanovi.xlsx", mime=mime)

        st.markdown("---")
        st.subheader("🗑️ Pojedinačno brisanje")
        if not df.empty:
            opts = df.apply(lambda r: f"{r['prezime']} {r['ime']} ({r.get('grupa_trening','')})", axis=1).tolist()
            ids = df["id"].tolist()
            to_del = st.selectbox("Član", options=ids, format_func=lambda i: opts[ids.index(i)])
            c1,c2 = st.columns(2)
            with c1: del_photo = st.checkbox("Obriši fotografiju", True)
            with c2: del_med = st.checkbox("Obriši potvrdu", True)
            if st.button("🗑️ Obriši", type="primary"):
                if delete_member(int(to_del), del_photo, del_med): st.success("Obrisan."); st.experimental_rerun()
                else: st.error("Brisanje nije uspjelo.")

    with tab_bulk:
        dfx = df_from_sql("SELECT id, prezime || ' ' || ime AS label, grupa_trening FROM members ORDER BY prezime, ime")
        if dfx.empty: st.info("Nema članova.")
        else:
            ids = dfx["id"].tolist()
            labels = dfx.apply(lambda r: f"{r['label']} ({r['grupa_trening'] or ''})", axis=1).tolist()
            sel = st.multiselect("Odaberi članove", options=ids, format_func=lambda i: labels[ids.index(i)])
            c1,c2 = st.columns(2)
            with c1: del_photo = st.checkbox("Obriši fotografije", True)
            with c2: del_med = st.checkbox("Obriši potvrde", True)
            if st.button("🗑️ Obriši odabrane", type="primary", disabled=not sel):
                ok = fail = 0
                for i in sel:
                    if delete_member(int(i), del_photo, del_med): ok += 1
                    else: fail += 1
                st.success(f"Obrisano: {ok}, neuspješno: {fail}"); st.experimental_rerun()

# ====== TRENERI ======
elif page == "🏋️ Treneri":
    tab_add, tab_list, tab_bulk = st.tabs(["➕ Dodaj","📥/📤 Excel & Popis","🗑️ Grupno brisanje"])
    with tab_add:
        with st.form("add_t"):
            c1,c2,c3 = st.columns(3)
            with c1:
                ime = st.text_input("Ime *"); prezime = st.text_input("Prezime *")
                datum_rod = st.date_input("Datum rođenja", value=date(1990,1,1))
            with c2:
                osobna = st.text_input("Broj osobne"); iban = st.text_input("IBAN"); telefon = st.text_input("Mobitel")
            with c3:
                email = st.text_input("E-mail"); oib = st.text_input("OIB"); napomena = st.text_area("Napomena", height=80)
            foto = st.file_uploader("Fotografija", type=["png","jpg","jpeg","webp"])
            ugovor = st.file_uploader("Ugovor (PDF/DOC/DOCX)", type=["pdf","doc","docx"])
            if st.form_submit_button("Spremi trenera"):
                fp = save_upload(foto, "trainers") if foto else None
                up = save_upload(ugovor, "trainers") if ugovor else None
                exec_sql("""INSERT INTO trainers (ime,prezime,datum_rodjenja,oib,osobna_broj,iban,telefon,email,foto_path,ugovor_path,napomena)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                         (ime.strip(),prezime.strip(),str(datum_rod),oib.strip(),osobna.strip(),iban.strip(),telefon.strip(),email.strip(),fp,up,napomena.strip()))
                st.success("✅ Trener dodan.")
    with tab_list:
        dft = df_from_sql("SELECT id, ime, prezime, datum_rodjenja, osobna_broj, iban, telefon, email, oib, foto_path, ugovor_path, napomena FROM trainers ORDER BY prezime, ime")
        df_mobile(dft)
        st.markdown("### 📤 Izvoz / 📥 Uvoz — Treneri")
        st.download_button("⬇️ Preuzmi trenere (Excel)", data=export_table_to_excel("trainers", True), file_name="treneri.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        upl = st.file_uploader("📥 Uvezi trenere (.xlsx)", type=["xlsx"], key="upl_trainers")
        if upl:
            try:
                n, warns = import_table_from_excel(upl, "trainers")
                st.success(f"✅ Uvezeno {n} trenera.")
                for w in warns: st.info(w)
                st.experimental_rerun()
            except Exception as e:
                st.error(f"❌ Uvoz nije uspio: {e}")
        tpl, mime = template_bytes(ALLOWED_COLS["trainers"])
        st.download_button("⬇️ Predložak (Treneri)", data=tpl, file_name="predlozak_treneri.xlsx", mime=mime)

        st.markdown("---")
        st.subheader("🗑️ Pojedinačno brisanje")
        if not dft.empty:
            ids = dft["id"].tolist()
            opts = dft.apply(lambda r: f"{r['prezime']} {r['ime']}", axis=1).tolist()
            to_del = st.selectbox("Trener", options=ids, format_func=lambda i: opts[ids.index(i)])
            del_files = st.checkbox("Obriši i datoteke", True)
            if st.button("🗑️ Obriši", type="primary"):
                if delete_trainer(int(to_del), del_files): st.success("Obrisan."); st.experimental_rerun()
                else: st.error("Brisanje nije uspjelo.")
    with tab_bulk:
        dft = df_from_sql("SELECT id, prezime || ' ' || ime AS label FROM trainers ORDER BY prezime, ime")
        ids = dft["id"].tolist(); labels = dft["label"].tolist()
        sel = st.multiselect("Odaberi trenere", options=ids, format_func=lambda i: labels[ids.index(i)])
        del_files = st.checkbox("Obriši i datoteke", True)
        if st.button("🗑️ Obriši odabrane", type="primary", disabled=not sel):
            ok = fail = 0
            for i in sel:
                if delete_trainer(int(i), del_files): ok += 1
                else: fail += 1
            st.success(f"Obrisano: {ok}, neuspješno: {fail}"); st.experimental_rerun()

# ====== VETERANI ======
elif page == "🎖️ Veterani":
    tab_add, tab_list, tab_bulk = st.tabs(["➕ Dodaj","📥/📤 Excel & Popis","🗑️ Grupno brisanje"])
    with tab_add:
        with st.form("add_v"):
            c1,c2,c3 = st.columns(3)
            with c1:
                ime = st.text_input("Ime *"); prezime = st.text_input("Prezime *")
                datum_rod = st.date_input("Datum rođenja", value=date(1980,1,1))
            with c2:
                osobna = st.text_input("Broj osobne"); telefon = st.text_input("Mobitel"); email = st.text_input("E-mail")
            with c3:
                oib = st.text_input("OIB"); napomena = st.text_area("Napomena", height=80)
            foto = st.file_uploader("Fotografija", type=["png","jpg","jpeg","webp"])
            ugovor = st.file_uploader("Dokument (PDF/DOC/DOCX)", type=["pdf","doc","docx"])
            if st.form_submit_button("Spremi veterana"):
                fp = save_upload(foto, "veterans") if foto else None
                up = save_upload(ugovor, "veterans") if ugovor else None
                exec_sql("""INSERT INTO veterans (ime,prezime,datum_rodjenja,oib,osobna_broj,telefon,email,foto_path,ugovor_path,napomena)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""",
                         (ime.strip(),prezime.strip(),str(datum_rod),oib.strip(),osobna.strip(),telefon.strip(),email.strip(),fp,up,napomena.strip()))
                st.success("✅ Veteran dodan.")
    with tab_list:
        dfv = df_from_sql("SELECT id, ime, prezime, datum_rodjenja, osobna_broj, telefon, email, oib, foto_path, ugovor_path, napomena FROM veterans ORDER BY prezime, ime")
        df_mobile(dfv)
        st.markdown("### 📤 Izvoz / 📥 Uvoz — Veterani")
        st.download_button("⬇️ Preuzmi veterane (Excel)", data=export_table_to_excel("veterans", True), file_name="veterani.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        upl = st.file_uploader("📥 Uvezi veterane (.xlsx)", type=["xlsx"], key="upl_veterans")
        if upl:
            try:
                n, warns = import_table_from_excel(upl, "veterans")
                st.success(f"✅ Uvezeno {n} veterana.")
                for w in warns: st.info(w)
                st.experimental_rerun()
            except Exception as e:
                st.error(f"❌ Uvoz nije uspio: {e}")
        tpl, mime = template_bytes(ALLOWED_COLS["veterans"])
        st.download_button("⬇️ Predložak (Veterani)", data=tpl, file_name="predlozak_veterani.xlsx", mime=mime)
    with tab_bulk:
        dfx = df_from_sql("SELECT id, prezime || ' ' || ime AS label FROM veterans ORDER BY prezime, ime")
        ids = dfx["id"].tolist(); labels = dfx["label"].tolist()
        sel = st.multiselect("Odaberi veterane", options=ids, format_func=lambda i: labels[ids.index(i)])
        del_files = st.checkbox("Obriši i datoteke", True)
        if st.button("🗑️ Obriši odabrane", type="primary", disabled=not sel):
            ok = fail = 0
            for i in sel:
                if delete_veteran(int(i), del_files): ok += 1
                else: fail += 1
            st.success(f"Obrisano: {ok}, neuspješno: {fail}"); st.experimental_rerun()

# ====== PRISUSTVO ======
elif page == "📅 Prisustvo":
    st.subheader("📅 Evidencija prisustva")
    d = st.date_input("Datum", value=date.today())
    termin = st.text_input("Termin (npr. 18:30-20:00)", value="18:30-20:00")

    df_groups = df_from_sql("SELECT DISTINCT grupa_trening FROM members WHERE COALESCE(grupa_trening,'')<>'' ORDER BY 1")
    groups = ["(sve)"] + df_groups["grupa_trening"].astype(str).tolist()
    grupa = st.selectbox("Grupa", groups)

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
        trajanje = st.number_input("Trajanje (min)", 30, 180, 90, 5)
        if st.button("💾 Spremi prisustvo"):
            rows = [(int(mid), str(d), termin.strip(), "" if grupa=="(sve)" else grupa, 1, int(trajanje)) for mid in checked]
            if rows:
                exec_many("INSERT INTO attendance (member_id, datum, termin, grupa, prisutan, trajanje_min) VALUES (?,?,?,?,?,?)", rows)
            st.success(f"Spremljeno prisutnih: {len(rows)}")

    st.divider()
    st.subheader("📈 Zadnjih 200")
    q = """
        SELECT a.datum, a.termin, m.prezime || ' ' || m.ime AS clan,
               COALESCE(a.grupa, m.grupa_trening) AS grupa, a.trajanje_min
        FROM attendance AS a
        JOIN members   AS m ON m.id = a.member_id
        ORDER BY a.datum DESC, m.prezime ASC
        LIMIT 200
    """
    df_last = df_from_sql(q)
    df_mobile(df_last)

    st.markdown("---")
    st.markdown("### 📤 Izvoz / 📥 Uvoz — Prisustvo")
    st.download_button("⬇️ Preuzmi prisustvo (Excel)", data=export_table_to_excel("attendance", True),
                       file_name="prisustvo.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    upl = st.file_uploader("📥 Uvezi prisustvo (.xlsx)", type=["xlsx"], key="upl_attendance")
    if upl:
        try:
            n, warns = import_table_from_excel(upl, "attendance")
            st.success(f"✅ Uvezeno {n} zapisa.")
            for w in warns: st.info(w)
            st.experimental_rerun()
        except Exception as e:
            st.error(f"❌ Uvoz nije uspio: {e}")
    tpl, mime = template_bytes(ALLOWED_COLS["attendance"])
    st.download_button("⬇️ Predložak (Prisustvo)", data=tpl, file_name="predlozak_prisustvo.xlsx", mime=mime)

# ====== SVI ČLANOVI ======
elif page == "👥 Svi članovi":
    st.subheader("Kompletan popis članova")
    df = df_from_sql("SELECT * FROM members ORDER BY prezime, ime")
    if df.empty:
        st.info("Nema članova u bazi.")
    else:
        def med_color(x):
            d = safe_date(x, None)
            if d is None: return '<span class="badge red">nema</span>'
            days = (d - date.today()).days
            if days < 0: cls = "red"
            elif days <= 30: cls = "yellow"
            else: cls = "green"
            return f'<span class="badge {cls}">{d.isoformat()}</span>'
        show = df.copy()
        show["Liječnička"] = show["medical_valid_until"].apply(med_color)
        st.write(show.to_html(escape=False, index=False), unsafe_allow_html=True)

# ====== STATISTIKA & PRETRAGA ======
elif page == "📊 Statistika & Pretraga":
    tabs = st.tabs(["Članovi","Treneri","Veterani","Prisustvo"])
    with tabs[0]:
        c1,c2,c3 = st.columns(3)
        ime = c1.text_input("Ime sadrži")
        prez = c2.text_input("Prezime sadrži")
        grp = c3.text_input("Grupa (točno, npr. U13)")
        q = "SELECT ime, prezime, grupa_trening, godina_rodjenja, medical_valid_until FROM members WHERE 1=1"
        params = []
        if ime: q += " AND ime LIKE ?"; params.append(f"%{ime}%")
        if prez: q += " AND prezime LIKE ?"; params.append(f"%{prez}%")
        if grp: q += " AND grupa_trening = ?"; params.append(grp.strip())
        q += " ORDER BY prezime, ime"
        df = df_from_sql(q, tuple(params))
        if not df.empty:
            df["status"] = df["medical_valid_until"].apply(
                lambda s: ("Isteklo" if (sd:=safe_date(s,None)) and sd < date.today()
                           else ("Uskoro" if sd and (sd-date.today()).days <= 30 else ("OK" if sd else "-"))))
            st.caption(f"Ukupno: {len(df)} · OK: {(df['status']=='OK').sum()} · Uskoro: {(df['status']=='Uskoro').sum()} · Isteklo: {(df['status']=='Isteklo').sum()}")
        df_mobile(df)
    with tabs[1]:
        txt = st.text_input("Traži (ime/prezime/telefon/email) — Treneri")
        df = df_from_sql("SELECT ime, prezime, telefon, email, iban FROM trainers")
        if txt:
            t = txt.lower()
            df = df[df.apply(lambda r: t in str(r.values).lower(), axis=1)]
        df_mobile(df)
    with tabs[2]:
        txt = st.text_input("Traži (ime/prezime/telefon/email) — Veterani")
        df = df_from_sql("SELECT ime, prezime, telefon, email FROM veterans")
        if txt:
            t = txt.lower()
            df = df[df.apply(lambda r: t in str(r.values).lower(), axis=1)]
        df_mobile(df)
    with tabs[3]:
        c1,c2,c3 = st.columns(3)
        od = c1.date_input("Od", value=date.today()-timedelta(days=30))
        do = c2.date_input("Do", value=date.today())
        grp = c3.text_input("Grupa")
        q = """SELECT a.datum, a.termin, a.grupa, m.prezime || ' ' || m.ime AS clan, a.trajanje_min
               FROM attendance a JOIN members m ON m.id=a.member_id
               WHERE date(a.datum) BETWEEN ? AND ?"""
        params = [str(od), str(do)]
        if grp: q += " AND COALESCE(a.grupa, m.grupa_trening) = ?"; params.append(grp.strip())
        q += " ORDER BY a.datum DESC, clan ASC"
        df = df_from_sql(q, tuple(params))
        if not df.empty:
            mins = df["trajanje_min"].fillna(0).sum()
            st.caption(f"Zapisa: {len(df)} · Ukupno: {mins} min ({mins/60.0:.2f} h)")
        df_mobile(df)

# ====== PODSJETNICI ======
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
                ok, msg = _send_email(tos, subj, body)
                if ok: sent += 1
                else: skipped += 1
            st.success(f"Poslano: {sent}, preskočeno: {skipped}")

    st.markdown("---")
    if AUTO_EMAIL_REMINDERS:
        s, k = run_daily_reminders(days)
        if s or k:
            st.info(f"Automatski ciklus (jednom dnevno): poslano {s}, preskočeno {k}.")
        else:
            st.caption("Automatski ciklus danas je već odrađen (ili nema primatelja).")

