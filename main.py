from fastapi import FastAPI, Response, Request, Form, Depends, HTTPException, status, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
import json
import base64
from sqlalchemy import create_engine, Column, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from jinja2 import Template
from typing import Optional

app = FastAPI(title="POS BUMDes Kembaran (Stable)")

SECRET_KEY = "BUMDES_RAHASIA_SUPER"

def create_session_token(username: str, nama: str, role: str, shift: str) -> str:
    data = {"username": username, "nama": nama, "role": role, "shift": shift}
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()

def get_current_user(session_token: Optional[str] = Cookie(None)):
    if not session_token: return None
    try:
        return json.loads(base64.urlsafe_b64decode(session_token.encode()).decode())
    except Exception: return None

# Menggunakan SQLite lokal di server agar 100% stabil dan anti-gagal koneksi
SQLALCHEMY_DATABASE_URL = "sqlite:///./pos_bumdes_stable.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserDB(Base):
    __tablename__ = "admin_users"
    username = Column(String, primary_key=True, index=True)
    password = Column(String)
    nama = Column(String)
    wa = Column(String)
    role = Column(String)

Base.metadata.create_all(bind=engine)

# Buat akun default otomatis
db_init = SessionLocal()
if not db_init.query(UserDB).first():
    db_init.add(UserDB(username="BUDI", password="123", nama="Budiono", wa="08974982752", role="Admin"))
    db_init.add(UserDB(username="KASIR", password="123", nama="Kasir Utama", wa="08974982752", role="Kasir"))
    db_init.commit()
db_init.close()

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

LOGIN_HTML = r"""
<!DOCTYPE html>
<html lang="id">
<head><meta charset="UTF-8"><title>Login POS BUMDes</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-gray-100 min-h-screen flex items-center justify-center p-4">
    <div class="max-w-md w-full bg-white rounded-2xl shadow-xl p-6 border">
        <h1 class="text-xl font-black text-center mb-1">POS BUMDES KEMBARAN</h1>
        <p class="text-xs text-center text-gray-500 mb-4">Silakan Login ke Sistem</p>
        <form action="/login" method="POST" class="space-y-4">
            {% if error %}<div class="bg-red-50 text-red-700 p-2 rounded text-xs font-bold text-center">{{ error }}</div>{% endif %}
            <div><label class="text-xs font-bold">Username</label><input type="text" name="username" required class="w-full p-2 border rounded uppercase" value="BUDI"></div>
            <div><label class="text-xs font-bold">Password</label><input type="password" name="password" required class="w-full p-2 border rounded" value="123"></div>
            <div><label class="text-xs font-bold">Shift Kerja</label><select name="shift" class="w-full p-2 border rounded"><option value="Shift 1">Shift 1 (Pagi)</option><option value="Shift 2">Shift 2 (Siang)</option></select></div>
            <button type="submit" class="w-full bg-blue-600 text-white font-bold py-3 rounded-lg shadow">MASUK KE SISTEM 🚀</button>
        </form>
    </div>
</body>
</html>
"""

POS_HTML = r"""
<!DOCTYPE html>
<html lang="id">
<head><meta charset="UTF-8"><title>Kasir POS</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-gray-100 min-h-screen p-6 flex items-center justify-center">
    <div class="max-w-md w-full bg-white rounded-2xl shadow-lg p-6 text-center space-y-4">
        <div class="w-16 h-16 bg-green-100 text-green-600 rounded-full flex items-center justify-center text-3xl mx-auto font-bold">✓</div>
        <h1 class="font-bold text-xl text-gray-800">BERHASIL MASUK!</h1>
        <p class="text-sm text-gray-600">Halo, <b class="text-blue-600">{{ user_aktif.nama }}</b><br>Role: <b>{{ user_aktif.role }}</b> | Shift: <b>{{ user_aktif.shift }}</b></p>
        <div class="pt-4 border-t"><a href="/logout" class="block bg-red-500 hover:bg-red-600 text-white py-2.5 rounded-lg font-bold text-xs shadow">Keluar / Logout</a></div>
    </div>
</body>
</html>
"""

@app.get("/login", response_class=HTMLResponse)
def login_page(error: str = ""):
    return HTMLResponse(content=Template(LOGIN_HTML).render(error=error))

@app.post("/login")
def process_login(response: Response, username: str = Form(...), password: str = Form(...), shift: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == username.upper(), UserDB.password == password).first()
    if user:
        token = create_session_token(user.username, user.nama, user.role, shift)
        res = RedirectResponse(url="/pos", status_code=303)
        res.set_cookie(key="session_token", value=token, httponly=True, max_age=86400)
        return res
    return RedirectResponse(url="/login?error=Username+atau+Password+salah!", status_code=303)

@app.get("/logout")
def logout(response: Response):
    res = RedirectResponse(url="/login", status_code=303)
    res.delete_cookie("session_token")
    return res

@app.get("/", response_class=HTMLResponse)
def root(): return RedirectResponse(url="/login")

@app.get("/pos", response_class=HTMLResponse)
def pos_page(user: dict = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login", status_code=303)
    return HTMLResponse(content=Template(POS_HTML).render(user_aktif=user))
