from fastapi import FastAPI, Response, Request, Form, Depends, HTTPException, status, BackgroundTasks, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import json
import base64
from sqlalchemy import create_engine, Column, Integer, String, Float, or_, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
import os
import urllib.parse
from jinja2 import Template
from typing import List, Optional

app = FastAPI(title="POS BUMDes Kembaran Versi 53 (Supabase Pure)")

SECRET_KEY = "BUMDES_RAHASIA_SUPER"

def create_session_token(username: str, nama: str, role: str, shift: str) -> str:
    data = {"username": username, "nama": nama, "role": role, "shift": shift}
    json_str = json.dumps(data)
    return base64.urlsafe_b64encode(json_str.encode()).decode()

def get_current_user(session_token: Optional[str] = Cookie(None)):
    if not session_token: return None
    try:
        json_str = base64.urlsafe_b64decode(session_token.encode()).decode()
        return json.loads(json_str)
    except Exception: return None


FORBIDDEN_HTML = r'''
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Akses Ditolak</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 min-h-screen flex items-center justify-center p-4">
    <div class="max-w-md w-full bg-white rounded-2xl shadow-xl p-8 text-center space-y-4 border">
        <div class="w-16 h-16 bg-red-100 text-red-600 rounded-full flex items-center justify-center text-3xl mx-auto font-black">!</div>
        <h1 class="text-xl font-black text-gray-800">Akses Ditolak (403)</h1>
        <p class="text-xs text-gray-500 leading-relaxed">Anda login sebagai <strong class="text-gray-800">{{ user.nama }}</strong> dengan role <strong class="text-gray-800">{{ user.role }}</strong>. Akun Anda tidak memiliki izin untuk mengakses halaman ini.</p>
        <div class="pt-4 flex flex-col gap-2">
            {% if user.role == 'Kasir' %}
            <a href="/pos" class="w-full bg-blue-600 text-white font-bold py-2.5 rounded-xl text-xs shadow">Kembali ke Kasir POS</a>
            {% elif user.role == 'Admin Kebun' %}
            <a href="/admin-kebun" class="w-full bg-emerald-600 text-white font-bold py-2.5 rounded-xl text-xs shadow">Kembali ke Panel Admin Kebun</a>
            {% elif user.role == 'Admin Keuangan' %}
            <a href="/admin" class="w-full bg-blue-600 text-white font-bold py-2.5 rounded-xl text-xs shadow">Kembali ke Panel Admin</a>
            {% else %}
            <a href="/pre-order" class="w-full bg-gray-800 text-white font-bold py-2.5 rounded-xl text-xs shadow">Kembali ke Halaman Utama</a>
            {% endif %}
            <a href="/logout" class="w-full bg-red-50 text-red-700 font-bold py-2 rounded-xl text-xs hover:bg-red-100">Ganti Akun / Logout</a>
        </div>
    </div>
</body>
</html>
'''

class CustomForbiddenException(HTTPException):
    def __init__(self, user: dict):
        super().__init__(status_code=403)
        self.user = user

def require_role(allowed_roles: list):
    def role_checker(user: dict = Depends(get_current_user)):
        if not user: raise HTTPException(status_code=303, headers={"Location": "/login"})
        if user.get("role") not in allowed_roles and user.get("role") != "Admin":
            raise CustomForbiddenException(user=user)
        return user
    return role_checker

@app.exception_handler(CustomForbiddenException)
async def custom_forbidden_handler(request: Request, exc: CustomForbiddenException):
    return HTMLResponse(content=Template(FORBIDDEN_HTML).render(user=exc.user), status_code=403)

STATIC_QRIS = "00020101021126590013ID.CO.BNI.WWW011893600009150484690802096175577690303UMI51450015ID.OR.GPNQR.WWW0215ID10266064913750303UMI5204544153033605802ID5915BUMDES KEMBARAN6008BANYUMAS61055318263049AFA"

def safe_float(val) -> float:
    if val is None: return 0.0
    val_str = str(val).strip().replace(' ', '').replace('Rp', '').replace('rp', '').replace('RP', '')
    if not val_str: return 0.0
    if val_str.count('.') > 1: val_str = val_str.replace('.', '')
    if val_str.count(',') > 1: val_str = val_str.replace(',', '')

    if ',' in val_str and '.' in val_str:
        if val_str.rfind(',') > val_str.rfind('.'): val_str = val_str.replace(',', '')
        else: val_str = val_str.replace('.', '').replace(',', '.')
    elif ',' in val_str: val_str = val_str.replace(',', '.')
    elif '.' in val_str:
        if len(val_str.split('.')[-1]) == 3: val_str = val_str.replace('.', '')
            
    try: return float(val_str)
    except ValueError: return 0.0

def create_dynamic_qris(base_qris: str, amount: float) -> str:
    if amount <= 0: return base_qris
    amount_str = str(int(amount))
    tag_54 = f"54{len(amount_str):02d}{amount_str}"
    idx = base_qris.find("5802ID")
    if idx == -1: return base_qris
    new_qris = base_qris[:idx] + tag_54 + base_qris[idx:-4]
    crc = 0xFFFF
    for char in new_qris:
        crc ^= ord(char) << 8
        for _ in range(8):
            if (crc & 0x8000) > 0: crc = (crc << 1) ^ 0x1021
            else: crc = crc << 1
        crc &= 0xFFFF
    return new_qris + f"{crc:04X}"

# Database Configuration (Supabase PostgreSQL / SQLite fallback)
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./pos_bumdes.db")

if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class PesananDB(Base):
    __tablename__ = "data_pemesan"
    id_pesanan = Column(String, primary_key=True, index=True)
    tanggal_transaksi = Column(String)
    nama_pelanggan = Column(String)
    no_whatsapp = Column(String)
    keterangan = Column(String)
    total_tagihan = Column(Float, default=0.0)
    nominal_dp = Column(Float, default=0.0)
    nominal_dp_diterima = Column(Float, default=0.0)
    status_dp = Column(String, default="Belum")
    qty_golden = Column(Float, default=0.0)
    qty_white = Column(Float, default=0.0)
    lajur_golden = Column(String, default="-")
    baris_golden = Column(Integer, default=0)
    aktual_golden = Column(Float, default=0.0)
    lajur_white = Column(String, default="-")
    baris_white = Column(Integer, default=0)
    aktual_white = Column(Float, default=0.0)
    status_pelunasan = Column(String, default="Belum")

class PosDB(Base):
    __tablename__ = "data_pos"
    id_pos = Column(String, primary_key=True, index=True)
    tanggal = Column(String)
    tipe_transaksi = Column(String)
    id_referensi = Column(String, nullable=True)
    nama_pelanggan = Column(String)
    qty_golden = Column(Float, default=0.0)
    qty_white = Column(Float, default=0.0)
    diskon_keterangan = Column(String, default="-")
    total_tagihan = Column(Float, default=0.0)
    dibayar = Column(Float, default=0.0)
    kembalian = Column(Float, default=0.0)
    metode_pembayaran = Column(String, default="Tunai")
    nama_petugas = Column(String, default="Kasir")
    shift = Column(String, default="Shift 1")

class StokKebunDB(Base):
    __tablename__ = "stok_kebun"
    id_stok = Column(String, primary_key=True)
    lajur = Column(String)
    baris = Column(Integer)
    jenis_buah = Column(String)
    berat = Column(Float, default=0.0)
    status = Column(String, default="Tersedia")
    id_pesanan = Column(String, nullable=True)
    nama_pemesan = Column(String, nullable=True)

class UserDB(Base):
    __tablename__ = "admin_users"
    username = Column(String, primary_key=True, index=True)
    password = Column(String)
    nama = Column(String)
    wa = Column(String)
    role = Column(String)

class PelangganDB(Base):
    __tablename__ = "data_pelanggan"
    wa = Column(String, primary_key=True, index=True)
    nama = Column(String)
    kategori = Column(String, default="Umum")
    diskon = Column(Float, default=0.0)
    status = Column(String, default="Aktif")
    catatan = Column(String, default="-")

class ConfigDB(Base):
    __tablename__ = "app_config"
    key = Column(String, primary_key=True, index=True)
    value = Column(String)

# Initialize database tables and default accounts
Base.metadata.create_all(bind=engine)
db_init = SessionLocal()
try:
    if not db_init.query(UserDB).first():
        db_init.add(UserDB(username="BUDI", password="123", nama="Budiono", wa="08974982752", role="Admin"))
        db_init.add(UserDB(username="TATA", password="41090", nama="TA'DYA ULFA WIJAYANTI", wa="6285747484090", role="Admin Keuangan"))
        db_init.add(UserDB(username="DUNUNG", password="160880", nama="DUNUNG SETIO PAMBUDI", wa="6288211700889", role="Admin Kebun"))
        db_init.add(UserDB(username="BUDIONO", password="290878", nama="BUDIONO", wa="8974982752", role="Kasir"))
        db_init.add(UserDB(username="TADYA", password="41090", nama="TA'DYA ULFA WIJAYANTI", wa="6285747484090", role="Kasir"))
        db_init.commit()
    
    if not db_init.query(ConfigDB).first():
        defaults = {
            "Kuota Promo": "100", "Persen Diskon": "0.0", "Tanggal Panen": "Segera",
            "WA Admin Utama": "08974982752", "WA Admin Keuangan": "08974982752",
            "WA Admin Kebun": "08974982752", "Harga Per Kg": "35000"
        }
        for k, v in defaults.items():
            db_init.add(ConfigDB(key=k, value=v))
        db_init.commit()
finally:
    db_init.close()

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def get_app_config() -> dict:
    db = SessionLocal()
    try:
        configs = db.query(ConfigDB).all()
        conf = {c.key: c.value for c in configs}
        if not conf:
            conf = {"Kuota Promo": 100, "Persen Diskon": 0.0, "Tanggal Panen": "Segera", "WA Admin Utama": "08974982752", "WA Admin Keuangan": "08974982752", "WA Admin Kebun": "08974982752", "Harga Per Kg": 35000.0}
        else:
            try:
                conf["Harga Per Kg"] = safe_float(conf.get("Harga Per Kg", "35000"))
                conf["Kuota Promo"] = int(conf.get("Kuota Promo", "100"))
                conf["Persen Diskon"] = float(conf.get("Persen Diskon", "0.0"))
            except: pass
        return conf
    finally:
        db.close()

# --- HTML Templates ---
ADMIN_KEBUN_HTML = r"""
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Panel Admin Kebun BUMDes V53</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>tailwind.config = { theme: { extend: { colors: { pos: '#059669' } } } }</script>
</head>
<body class="bg-emerald-50 min-h-screen pb-10">
    <nav class="bg-emerald-700 shadow-md px-6 py-4 flex justify-between items-center sticky top-0 z-50 text-white">
        <div class="flex items-center space-x-3"><span class="text-2xl">👨‍🌾</span><span class="text-xl font-black tracking-wide">PANEL ADMIN KEBUN</span> <div class="ml-4 px-3 py-1 rounded bg-emerald-800 text-sm font-semibold border border-emerald-500">Halo, {{ user_aktif.nama if user_aktif else "Admin" }}</div></div>
        <div class="flex space-x-3 text-sm items-center">
            <button type="button" onclick="bukaModalPrinter()" class="bg-teal-600 text-white px-3 py-1.5 rounded font-bold text-xs shadow hover:bg-teal-700 transition">🖨️ Printer</button>
            <a href="/admin" class="bg-white text-emerald-800 px-3 py-1.5 rounded font-bold text-xs shadow hover:bg-gray-100 transition">← Admin Pusat</a>
            <a href="/pos" class="bg-blue-600 text-white px-3 py-1.5 rounded font-bold text-xs shadow hover:bg-blue-700 transition">🛒 Kasir</a>
            <a href="/logout" class="bg-red-500 hover:bg-red-600 text-white px-3 py-1.5 rounded font-bold text-xs shadow ml-2">🚪 Keluar</a>
        </div>
    </nav>
    <div class="max-w-7xl mx-auto p-4 space-y-6 mt-4">
        <div class="bg-white rounded-2xl shadow-sm border border-emerald-200 overflow-hidden">
            <div class="p-4 bg-emerald-800 text-white flex justify-between items-center">
                <h2 class="font-bold text-lg">📊 Dashboard Rekap Stok Kebun</h2>
                <a href="/export-stok-kebun" target="_blank" class="bg-emerald-500 hover:bg-emerald-400 text-white px-4 py-1.5 rounded font-bold text-xs shadow-md transition flex items-center gap-2">📥 Export CSV</a>
            </div>
            <div class="p-5 bg-emerald-50/50 grid grid-cols-1 md:grid-cols-2 gap-5">
                <div class="bg-white p-4 rounded-xl border border-yellow-200 shadow-sm flex flex-col">
                    <div class="font-bold text-gray-800 border-b pb-2 mb-3 flex items-center"><div class="w-3 h-3 rounded-full bg-yellow-400 mr-2"></div>Melon Golden Humi</div>
                    <div class="grid grid-cols-2 gap-3 text-sm">
                        <div class="bg-green-50 p-3 rounded-lg text-center border border-green-100"><div class="text-xs text-gray-500 font-semibold mb-1">Stok Tersedia</div><div class="font-black text-green-700 text-2xl">{{ rekap_stok['Golden']['Tersedia_Butir'] }} <span class="text-xs font-normal">Btr</span></div><div class="text-xs font-bold text-green-800 mt-1">{{ "%.2f"|format(rekap_stok['Golden']['Tersedia_Kg']) }} KG</div></div>
                        <div class="bg-orange-50 p-3 rounded-lg text-center border border-orange-100"><div class="text-xs text-gray-500 font-semibold mb-1">Telah Diplot PO</div><div class="font-black text-orange-700 text-2xl">{{ rekap_stok['Golden']['Dipesan_Butir'] }} <span class="text-xs font-normal">Btr</span></div><div class="text-xs font-bold text-orange-800 mt-1">{{ "%.2f"|format(rekap_stok['Golden']['Dipesan_Kg']) }} KG</div></div>
                    </div>
                </div>
                <div class="bg-white p-4 rounded-xl border border-teal-200 shadow-sm flex flex-col">
                    <div class="font-bold text-gray-800 border-b pb-2 mb-3 flex items-center"><div class="w-3 h-3 rounded-full bg-teal-400 mr-2"></div>Melon White Humi</div>
                    <div class="grid grid-cols-2 gap-3 text-sm">
                        <div class="bg-green-50 p-3 rounded-lg text-center border border-green-100"><div class="text-xs text-gray-500 font-semibold mb-1">Stok Tersedia</div><div class="font-black text-green-700 text-2xl">{{ rekap_stok['White']['Tersedia_Butir'] }} <span class="text-xs font-normal">Btr</span></div><div class="text-xs font-bold text-green-800 mt-1">{{ "%.2f"|format(rekap_stok['White']['Tersedia_Kg']) }} KG</div></div>
                        <div class="bg-orange-50 p-3 rounded-lg text-center border border-orange-100"><div class="text-xs text-gray-500 font-semibold mb-1">Telah Diplot PO</div><div class="font-black text-orange-700 text-2xl">{{ rekap_stok['White']['Dipesan_Butir'] }} <span class="text-xs font-normal">Btr</span></div><div class="text-xs font-bold text-orange-800 mt-1">{{ "%.2f"|format(rekap_stok['White']['Dipesan_Kg']) }} KG</div></div>
                    </div>
                </div>
            </div>
        </div>

        <div class="bg-white rounded-2xl shadow-sm border border-emerald-200 overflow-hidden">
            <div class="p-4 bg-emerald-600 text-white flex justify-between items-center"><h2 class="font-bold text-lg">➕ Input Stok Buah Tersedia di Kebun</h2></div>
            <div class="p-5 bg-emerald-50/50">
                <form action="/input-stok" method="POST" class="flex flex-col md:flex-row gap-4 items-end">
                    <div class="w-full md:w-1/5"><label class="text-xs font-bold text-gray-700 block mb-1">Lajur</label><select name="lajur" class="w-full border rounded p-2 text-sm font-bold bg-white" required>{% for l in ['A','B','C','D','E','F','G'] %}<option value="{{l}}">Lajur {{l}}</option>{% endfor %}</select></div>
                    <div class="w-full md:w-1/5"><label class="text-xs font-bold text-gray-700 block mb-1">Baris</label><select name="baris" class="w-full border rounded p-2 text-sm font-bold bg-white" required>{% for b in range(1, 11) %}<option value="{{b}}">Baris {{b}}</option>{% endfor %}</select></div>
                    <div class="w-full md:w-1/5"><label class="text-xs font-bold text-gray-700 block mb-1">Jenis Buah</label><select name="jenis_buah" class="w-full border rounded p-2 text-sm font-bold bg-white" required><option value="Golden">Melon Golden</option><option value="White">Melon White</option></select></div>
                    <div class="w-full md:w-1/5"><label class="text-xs font-bold text-gray-700 block mb-1">Berat Aktual (KG)</label><input type="number" step="any" name="berat" placeholder="Contoh: 1.5" class="w-full border rounded p-2 text-sm font-black bg-white" required></div>
                    <div class="w-full md:w-1/5"><button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2 px-4 rounded text-sm shadow">💾 Simpan ke Denah</button></div>
                </form>
            </div>
        </div>
        <div class="bg-white rounded-2xl shadow-sm border border-emerald-200 overflow-hidden">
            <div class="p-4 border-b bg-gray-50 flex justify-between items-center"><h2 class="font-bold text-gray-800 text-lg">🗺️ Denah Lokasi & Status Stok Aktual</h2></div>
            <div class="p-4 overflow-x-auto bg-emerald-50/50">
                <div class="min-w-[800px]">
                    <div class="grid grid-cols-8 gap-2 text-center text-xs mb-2"><div></div>{% for l in ['A','B','C','D','E','F','G'] %}<div class="font-black bg-emerald-200 text-emerald-800 py-2 rounded shadow-sm">LAJUR {{ l }}</div>{% endfor %}</div>
                    {% for baris in range(1, 11) %}
                    <div class="grid grid-cols-8 gap-2 mt-2">
                        <div class="font-black bg-emerald-100 text-emerald-800 flex items-center justify-center rounded shadow-sm">BARIS {{ baris }}</div>
                        {% for lajur in ['A','B','C','D','E','F','G'] %}
                        <div class="border border-emerald-200 rounded p-1 min-h-[55px] bg-white text-[10px] text-left shadow-sm relative">
                            {% if denah[lajur][baris]|length > 0 %}
                                {% for item in denah[lajur][baris] %}
                                    <div class="{% if item.status == 'Tersedia' %}bg-green-100 text-green-800 border-green-300{% else %}bg-yellow-100 text-yellow-800 border-yellow-300{% endif %} font-bold mb-1 px-1.5 py-1 rounded border leading-tight">
                                        <div class="flex justify-between"><span>{{ 'G' if item.jenis == 'Golden' else 'W' }}: {{ item.berat }}kg</span><a href="/hapus-stok/{{ item.id }}" onclick="return confirm('Hapus stok ini?')" class="text-red-500">✕</a></div>
                                        {% if item.status != 'Tersedia' %}<div class="text-[8px] mt-0.5 text-gray-600 truncate border-t border-yellow-200 pt-0.5">PO: {{ item.pemesan }}</div>{% endif %}
                                    </div>
                                {% endfor %}
                            {% else %}<div class="text-gray-300 text-center italic mt-3 text-[9px]">Kosong</div>{% endif %}
                        </div>
                        {% endfor %}
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        <div class="bg-white rounded-2xl shadow-sm border border-emerald-200 overflow-hidden">
            <div class="p-4 border-b bg-gray-50 flex justify-between items-center"><h2 class="font-bold text-gray-800 text-lg">📋 Plotting Pesanan PO ke Denah Kebun</h2></div>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-sm whitespace-nowrap">
                    <thead class="bg-emerald-600 text-white text-[11px] uppercase border-b">
                        <tr><th class="p-4 w-1/4">Info Pelanggan & PO</th><th class="p-4 bg-orange-600/90 w-1/4">🍈 Pilih Stok Golden</th><th class="p-4 bg-teal-600/90 w-1/4">🍈 Pilih Stok White</th><th class="p-4 text-center w-1/4">Aksi / Kirim WA</th></tr>
                    </thead>
                    <tbody class="divide-y divide-gray-200">
                        {% for p in pesanan_list %}
                        <tr class="hover:bg-emerald-50 transition">
                            <td class="p-4"><div class="font-bold text-gray-800 text-base">{{ p.nama_pelanggan }}</div><div class="font-mono text-xs text-gray-500">{{ p.id_pesanan }}</div><div class="text-[11px] text-blue-600 mt-1 font-semibold">📞 {{ p.no_whatsapp }}</div></td>
                            <td class="p-4 bg-orange-50/30 align-top">
                                {% if p.qty_golden > 0 %}
                                    <select id="sg_{{ p.id_pesanan }}" class="w-full border rounded p-1.5 text-xs font-bold bg-white"><option value="">-- Pilih Stok Golden --</option>
                                    {% for s in stok_g %}{% if s.status == 'Tersedia' or s.id_pesanan == p.id_pesanan %}<option value="{{s.id_stok}}" {% if s.id_pesanan == p.id_pesanan %}selected{% endif %}>Lajur {{s.lajur}} - Brs {{s.baris}} ({{s.berat}} KG)</option>{% endif %}{% endfor %}
                                    </select>
                                {% else %}<div class="text-xs text-gray-400 italic">Tidak beli Golden</div>{% endif %}
                            </td>
                            <td class="p-4 bg-teal-50/30 align-top">
                                {% if p.qty_white > 0 %}
                                    <select id="sw_{{ p.id_pesanan }}" class="w-full border rounded p-1.5 text-xs font-bold bg-white"><option value="">-- Pilih Stok White --</option>
                                    {% for s in stok_w %}{% if s.status == 'Tersedia' or s.id_pesanan == p.id_pesanan %}<option value="{{s.id_stok}}" {% if s.id_pesanan == p.id_pesanan %}selected{% endif %}>Lajur {{s.lajur}} - Brs {{s.baris}} ({{s.berat}} KG)</option>{% endif %}{% endfor %}
                                    </select>
                                {% else %}<div class="text-xs text-gray-400 italic">Tidak beli White</div>{% endif %}
                            </td>
                            <td class="p-4 text-center space-y-2 align-top">
                                <button type="button" onclick="simpanPlotting('{{ p.id_pesanan }}')" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-2 rounded text-xs font-bold shadow mb-1">💾 Tandai & Simpan</button>
                                <button type="button" onclick="cetakPlotPanen('{{ p.id_pesanan }}')" class="block w-full text-center bg-gray-800 hover:bg-black text-white px-3 py-2 rounded text-[10px] font-bold shadow">🖨️ Cetak Plot Panen</button>
                                <button type="button" onclick="kirimWA('{{ p.id_pesanan }}', '{{ p.nama_pelanggan }}', '{{ p.no_whatsapp }}', {{ p.qty_golden }}, {{ p.qty_white }})" class="w-full bg-green-500 hover:bg-green-600 text-white px-3 py-2 rounded text-xs font-bold shadow">📱 Kirim WA</button>
                            </td>
                        </tr>
                        {% endfor %}
                        {% if not pesanan_list %}<tr><td colspan="4" class="p-8 text-center text-gray-400 font-bold">Belum ada pesanan PO yang aktif.</td></tr>{% endif %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    <script>
        async function simpanPlotting(id) {
            let sg = document.getElementById('sg_'+id)?.value || ''; 
            let sw = document.getElementById('sw_'+id)?.value || '';
            let fd = new FormData(); fd.append('id_sg', sg); fd.append('id_sw', sw);
            try {
                let res = await fetch('/update-kebun/' + id, { method: 'POST', body: fd });
                if(res.ok) { alert("Plotting berhasil!"); window.location.reload(); }
                else alert("Gagal menyimpan data!");
            } catch(e) { alert("Error jaringan."); }
        }
        function kirimWA(id, nama, hp, qtyG, qtyW) {
            let elG = document.getElementById('sg_'+id);
            let elW = document.getElementById('sw_'+id);
            let txtG = (qtyG > 0 && elG && elG.value) ? elG.options[elG.selectedIndex].text : "Belum diplot";
            let txtW = (qtyW > 0 && elW && elW.value) ? elW.options[elW.selectedIndex].text : "Belum diplot";
            let no = hp.trim(); if(no.startsWith('0')) no = '62' + no.substring(1);
            let pesan = `Halo Bpk/Ibu *${nama}*, Pesanan (ID: *${id}*) sudah siap di kebun.`;
            if(qtyG > 0) pesan += `\n- Golden: ${txtG}`;
            if(qtyW > 0) pesan += `\n- White: ${txtW}`;
            pesan += `\n\nSilakan tunjukkan pesan ini ke kasir. Terima kasih.`;
            window.open(`https://api.whatsapp.com/send?phone=${no}&text=` + encodeURIComponent(pesan), '_blank');
        }
    </script>
</body>
</html>
"""

PRE_ORDER_HTML = r"""
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Pre-Order BUMDes Kembaran</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>tailwind.config = { theme: { extend: { colors: { shopee: '#EE4D2D' } } } }</script>
</head>
<body class="bg-gray-100 pb-20">
    <header class="bg-shopee text-white p-4 shadow-md sticky top-0 z-50">
        <div class="max-w-md mx-auto flex justify-between items-center">
            <h1 class="font-bold text-lg">Pre-Order BUMDes</h1>
            <a href="/login" class="text-xs bg-white text-shopee px-2.5 py-1 rounded font-bold shadow">Login Admin</a>
        </div>
    </header>
    <main class="max-w-md mx-auto bg-white min-h-screen pb-10 p-4">
        {% set kuota_promo = config.get('Kuota Promo', 0)|int %}
        {% set harga_asli = config.get('Harga Per Kg', 35000.0)|float %}
        <form action="/submit-order" method="POST" class="space-y-4">
            <div class="grid grid-cols-2 gap-4">
                <div class="border rounded-lg p-3 bg-white text-center">
                    <h2 class="text-xs font-bold text-gray-800">Melon Golden</h2>
                    <div class="text-shopee font-bold text-sm my-1">Rp {{ "{:,.0f}".format(harga_asli) }}/Kg</div>
                    <input type="number" name="qty_golden" value="0" min="0" class="w-full border rounded p-1.5 text-lg font-bold text-center">
                </div>
                <div class="border rounded-lg p-3 bg-white text-center">
                    <h2 class="text-xs font-bold text-gray-800">Melon White</h2>
                    <div class="text-shopee font-bold text-sm my-1">Rp {{ "{:,.0f}".format(harga_asli) }}/Kg</div>
                    <input type="number" name="qty_white" value="0" min="0" class="w-full border rounded p-1.5 text-lg font-bold text-center">
                </div>
            </div>
            <div class="bg-gray-50 p-4 rounded-xl border space-y-3">
                <div><label class="text-xs text-gray-600 font-semibold block mb-1">Nama Lengkap</label><input type="text" name="nama_pelanggan" required class="w-full p-2 border rounded text-sm"></div>
                <div><label class="text-xs text-gray-600 font-semibold block mb-1">WhatsApp Aktif</label><input type="tel" name="no_whatsapp" required class="w-full p-2 border rounded text-sm"></div>
                <div><label class="text-xs text-gray-600 font-semibold block mb-1">Keterangan</label><textarea name="keterangan" class="w-full p-2 border rounded text-sm" rows="2"></textarea></div>
            </div>
            <button type="submit" class="w-full bg-shopee text-white font-bold py-3.5 rounded-lg shadow-lg text-sm">Pesan Sekarang & Bayar DP 🚀</button>
        </form>
    </main>
</body>
</html>
"""

SUCCESS_HTML = r"""
<!DOCTYPE html>
<html lang="id">
<head><meta charset="UTF-8"><title>Berhasil Pesan</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-gray-100 min-h-screen p-4 flex items-center justify-center">
    <div class="max-w-md w-full bg-white rounded-2xl shadow-md p-6 text-center space-y-4">
        <div class="w-16 h-16 bg-green-100 text-green-600 rounded-full flex items-center justify-center text-3xl mx-auto">✓</div>
        <h1 class="font-bold text-xl text-gray-800">Pre-Order Berhasil Dicatat!</h1>
        <p class="text-xs text-gray-500">ID Pesanan Anda: <span class="font-mono font-bold text-orange-600 text-sm">{{ order.id_pesanan }}</span></p>
        <div class="bg-blue-50 border border-blue-200 p-4 rounded-xl">
            <p class="text-xs font-bold text-blue-800 mb-2">Scan QRIS untuk Pembayaran DP:</p>
            <img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={{ qris_url_encoded }}" class="h-44 w-44 mx-auto object-contain bg-white p-2 border rounded">
        </div>
        <a href="{{ wa_link }}" target="_blank" class="block w-full bg-green-500 hover:bg-green-600 text-white font-bold py-3 rounded-lg text-sm shadow">💬 Konfirmasi via WhatsApp</a>
        <a href="/pre-order" class="block text-xs text-gray-500 font-semibold hover:underline pt-2">← Buat Pesanan Baru</a>
    </div>
</body>
</html>
"""

POS_HTML = r"""
<!DOCTYPE html>
<html lang="id">
<head><meta charset="UTF-8"><title>Kasir POS BUMDes Kembaran</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-gray-100 min-h-screen p-6">
    <div class="max-w-xl mx-auto bg-white rounded-2xl shadow p-6 space-y-4">
        <div class="flex justify-between items-center border-b pb-3"><h1 class="font-bold text-lg">🛒 Kasir POS</h1><a href="/admin" class="text-xs bg-gray-200 px-3 py-1.5 rounded font-bold">Admin</a></div>
        <p class="text-sm text-gray-600">Sistem POS aktif menggunakan Supabase Database.</p>
        <a href="/logout" class="block text-center bg-red-500 text-white py-2 rounded font-bold text-xs">Keluar</a>
    </div>
</body>
</html>
"""

ADMIN_HTML = r"""
<!DOCTYPE html>
<html lang="id">
<head><meta charset="UTF-8"><title>Admin POS Pro</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-gray-50 min-h-screen p-6">
    <div class="max-w-4xl mx-auto bg-white rounded-2xl shadow p-6 space-y-4">
        <div class="flex justify-between items-center border-b pb-4"><h1 class="font-bold text-xl text-orange-600">Admin Panel BUMDes</h1><div class="space-x-2"><a href="/admin-kebun" class="text-xs bg-emerald-600 text-white px-3 py-1.5 rounded font-bold">Kebun</a><a href="/logout" class="text-xs bg-red-500 text-white px-3 py-1.5 rounded font-bold">Keluar</a></div></div>
        <p class="text-sm text-gray-700">Total Pesanan PO: <b>{{ pesanan_list|length }}</b></p>
    </div>
</body>
</html>
"""

CONFIG_ADMIN_HTML = r"""<!DOCTYPE html><html><body class="p-6"><h1>Setting Config</h1><a href="/admin">Kembali</a></body></html>"""
LAPORAN_HTML = r"""<!DOCTYPE html><html><body class="p-6"><h1>Laporan</h1><a href="/admin">Kembali</a></body></html>"""
ADMIN_USERS_HTML = r"""<!DOCTYPE html><html><body class="p-6"><h1>Users</h1><a href="/admin">Kembali</a></body></html>"""
PELANGGAN_HTML = r"""<!DOCTYPE html><html><body class="p-6"><h1>Pelanggan</h1><a href="/admin">Kembali</a></body></html>"""

LOGIN_HTML = r"""
<!DOCTYPE html>
<html lang="id">
<head><meta charset="UTF-8"><title>Login POS BUMDes</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-gray-100 min-h-screen flex items-center justify-center p-4">
    <div class="max-w-md w-full bg-white rounded-2xl shadow-xl p-6 border">
        <h1 class="text-xl font-black text-center mb-4">LOGIN POS BUMDES</h1>
        <form action="/login" method="POST" class="space-y-4">
            {% if error %}<div class="bg-red-50 text-red-700 p-2 rounded text-xs font-bold text-center">{{ error }}</div>{% endif %}
            <div><label class="text-xs font-bold">Username</label><input type="text" name="username" required class="w-full p-2 border rounded uppercase"></div>
            <div><label class="text-xs font-bold">Password</label><input type="password" name="password" required class="w-full p-2 border rounded"></div>
            <div><label class="text-xs font-bold">Shift</label><select name="shift" class="w-full p-2 border rounded"><option value="Shift 1">Shift 1</option><option value="Shift 2">Shift 2</option></select></div>
            <button type="submit" class="w-full bg-blue-600 text-white font-bold py-3 rounded">MASUK</button>
        </form>
    </div>
</body>
</html>
"""

# --- FastAPI Routes ---
@app.get("/login", response_class=HTMLResponse)
def login_page(error: str = ""):
    return HTMLResponse(content=Template(LOGIN_HTML).render(error=error))

@app.post("/login")
def process_login(response: Response, username: str = Form(...), password: str = Form(...), shift: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == username.upper(), UserDB.password == password).first()
    if user:
        token = create_session_token(user.username, user.nama, user.role, shift)
        target_url = "/pos" if user.role == "Kasir" else ("/admin-kebun" if user.role == "Admin Kebun" else "/admin")
        response = RedirectResponse(url=target_url, status_code=303)
        response.set_cookie(key="session_token", value=token, httponly=True, max_age=86400)
        return response
    return RedirectResponse(url="/login?error=Username+atau+Password+salah!", status_code=303)

@app.get("/logout")
def logout(response: Response):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_token")
    return response

@app.get("/", response_class=HTMLResponse)
def root(): return RedirectResponse(url="/pre-order")

@app.get("/pre-order", response_class=HTMLResponse)
def pre_order_page(): return HTMLResponse(content=Template(PRE_ORDER_HTML).render(config=get_app_config()))

@app.get("/pos", response_class=HTMLResponse)
def pos_page(request: Request, user: dict = Depends(require_role(["Admin", "Admin Keuangan", "Kasir"]))):
    return HTMLResponse(content=Template(POS_HTML).render(config=get_app_config(), user_aktif=user))

@app.get("/admin-kebun", response_class=HTMLResponse)
def admin_kebun_page(db: Session = Depends(get_db), user: dict = Depends(require_role(["Admin", "Admin Kebun"]))):
    pesanan_list = db.query(PesananDB).filter(PesananDB.status_pelunasan != 'Sudah Lunas', PesananDB.status_dp == 'Sudah').all()
    semua_stok = db.query(StokKebunDB).all()
    denah = {l: {b: [] for b in range(1, 11)} for l in ['A','B','C','D','E','F','G']}
    stok_g, stok_w = [], []
    rekap_stok = {
        "Golden": {"Tersedia_Butir": 0, "Tersedia_Kg": 0.0, "Dipesan_Butir": 0, "Dipesan_Kg": 0.0},
        "White": {"Tersedia_Butir": 0, "Tersedia_Kg": 0.0, "Dipesan_Butir": 0, "Dipesan_Kg": 0.0}
    }
    for s in semua_stok:
        if s.lajur in denah and 1 <= s.baris <= 10:
            denah[s.lajur][s.baris].append({"id": s.id_stok, "jenis": s.jenis_buah, "berat": s.berat, "status": s.status, "pemesan": s.nama_pemesan or "-"})
        if s.jenis_buah in rekap_stok:
            if s.status == "Tersedia":
                rekap_stok[s.jenis_buah]["Tersedia_Butir"] += 1
                rekap_stok[s.jenis_buah]["Tersedia_Kg"] += s.berat
            elif s.status in ["Dipesan", "Terjual", "Sudah Lunas"]:
                rekap_stok[s.jenis_buah]["Dipesan_Butir"] += 1
                rekap_stok[s.jenis_buah]["Dipesan_Kg"] += s.berat
        if s.jenis_buah == "Golden": stok_g.append(s)
        elif s.jenis_buah == "White": stok_w.append(s)
    return Template(ADMIN_KEBUN_HTML).render(pesanan_list=pesanan_list, denah=denah, stok_g=stok_g, stok_w=stok_w, rekap_stok=rekap_stok, user_aktif=user)

@app.post("/input-stok")
def input_stok(lajur: str = Form(...), baris: int = Form(...), jenis_buah: str = Form(...), berat: float = Form(...), db: Session = Depends(get_db)):
    id_stok = f"{jenis_buah}-{lajur}-{baris}"
    stok = db.query(StokKebunDB).filter_by(id_stok=id_stok).first()
    if stok:
        stok.berat = berat
        if stok.status == "Terjual": stok.status = "Tersedia"
    else:
        stok = StokKebunDB(id_stok=id_stok, lajur=lajur, baris=baris, jenis_buah=jenis_buah, berat=berat)
        db.add(stok)
    db.commit()
    return RedirectResponse(url="/admin-kebun", status_code=303)

@app.get("/hapus-stok/{id_stok}")
def hapus_stok(id_stok: str, db: Session = Depends(get_db)):
    stok = db.query(StokKebunDB).filter_by(id_stok=id_stok).first()
    if stok:
        db.delete(stok)
        db.commit()
    return RedirectResponse(url="/admin-kebun", status_code=303)

@app.post("/update-kebun/{id_pesanan}")
def update_kebun(id_pesanan: str, id_sg: str = Form(""), id_sw: str = Form(""), db: Session = Depends(get_db)):
    order = db.query(PesananDB).filter_by(id_pesanan=id_pesanan).first()
    if not order: raise HTTPException(status_code=404, detail="Order tidak ditemukan")
    for os in db.query(StokKebunDB).filter_by(id_pesanan=id_pesanan).all():
        os.status = "Tersedia"; os.id_pesanan = None; os.nama_pemesan = None
    lg, bg, ag, lw, bw, aw = "-", 0, 0.0, "-", 0, 0.0
    if id_sg:
        sg = db.query(StokKebunDB).filter_by(id_stok=id_sg).first()
        if sg: sg.status = "Dipesan"; sg.id_pesanan = order.id_pesanan; sg.nama_pemesan = order.nama_pelanggan; lg, bg, ag = sg.lajur, sg.baris, sg.berat
    if id_sw:
        sw = db.query(StokKebunDB).filter_by(id_stok=id_sw).first()
        if sw: sw.status = "Dipesan"; sw.id_pesanan = order.id_pesanan; sw.nama_pemesan = order.nama_pelanggan; lw, bw, aw = sw.lajur, sw.baris, sw.berat
    order.lajur_golden = lg; order.baris_golden = bg; order.aktual_golden = ag
    order.lajur_white = lw; order.baris_white = bw; order.aktual_white = aw
    db.commit()
    return {"status": "success"}

@app.get("/api/qris")
def get_qris_api(amount: float):
    dq = create_dynamic_qris(STATIC_QRIS, amount)
    return {"qris_string": dq, "qris_url": f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={urllib.parse.quote(dq)}"}

@app.post("/submit-order")
def submit_order(nama_pelanggan: str = Form(...), no_whatsapp: str = Form(...), keterangan: str = Form(""), qty_golden: float = Form(0.0), qty_white: float = Form(0.0), db: Session = Depends(get_db)):
    config = get_app_config()
    harga = float(config.get("Harga Per Kg", 35000))
    est_berat = (qty_golden + qty_white) * 1.5
    total = float(est_berat * harga)
    dp = float(total * 0.5)
    id_pes = f"PO-{datetime.now().strftime('%d%H%M%S')}"
    new_order = PesananDB(
        id_pesanan=id_pes, tanggal_transaksi=datetime.now().strftime("%Y-%m-%d %H:%M"), 
        nama_pelanggan=nama_pelanggan, no_whatsapp=no_whatsapp, keterangan=keterangan or "-", 
        total_tagihan=total, nominal_dp=dp, nominal_dp_diterima=0.0, status_dp="Belum", 
        qty_golden=qty_golden, qty_white=qty_white, status_pelunasan="Belum"
    )
    db.add(new_order); db.commit()
    return RedirectResponse(url=f"/success?id={id_pes}", status_code=303)

@app.get("/success", response_class=HTMLResponse)
def success_page(id: str, db: Session = Depends(get_db)):
    order = db.query(PesananDB).filter_by(id_pesanan=id).first()
    if not order: return RedirectResponse(url="/pre-order")
    config = get_app_config()
    wa = str(config.get("WA Admin Keuangan", "08974982752")).strip()
    if wa.startswith('0'): wa = '62' + wa[1:]
    dq = urllib.parse.quote(create_dynamic_qris(STATIC_QRIS, order.nominal_dp or 0.0))
    pesan_wa = f"Halo Admin Keuangan, saya sudah transfer DP sebesar Rp {order.nominal_dp:,.0f} untuk ID Pesanan {order.id_pesanan}."
    wa_link = f"https://api.whatsapp.com/send?phone={wa}&text={urllib.parse.quote(pesan_wa)}"
    return HTMLResponse(content=Template(SUCCESS_HTML).render(order=order, qris_url_encoded=dq, wa_link=wa_link))

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(db: Session = Depends(get_db), user: dict = Depends(require_role(["Admin", "Admin Keuangan"]))):
    pl = db.query(PesananDB).all()
    return Template(ADMIN_HTML).render(pesanan_list=pl)

@app.get("/export-stok-kebun")
def export_stok_kebun(db: Session = Depends(get_db)):
    stok = db.query(StokKebunDB).all()
    csv_lines = ["ID Stok,Lajur,Baris,Jenis Buah,Berat Aktual (KG),Status,ID Pesanan (PO),Nama Pemesan"]
    for s in stok:
        id_pes = str(s.id_pesanan or "-").replace(",", " ")
        nama_pem = str(s.nama_pemesan or "-").replace(",", " ")
        csv_lines.append(f"{s.id_stok},{s.lajur},{s.baris},{s.jenis_buah},{s.berat},{s.status},{id_pes},{nama_pem}")
    return Response(content="\n".join(csv_lines), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=Laporan_Stok_Kebun_BUMDes.csv"})

@app.get("/api/cari-pelanggan")
def cari_pelanggan_api(q: str, db: Session = Depends(get_db)):
    results = []
    pelanggan = db.query(PelangganDB).filter(or_(PelangganDB.nama.ilike(f"%{q}%"), PelangganDB.wa.ilike(f"%{q}%"))).all()
    for p in pelanggan:
        results.append({"nama": p.nama, "wa": p.wa, "kategori": p.kategori, "diskon": p.diskon})
    return results
