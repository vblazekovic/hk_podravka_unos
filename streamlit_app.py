
# streamlit_app.py — HK Podravka • Sustav (prazan)
# Moduli: Natjecanja + Rezultati + Članovi + Prisustvo + Prisustvo trenera + Treneri + Obavijesti + Klub + Dijagnostika
# Dodano: e-mail obavijesti (SMTP), WhatsApp linkovi, opcionalni SMS (Twilio), mobile-friendly CSS

import io
import os
import json
import sqlite3
import ssl
import smtplib
from email.mime.text import MIMEText
from urllib.parse import quote_plus

from datetime import datetime, date
from typing import List, Optional

import pandas as pd
import streamlit as st

# ---------------------------------- Osnovno ----------------------------------
st.set_page_config(
    page_title="HK Podravka — Sustav",
    page_icon="🥇",
    layout="wide",
    initial_sidebar_state="collapsed",  # bolje za mobitel
)

# --- MOBILE-FRIENDLY STYLES ---
MOBILE_CSS = """
@media (max-width: 640px) {
  html, body { font-size: 16px; }
  section.main > div { padding-top: 0.5rem !important; }
  h1, h2, h3 { margin: 0.5rem 0 0.35rem 0; }
}
.stButton button { padding: 0.9rem 1.15rem; border-radius: 12px; font-weight: 600; }
.stCheckbox label, .stRadio label { padding: 0.35rem 0; }
.stTextInput input, .stNumberInput input, .stDateInput input, .stTimeInput input,
.stSelectbox [data-baseweb="select"] > div, .stMultiSelect [data-baseweb="select"] > div {
  min-height: 44px; font-size: 1rem;
}
.stMultiSelect [data-baseweb="tag"] { max-width: 100%; }
[data-testid="stDataFrame"] div[role="grid"] { overflow-x: auto !important; }
img { max-width: 100%; height: auto; }
.stFileUploader > section div { word-break: break-word; }
"""
st.markdown(f"<style>{MOBILE_CSS}</style>", unsafe_allow_html=True)

DB_PATH = "data/rezultati_knjiga1.sqlite"
UPLOAD_ROOT = "data/uploads"
UPLOADS = {
    "members": os.path.join(UPLOAD_ROOT, "members"),
    "competitions": os.path.join(UPLOAD_ROOT, "competitions"),
    "trainers": os.path.join(UPLOAD_ROOT, "trainers"),
    "club": os.path.join(UPLOAD_ROOT, "club"),
}

# --- Email/SMS konfiguracija ---
CLUB_EMAIL = "hsk.podravka@gmail.com"
ADMIN_EMAIL = "vblazekovic76@gmail.com"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_USER = CLUB_EMAIL
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD")  # postavi u okruženju

# Twilio (opcionalno)
TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.environ.get("TWILIO_FROM_NUMBER")  # npr. +123456789

COMP_TYPES_DEFAULT = [
    "PRVENSTVO HRVATSKE", "REPREZENTATIVNI NASTUP", "MEĐUNARODNI TURNIR",
    "KUP", "LIGA", "REGIONALNO", "KVALIFIKACIJE", "ŠKOLSKO", "OSTALO",
]
STYLES = ["GR", "FS", "WW", "BW", "MODIFICIRANI"]
AGE_GROUPS = ["početnici", "početnice", "U11", "U13", "U15", "U17", "U20", "U23", "seniori", "seniorke"]

# ---------------------------------- Utils ------------------------------------
def ensure_dirs():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    for p in UPLOADS.values():
        os.makedirs(p, exist_ok=True)

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

def save_upload(file, subfolder: str) -> Optional[str]:
    if not file:
        return None
    ensure_dirs()
    safe_name = file.name.replace("/", "_").replace("\\", "_")
    path = os.path.join(UPLOADS[subfolder], safe_name)
    with open(path, "wb") as out:
        out.write(file.read())
    return path

# ---------- Messaging helpers ----------
def _send_email_smtp(to_list: List[str], subject: str, body: str) -> tuple[bool, str]:
    """Pošalji e-mail preko Gmail SMTP. Vraća (ok, msg)."""
    if not SMTP_APP_PASSWORD:
        return False, "SMTP_APP_PASSWORD nije postavljen u okruženju."
    try:
        msg = MIMEText(body, _charset="utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = ", ".join(to_list)
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(SMTP_USER, SMTP_APP_PASSWORD)
            server.sendmail(SMTP_USER, to_list, msg.as_string())
        return True, "E-mail poslan."
    except Exception as e:
        return False, f"Greška slanja e-maila: {e}"

def _format_hr_phone_to_e164(phone: str) -> Optional[str]:
    """Pokušaj pretvoriti HR broj u E.164. npr. 0912345678 -> +385912345678"""
    if not phone:
        return None
    p = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if p.startswith("+"):  # već e164
        return p
    if p.startswith("0"):
        return "+385" + p[1:]
    # ako je već bez nule i bez +385 (npr. 91...), dodaj +385
    if len(p) in (8, 9) and not p.startswith("385"):
        return "+385" + p
    if p.startswith("385"):
        return "+" + p
    return None

def _wa_link(phone: str, text: str) -> Optional[str]:
    """Generiraj WhatsApp link za poruku."""
    e164 = _format_hr_phone_to_e164(phone)
    if not e164:
        return None
    return f"https://wa.me/{e164.replace('+','')}" + f"?text={quote_plus(text)}"

def _send_sms_twilio(to_phone: str, text: str) -> tuple[bool, str]:
    """Pošalji SMS preko Twilio (ako je konfiguriran)."""
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM):
        return False, "Twilio nije konfiguriran (env varijable)."
    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        to_e164 = _format_hr_phone_to_e164(to_phone)
        if not to_e164:
            return False, "Neispravan broj primatelja."
        message = client.messages.create(
            body=text,
            from_=TWILIO_FROM,
            to=to_e164
        )
        return True, f"SMS poslan (sid: {message.sid})."
    except Exception as e:
        return False, f"Greška slanja SMS-a: {e}"

# ---------------------------------- DB init ----------------------------------
def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript("""
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

    -- ČLANOVI
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

    -- PRISUSTVO ČLANOVA
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
        datum TEXT NOT NULL,
        termin TEXT,
        grupa TEXT,
        prisutan INTEGER NOT NULL DEFAULT 1,
        trajanje_min INTEGER DEFAULT 90,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- TRENERI
    CREATE TABLE IF NOT EXISTS trainers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ime TEXT,
        prezime TEXT,
        datum_rodjenja TEXT,
        oib TEXT,
        osobna_broj TEXT,
        iban TEXT,
        telefon TEXT,
        email TEXT,
        foto_path TEXT,
        ugovor_path TEXT,
        napomena TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- PRISUSTVO TRENERA
    CREATE TABLE IF NOT EXISTS trainer_attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trainer_id INTEGER NOT NULL REFERENCES trainers(id) ON DELETE CASCADE,
        datum TEXT NOT NULL,
        grupa TEXT,
        vrijeme_od TEXT,
        vrijeme_do TEXT,
        trajanje_min INTEGER,
        napomena TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- KLUB
    CREATE TABLE IF NOT EXISTS club_info (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        naziv TEXT,
        adresa TEXT,
        grad TEXT,
        oib TEXT,
        iban TEXT,
        email TEXT,
        telefon TEXT,
        web TEXT,
        logo_path TEXT,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS club_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        file_path TEXT,
        uploaded_at TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    # default 1 row in club_info
    cur.execute("SELECT COUNT(*) FROM club_info")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO club_info (id, naziv, email, updated_at) VALUES (1, 'HK Podravka', ?, datetime('now'))", (CLUB_EMAIL,))
        conn.commit()
    conn.close()

init_db()

# ---------------------------------- Helpers ----------------------------------
def next_redni_broj() -> int:
    d = df_from_sql("SELECT MAX(redni_broj) AS mx FROM competitions")
    if d.empty or d.iloc[0, 0] is None:
        return 1
    return int(d.iloc[0, 0]) + 1

def delete_member(member_id: int, delete_photo: bool = True) -> bool:
    try:
        dfp = df_from_sql("SELECT foto_path FROM members WHERE id=?", (member_id,))
        if delete_photo and not dfp.empty:
            fp = str(dfp.iloc[0]["foto_path"] or "").strip()
            if fp and os.path.isfile(fp):
                try: os.remove(fp)
                except Exception: pass
        exec_sql("DELETE FROM members WHERE id=?", (member_id,))
        return True
    except Exception:
        return False

def delete_trainer(trainer_id: int, delete_files: bool = True) -> bool:
    try:
        dfp = df_from_sql("SELECT foto_path, ugovor_path FROM trainers WHERE id=?", (trainer_id,))
        if delete_files and not dfp.empty:
            for col in ("foto_path", "ugovor_path"):
                fp = str(dfp.iloc[0][col] or "").strip()
                if fp and os.path.isfile(fp):
                    try: os.remove(fp)
                    except Exception: pass
        exec_sql("DELETE FROM trainers WHERE id=?", (trainer_id,))
        return True
    except Exception:
        return False

def df_mobile(df: pd.DataFrame, height: int = 420):
    st.dataframe(df, use_container_width=True, height=height)

# ---------------------------------- UI ---------------------------------------
st.title("🥇 HK Podravka — Sustav (prazan)")

page = st.sidebar.radio(
    "Navigacija",
    [
        "➕ Natjecanja",
        "🧾 Rezultati",
        "👤 Članovi",
        "📅 Prisustvo",
        "📘 Prisustvo trenera",
        "🏋️ Treneri",
        "📣 Obavijesti",  # NOVO
        "🏛️ Klub",
        "⚙️ Dijagnostika",
    ],
)

# ----------------------- ➕ Natjecanja -----------------------
if page == "➕ Natjecanja":
    st.subheader("➕ Unos natjecanja")
    with st.form("frm_comp_add"):
        rb = next_redni_broj()
        st.caption(f"Redni broj (auto): **{rb}**")
        c1, c2, c3 = st.columns(3)
        with c1:
            godina = st.number_input("Godina", 1990, 2100, datetime.now().year, 1)
            datum = st.date_input("Datum (početak)")
            datum_kraj = st.date_input("Datum (kraj)", value=datum)
        with c2:
            natjecanje = st.selectbox("Tip natjecanja", COMP_TYPES_DEFAULT, index=0)
            ime_natjecanja = st.text_input("Ime natjecanja (opcionalno)")
            stil = st.selectbox("Stil", STYLES, index=0)
        with c3:
            mjesto = st.text_input("Mjesto")
            drzava = st.text_input("Država (npr. Croatia)")
            kratica = st.text_input("Kratica države (CRO/ITA/SRB...)", value="CRO")
        c4, c5 = st.columns(2)
        with c4:
            nastupilo = st.number_input("Nastupilo hrvača Podravke", 0, 1000, 0, 1)
            ekipno = st.text_input("Ekipno (npr. ekipni poredak)")
        with c5:
            trener = st.text_input("Trener")
        st.markdown("**Dodatno**")
        link_rez = st.text_input("Link na rezultate (URL)")
        napomena = st.text_area("Napomena", height=80)
        vijest = st.text_area("Tekst vijesti (za web objavu)", height=160)
        imgs = st.file_uploader("Slike (više datoteka)", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True)

        if st.form_submit_button("Spremi natjecanje"):
            comp_id = exec_sql(
                """
                INSERT INTO competitions
                (redni_broj, godina, datum, datum_kraj, natjecanje, ime_natjecanja, stil_hrvanja, mjesto, drzava, kratica_drzave,
                 nastupilo_podravke, ekipno, trener, napomena, link_rezultati, galerija_json, vijest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rb, int(godina), str(datum), str(datum_kraj), natjecanje.strip(), ime_natjecanja.strip(), stil.strip(),
                    mjesto.strip(), drzava.strip(), kratica.strip(), int(nastupilo), ekipno.strip(), trener.strip(),
                    napomena.strip(), link_rez.strip(), None, vijest.strip(),
                ),
            )
            paths = []
            if imgs:
                for f in imgs:
                    p = save_upload(f, "competitions")
                    if p: paths.append(p)
            if paths:
                exec_sql("UPDATE competitions SET galerija_json=? WHERE id=?", (json.dumps(paths, ensure_ascii=False), comp_id))
            st.success(f"✅ Natjecanje spremljeno (# {rb}).")

            # --- AUTOMATSKA E-MAIL OBAVIJEST ADMINU I KLUBU ---
            subject = f"Novo natjecanje #{rb} — {ime_natjecanja or natjecanje}"
            body = (
                f"Novo natjecanje je dodano u sustav HK Podravka:\n\n"
                f"• Naziv: {ime_natjecanja or '-'}\n"
                f"• Tip: {natjecanje}\n"
                f"• Datum: {datum} — {datum_kraj}\n"
                f"• Mjesto: {mjesto}, {drzava} ({kratica})\n"
                f"• Stil: {stil}\n"
                f"• Trener: {trener or '-'}\n"
                f"• Nastupilo: {nastupilo}\n"
                f"• Link rezultati: {link_rez or '-'}\n"
            )
            ok, msg = _send_email_smtp([ADMIN_EMAIL, CLUB_EMAIL], subject, body)
            if ok:
                st.info("📧 Poslana e-mail obavijest administratoru i klubu.")
            else:
                st.warning(f"📧 E-mail nije poslan: {msg}")

    st.divider()
    dfc = df_from_sql(
        "SELECT id, redni_broj, godina, datum, ime_natjecanja, mjesto, drzava FROM competitions ORDER BY godina DESC, datum DESC"
    )
    df_mobile(dfc)

# ----------------------- 🧾 Rezultati -----------------------
elif page == "🧾 Rezultati":
    st.subheader("🧾 Unos rezultata (po natjecanju)")
    dfc = df_from_sql("SELECT id, redni_broj, datum, ime_natjecanja FROM competitions ORDER BY godina DESC, datum DESC")
    if dfc.empty:
        st.info("Prvo dodaj natjecanje.")
    else:
        comp_labels = dfc.apply(lambda rr: f"#{int(rr['redni_broj'])} — {rr['datum']} — {rr['ime_natjecanja'] or ''}", axis=1).tolist()
        comp_map = {comp_labels[i]: int(dfc.iloc[i]["id"]) for i in range(len(comp_labels))}
        sel = st.selectbox("Natjecanje", comp_labels)
        competition_id = comp_map[sel]

        with st.form("frm_res"):
            c1, c2, c3 = st.columns(3)
            with c1:
                ime_prezime = st.text_input("Ime i prezime")
                spol = st.selectbox("Spol", ["M", "Ž"])
                kategorija = st.text_input("Kategorija")
                uzrast = st.selectbox("Uzrast", AGE_GROUPS, index=2)
            with c2:
                borbi = st.number_input("Broj borbi", 0, 200, 0, 1)
                pobjeda = st.number_input("Pobjeda", 0, 200, 0, 1)
                izgubljenih = st.number_input("Poraza", 0, 200, 0, 1)
            with c3:
                plasman = st.text_input("Plasman (1/2/3/...)")
            if st.form_submit_button("Spremi rezultat"):
                if not ime_prezime.strip():
                    st.error("Ime i prezime je obavezno.")
                else:
                    exec_sql(
                        """
                        INSERT INTO results (competition_id, ime_prezime, spol, plasman, kategorija, uzrast, borbi, pobjeda, izgubljenih)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (competition_id, ime_prezime.strip(), spol, plasman.strip(), kategorija.strip(), uzrast.strip(), int(borbi), int(pobjeda), int(izgubljenih)),
                    )
                    st.success("✅ Rezultat spremljen.")

    st.divider()
    dfr = df_from_sql(
        """
        SELECT r.id, c.redni_broj, c.ime_natjecanja, c.datum, r.ime_prezime, r.spol, r.kategorija, r.uzrast,
               r.borbi, r.pobjeda, r.izgubljenih, r.plasman
        FROM results r JOIN competitions c ON c.id=r.competition_id
        ORDER BY r.id DESC LIMIT 200
        """
    )
    df_mobile(dfr)

# ----------------------- 👤 Članovi -----------------------
elif page == "👤 Članovi":
    tab_add, tab_edit, tab_list = st.tabs(["➕ Dodaj", "🛠 Uredi/obriši", "📋 Popis & izvoz"])

    # ➕ Dodaj
    with tab_add:
        with st.form("frm_member_add"):
            c1, c2, c3 = st.columns(3)
            with c1:
                ime = st.text_input("Ime *")
                prezime = st.text_input("Prezime *")
                datum_rod = st.date_input("Datum rođenja", value=date(2010, 1, 1))
            with c2:
                godina_rod = st.number_input("Godina rođenja", 1900, 2100, 2010, 1)
                email_s = st.text_input("E-mail sportaša")
                email_r = st.text_input("E-mail roditelja")
            with c3:
                tel_s = st.text_input("Kontakt sportaša (mobitel)")
                tel_r = st.text_input("Kontakt roditelja (mobitel)")
                cl_br = st.text_input("Članski broj")
            c4, c5 = st.columns(2)
            with c4:
                oib = st.text_input("OIB")
                adresa = st.text_input("Adresa prebivališta")
            with c5:
                grupa = st.text_input("Grupa treninga (npr. U13)")
                foto = st.file_uploader("Fotografija (opcionalno)", type=["png", "jpg", "jpeg", "webp"])
            if st.form_submit_button("Spremi člana"):
                foto_path = save_upload(foto, "members") if foto else None
                exec_sql(
                    """
                    INSERT INTO members
                    (ime, prezime, datum_rodjenja, godina_rodjenja, email_sportas, email_roditelj,
                     telefon_sportas, telefon_roditelj, clanski_broj, oib, adresa, grupa_trening, foto_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ime.strip(), prezime.strip(), str(datum_rod), int(godina_rod), email_s.strip(), email_r.strip(),
                        tel_s.strip(), tel_r.strip(), cl_br.strip(), oib.strip(), adresa.strip(), grupa.strip(), foto_path,
                    ),
                )
                st.success("✅ Član dodan.")

    # 🛠 Uredi / obriši
    with tab_edit:
        dfm = df_from_sql("SELECT * FROM members ORDER BY prezime, ime")
        if dfm.empty:
            st.info("Nema članova.")
        else:
            labels = dfm.apply(lambda rr: f"{rr['prezime']} {rr['ime']} — {rr.get('grupa_trening','')}", axis=1).tolist()
            idx = st.selectbox("Odaberi člana", list(range(len(labels))), format_func=lambda i: labels[i])
            r = dfm.iloc[idx]

            fp_show = str(r.get("foto_path") or "").strip()
            if fp_show and os.path.isfile(fp_show):
                st.image(fp_show, width=220, caption="Fotografija člana")

            with st.form("frm_member_edit"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    ime = st.text_input("Ime *", value=str(r["ime"] or ""))
                    prezime = st.text_input("Prezime *", value=str(r["prezime"] or ""))
                    try:
                        init_date = pd.to_datetime(r["datum_rodjenja"]).date() if r["datum_rodjenja"] else date(2010, 1, 1)
                    except Exception:
                        init_date = date(2010, 1, 1)
                    datum_rod = st.date_input("Datum rođenja", value=init_date)
                with c2:
                    god_v = pd.to_numeric(r.get("godina_rodjenja"), errors="coerce")
                    init_god = int(god_v) if pd.notna(god_v) else 2010
                    godina_rod = st.number_input("Godina rođenja", 1900, 2100, init_god, 1)
                    email_s = st.text_input("E-mail sportaša", value=str(r["email_sportas"] or ""))
                    email_r = st.text_input("E-mail roditelja", value=str(r["email_roditelj"] or ""))
                with c3:
                    tel_s = st.text_input("Kontakt sportaša (mobitel)", value=str(r["telefon_sportas"] or ""))
                    tel_r = st.text_input("Kontakt roditelja (mobitel)", value=str(r["telefon_roditelj"] or ""))
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
                        foto_path = save_upload(nova_foto, "members") or foto_path
                    exec_sql(
                        """
                        UPDATE members SET
                        ime=?, prezime=?, datum_rodjenja=?, godina_rodjenja=?, email_sportas=?, email_roditelj=?,
                        telefon_sportas=?, telefon_roditelj=?, clanski_broj=?, oib=?, adresa=?, grupa_trening=?, foto_path=?
                        WHERE id=?
                        """,
                        (
                            ime.strip(), prezime.strip(), str(datum_rod), int(godina_rod), email_s.strip(), email_r.strip(),
                            tel_s.strip(), tel_r.strip(), cl_br.strip(), oib.strip(), adresa.strip(), grupa.strip(),
                            foto_path, int(r["id"]),
                        ),
                    )
                    st.success("✅ Izmjene spremljene.")
                    st.rerun()

            st.markdown("---")
            st.subheader("🗑️ Brisanje člana")
            col_a, col_b, col_c = st.columns([1, 1, 2])
            with col_a:
                del_photo = st.checkbox("Obriši i fotografiju", value=True, key="member_del_photo")
            with col_b:
                confirm_del = st.checkbox("Potvrđujem brisanje", key="member_confirm_delete")
            with col_c:
                if st.button("🗑️ Obriši ovog člana", disabled=not confirm_del, type="primary", key="member_delete_btn"):
                    ok = delete_member(int(r["id"]), delete_photo=del_photo)
                    if ok:
                        st.success(f"Član {r['prezime']} {r['ime']} obrisan.")
                        st.rerun()
                    else:
                        st.error("Brisanje nije uspjelo.")

    with tab_list:
        dfm = df_from_sql(
            "SELECT ime, prezime, grupa_trening, datum_rodjenja, godina_rodjenja, email_sportas, email_roditelj, telefon_sportas, telefon_roditelj, clanski_broj, oib, adresa, foto_path FROM members ORDER BY prezime, ime"
        )
        df_mobile(dfm)

# ----------------------- 📅 Prisustvo -----------------------
elif page == "📅 Prisustvo":
    st.subheader("📅 Evidencija prisustva")
    d = st.date_input("Datum", value=date.today())
    termin_sel = st.selectbox("Termin", ["18:30-20:00", "20:00-22:00", "Upiši ručno…"])
    termin = st.text_input("Termin (npr. 09:00-10:30)", label_visibility="collapsed") if termin_sel == "Upiši ručno…" else termin_sel

    df_groups = df_from_sql("SELECT DISTINCT grupa_trening FROM members WHERE grupa_trening IS NOT NULL AND grupa_trening<>'' ORDER BY 1")
    grupe = df_groups["grupa_trening"].dropna().astype(str).tolist()
    grupa = st.selectbox("Grupa", ["(sve)"] + grupe)

    if grupa == "(sve)":
        dfm = df_from_sql("SELECT id, ime, prezime, grupa_trening FROM members ORDER BY prezime, ime")
    else:
        dfm = df_from_sql("SELECT id, ime, prezime, grupa_trening FROM members WHERE grupa_trening=? ORDER BY prezime, ime", (grupa,))

    if dfm.empty:
        st.info("Nema članova u odabranoj grupi.")
    else:
        ids = dfm["id"].tolist()
        labels = dfm.apply(lambda rr: f"{rr['prezime']} {rr['ime']} ({rr.get('grupa_trening','')})", axis=1).tolist()
        checked = st.multiselect(
            "Označi prisutne",
            options=ids,
            format_func=lambda mid: labels[ids.index(mid)],
            placeholder="Dodirni za odabir članova…",
        )
        trajanje = st.number_input("Trajanje treninga (minute)", 30, 180, 90, 5)
        if st.button("💾 Spremi prisustvo"):
            rows = [(int(mid), str(d), termin.strip(), "" if grupa == "(sve)" else grupa, 1, int(trajanje)) for mid in checked]
            if rows:
                exec_many("INSERT INTO attendance (member_id, datum, termin, grupa, prisutan, trajanje_min) VALUES (?, ?, ?, ?, ?, ?)", rows)
            st.success(f"Spremljeno prisutnih: {len(rows)}")

    st.divider()
    st.subheader("📈 Zadnjih 200")
    q = """
        SELECT a.datum, a.termin, m.prezime || ' ' || m.ime AS clan,
               COALESCE(a.grupa, m.grupa_trening) AS grupa, a.trajanje_min
        FROM attendance AS a
        JOIN members   AS m ON m.id = a.member_id
        ORDER BY a.datum DESC, m.prezime ASC, m.ime ASC
        LIMIT 200
    """
    try:
        df_last = df_from_sql(q)
    except Exception:
        init_db(); df_last = df_from_sql(q)
    df_mobile(df_last)

# ----------------------- 📘 Prisustvo trenera -----------------------
elif page == "📘 Prisustvo trenera":
    st.subheader("📘 Evidencija prisustva trenera")
    dft = df_from_sql("SELECT id, ime, prezime FROM trainers ORDER BY prezime, ime")
    if dft.empty:
        st.info("Nema trenera u bazi. Dodaj trenera u odjeljku 🏋️ Treneri.")
    else:
        trener_map = {f"{r['prezime']} {r['ime']}": int(r["id"]) for _, r in dft.iterrows()}
        trener_label = st.selectbox("Trener", list(trener_map.keys()))
        trener_id = trener_map[trener_label]
        datum = st.date_input("Datum treninga", value=date.today())

        df_groups = df_from_sql("SELECT DISTINCT grupa_trening FROM members WHERE grupa_trening IS NOT NULL AND grupa_trening<>'' ORDER BY 1")
        grupe = df_groups["grupa_trening"].dropna().astype(str).tolist()
        grupa_sel = st.selectbox("Grupa", grupe + ["(upiši ručno)"]) if grupe else "(upiši ručno)"
        grupa = st.text_input("Upiši grupu (npr. U13)", value="") if grupa_sel == "(upiši ručno)" else grupa_sel

        c1, c2 = st.columns(2)
        with c1: t_od = st.time_input("Vrijeme od", value=None, step=300)
        with c2: t_do = st.time_input("Vrijeme do", value=None, step=300)
        napomena = st.text_input("Napomena (opcionalno)", value="")

        def _mins(t1, t2):
            if t1 is None or t2 is None: return None
            from datetime import datetime as dt
            d1 = dt.combine(date.today(), t1); d2 = dt.combine(date.today(), t2)
            if d2 < d1: return None
            return int((d2 - d1).total_seconds() // 60)

        trajanje_min = _mins(t_od, t_do)
        if trajanje_min is not None:
            st.caption(f"Trajanje: **{trajanje_min} min** (~ {trajanje_min/60:.2f} h)")

        if st.button("💾 Spremi prisustvo trenera", type="primary", disabled=(trajanje_min is None or not grupa.strip())):
            try:
                exec_sql(
                    """
                    INSERT INTO trainer_attendance (trainer_id, datum, grupa, vrijeme_od, vrijeme_do, trajanje_min, napomena)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(trener_id), str(datum), grupa.strip(),
                        (t_od.strftime("%H:%M") if t_od else None),
                        (t_do.strftime("%H:%M") if t_do else None),
                        int(trajanje_min) if trajanje_min is not None else None,
                        napomena.strip(),
                    ),
                )
                st.success("✅ Prisustvo trenera spremljeno.")
            except Exception as e:
                st.error(f"Greška pri spremanju: {e}")

    st.markdown("---")
    st.subheader("📊 Pregled po mjesecu")
    from datetime import datetime as _dt
    _today = _dt.today()
    colm1, colm2, colm3 = st.columns(3)
    with colm1: year = st.number_input("Godina", 2000, 2100, _today.year, 1)
    with colm2: month = st.number_input("Mjesec", 1, 12, _today.month, 1)
    with colm3:
        dft2 = df_from_sql("SELECT id, ime, prezime FROM trainers ORDER BY prezime, ime")
        trener_map2 = {f"{r['prezime']} {r['ime']}": int(r["id"]) for _, r in dft2.iterrows()} if not dft2.empty else {}
        trener_filter = st.selectbox("Trener (filter)", ["(svi)"] + list(trener_map2.keys()) if trener_map2 else ["(svi)"])

    ym = f"{int(year)}-{int(month):02d}"
    sql = """
        SELECT ta.id, ta.datum, ta.grupa, ta.vrijeme_od, ta.vrijeme_do, ta.trajanje_min,
               t.prezime || ' ' || t.ime AS trener
        FROM trainer_attendance ta
        JOIN trainers t ON t.id = ta.trainer_id
        WHERE strftime('%Y-%m', ta.datum) = ?
    """
    params = [ym]
    if trener_filter != "(svi)":
        sql += " AND ta.trainer_id = ?"
        params.append(trener_map2[trener_filter])
    sql += " ORDER BY ta.datum ASC, trener ASC, ta.vrijeme_od ASC"

    try:
        df_att = df_from_sql(sql, tuple(params))
    except Exception:
        init_db(); df_att = df_from_sql(sql, tuple(params))

    if df_att.empty:
        st.info("Nema zapisa za odabrani mjesec/trenera.")
    else:
        df_att["sati"] = df_att["trajanje_min"].fillna(0) / 60.0
        st.write("✅ Detalji (po zapisima):"); df_mobile(df_att)
        sum_trener = df_att.groupby("trener", as_index=False)["trajanje_min"].sum().rename(columns={"trajanje_min":"minuta"})
        sum_trener["sati"] = (sum_trener["minuta"]/60.0).round(2)
        sum_dan = df_att.groupby("datum", as_index=False)["trajanje_min"].sum().rename(columns={"trajanje_min":"minuta"})
        sum_dan["sati"] = (sum_dan["minuta"]/60.0).round(2)
        st.markdown("**Sažetak po treneru (mjesec):**"); df_mobile(sum_trener, height=280)
        st.markdown("**Sažetak po danu (mjesec):**"); df_mobile(sum_dan, height=280)

        from io import BytesIO
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            df_att.to_excel(writer, index=False, sheet_name="Zapisi")
            sum_trener.to_excel(writer, index=False, sheet_name="Sažetak_trener")
            sum_dan.to_excel(writer, index=False, sheet_name="Sažetak_dan")
        st.download_button("⬇️ Izvoz (mjesec)", data=bio.getvalue(), file_name=f"prisustvo_trenera_{ym}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ----------------------- 🏋️ Treneri -----------------------
elif page == "🏋️ Treneri":
    tab_add, tab_edit, tab_list = st.tabs(["➕ Dodaj trenera", "🛠 Uredi/obriši", "📋 Popis & izvoz"])
    with tab_add:
        with st.form("frm_trainer_add"):
            c1, c2, c3 = st.columns(3)
            with c1:
                ime = st.text_input("Ime *"); prezime = st.text_input("Prezime *")
                datum_rod = st.date_input("Datum rođenja", value=date(1990, 1, 1))
            with c2:
                osobna = st.text_input("Broj osobne iskaznice")
                iban = st.text_input("IBAN (HR...)")
                telefon = st.text_input("Mobitel")
            with c3:
                email = st.text_input("E-mail")
                oib = st.text_input("OIB")
                napomena = st.text_area("Napomena", height=80)
            foto = st.file_uploader("Fotografija (JPG/PNG/WEBP)", type=["png", "jpg", "jpeg", "webp"])
            ugovor = st.file_uploader("Ugovor s klubom (PDF/DOC/DOCX)", type=["pdf", "doc", "docx"])
            if st.form_submit_button("Spremi trenera"):
                foto_path = save_upload(foto, "trainers") if foto else None
                ugovor_path = save_upload(ugovor, "trainers") if ugovor else None
                exec_sql(
                    """
                    INSERT INTO trainers (ime, prezime, datum_rodjenja, oib, osobna_broj, iban, telefon, email, foto_path, ugovor_path, napomena)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (ime.strip(), prezime.strip(), str(datum_rod), oib.strip(), osobna.strip(), iban.strip(), telefon.strip(), email.strip(), foto_path, ugovor_path, napomena.strip()),
                )
                st.success("✅ Trener dodan.")

    with tab_edit:
        dft = df_from_sql("SELECT * FROM trainers ORDER BY prezime, ime")
        if dft.empty:
            st.info("Nema trenera.")
        else:
            labels = dft.apply(lambda rr: f"{rr['prezime']} {rr['ime']}", axis=1).tolist()
            idx = st.selectbox("Odaberi trenera", list(range(len(labels))), format_func=lambda i: labels[i])
            r = dft.iloc[idx]
            fp_t = str(r.get("foto_path") or "").strip()
            if fp_t and os.path.isfile(fp_t):
                st.image(fp_t, width=220, caption="Fotografija trenera")
            with st.form("frm_trainer_edit"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    ime = st.text_input("Ime *", value=str(r["ime"] or ""))
                    prezime = st.text_input("Prezime *", value=str(r["prezime"] or ""))
                    try:
                        init_date = pd.to_datetime(r["datum_rodjenja"]).date() if r["datum_rodjenja"] else date(1990, 1, 1)
                    except Exception:
                        init_date = date(1990, 1, 1)
                    datum_rod = st.date_input("Datum rođenja", value=init_date)
                with c2:
                    osobna = st.text_input("Broj osobne iskaznice", value=str(r["osobna_broj"] or ""))
                    iban = st.text_input("IBAN", value=str(r["iban"] or ""))
                    telefon = st.text_input("Mobitel", value=str(r["telefon"] or ""))
                with c3:
                    email = st.text_input("E-mail", value=str(r["email"] or ""))
                    oib = st.text_input("OIB", value=str(r["oib"] or ""))
                    napomena = st.text_area("Napomena", value=str(r["napomena"] or ""), height=80)
                nova_foto = st.file_uploader("Zamijeni fotografiju", type=["png", "jpg", "jpeg", "webp"])
                novi_ugovor = st.file_uploader("Dodaj/zamijeni ugovor", type=["pdf", "doc", "docx"])
                if st.form_submit_button("Spremi izmjene"):
                    foto_path = r.get("foto_path")
                    if nova_foto is not None: foto_path = save_upload(nova_foto, "trainers") or foto_path
                    ugovor_path = r.get("ugovor_path")
                    if novi_ugovor is not None: ugovor_path = save_upload(novi_ugovor, "trainers") or ugovor_path
                    exec_sql(
                        """
                        UPDATE trainers SET
                            ime=?, prezime=?, datum_rodjenja=?, oib=?, osobna_broj=?, iban=?, telefon=?, email=?, foto_path=?, ugovor_path=?, napomena=?
                        WHERE id=?
                        """,
                        (ime.strip(), prezime.strip(), str(datum_rod), oib.strip(), osobna.strip(), iban.strip(), telefon.strip(), email.strip(), foto_path, ugovor_path, napomena.strip(), int(r["id"])),
                    )
                    st.success("✅ Izmjene spremljene."); st.rerun()

            st.markdown("---")
            st.subheader("🗑️ Brisanje trenera")
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1: del_files = st.checkbox("Obriši i datoteke", value=True, key="trainer_del_files")
            with c2: confirm_tr = st.checkbox("Potvrđujem brisanje", key="trainer_confirm_delete")
            with c3:
                if st.button("🗑️ Obriši ovog trenera", disabled=not confirm_tr, type="primary", key="trainer_delete_btn"):
                    if delete_trainer(int(r["id"]), delete_files=del_files):
                        st.success(f"Trener {r['prezime']} {r['ime']} obrisan."); st.rerun()
                    else:
                        st.error("Brisanje nije uspjelo.")

    with tab_list:
        dft = df_from_sql("SELECT ime, prezime, datum_rodjenja, osobna_broj, iban, telefon, email, oib, foto_path, ugovor_path FROM trainers ORDER BY prezime, ime")
        df_mobile(dft)

# ----------------------- 📣 Obavijesti -----------------------
elif page == "📣 Obavijesti":
    st.subheader("📣 Slanje obavijesti (e-mail, WhatsApp linkovi, SMS*)")
    st.caption("SMS zahtijeva Twilio konfiguraciju (opcionalno). WhatsApp se šalje ručno preko otvorenog linka.")

    kanal = st.multiselect("Kanal", ["E-mail", "WhatsApp linkovi", "SMS (Twilio)"], default=["E-mail"])
    publika = st.radio("Publika", ["Članovi", "Treneri"], horizontal=True)

    if publika == "Članovi":
        dfm = df_from_sql("SELECT id, ime, prezime, email_sportas, email_roditelj, telefon_sportas, telefon_roditelj, grupa_trening FROM members ORDER BY prezime, ime")
        grupe = sorted([g for g in dfm["grupa_trening"].dropna().astype(str).unique().tolist() if g])
        grupa_sel = st.selectbox("Grupa (filter)", ["(sve)"] + grupe)
        if grupa_sel != "(sve)":
            dfm = dfm[dfm["grupa_trening"].astype(str) == grupa_sel]
        if dfm.empty:
            st.info("Nema članova za odabrani filter.")
        else:
            names = dfm.apply(lambda r: f"{r['prezime']} {r['ime']} ({r.get('grupa_trening','')})", axis=1).tolist()
            ids = dfm["id"].tolist()
            odabrani = st.multiselect("Primatelji", options=ids, default=ids, format_func=lambda mid: names[ids.index(mid)])
            subj = st.text_input("Naslov poruke (za e-mail)", value="Obavijest HK Podravka")
            body = st.text_area("Tekst poruke", height=160, value="Poštovani,\n\n...")
            if st.button("📤 Pošalji / Pripremi linkove"):
                df_sel = dfm[dfm["id"].isin(odabrani)]
                # E-mail
                if "E-mail" in kanal:
                    to_emails = []
                    for _, rr in df_sel.iterrows():
                        for c in ("email_sportas", "email_roditelj"):
                            em = str(rr.get(c) or "").strip()
                            if em: to_emails.append(em)
                    to_emails = sorted(list(set(to_emails)))
                    if to_emails:
                        ok, msg = _send_email_smtp(to_emails, subj, body)
                        st.success(f"📧 E-mail ({len(to_emails)} primatelja): {msg}" if ok else f"📧 E-mail nije poslan: {msg}")
                    else:
                        st.warning("Nema e-mail adresa za odabrane članove.")
                # WhatsApp
                if "WhatsApp linkovi" in kanal:
                    st.markdown("**WhatsApp linkovi (klikni svaki red):**")
                    for _, rr in df_sel.iterrows():
                        for c in ("telefon_sportas", "telefon_roditelj"):
                            ph = str(rr.get(c) or "").strip()
                            if not ph: continue
                            link = _wa_link(ph, body)
                            if link:
                                st.markdown(f"- {rr['prezime']} {rr['ime']}: [{link}]({link})")
                    st.info("Otvorit će se WhatsApp Web / App s predloženom porukom; potvrdi slanje ručno.")
                # SMS
                if "SMS (Twilio)" in kanal:
                    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM):
                        st.warning("Twilio nije konfiguriran (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER).")
                    else:
                        sent, failed = 0, 0
                        for _, rr in df_sel.iterrows():
                            for c in ("telefon_sportas", "telefon_roditelj"):
                                ph = str(rr.get(c) or "").strip()
                                if not ph: continue
                                ok, msg = _send_sms_twilio(ph, body)
                                if ok: sent += 1
                                else: failed += 1
                        st.success(f"📱 SMS poslan: {sent}, neuspješno: {failed}")

    else:  # Treneri
        dft = df_from_sql("SELECT id, ime, prezime, email, telefon FROM trainers ORDER BY prezime, ime")
        if dft.empty:
            st.info("Nema trenera.")
        else:
            names = dft.apply(lambda r: f"{r['prezime']} {r['ime']}", axis=1).tolist()
            ids = dft["id"].tolist()
            odabrani = st.multiselect("Primatelji", options=ids, default=ids, format_func=lambda mid: names[ids.index(mid)])
            subj = st.text_input("Naslov poruke (za e-mail)", value="Obavijest HK Podravka — treneri")
            body = st.text_area("Tekst poruke", height=160, value="Poštovani treneri,\n\n...")
            if st.button("📤 Pošalji / Pripremi linkove"):
                df_sel = dft[dft["id"].isin(odabrani)]
                if "E-mail" in kanal:
                    to_emails = [str(rr.get("email") or "").strip() for _, rr in df_sel.iterrows() if str(rr.get("email") or "").strip()]
                    if to_emails:
                        ok, msg = _send_email_smtp(sorted(list(set(to_emails))), subj, body)
                        st.success(f"📧 E-mail ({len(to_emails)}): {msg}" if ok else f"📧 E-mail nije poslan: {msg}")
                    else:
                        st.warning("Nema e-mail adresa za odabrane trenere.")
                if "WhatsApp linkovi" in kanal:
                    st.markdown("**WhatsApp linkovi (klikni svaki red):**")
                    for _, rr in df_sel.iterrows():
                        ph = str(rr.get("telefon") or "").strip()
                        if not ph: continue
                        link = _wa_link(ph, body)
                        if link:
                            st.markdown(f"- {rr['prezime']} {rr['ime']}: [{link}]({link})")
                if "SMS (Twilio)" in kanal:
                    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM):
                        st.warning("Twilio nije konfiguriran (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER).")
                    else:
                        sent, failed = 0, 0
                        for _, rr in df_sel.iterrows():
                            ph = str(rr.get("telefon") or "").strip()
                            if not ph: continue
                            ok, msg = _send_sms_twilio(ph, body)
                            if ok: sent += 1
                            else: failed += 1
                        st.success(f"📱 SMS poslan: {sent}, neuspješno: {failed}")

# ----------------------- 🏛️ Klub -----------------------
elif page == "🏛️ Klub":
    st.subheader("🏛️ Podaci o klubu")
    dfc = df_from_sql("SELECT * FROM club_info WHERE id=1")
    if dfc.empty:
        st.error("Nije inicijalizirano. Otvori Dijagnostika i inicijaliziraj bazu.")
    else:
        r_club = dfc.iloc[0]
        with st.form("frm_club"):
            c1, c2 = st.columns(2)
            with c1:
                naziv = st.text_input("Naziv kluba", value=str(r_club.get("naziv", "") or ""))
                adresa = st.text_input("Adresa", value=str(r_club.get("adresa", "") or ""))
                grad = st.text_input("Grad", value=str(r_club.get("grad", "") or ""))
                oib_k = st.text_input("OIB", value=str(r_club.get("oib", "") or ""))
            with c2:
                iban_k = st.text_input("IBAN", value=str(r_club.get("iban", "") or ""))
                email_k = st.text_input("E-mail", value=str(r_club.get("email", "") or CLUB_EMAIL))
                telefon_k = st.text_input("Telefon", value=str(r_club.get("telefon", "") or ""))
                web_k = st.text_input("Web", value=str(r_club.get("web", "") or ""))
            logo = st.file_uploader("Logo (opcionalno)", type=["png", "jpg", "jpeg", "webp"])
            if st.form_submit_button("Spremi podatke"):
                logo_path = str(r_club.get("logo_path") or "")
                if logo is not None:
                    logo_path = save_upload(logo, "club") or logo_path
                exec_sql(
                    """
                    UPDATE club_info
                       SET naziv=?, adresa=?, grad=?, oib=?, iban=?, email=?, telefon=?, web=?, logo_path=?, updated_at=datetime('now')
                     WHERE id=1
                    """,
                    (naziv.strip(), adresa.strip(), grad.strip(), oib_k.strip(), iban_k.strip(), email_k.strip(), telefon_k.strip(), web_k.strip(), logo_path),
                )
                st.success("✅ Podaci spremljeni.")

        df_logo = df_from_sql("SELECT logo_path FROM club_info WHERE id=1")
        lp = str(df_logo.iloc[0]["logo_path"] or "") if not df_logo.empty else ""
        if lp and os.path.isfile(lp): st.image(lp, width=220, caption="Logo kluba")

        st.markdown("---")
        st.subheader("📎 Dokumenti kluba (npr. Statut, Pravilnici)")
        title = st.text_input("Naslov dokumenta")
        doc = st.file_uploader("Dokument (PDF/DOC/DOCX)", type=["pdf", "doc", "docx"])
        if st.button("📤 Učitaj dokument"):
            if not title or not doc:
                st.error("Unesi naslov i dokument.")
            else:
                pth = save_upload(doc, "club")
                exec_sql("INSERT INTO club_documents (title, file_path) VALUES (?, ?)", (title.strip(), pth))
                st.success("✅ Dokument učitan.")

        dcd = df_from_sql("SELECT id, title, file_path, uploaded_at FROM club_documents ORDER BY uploaded_at DESC")
        df_mobile(dcd, height=300)
        del_id = st.number_input("ID dokumenta za brisanje", min_value=0, step=1, value=0)
        if st.button("🗑️ Obriši dokument"):
            if del_id:
                row = df_from_sql("SELECT file_path FROM club_documents WHERE id=?", (int(del_id),))
                if not row.empty:
                    fp = str(row.iloc[0]["file_path"] or "")
                    if fp and os.path.isfile(fp):
                        try: os.remove(fp)
                        except Exception: pass
                exec_sql("DELETE FROM club_documents WHERE id=?", (int(del_id),))
                st.success("Dokument obrisan.")

# ----------------------- ⚙️ Dijagnostika -----------------------
else:
    st.subheader("⚙️ Dijagnostika")
    st.write("🗃️ Put do baze:", os.path.abspath(DB_PATH))
    st.write("📁 Upload root:", os.path.abspath(UPLOAD_ROOT))
    for k, p in UPLOADS.items():
        st.write(f"📁 {k}:", os.path.abspath(p))
    conn = get_conn()
    tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name", conn)
    conn.close()
    st.write("Tablice u bazi:", tables)

    if st.button("🔧 Inicijaliziraj/kreiraj bazu (ponovno)"):
        init_db(); st.success("Baza inicijalizirana.")

    st.markdown("---")
    st.subheader("🗑️ Očisti sve podatke u bazi")
    confirm_wipe = st.checkbox("Potvrđujem brisanje svih podataka (ne može se vratiti!)", key="wipe_confirm")
    if st.button("🔥 Obriši sve tablice (sadržaj)", disabled=not confirm_wipe, type="primary", key="wipe_btn"):
        try:
            conn = get_conn(); cur = conn.cursor()
            cur.executescript("""
            DELETE FROM attendance;
            DELETE FROM results;
            DELETE FROM competitions;
            DELETE FROM members;
            DELETE FROM trainers;
            DELETE FROM trainer_attendance;
            DELETE FROM club_documents;

            UPDATE club_info
               SET naziv='HK Podravka',
                   adresa=NULL, grad=NULL, oib=NULL, iban=NULL,
                   email=NULL, telefon=NULL, web=NULL, logo_path=NULL,
                   updated_at=datetime('now');
            """)
            conn.commit(); conn.close()
            st.success("✅ Svi podaci su obrisani. Struktura tablica je ostala.")
        except Exception as e:
            st.error(f"Greška pri brisanju: {e}")
