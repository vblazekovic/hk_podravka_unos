
import os, json, sqlite3, re
from io import BytesIO
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st

# ======================= CONFIG =======================
st.set_page_config(page_title="HK Podravka – evidencije", layout="wide")

# ======================= CONSTANTS =======================
DB_PATH = "data/app.db"
os.makedirs("data", exist_ok=True)

COUNTRIES = [
    "Hrvatska","Slovenija","Srbija","Bosna i Hercegovina","Crna Gora","Sjeverna Makedonija","Albanija",
    "Austrija","Mađarska","Italija","Njemačka","Švicarska","Francuska","Španjolska","Belgija",
    "Nizozemska","Poljska","Češka","Slovačka","Rumunjska","Bugarska","Grčka","Turska",
    "Ujedinjeno Kraljevstvo","Irska","Portugal","Norveška","Švedska","Finska","Danska","Island",
    "SAD","Kanada"
]

CITY_TO_COUNTRY = {
    "Zagreb": "Hrvatska","Split":"Hrvatska","Rijeka":"Hrvatska","Osijek":"Hrvatska","Koprivnica":"Hrvatska",
    "Zadar":"Hrvatska","Pula":"Hrvatska","Varaždin":"Hrvatska","Ljubljana":"Slovenija","Maribor":"Slovenija",
    "Beograd":"Srbija","Novi Sad":"Srbija","Sarajevo":"Bosna i Hercegovina","Mostar":"Bosna i Hercegovina","Tuzla":"Bosna i Hercegovina"
}

# ======================= HELPERS =======================
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def exec_sql(q, params=()):
    with get_conn() as conn:
        conn.execute(q, params)
        conn.commit()

def df_from_sql(q, params=()):
    with get_conn() as conn:
        return pd.read_sql_query(q, conn, params=params)

def _safe_int(x, default=None):
    try:
        return int(x)
    except Exception:
        return default

def _nz(x, default=""):
    return x if (x is not None and str(x).strip() != "") else default

def guess_country_for_city(city: str) -> str | None:
    if not city: return None
    for k, v in CITY_TO_COUNTRY.items():
        if k.lower() == str(city).strip().lower():
            return v
    return None

def status_badge(expiry: str|None, warn_days=30):
    if not expiry: return "⚪"
    try:
        d = datetime.fromisoformat(str(expiry)).date()
    except Exception:
        return "⚪"
    days = (d - date.today()).days
    if days < 0: return "🔴 isteklo"
    if days <= warn_days: return f"🟠 {days} dana"
    return f"🟢 {days} dana"

def get_setting(key: str, default: str|None=None):
    try:
        df = df_from_sql("SELECT value FROM settings WHERE key=?", (key,))
        if not df.empty: return df["value"].iloc[0]
    except Exception: pass
    return default

def set_setting(key: str, value: str):
    exec_sql("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,value))

# ---------- Excel predlošci i uvoz ----------
def template_competitions() -> bytes:
    cols = ["godina","datum","datum_kraj","tip_natjecanja","ime_natjecanja","stil_hrvanja",
            "mjesto","drzava","kratica_drzave","nastupilo_podravke","ekipni_plasman","trener","napomena","link_rezultati"]
    df = pd.DataFrame(columns=cols)
    bio = BytesIO(); 
    with pd.ExcelWriter(bio, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name="Natjecanja")
    return bio.getvalue()

def template_results() -> bytes:
    cols = ["sportas","member_id","kategorija","ukupno_borbi","pobjeda","poraza",
            "pobjede_nad","izgubljeno_od","napomena","medalja","plasman"]
    df = pd.DataFrame(columns=cols)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name="Rezultati")
    return bio.getvalue()

def import_competitions_from_excel(file) -> tuple[int, list[str]]:
    warns=[]; n=0
    df = pd.read_excel(file, sheet_name=0)
    df.columns = [str(c).strip().lower() for c in df.columns]
    need = ["godina","datum","datum_kraj","tip_natjecanja","ime_natjecanja","stil_hrvanja",
            "mjesto","drzava","kratica_drzave","nastupilo_podravke","ekipni_plasman","trener","napomena","link_rezultati"]
    for c in need:
        if c not in df.columns:
            df[c]=None; warns.append(f"Nedostajala kolona: {c} (postavljena prazno)")
    for _,r in df.iterrows():
        try:
            exec_sql("""
                INSERT INTO competitions(godina, datum, datum_kraj, natjecanje, ime_natjecanja, stil_hrvanja,
                                         mjesto, drzava, kratica_drzave, nastupilo_podravke, ekipno, trener, napomena, link_rezultati)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                _safe_int(r.get("godina"), None),
                _nz(r.get("datum"), None),
                _nz(r.get("datum_kraj"), None),
                _nz(r.get("tip_natjecanja"), None),
                _nz(r.get("ime_natjecanja"), None),
                _nz(r.get("stil_hrvanja"), None),
                _nz(r.get("mjesto"), None),
                _nz(r.get("drzava"), None),
                _nz(r.get("kratica_drzave"), None),
                _safe_int(r.get("nastupilo_podravke"), None),
                _nz(r.get("ekipni_plasman"), None),
                _nz(r.get("trener"), None),
                _nz(r.get("napomena"), None),
                _nz(r.get("link_rezultati"), None)
            ))
            n+=1
        except Exception as e:
            warns.append(f"Red preskočen: {e}")
    return n, warns

def import_results_from_excel(file, competition_id: int) -> tuple[int, list[str]]:
    warns=[]; n=0
    df = pd.read_excel(file, sheet_name=0)
    df.columns = [str(c).strip().lower() for c in df.columns]
    need = ["sportas","member_id","kategorija","ukupno_borbi","pobjeda","poraza","pobjede_nad","izgubljeno_od","napomena","medalja","plasman"]
    for c in need:
        if c not in df.columns:
            df[c]=None; warns.append(f"Nedostajala kolona: {c} (postavljena prazno)")
    for _, r in df.iterrows():
        med = str(r.get("medalja")).strip() if pd.notna(r.get("medalja")) else ""
        if med not in {"","—","🥇","🥈","🥉"}: med=""
        pobjede = [s.strip() for s in str(_nz(r.get("pobjede_nad"))).splitlines() if s.strip()]
        izgubljeno = [s.strip() for s in str(_nz(r.get("izgubljeno_od"))).splitlines() if s.strip()]
        try:
            exec_sql("""
                INSERT INTO competition_results(competition_id, member_id, sportas, kategorija, ukupno_borbi,
                                                pobjeda, poraza, pobjede_nad, izgubljeno_od, napomena, medalja, plasman)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                int(competition_id),
                _safe_int(r.get("member_id"), None) or None,
                _nz(r.get("sportas"), None),
                _nz(r.get("kategorija"), None),
                _safe_int(r.get("ukupno_borbi"), 0),
                _safe_int(r.get("pobjeda"), 0),
                _safe_int(r.get("poraza"), 0),
                json.dumps(pobjede),
                json.dumps(izgubljeno),
                _nz(r.get("napomena"), None),
                (med if med in {"🥇","🥈","🥉"} else None),
                _nz(r.get("plasman"), None),
            ))
            n+=1
        except Exception as e:
            warns.append(f"Red preskočen: {e}")
    return n, warns

# ======================= DB INIT =======================
def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);

        CREATE TABLE IF NOT EXISTS members(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ime TEXT, prezime TEXT, datum_rodjenja TEXT,
            grupa_trening TEXT,
            medical_path TEXT, medical_valid_until TEXT,
            pristupnica_path TEXT, pristupnica_date TEXT,
            ugovor_path TEXT,
            passport_number TEXT, passport_issuer TEXT, passport_expiry TEXT
        );

        CREATE TABLE IF NOT EXISTS trainers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ime TEXT, prezime TEXT
        );

        CREATE TABLE IF NOT EXISTS groups(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naziv TEXT UNIQUE,
            trener TEXT
        );

        CREATE TABLE IF NOT EXISTS competitions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            godina INTEGER,
            datum TEXT, datum_kraj TEXT,
            natjecanje TEXT,           -- TIP natjecanja
            ime_natjecanja TEXT,
            stil_hrvanja TEXT,
            mjesto TEXT, drzava TEXT, kratica_drzave TEXT,
            nastupilo_podravke INTEGER,
            ekipno TEXT,
            trener TEXT,
            napomena TEXT,
            link_rezultati TEXT
        );

        CREATE TABLE IF NOT EXISTS competition_results(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competition_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
            member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
            sportas TEXT,
            kategorija TEXT,
            ukupno_borbi INTEGER DEFAULT 0,
            pobjeda INTEGER DEFAULT 0,
            poraza INTEGER DEFAULT 0,
            pobjede_nad TEXT,
            izgubljeno_od TEXT,
            napomena TEXT,
            medalja TEXT,
            plasman TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS attendance(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
            datum TEXT, prisutan INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS coach_attendance(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trener_id INTEGER REFERENCES trainers(id) ON DELETE SET NULL,
            trener TEXT, datum TEXT NOT NULL,
            grupa TEXT,
            vrijeme_od TEXT, vrijeme_do TEXT,
            trajanje_min INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)
        conn.commit()

init_db()

# ======================= SIDEBAR / LOGO =======================
logo_path = get_setting("logo_path", "logo.jpg")
try:
    st.sidebar.image(logo_path, use_column_width=True)
except Exception:
    st.sidebar.caption("Dodaj logo u ⚙️ Postavke")

page = st.sidebar.radio("Navigacija", [
    "👤 Članovi",
    "🏆 Natjecanja",
    "🥇 Rezultati",
    "📊 Rezultati — Statistika & Izvoz",
    "🧑‍🏫 Prisustvo trenera",
    "👥 Grupe",
    "🔁 Uvoz starih rezultata",
    "⚙️ Postavke"
])

# ======================= PAGES =======================

# --------- CLANOVI ---------
if page == "👤 Članovi":
    st.header("👤 Članovi")
    tab_add, tab_list, tab_docs = st.tabs(["➕ Dodaj/uredi","📋 Popis","📎 Dokumenti"])

    with tab_add:
        st.subheader("Dodaj člana")
        c1,c2,c3 = st.columns(3)
        with c1:
            ime = st.text_input("Ime")
            prezime = st.text_input("Prezime")
        with c2:
            datum_rod = st.date_input("Datum rođenja", value=None)
            grupa = st.text_input("Grupa treninga")
        with c3:
            pass_no = st.text_input("Broj putovnice")
            pass_issuer = st.text_input("Izdavatelj putovnice")
            pass_until = st.date_input("Putovnica vrijedi do", value=None)

        if st.button("💾 Spremi člana", type="primary"):
            exec_sql("""
                INSERT INTO members(ime, prezime, datum_rodjenja, grupa_trening, passport_number, passport_issuer, passport_expiry)
                VALUES (?,?,?,?,?,?,?)
            """, (ime.strip() or None, prezime.strip() or None, str(datum_rod) if datum_rod else None, grupa.strip() or None,
                  pass_no.strip() or None, pass_issuer.strip() or None, str(pass_until) if pass_until else None))
            st.success("Član spremljen.")

    with tab_list:
        df = df_from_sql("SELECT * FROM members ORDER BY prezime, ime")
        if df.empty:
            st.info("Nema članova.")
        else:
            df["Liječnička"] = df["medical_valid_until"].apply(lambda x: status_badge(x))
            df["Putovnica"] = df["passport_expiry"].apply(lambda x: status_badge(x))
            st.dataframe(df[["prezime","ime","grupa_trening","Liječnička","Putovnica"]], use_container_width=True)

    with tab_docs:
        dfl = df_from_sql("SELECT id, prezime||' '||ime AS label FROM members ORDER BY prezime, ime")
        if dfl.empty:
            st.info("Nema članova.")
        else:
            sel_mid = st.selectbox("Član", options=dfl["id"].tolist(), format_func=lambda i: dfl.loc[dfl['id']==i,'label'].iloc[0])
            colA,colB = st.columns(2)
            with colA:
                f_ugovor = st.file_uploader("Ugovor (PDF/JPG)", type=["pdf","jpg","jpeg","png"])
                f_pristup = st.file_uploader("Pristupnica (PDF/JPG)", type=["pdf","jpg","jpeg","png"])
                f_med = st.file_uploader("Liječnička potvrda (PDF/JPG)", type=["pdf","jpg","jpeg","png"])
                med_until = st.date_input("Liječnička vrijedi do", value=None)
            with colB:
                pass_no = st.text_input("Broj putovnice (izmjena)")
                pass_issuer = st.text_input("Izdavatelj putovnice (izmjena)")
                pass_until = st.date_input("Putovnica vrijedi do (izmjena)", value=None)

            if st.button("💾 Spremi dokumente", type="primary"):
                os.makedirs("data/uploads", exist_ok=True)
                sets=[]; vals=[]
                def save_file(prefix, f):
                    if not f: return None
                    p=f"data/uploads/{prefix}_{sel_mid}_{int(datetime.now().timestamp())}.{f.name.split('.')[-1]}"
                    open(p,"wb").write(f.read()); return p
                up_ug=save_file("ugovor", f_ugovor); up_pr=save_file("pristupnica", f_pristup); up_md=save_file("lijecnicka", f_med)
                if up_ug: sets+=["ugovor_path=?"]; vals+=[up_ug]
                if up_pr: sets+=["pristupnica_path=?"]; vals+=[up_pr]
                if up_md: sets+=["medical_path=?"]; vals+=[up_md]
                if med_until: sets+=["medical_valid_until=?"]; vals+=[str(med_until)]
                if (pass_no or "").strip(): sets+=["passport_number=?"]; vals+=[pass_no.strip()]
                if (pass_issuer or "").strip(): sets+=["passport_issuer=?"]; vals+=[pass_issuer.strip()]
                if pass_until: sets+=["passport_expiry=?"]; vals+=[str(pass_until)]
                if sets:
                    q = "UPDATE members SET "+", ".join(sets)+" WHERE id=?"
                    vals.append(int(sel_mid)); exec_sql(q, tuple(vals)); st.success("Spremljeno.")

# --------- NATJECANJA ---------
if page == "🏆 Natjecanja":
    st.header("🏆 Natjecanja")
    with st.expander("➕ Dodaj natjecanje", expanded=False):
        c1,c2,c3 = st.columns(3)
        with c1:
            godina = st.number_input("Godina", min_value=2010, max_value=date.today().year+1, value=date.today().year, step=1)
            datum = st.date_input("Datum početka", value=None)
            datum_kraj = st.date_input("Datum završetka", value=None)
        with c2:
            tip = st.text_input("TIP natjecanja (npr. Prvenstvo Hrvatske)")
            ime_nat = st.text_input("Naziv natjecanja")
            stil = st.text_input("Stil hrvanja")
        with c3:
            mjesto = st.text_input("Mjesto")
            pred_drz = guess_country_for_city(mjesto) if mjesto else None
            drzava = st.selectbox("Država", options=COUNTRIES, index=(COUNTRIES.index(pred_drz) if pred_drz in COUNTRIES else 0))
            kr = st.text_input("Kratica države", value="HRV" if drzava=="Hrvatska" else "")
        c4,c5,c6 = st.columns(3)
        with c4:
            nastupilo = st.number_input("Broj hrvača (nastupilo)", min_value=0, step=1)
        with c5:
            ekipno = st.text_input("Ekipni plasman")
        with c6:
            trener = st.text_input("Trener")
        napomena = st.text_area("Napomena", placeholder="...")
        link_rez = st.text_input("Link rezultati", placeholder="https://...")

        if st.button("💾 Spremi natjecanje", type="primary"):
            exec_sql("""
                INSERT INTO competitions(godina, datum, datum_kraj, natjecanje, ime_natjecanja, stil_hrvanja, mjesto, drzava, kratica_drzave, nastupilo_podravke, ekipno, trener, napomena, link_rezultati)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (int(godina), str(datum) if datum else None, str(datum_kraj) if datum_kraj else None, tip.strip() or None, ime_nat.strip() or None, 
                  stil.strip() or None, mjesto.strip() or None, drzava or None, kr.strip() or None, int(nastupilo), ekipno.strip() or None, trener.strip() or None, 
                  napomena.strip() or None, link_rez.strip() or None))
            st.success("Natjecanje spremljeno.")

    st.markdown("### 📥 Uvoz / 📄 Predložak / ⬇️ Izvoz")
    colc1,colc2,colc3 = st.columns(3)
    with colc1:
        if st.button("📄 Predložak (Natjecanja)"):
            f = template_competitions(); fn="data/predlozak_natjecanja.xlsx"; open(fn,"wb").write(f)
            st.success(f"[Preuzmi]({fn})")
    with colc2:
        uplc = st.file_uploader("Učitaj Excel (Natjecanja)", type=["xlsx"], key="upl_comp_xlsx")
        if uplc:
            n,w = import_competitions_from_excel(uplc); st.success(f"✅ Uvezeno {n} natjecanja."); [st.info(i) for i in w]; st.experimental_rerun()
    with colc3:
        df_all = df_from_sql("SELECT * FROM competitions ORDER BY godina DESC, datum DESC, id DESC")
        if not df_all.empty and st.button("⬇️ Izvoz (Natjecanja)"):
            bio = BytesIO(); df_all.to_excel(bio, index=False); fn="data/natjecanja_izvoz.xlsx"; open(fn,"wb").write(bio.getvalue()); st.success(f"[Preuzmi]({fn})")

    st.markdown("### 📋 Popis natjecanja")
    df = df_from_sql("SELECT * FROM competitions ORDER BY godina DESC, datum DESC, id DESC")
    if df.empty:
        st.info("Nema natjecanja.")
    else:
        view = df[[
            "godina","datum","datum_kraj","natjecanje","ime_natjecanja","stil_hrvanja","mjesto","drzava","kratica_drzave","nastupilo_podravke","ekipno","trener","napomena"
        ]].rename(columns={"natjecanje":"TIP"})
        st.dataframe(view, use_container_width=True)

# --------- REZULTATI ---------
if page == "🥇 Rezultati":
    st.header("🥇 Rezultati")
    df_comp = df_from_sql("SELECT id, godina, datum, ime_natjecanja, natjecanje, mjesto, drzava FROM competitions ORDER BY godina DESC, datum DESC, id DESC")
    if df_comp.empty:
        st.info("Prvo dodaj natjecanje.")
    else:
        comp_id = st.selectbox("Natjecanje", options=df_comp["id"].tolist(),
                               format_func=lambda i: f"{df_comp.loc[df_comp['id']==i,'godina'].iloc[0]} — {df_comp.loc[df_comp['id']==i,'ime_natjecanja'].iloc[0]} ({df_comp.loc[df_comp['id']==i,'mjesto'].iloc[0]}, {df_comp.loc[df_comp['id']==i,'drzava'].iloc[0]})")
        sel = df_comp[df_comp["id"]==comp_id].iloc[0].to_dict()

        with st.expander("➕ Unos rezultata", expanded=False):
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
            colx1,colx2,colx3 = st.columns(3)
            with colx1:
                ukupno = st.number_input("Ukupno borbi", min_value=0, step=1)
            with colx2:
                pobjeda = st.number_input("Pobjeda", min_value=0, step=1)
            with colx3:
                poraza = st.number_input("Poraza", min_value=0, step=1)
            c1,c2 = st.columns(2)
            with c1:
                pobjede_nad_raw = st.text_area("Pobjede nad (svaki u novi red)")
            with c2:
                izgubljeno_od_raw = st.text_area("Izgubljeno od (svaki u novi red)")
            colm1, colm2 = st.columns(2)
            with colm1:
                napomena = st.text_area("Napomena (opcionalno)")
            with colm2:
                medalja = st.selectbox("Medalja", options=["—","🥇","🥈","🥉"], index=0)
                plasman = st.text_input("Plasman (npr. 5.)", value="")

            if st.button("💾 Spremi rezultat", type="primary"):
                pobjede_list = [x.strip() for x in (pobjede_nad_raw or "").splitlines() if x.strip()]
                izgubljeno_list = [x.strip() for x in (izgubljeno_od_raw or "").splitlines() if x.strip()]
                exec_sql("""
                    INSERT INTO competition_results(competition_id, member_id, sportas, kategorija, ukupno_borbi, pobjeda, poraza, pobjede_nad, izgubljeno_od, napomena, medalja, plasman)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (int(comp_id), int(member_id) if member_id else None, (sportas_txt.strip() or None),
                      (kategorija.strip() or None), int(ukupno), int(pobjeda), int(poraza),
                      json.dumps(pobjede_list), json.dumps(izgubljeno_list), (napomena.strip() or None),
                      (medalja if medalja!='—' else None), (plasman.strip() or None)))
                st.success("Rezultat spremljen.")

        st.markdown("### 📥 Uvoz / 📄 Predložak / ⬇️ Izvoz")
        colr1,colr2,colr3 = st.columns(3)
        with colr1:
            if st.button("📄 Predložak (Rezultati)"):
                f = template_results(); fn="data/predlozak_rezultati.xlsx"; open(fn,"wb").write(f)
                st.success(f"[Preuzmi]({fn})")
        with colr2:
            uplr = st.file_uploader("Učitaj Excel (Rezultati)", type=["xlsx"], key="upl_res")
            if uplr:
                n,w = import_results_from_excel(uplr, competition_id=int(comp_id))
                st.success(f"✅ Uvezeno {n} rezultata."); [st.info(i) for i in w]; st.experimental_rerun()
        with colr3:
            dfr_all = df_from_sql("""
                SELECT COALESCE(r.sportas, m.prezime||' '||m.ime) AS Sportaš, r.kategorija AS Kategorija,
                       r.ukupno_borbi AS Ukupno_borbi, r.pobjeda AS Pobjede, r.poraza AS Porazi,
                       r.medalja AS Medalja, r.plasman AS Plasman, r.napomena AS Napomena
                FROM competition_results r
                LEFT JOIN members m ON m.id=r.member_id
                WHERE r.competition_id=?
            """, (int(comp_id),))
            if not dfr_all.empty and st.button("⬇️ Izvoz (Rezultati)"):
                bio = BytesIO(); dfr_all.to_excel(bio, index=False); fn="data/rezultati_izvoz.xlsx"; open(fn,"wb").write(bio.getvalue()); st.success(f"[Preuzmi]({fn})")

        st.markdown("### 📋 Rezultati — popis")
        dfr = df_from_sql("""
            SELECT r.id, COALESCE(r.sportas, m.prezime||' '||m.ime) AS Sportaš, r.kategorija,
                   r.ukupno_borbi AS Ukupno, r.pobjeda AS Pobjede, r.poraza AS Porazi, r.medalja, r.plasman, r.napomena
            FROM competition_results r LEFT JOIN members m ON m.id=r.member_id
            WHERE r.competition_id=? ORDER BY Sportaš
        """, (int(comp_id),))
        if dfr.empty:
            st.info("Nema rezultata.")
        else:
            st.dataframe(dfr.drop(columns=["id"]), use_container_width=True)

# --------- STATISTIKA ---------
if page == "📊 Rezultati — Statistika & Izvoz":
    st.header("📊 Rezultati — Statistika & Izvoz")
    c1,c2,c3,c4 = st.columns(4)
    with c1:
        god = st.number_input("Godina", min_value=2010, max_value=date.today().year, value=date.today().year, step=1)
    with c2:
        samo_ph = st.checkbox("Samo Prvenstvo Hrvatske")
    with c3:
        sportas_filter = st.text_input("Sportaš (ime/prezime)")
    with c4:
        natjec_filter = st.text_input("Filter naziva natjecanja")

    q = """
        SELECT r.*, COALESCE(r.sportas, m.prezime||' '||m.ime) AS sportas_label,
               c.ime_natjecanja, c.natjecanje, c.godina, c.datum, c.mjesto, c.drzava
        FROM competition_results r
        JOIN competitions c ON c.id = r.competition_id
        LEFT JOIN members m ON m.id = r.member_id
        WHERE c.godina = ?
    """
    dfr = df_from_sql(q, (int(god),))

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
        c1m,c2m,c3m = st.columns(3)
        c1m.metric("🥇", int(medal_counts.get("🥇", 0)))
        c2m.metric("🥈", int(medal_counts.get("🥈", 0)))
        c3m.metric("🥉", int(medal_counts.get("🥉", 0)))

        dfr["mjesec"] = dfr["datum"].str.slice(0,7)
        by_year = dfr.groupby("godina")[["ukupno_borbi","pobjeda","poraza"]].sum().reset_index()
        by_month = dfr.groupby(["godina","mjesec"])[["ukupno_borbi","pobjeda","poraza"]].sum().reset_index()
        by_ath = dfr.groupby("sportas_label")[["ukupno_borbi","pobjeda","poraza"]].sum().reset_index().sort_values("pobjeda", ascending=False)

        st.subheader("Po godinama"); st.dataframe(by_year, use_container_width=True)
        st.subheader("Po mjesecima"); st.dataframe(by_month, use_container_width=True)
        st.subheader("Po sportašima"); st.dataframe(by_ath, use_container_width=True)

        if st.button("⬇️ Izvoz statistike (Excel)"):
            out = BytesIO()
            with pd.ExcelWriter(out, engine="xlsxwriter") as w:
                dfr.to_excel(w, index=False, sheet_name="Rezultati (filtrirano)")
                by_year.to_excel(w, index=False, sheet_name="Po godinama")
                by_month.to_excel(w, index=False, sheet_name="Po mjesecima")
                by_ath.to_excel(w, index=False, sheet_name="Po sportašima")
            fn="data/rezultati_statistika.xlsx"; open(fn,"wb").write(out.getvalue()); st.success(f"[Preuzmi Excel]({fn})")

# --------- PRISUSTVO TRENERA ---------
if page == "🧑‍🏫 Prisustvo trenera":
    st.header("🧑‍🏫 Prisustvo trenera")
    st.caption("Trenera možeš odabrati ručno bez obzira na matičnu grupu (zamjene i sl.).")
    tab_unos, tab_stat = st.tabs(["➕ Unos","📈 Statistika"])

    with tab_unos:
        df_t = df_from_sql("SELECT id, ime, prezime FROM trainers ORDER BY prezime, ime")
        trener_map = {int(r.id): f"{r.prezime} {r.ime}" for _,r in df_t.iterrows()} if not df_t.empty else {}
        trener_id = st.selectbox("Trener (iz baze, opcionalno)", options=[None]+list(trener_map.keys()), format_func=lambda i: "—" if i is None else trener_map[i])
        trener_name = st.text_input("Ime i prezime (ručno, ako nije iz baze)", value=(trener_map.get(trener_id) if trener_id else ""))

        df_groups = df_from_sql("SELECT DISTINCT COALESCE(grupa_trening,'') AS g FROM members WHERE COALESCE(grupa_trening,'')<>'' ORDER BY 1")
        gr_options = ["(ručno)"] + df_groups["g"].tolist()
        gr_pick = st.selectbox("Grupa", gr_options)
        if gr_pick == "(ručno)":
            grupa = st.text_input("Upiši grupu")
        else:
            grupa = gr_pick

        izbor = st.radio("Vrijeme", options=["18:30–20:00","20:15–22:00","Ručno"], horizontal=True)
        if izbor == "18:30–20:00":
            vrijeme_od, vrijeme_do = "18:30","20:00"
        elif izbor == "20:15–22:00":
            vrijeme_od, vrijeme_do = "20:15","22:00"
        else:
            t1 = st.time_input("Od", value=datetime.strptime("18:30","%H:%M").time())
            t2 = st.time_input("Do", value=datetime.strptime("20:00","%H:%M").time())
            vrijeme_od, vrijeme_do = t1.strftime("%H:%M"), t2.strftime("%H:%M")
        datum = st.date_input("Datum", value=date.today())
        try:
            h1,m1 = map(int, vrijeme_od.split(":")); h2,m2 = map(int, vrijeme_do.split(":"))
            trajanje_min = max(0, (h2*60+m2)-(h1*60+m1))
        except Exception:
            trajanje_min = None
        st.caption(f"Trajanje: {trajanje_min/60:.2f} h" if trajanje_min is not None else "Trajanje nije izračunato.")

        if st.button("💾 Spremi prisustvo", type="primary"):
            exec_sql("""
                INSERT INTO coach_attendance(trener_id, trener, datum, grupa, vrijeme_od, vrijeme_do, trajanje_min)
                VALUES (?,?,?,?,?,?,?)
            """, (int(trener_id) if trener_id else None, trener_name.strip() or None, str(datum), grupa or None, vrijeme_od, vrijeme_do, trajanje_min))
            st.success("Spremljeno.")

    with tab_stat:
        god = st.number_input("Godina", min_value=2020, max_value=date.today().year+1, value=date.today().year, step=1)
        mjesec = st.selectbox("Mjesec", options=[0]+list(range(1,13)), format_func=lambda m: "Svi" if m==0 else f"{m:02d}")
        dfa = df_from_sql("SELECT trener, datum, trajanje_min FROM coach_attendance WHERE substr(datum,1,4)=?", (str(int(god)),))
        if int(mjesec)>0:
            dfa = dfa[dfa["datum"].str.slice(5,7)==f"{int(mjesec):02d}"]
        if dfa.empty:
            st.info("Nema podataka.")
        else:
            dfa["sati"]=dfa["trajanje_min"].fillna(0)/60.0
            st.metric("Ukupno sati", f"{dfa['sati'].sum():.2f}")
            by_tr = dfa.groupby("trener")["sati"].sum().sort_values(ascending=False).reset_index()
            st.subheader("Po treneru"); st.dataframe(by_tr, use_container_width=True)
            dfa["YYYYMM"] = dfa["datum"].str.slice(0,7)
            by_m = dfa.groupby("YYYYMM")["sati"].sum().reset_index().rename(columns={"YYYYMM":"Mjesec","sati":"Sati"})
            st.subheader("Po mjesecima"); st.bar_chart(by_m.set_index("Mjesec"))

# --------- GRUPE ---------
if page == "👥 Grupe":
    st.header("👥 Grupe")
    c1,c2 = st.columns([1,2])
    with c1:
        st.subheader("➕ Dodaj/uredi grupu")
        g_name = st.text_input("Naziv grupe")
        g_trainer = st.text_input("Trener (ime/prezime)")
        if st.button("Spremi grupu"):
            if g_name.strip():
                exec_sql("INSERT INTO groups(naziv,trener) VALUES(?,?) ON CONFLICT(naziv) DO UPDATE SET trener=excluded.trener", (g_name.strip(), g_trainer.strip() or None))
                st.success("Grupa spremljena.")
    with c2:
        st.subheader("📋 Grupe i članovi")
        dfg = df_from_sql("SELECT id, naziv, trener FROM groups ORDER BY naziv")
        if dfg.empty:
            st.info("Nema grupa.")
        else:
            st.dataframe(dfg, use_container_width=True)
            sel = st.selectbox("Odaberi grupu za prikaz članova", options=dfg["naziv"].tolist())
            dfm = df_from_sql("SELECT prezime||' '||ime AS sportas, grupa_trening FROM members WHERE grupa_trening=? ORDER BY prezime, ime", (sel,))
            st.write(f"Članovi u grupi **{sel}**")
            st.dataframe(dfm, use_container_width=True)

# --------- LEGACY IMPORT ---------
if page == "🔁 Uvoz starih rezultata":
    st.header("🔁 Uvoz starih rezultata")
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
        st.info("Nije pronađena stara tablica rezultata ('results', 'rezultati', ...). Ako imaš Excel/CSV, uvezi kroz 🥇 Rezultati.")
    else:
        pick = st.selectbox("Stara tablica", options=legacy_tables)
        df_legacy = df_from_sql(f"SELECT * FROM {pick} LIMIT 5")
        st.subheader("Primjer podataka (prvih 5)"); st.dataframe(df_legacy, use_container_width=True)
        dry = st.checkbox("Suhi test (bez spremanja)", value=True)
        if st.button("🚚 Pokreni migraciju"):
            dfl = df_from_sql(f"SELECT * FROM {pick}")
            inserted = 0; skipped = 0
            for _, r in dfl.iterrows():
                try:
                    comp_id = _safe_int(r.get("competition_id"), None)
                    if not comp_id: skipped+=1; continue
                    pobjede_list = [s.strip() for s in str(_nz(r.get("pobjede_nad"))).splitlines() if s.strip()]
                    izgubljeno_list = [s.strip() for s in str(_nz(r.get("izgubljeno_od"))).splitlines() if s.strip()]
                    if dry:
                        inserted += 1
                    else:
                        exec_sql("""
                            INSERT INTO competition_results(competition_id, member_id, sportas, kategorija, ukupno_borbi, pobjeda, poraza, pobjede_nad, izgubljeno_od, napomena, medalja, plasman)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """, (comp_id, _safe_int(r.get("member_id"), None), _nz(r.get("sportas"), None), _nz(r.get("kategorija"), None),
                              _safe_int(r.get("ukupno_borbi"), 0), _safe_int(r.get("pobjeda"), 0), _safe_int(r.get("poraza"), 0),
                              json.dumps(pobjede_list), json.dumps(izgubljeno_list), _nz(r.get("napomena"), None), _nz(r.get("medalja"), None), _nz(r.get("plasman"), None)))
                        inserted += 1
                except Exception:
                    skipped+=1
            if dry: st.warning(f"Suhi test: migriralo bi se {inserted} redaka, preskočeno {skipped}.")
            else: st.success(f"Migrirano: {inserted}, preskočeno {skipped}")

# --------- SETTINGS ---------
if page == "⚙️ Postavke":
    st.header("⚙️ Postavke")
    st.subheader("Logo kluba")
    upl = st.file_uploader("Učitaj logo (.jpg/.png)", type=["jpg","jpeg","png"], key="logo_upl")
    if upl is not None:
        lp = f"data/logo_uploaded_{int(datetime.now().timestamp())}.{upl.name.split('.')[-1]}"
        open(lp, "wb").write(upl.read())
        set_setting("logo_path", lp)
        st.success("Logo spremljen.")
        st.experimental_rerun()
    st.caption(f"Aktualni logo: {get_setting('logo_path','logo.jpg')}")
