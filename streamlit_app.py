
import os, sqlite3
from io import BytesIO
from datetime import datetime, date, timedelta
from typing import List, Tuple, Optional

import pandas as pd
import numpy as np
import streamlit as st

# ================= Base =================
st.set_page_config(page_title="HK Podravka — Sustav", page_icon="🥇", layout="wide", initial_sidebar_state="collapsed")
CSS = """
@media (max-width:640px){html,body{font-size:16px}section.main>div{padding-top:.5rem!important}}
.stButton button{padding:.9rem 1.15rem;border-radius:12px;font-weight:600}
[data-testid="stDataFrame"] div[role="grid"]{overflow-x:auto!important}
.badge{padding:.2rem .5rem;border-radius:.5rem;font-weight:700;color:#fff}
.badge.green{background:#16a34a}.badge.yellow{background:#f59e0b}.badge.red{background:#dc2626}
"""
st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)

DB_PATH = "data/hk_podravka.sqlite"
UPLOAD_ROOT = "data/uploads"
UPLOADS = {k: os.path.join(UPLOAD_ROOT, k) for k in ["members","trainers","veterans","medical"]}

def ensure_dirs():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    for p in UPLOADS.values(): os.makedirs(p, exist_ok=True)

def get_conn():
    ensure_dirs(); c = sqlite3.connect(DB_PATH); c.execute("PRAGMA foreign_keys=ON;"); return c

# ============== Safe date ==============
from datetime import datetime as _dt, date as _date
def safe_date(val, default:_date=_date(2010,1,1))->_date:
    try:
        if isinstance(val,(list,tuple)): val = val[0] if val else None
        if hasattr(val,"iloc"): val = val.iloc[0] if len(val) else None
        elif isinstance(val,np.ndarray): val = val[0] if val.size else None
        if isinstance(val,str) and val.strip().lower() in {"","nat","nan","none"}: val=None
        if isinstance(val,_date) and not isinstance(val,_dt): return val
        ts = pd.to_datetime(val, errors="coerce")
        if pd.isna(ts): return default
        if not isinstance(ts,_dt): ts = pd.Timestamp(ts).to_pydatetime()
        return ts.date()
    except Exception: return default

# ============== Init DB ===============
def init_db():
    conn = get_conn(); cur = conn.cursor()
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
    # migrations
    cols = pd.read_sql("PRAGMA table_info(members)", conn)["name"].tolist()
    if "medical_valid_until" not in cols: cur.execute("ALTER TABLE members ADD COLUMN medical_valid_until TEXT")
    if "medical_path" not in cols: cur.execute("ALTER TABLE members ADD COLUMN medical_path TEXT")
    conn.commit(); conn.close()
init_db()

# ============== SQL helpers ==============
def df_from_sql(q, params:tuple=()): conn=get_conn(); df=pd.read_sql(q, conn, params=params); conn.close(); return df
def exec_sql(q, params:tuple=()): conn=get_conn(); cur=conn.cursor(); cur.execute(q, params); conn.commit(); lid=cur.lastrowid; conn.close(); return lid
def exec_many(q, rows:List[tuple]): conn=get_conn(); cur=conn.cursor(); cur.executemany(q, rows); conn.commit(); conn.close()

def save_upload(file, subfolder)->Optional[str]:
    if not file: return None
    ensure_dirs(); name=file.name.replace("/","_").replace("\","_")
    p=os.path.join(UPLOADS[subfolder], name); open(p,"wb").write(file.read()); return p

def df_mobile(df, h=420): st.dataframe(df, use_container_width=True, height=h)

# ============== Excel I/O ==============
ALLOWED_COLS = {
    "members":["ime","prezime","datum_rodjenja","godina_rodjenja","email_sportas","email_roditelj",
               "telefon_sportas","telefon_roditelj","clanski_broj","oib","adresa","grupa_trening","foto_path",
               "medical_valid_until","medical_path"],
    "trainers":["ime","prezime","datum_rodjenja","oib","osobna_broj","iban","telefon","email","foto_path","ugovor_path","napomena"],
    "veterans":["ime","prezime","datum_rodjenja","oib","osobna_broj","telefon","email","foto_path","ugovor_path","napomena"],
    "attendance":["member_id","datum","termin","grupa","prisutan","trajanje_min"],
}
def _normalize_dates(df, cols):
    for c in cols:
        if c in df.columns:
            try: df[c]=pd.to_datetime(df[c]).dt.date.astype(str)
            except Exception: df[c]=df[c].astype(str)
    return df

def export_table_to_excel(table:str, use_allowed_cols=False)->bytes:
    if use_allowed_cols and table in ALLOWED_COLS:
        cols=", ".join(ALLOWED_COLS[table]); q=f"SELECT {cols} FROM {table}"
    else:
        q=f"SELECT * FROM {table}"
    df=df_from_sql(q)
    if table=="members": df=_normalize_dates(df,["datum_rodjenja","medical_valid_until"])
    elif table in ("trainers","veterans"): df=_normalize_dates(df,["datum_rodjenja"])
    elif table=="attendance": df=_normalize_dates(df,["datum"])
    bio=BytesIO(); 
    with pd.ExcelWriter(bio, engine="openpyxl") as w: df.to_excel(w, index=False, sheet_name=table)
    return bio.getvalue()

def _cast_types_for_table(table, df):
    dfx=df.copy()
    if table=="attendance":
        for c in ["member_id","prisutan","trajanje_min"]:
            if c in dfx.columns: dfx[c]=pd.to_numeric(dfx[c], errors="coerce").astype("Int64")
        dfx=_normalize_dates(dfx,["datum"])
    elif table=="members":
        dfx=_normalize_dates(dfx,["datum_rodjenja","medical_valid_until"])
    else:
        dfx=_normalize_dates(dfx,["datum_rodjenja"])
    return dfx

def import_table_from_excel(file, table)->Tuple[int, List[str]]:
    try: df_new=pd.read_excel(file)
    except Exception as e: raise ValueError(f"Ne mogu pročitati Excel: {e}")
    if table not in ALLOWED_COLS: raise ValueError("Uvoz nije podržan za ovu tablicu.")
    keep=[c for c in df_new.columns if c in ALLOWED_COLS[table]]
    dropped=[c for c in df_new.columns if c not in ALLOWED_COLS[table]]
    df_new=df_new[keep].copy(); df_new=_cast_types_for_table(table, df_new)
    conn=get_conn()
    try: df_new.to_sql(table, conn, if_exists="append", index=False)
    finally: conn.close()
    warns=[]; 
    if dropped: warns.append(f"Izostavljene kolone: {', '.join(map(str,dropped))}")
    return len(df_new), warns

def template_bytes(columns:List[str])->Tuple[bytes,str]:
    df=pd.DataFrame(columns=columns); bio=BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w: df.to_excel(w, index=False, sheet_name="predlozak")
    return bio.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# ============== Delete ==============
def delete_member(mid:int, del_photo=True, del_med=True):
    try:
        r=df_from_sql("SELECT foto_path, medical_path FROM members WHERE id=?", (mid,))
        if not r.empty:
            if del_photo:
                p=str(r.iloc[0]["foto_path"] or "")
                if p and os.path.isfile(p):
                    try: os.remove(p)
                    except Exception: pass
            if del_med:
                m=str(r.iloc[0]["medical_path"] or "")
                if m and os.path.isfile(m):
                    try: os.remove(m)
                    except Exception: pass
        exec_sql("DELETE FROM members WHERE id=?", (mid,)); return True
    except Exception: return False

def delete_trainer(tid:int, del_files=True):
    try:
        r=df_from_sql("SELECT foto_path, ugovor_path FROM trainers WHERE id=?", (tid,))
        if del_files and not r.empty:
            for c in ("foto_path","ugovor_path"):
                p=str(r.iloc[0][c] or ""); 
                if p and os.path.isfile(p):
                    try: os.remove(p)
                    except Exception: pass
        exec_sql("DELETE FROM trainers WHERE id=?", (tid,)); return True
    except Exception: return False

def delete_veteran(vid:int, del_files=True):
    try:
        r=df_from_sql("SELECT foto_path, ugovor_path FROM veterans WHERE id=?", (vid,))
        if del_files and not r.empty:
            for c in ("foto_path","ugovor_path"):
                p=str(r.iloc[0][c] or ""); 
                if p and os.path.isfile(p):
                    try: os.remove(p)
                    except Exception: pass
        exec_sql("DELETE FROM veterans WHERE id=?", (vid,)); return True
    except Exception: return False

# ============== UI routing ==============
st.title("🥇 HK Podravka — Sustav")
page = st.sidebar.radio("Navigacija", [
    "👤 Članovi","🏋️ Treneri","🎖️ Veterani","📅 Prisustvo",
    "👥 Svi članovi","📊 Statistika & Pretraga"
])

# ============== ČLANOVI ==============
if page=="👤 Članovi":
    tab_add, tab_edit, tab_list, tab_bulk = st.tabs(["➕ Dodaj","🛠 Uredi/obriši","📥/📤 Excel & Popis","🗑️ Grupno brisanje"])

    with tab_add:
        with st.form("add_m"):
            c1,c2,c3 = st.columns(3)
            with c1:
                ime=st.text_input("Ime *"); prezime=st.text_input("Prezime *")
                datum_rod=st.date_input("Datum rođenja", value=date(2010,1,1))
            with c2:
                godina_rod=st.number_input("Godina rođenja",1900,2100,2010,1)
                email_s=st.text_input("E-mail sportaša"); email_r=st.text_input("E-mail roditelja")
            with c3:
                tel_s=st.text_input("Mobitel sportaša"); tel_r=st.text_input("Mobitel roditelja")
                cl_br=st.text_input("Članski broj")
            c4,c5=st.columns(2)
            with c4:
                oib=st.text_input("OIB"); adresa=st.text_input("Adresa"); grupa=st.text_input("Grupa treninga (npr. U13)")
            with c5:
                foto=st.file_uploader("Fotografija", type=["png","jpg","jpeg","webp"])
                st.caption("🩺 Liječnička potvrda")
                med_until=st.date_input("Vrijedi do", value=date.today()+timedelta(days=365))
                med_file=st.file_uploader("Potvrda (PDF/JPG/PNG)", type=["pdf","jpg","jpeg","png"])
            if st.form_submit_button("Spremi člana"):
                fp=save_upload(foto,"members") if foto else None
                mp=save_upload(med_file,"medical") if med_file else None
                exec_sql("""INSERT INTO members
                    (ime,prezime,datum_rodjenja,godina_rodjenja,email_sportas,email_roditelj,telefon_sportas,telefon_roditelj,
                     clanski_broj,oib,adresa,grupa_trening,foto_path,medical_valid_until,medical_path)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""" ,
                    (ime.strip(),prezime.strip(),str(datum_rod),int(godina_rod),email_s.strip(),email_r.strip(),
                     tel_s.strip(),tel_r.strip(),cl_br.strip(),oib.strip(),adresa.strip(),grupa.strip(),fp,str(med_until),mp))
                st.success("✅ Član dodan.")

    with tab_edit:
        dfm=df_from_sql("SELECT * FROM members ORDER BY prezime, ime")
        if dfm.empty: st.info("Nema članova.")
        else:
            labels=dfm.apply(lambda r:f"{r['prezime']} {r['ime']} — {r.get('grupa_trening','')}", axis=1).tolist()
            idx=st.selectbox("Odaberi člana", list(range(len(labels))), format_func=lambda i: labels[i])
            r=dfm.iloc[idx]
            with st.form("edit_m"):
                c1,c2,c3=st.columns(3)
                with c1:
                    ime=st.text_input("Ime *", r["ime"] or ""); prezime=st.text_input("Prezime *", r["prezime"] or "")
                    datum_rod=st.date_input("Datum rođenja", value=safe_date(r.get("datum_rodjenja"), date(2010,1,1)))
                with c2:
                    g=pd.to_numeric(r.get("godina_rodjenja"), errors="coerce")
                    godina_rod=st.number_input("Godina rođenja",1900,2100,int(g) if pd.notna(g) else 2010,1)
                    email_s=st.text_input("E-mail sportaša", r["email_sportas"] or ""); email_r=st.text_input("E-mail roditelja", r["email_roditelj"] or "")
                with c3:
                    tel_s=st.text_input("Mobitel sportaša", r["telefon_sportas"] or ""); tel_r=st.text_input("Mobitel roditelja", r["telefon_roditelj"] or "")
                    cl_br=st.text_input("Članski broj", r["clanski_broj"] or "")
                c4,c5=st.columns(2)
                with c4:
                    oib=st.text_input("OIB", r["oib"] or ""); adresa=st.text_input("Adresa", r["adresa"] or ""); grupa=st.text_input("Grupa treninga", r["grupa_trening"] or "")
                with c5:
                    nova_foto=st.file_uploader("Zamijeni fotografiju", type=["png","jpg","jpeg","webp"])
                    med_until=st.date_input("Liječnička: vrijedi do", value=safe_date(r.get("medical_valid_until"), date.today()+timedelta(days=365)))
                    med_file=st.file_uploader("Zamijeni potvrdu (PDF/JPG/PNG)", type=["pdf","jpg","jpeg","png"])
                if st.form_submit_button("Spremi izmjene"):
                    fp=r.get("foto_path"); 
                    if nova_foto is not None: fp=save_upload(nova_foto,"members") or fp
                    mp=r.get("medical_path"); 
                    if med_file is not None: mp=save_upload(med_file,"medical") or mp
                    exec_sql("""UPDATE members SET
                        ime=?,prezime=?,datum_rodjenja=?,godina_rodjenja=?,email_sportas=?,email_roditelj=?,telefon_sportas=?,telefon_roditelj=?,
                        clanski_broj=?,oib=?,adresa=?,grupa_trening=?,foto_path=?,medical_valid_until=?,medical_path=? WHERE id=?""" ,
                        (ime.strip(),prezime.strip(),str(datum_rod),int(godina_rod),email_s.strip(),email_r.strip(),tel_s.strip(),tel_r.strip(),
                         cl_br.strip(),oib.strip(),adresa.strip(),grupa.strip(),fp,str(med_until),mp,int(r["id"])))
                    st.success("✅ Spremljeno."); st.experimental_rerun()
            st.markdown("---")
            c1,c2,c3=st.columns([1,1,2])
            with c1: del_photo=st.checkbox("Obriši fotografiju", True)
            with c2: del_med=st.checkbox("Obriši potvrdu", True)
            with c3:
                if st.button("🗑️ Obriši ovog člana", type="primary"):
                    if delete_member(int(r["id"]), del_photo, del_med): st.success("Obrisan."); st.experimental_rerun()
                    else: st.error("Brisanje nije uspjelo.")

    with tab_list:
        dfm=df_from_sql("""SELECT ime, prezime, grupa_trening, datum_rodjenja, godina_rodjenja, email_sportas, email_roditelj,
                                  telefon_sportas, telefon_roditelj, clanski_broj, oib, adresa, medical_valid_until, medical_path, foto_path
                           FROM members ORDER BY prezime, ime""")
        def med_status(x):
            d=safe_date(x, None)
            if d is None: return "—"
            days=(d-date.today()).days
            if days<0: return "🟥 istekao"
            if days<=30: return "🟨 uskoro"
            return "🟩 vrijedi"
        if not dfm.empty: dfm["Liječnička"]=dfm["medical_valid_until"].apply(med_status)
        df_mobile(dfm)
        st.markdown("### 📤 Izvoz / 📥 Uvoz — Članovi")
        dl=export_table_to_excel("members", use_allowed_cols=True)
        st.download_button("⬇️ Preuzmi članove (Excel)", data=dl, file_name="clanovi.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        upl=st.file_uploader("📥 Uvezi članove (.xlsx)", type=["xlsx"], key="upl_m")
        if upl:
            try: n,w=import_table_from_excel(upl,"members"); st.success(f"✅ Uvezeno {n} redaka."); [st.info(i) for i in w]; st.experimental_rerun()
            except Exception as e: st.error(f"❌ Uvoz nije uspio: {e}")
        tpl,mime=template_bytes(ALLOWED_COLS["members"])
        st.download_button("⬇️ Predložak (Članovi)", data=tpl, file_name="predlozak_clanovi.xlsx", mime=mime)

    with tab_bulk:
        dfm=df_from_sql("SELECT id, prezime||' '||ime AS naziv, grupa_trening FROM members ORDER BY prezime, ime")
        if dfm.empty: st.info("Nema članova.")
        else:
            ids=dfm["id"].tolist(); labels=dfm.apply(lambda r:f"{r['naziv']} ({r['grupa_trening'] or ''})", axis=1).tolist()
            chosen=st.multiselect("Odaberi za brisanje", options=ids, format_func=lambda x: labels[ids.index(x)])
            col1,col2=st.columns(2)
            with col1: dph=st.checkbox("Obriši fotografije", True)
            with col2: dmd=st.checkbox("Obriši potvrde", True)
            if st.button("🗑️ Obriši odabrane", type="primary", disabled=not chosen):
                ok=0; fail=0
                for mid in chosen:
                    if delete_member(int(mid), dph, dmd): ok+=1
                    else: fail+=1
                st.success(f"Obrisano: {ok}, neuspjelo: {fail}"); st.experimental_rerun()

# ============== TRENERI ==============
elif page=="🏋️ Treneri":
    tab_add, tab_list, tab_bulk = st.tabs(["➕ Dodaj","📥/📤 Excel & Popis","🗑️ Grupno brisanje"])
    with tab_add:
        with st.form("add_t"):
            c1,c2,c3=st.columns(3)
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
                            VALUES (?,?,?,?,?,?,?,?,?,?,?)""" ,
                         (ime.strip(),prezime.strip(),str(datum_rod),oib.strip(),osobna.strip(),iban.strip(),telefon.strip(),email.strip(),fp,up,napomena.strip()))
                st.success("✅ Trener dodan.")
    with tab_list:
        dft=df_from_sql("SELECT ime, prezime, datum_rodjenja, osobna_broj, iban, telefon, email, oib, foto_path, ugovor_path, napomena FROM trainers ORDER BY prezime, ime")
        df_mobile(dft)
        st.markdown("### 📤 Izvoz / 📥 Uvoz — Treneri")
        dl=export_table_to_excel("trainers", use_allowed_cols=True)
        st.download_button("⬇️ Preuzmi trenere (Excel)", data=dl, file_name="treneri.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        upl=st.file_uploader("📥 Uvezi trenere (.xlsx)", type=["xlsx"], key="upl_t")
        if upl:
            try: n,w=import_table_from_excel(upl,"trainers"); st.success(f"✅ Uvezeno {n} trenera."); [st.info(i) for i in w]; st.experimental_rerun()
            except Exception as e: st.error(f"❌ Uvoz nije uspio: {e}")
        tpl,mime=template_bytes(ALLOWED_COLS["trainers"])
        st.download_button("⬇️ Predložak (Treneri)", data=tpl, file_name="predlozak_treneri.xlsx", mime=mime)
    with tab_bulk:
        dft=df_from_sql("SELECT id, prezime||' '||ime AS naziv FROM trainers ORDER BY prezime, ime")
        ids=dft["id"].tolist(); labels=dft["naziv"].tolist()
        chosen=st.multiselect("Za brisanje", options=ids, format_func=lambda x: labels[ids.index(x)])
        del_files=st.checkbox("Obriši i datoteke", True)
        if st.button("🗑️ Obriši odabrane", type="primary", disabled=not chosen):
            ok=0; fail=0
            for tid in chosen:
                if delete_trainer(int(tid), del_files): ok+=1
                else: fail+=1
            st.success(f"Obrisano: {ok}, neuspjelo: {fail}"); st.experimental_rerun()

# ============== VETERANI ==============
elif page=="🎖️ Veterani":
    tab_add, tab_list, tab_bulk = st.tabs(["➕ Dodaj","📥/📤 Excel & Popis","🗑️ Grupno brisanje"])
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
                            VALUES (?,?,?,?,?,?,?,?,?,?)""" ,
                         (ime.strip(),prezime.strip(),str(datum_rod),oib.strip(),osobna.strip(),telefon.strip(),email.strip(),fp,up,napomena.strip()))
                st.success("✅ Veteran dodan.")
    with tab_list:
        dfv=df_from_sql("SELECT ime, prezime, datum_rodjenja, osobna_broj, telefon, email, oib, foto_path, ugovor_path, napomena FROM veterans ORDER BY prezime, ime")
        df_mobile(dfv)
        st.markdown("### 📤 Izvoz / 📥 Uvoz — Veterani")
        dl=export_table_to_excel("veterans", use_allowed_cols=True)
        st.download_button("⬇️ Preuzmi veterane (Excel)", data=dl, file_name="veterani.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        upl=st.file_uploader("📥 Uvezi veterane (.xlsx)", type=["xlsx"], key="upl_v")
        if upl:
            try: n,w=import_table_from_excel(upl,"veterans"); st.success(f"✅ Uvezeno {n} veterana."); [st.info(i) for i in w]; st.experimental_rerun()
            except Exception as e: st.error(f"❌ Uvoz nije uspio: {e}")
        tpl,mime=template_bytes(ALLOWED_COLS["veterans"])
        st.download_button("⬇️ Predložak (Veterani)", data=tpl, file_name="predlozak_veterani.xlsx", mime=mime)
    with tab_bulk:
        dfv=df_from_sql("SELECT id, prezime||' '||ime AS naziv FROM veterans ORDER BY prezime, ime")
        ids=dfv["id"].tolist(); labels=dfv["naziv"].tolist()
        chosen=st.multiselect("Za brisanje", options=ids, format_func=lambda x: labels[ids.index(x)])
        del_files=st.checkbox("Obriši i datoteke", True)
        if st.button("🗑️ Obriši odabrane", type="primary", disabled=not chosen):
            ok=0; fail=0
            for vid in chosen:
                if delete_veteran(int(vid), del_files): ok+=1
                else: fail+=1
            st.success(f"Obrisano: {ok}, neuspjelo: {fail}"); st.experimental_rerun()

# ============== PRISUSTVO ==============
elif page=="📅 Prisustvo":
    st.subheader("📅 Evidencija prisustva")
    d=st.date_input("Datum", value=date.today())
    termin_sel=st.selectbox("Termin", ["18:30-20:00","20:00-22:00","Upiši ručno…"])
    termin=st.text_input("Termin (npr. 09:00-10:30)", label_visibility="collapsed") if termin_sel=="Upiši ručno…" else termin_sel

    df_groups=df_from_sql("SELECT DISTINCT grupa_trening FROM members WHERE COALESCE(grupa_trening,'')<>'' ORDER BY 1")
    groups=["(sve)"] + df_groups["grupa_trening"].astype(str).tolist()
    grupa=st.selectbox("Grupa", groups)

    if grupa=="(sve)":
        dfm=df_from_sql("SELECT id, ime, prezime, grupa_trening FROM members ORDER BY prezime, ime")
    else:
        dfm=df_from_sql("SELECT id, ime, prezime, grupa_trening FROM members WHERE grupa_trening=? ORDER BY prezime, ime",(grupa,))
    if dfm.empty: st.info("Nema članova u grupi.")
    else:
        ids=dfm["id"].tolist(); labels=dfm.apply(lambda r:f"{r['prezime']} {r['ime']} ({r.get('grupa_trening','')})", axis=1).tolist()
        checked=st.multiselect("Označi prisutne", options=ids, format_func=lambda x: labels[ids.index(x)])
        trajanje=st.number_input("Trajanje (min)",30,180,90,5)
        if st.button("💾 Spremi prisustvo"):
            rows=[(int(mid), str(d), termin.strip(), "" if grupa=="(sve)" else grupa, 1, int(trajanje)) for mid in checked]
            if rows: exec_many("INSERT INTO attendance (member_id, datum, termin, grupa, prisutan, trajanje_min) VALUES (?,?,?,?,?,?)", rows)
            st.success(f"Spremljeno prisutnih: {len(rows)}")

    st.divider()
    st.subheader("📈 Zadnjih 200")
    q="""SELECT a.datum, a.termin, m.prezime||' '||m.ime AS clan, COALESCE(a.grupa,m.grupa_trening) AS grupa, a.trajanje_min
         FROM attendance a JOIN members m ON m.id=a.member_id ORDER BY a.datum DESC, m.prezime ASC LIMIT 200"""
    df_last=df_from_sql(q); df_mobile(df_last)

    st.markdown("---"); st.markdown("### 📤 Izvoz / 📥 Uvoz — Prisustvo")
    dl=export_table_to_excel("attendance", use_allowed_cols=True)
    st.download_button("⬇️ Preuzmi prisustvo (Excel)", data=dl, file_name="prisustvo.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    upl=st.file_uploader("📥 Uvezi prisustvo (.xlsx)", type=["xlsx"], key="upl_a")
    if upl:
        try: n,w=import_table_from_excel(upl,"attendance"); st.success(f"✅ Uvezeno {n} zapisa."); [st.info(i) for i in w]; st.experimental_rerun()
        except Exception as e: st.error(f"❌ Uvoz nije uspio: {e}")
    tpl,mime=template_bytes(ALLOWED_COLS["attendance"])
    st.download_button("⬇️ Predložak (Prisustvo)", data=tpl, file_name="predlozak_prisustvo.xlsx", mime=mime)

# ============== SVI ČLANOVI ==============
elif page=="👥 Svi članovi":
    st.subheader("Kompletan popis članova")
    dfm=df_from_sql("SELECT * FROM members ORDER BY prezime, ime")
    if not dfm.empty:
        def med_color(x):
            d=safe_date(x, None)
            if d is None: return '<span class="badge red">nema</span>'
            days=(d-date.today()).days
            if days<0: cls="red"
            elif days<=30: cls="yellow"
            else: cls="green"
            return f'<span class="badge {cls}">{d.isoformat()}</span>'
        show=dfm.copy()
        show["Liječnička"]=show["medical_valid_until"].apply(med_color)
        st.write(show.drop(columns=[]).to_html(escape=False, index=False), unsafe_allow_html=True)
    else:
        st.info("Nema članova u bazi.")

# ============== STATISTIKA & PRETRAGA ==============
elif page=="📊 Statistika & Pretraga":
    st.subheader("Pretraga")
    q=st.text_input("Traži (ime, prezime, grupa, OIB, e-mail, telefon)")
    grupa=st.text_input("Filter grupa (prazno = sve)")
    god_od=st.number_input("Godina rođenja od", 1900, 2100, 1900, 1)
    god_do=st.number_input("Godina rođenja do", 1900, 2100, 2100, 1)
    dfm=df_from_sql("SELECT * FROM members")
    if q:
        ql=q.lower()
        dfm=dfm[dfm.apply(lambda r: any(ql in str(r[c]).lower() for c in ["ime","prezime","grupa_trening","oib","email_sportas","email_roditelj","telefon_sportas","telefon_roditelj","clanski_broj"]), axis=1)]
    if grupa.strip():
        dfm=dfm[dfm["grupa_trening"].astype(str).str.lower()==grupa.strip().lower()]
    dfm=dfm[(pd.to_numeric(dfm["godina_rodjenja"], errors="coerce")>=god_od) & (pd.to_numeric(dfm["godina_rodjenja"], errors="coerce")<=god_do)]
    st.caption(f"Pronađeno: {len(dfm)}"); df_mobile(dfm)

    st.subheader("Statistika")
    total=len(dfm); by_group=dfm.groupby("grupa_trening", dropna=False).size().reset_index(name="broj").sort_values("broj", ascending=False)
    st.write("Ukupno članova (filter):", total)
    df_mobile(by_group, h=300)

    st.markdown("### 📤 Izvoz rezultata pretrage")
    bio=BytesIO(); 
    with pd.ExcelWriter(bio, engine="openpyxl") as w: dfm.to_excel(w, index=False, sheet_name="pretraga")
    st.download_button("⬇️ Preuzmi (Excel)", data=bio.getvalue(), file_name="pretraga_clanovi.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
