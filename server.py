import sqlite3
import unicodedata
import os
import time
import hashlib
from fastapi import FastAPI, Query, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import httpx

app = FastAPI(title="MacroFit Multi-User API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "alimentos_cache.db"

# ==============================================================================
# CHAVE MESTRA PARA RECUPERAÇÃO DE SENHA (Altere se desejar)
# ==============================================================================
CHAVE_MESTRA_RECUPERACAO = os.getenv("MACROFIT_RESET_KEY", "macrofit2026")

FATSECRET_CLIENT_ID = os.getenv("FATSECRET_CLIENT_ID", "fe6063cade4b4ca3ba6487f3d521c556")
FATSECRET_CLIENT_SECRET = os.getenv("FATSECRET_CLIENT_SECRET", "a4833d40ca15452392896fb1efa1bc64")

token_cache = {
    "access_token": None,
    "expires_at": 0
}

# --- MODELOS PYDANTIC ---
class AuthRequest(BaseModel):
    username: str
    password: str

class ResetPasswordRequest(BaseModel):
    username: str
    chave_mestra: str
    nova_senha: str

class MetasModel(BaseModel):
    kcal: int
    prot: float
    carb: float
    fat: float
    agua: int

class AguaModel(BaseModel):
    data: str
    quantidade: float

class RegistroRefeicaoModel(BaseModel):
    data: str
    categoria: str
    nome: str
    marca: Optional[str] = "Genérico"
    quantidade: float
    unidade_desc: str
    calorias: float
    proteinas: float
    carboidratos: float
    gorduras: float

class AlimentoManual(BaseModel):
    nome: str
    marca: Optional[str] = "Manual"
    calorias: float
    proteinas: float
    carboidratos: float
    gorduras: float

# --- FUNÇÕES UTILITÁRIAS ---
def hash_senha(senha: str) -> str:
    return hashlib.sha256(senha.encode()).hexdigest()

def remover_acentos(texto: str) -> str:
    if not texto:
        return ""
    nfkd = unicodedata.normalize('NFKD', str(texto))
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower().strip()

# --- INICIALIZAÇÃO DO BANCO DE DADOS ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                senha_hash TEXT NOT NULL,
                token TEXT UNIQUE,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metas_usuario (
                user_id INTEGER PRIMARY KEY,
                kcal INTEGER DEFAULT 2200,
                prot REAL DEFAULT 160.0,
                carb REAL DEFAULT 250.0,
                fat REAL DEFAULT 60.0,
                agua INTEGER DEFAULT 2500,
                FOREIGN KEY (user_id) REFERENCES usuarios(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS consumo_agua (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                quantidade REAL DEFAULT 0,
                UNIQUE(user_id, data),
                FOREIGN KEY (user_id) REFERENCES usuarios(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS diario_refeicoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                categoria TEXT NOT NULL,
                nome TEXT NOT NULL,
                marca TEXT,
                quantidade REAL NOT NULL,
                unidade_desc TEXT,
                calorias REAL NOT NULL,
                proteinas REAL NOT NULL,
                carboidratos REAL NOT NULL,
                gorduras REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES usuarios(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alimentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                marca TEXT,
                calorias REAL DEFAULT 0,
                proteinas REAL DEFAULT 0,
                carboidratos REAL DEFAULT 0,
                gorduras REAL DEFAULT 0,
                fonte TEXT DEFAULT 'TACO'
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_nome ON alimentos(nome);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_diario ON diario_refeicoes(user_id, data);")
        conn.commit()

init_db()

# --- AUTENTICAÇÃO E RECUPERAÇÃO ---
def obter_usuario_por_token(token: str) -> int:
    if not token:
        raise HTTPException(status_code=401, detail="Token não fornecido")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM usuarios WHERE token = ?", (token,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Sessão inválida ou expirada")
        return row[0]

@app.post("/api/auth/register")
def register(auth: AuthRequest):
    u = auth.username.strip().lower()
    if len(u) < 3 or len(auth.password) < 4:
        raise HTTPException(status_code=400, detail="Usuário deve ter min 3 letras e senha min 4 caracteres")
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM usuarios WHERE username = ?", (u,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Este nome de usuário já existe.")
        
        token = hashlib.sha256(f"{u}_{time.time()}".encode()).hexdigest()
        cursor.execute("INSERT INTO usuarios (username, senha_hash, token) VALUES (?, ?, ?)", 
                       (u, hash_senha(auth.password), token))
        user_id = cursor.lastrowid

        cursor.execute("INSERT INTO metas_usuario (user_id) VALUES (?)", (user_id,))
        conn.commit()

    return {"status": "ok", "token": token, "username": u}

@app.post("/api/auth/login")
def login(auth: AuthRequest):
    u = auth.username.strip().lower()
    h = hash_senha(auth.password)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM usuarios WHERE username = ? AND senha_hash = ?", (u, h))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="Usuário ou senha incorretos")
        
        token = hashlib.sha256(f"{u}_{time.time()}".encode()).hexdigest()
        cursor.execute("UPDATE usuarios SET token = ? WHERE id = ?", (token, row[0]))
        conn.commit()

    return {"status": "ok", "token": token, "username": u}

@app.post("/api/auth/reset-password")
def reset_password(req: ResetPasswordRequest):
    u = req.username.strip().lower()
    if req.chave_mestra.strip() != CHAVE_MESTRA_RECUPERACAO:
        raise HTTPException(status_code=403, detail="Chave mestra incorreta.")
    
    if len(req.nova_senha) < 4:
        raise HTTPException(status_code=400, detail="A nova senha deve ter no mínimo 4 caracteres.")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM usuarios WHERE username = ?", (u,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        
        novo_hash = hash_senha(req.nova_senha)
        token = hashlib.sha256(f"{u}_{time.time()}".encode()).hexdigest()
        cursor.execute("UPDATE usuarios SET senha_hash = ?, token = ? WHERE id = ?", (novo_hash, token, row[0]))
        conn.commit()

    return {"status": "ok", "token": token, "username": u, "mensagem": "Senha redefinida com sucesso!"}

# --- METAS & CONSUMO DO USUÁRIO ---
@app.get("/api/usuario/dados-completos")
def obter_dados_usuario(data: str = Query(...), authorization: Optional[str] = Header(None)):
    user_id = obter_usuario_por_token(authorization)
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT kcal, prot, carb, fat, agua FROM metas_usuario WHERE user_id = ?", (user_id,))
        metas = dict(cursor.fetchone() or {"kcal": 2200, "prot": 160, "carb": 250, "fat": 60, "agua": 2500})

        cursor.execute("SELECT quantidade FROM consumo_agua WHERE user_id = ? AND data = ?", (user_id, data))
        row_agua = cursor.fetchone()
        agua = row_agua["quantidade"] if row_agua else 0.0

        cursor.execute("""
            SELECT id, categoria, nome, marca, quantidade, unidade_desc, calorias, proteinas, carboidratos, gorduras 
            FROM diario_refeicoes 
            WHERE user_id = ? AND data = ?
        """, (user_id, data))
        
        diario = {}
        for r in cursor.fetchall():
            cat = r["categoria"]
            if cat not in diario:
                diario[cat] = []
            diario[cat].append({
                "id": r["id"],
                "nome": r["nome"],
                "marca": r["marca"],
                "quantidade": r["quantidade"],
                "unidadeDesc": r["unidade_desc"],
                "calorias": r["calorias"],
                "proteinas": r["proteinas"],
                "carboidratos": r["carboidratos"],
                "gorduras": r["gorduras"]
            })

    return {
        "metas": metas,
        "agua": agua,
        "diario": diario
    }

@app.post("/api/usuario/metas")
def salvar_metas(m: MetasModel, authorization: Optional[str] = Header(None)):
    user_id = obter_usuario_por_token(authorization)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO metas_usuario (user_id, kcal, prot, carb, fat, agua) 
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
            kcal=excluded.kcal, prot=excluded.prot, carb=excluded.carb, fat=excluded.fat, agua=excluded.agua
        """, (user_id, m.kcal, m.prot, m.carb, m.fat, m.agua))
        conn.commit()
    return {"status": "ok"}

@app.post("/api/usuario/agua")
def salvar_agua(a: AguaModel, authorization: Optional[str] = Header(None)):
    user_id = obter_usuario_por_token(authorization)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO consumo_agua (user_id, data, quantidade) 
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, data) DO UPDATE SET quantidade=excluded.quantidade
        """, (user_id, a.data, a.quantidade))
        conn.commit()
    return {"status": "ok"}

@app.post("/api/usuario/refeicao")
def adicionar_item_refeicao(item: RegistroRefeicaoModel, authorization: Optional[str] = Header(None)):
    user_id = obter_usuario_por_token(authorization)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO diario_refeicoes 
            (user_id, data, categoria, nome, marca, quantidade, unidade_desc, calorias, proteinas, carboidratos, gorduras)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, item.data, item.categoria, item.nome, item.marca, item.quantidade, item.unidade_desc, item.calorias, item.proteinas, item.carboidratos, item.gorduras))
        conn.commit()
        novo_id = cursor.lastrowid
    return {"status": "ok", "id": novo_id}

@app.delete("/api/usuario/refeicao/{item_id}")
def remover_item_refeicao(item_id: int, authorization: Optional[str] = Header(None)):
    user_id = obter_usuario_por_token(authorization)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM diario_refeicoes WHERE id = ? AND user_id = ?", (item_id, user_id))
        conn.commit()
    return {"status": "ok"}

# --- BUSCA DE ALIMENTOS & FATSECRET ---
async def obter_token_fatsecret():
    agora = time.time()
    if token_cache["access_token"] and token_cache["expires_at"] > agora:
        return token_cache["access_token"]

    auth_url = "https://oauth.fatsecret.com/connect/token"
    data = {"grant_type": "client_credentials", "scope": "basic"}

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.post(auth_url, data=data, auth=(FATSECRET_CLIENT_ID, FATSECRET_CLIENT_SECRET))
            if resp.status_code == 200:
                token_data = resp.json()
                token_cache["access_token"] = token_data.get("access_token")
                token_cache["expires_at"] = agora + float(token_data.get("expires_in", 86400)) - 60
                return token_cache["access_token"]
    except Exception as e:
        print(f"Erro token FatSecret: {e}")
    return None

@app.post("/api/alimentos")
def salvar_alimento_manual(item: AlimentoManual):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO alimentos (nome, marca, calorias, proteinas, carboidratos, gorduras, fonte)
            VALUES (?, ?, ?, ?, ?, ?, 'MANUAL')
        """, (item.nome.strip(), item.marca.strip(), round(item.calorias, 1), round(item.proteinas, 1), round(item.carboidratos, 1), round(item.gorduras, 1)))
        conn.commit()
    return {"status": "sucesso"}

@app.get("/api/alimentos")
async def buscar_alimentos(q: str = Query(..., min_length=2)):
    termo_limpo = remover_acentos(q)
    palavras_busca = termo_limpo.split()
    resultados_locais = []

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT nome, marca, calorias, proteinas, carboidratos, gorduras, fonte FROM alimentos")
        for r in cursor.fetchall():
            n_limpo = remover_acentos(r["nome"])
            m_limpo = remover_acentos(r["marca"] or "")
            if all(p in n_limpo or p in m_limpo for p in palavras_busca):
                resultados_locais.append(dict(r))

    if len(resultados_locais) >= 8:
        return {"origem": "taco_local", "total": len(resultados_locais), "itens": resultados_locais}

    token = await obter_token_fatsecret()
    novos_itens = []

    if token:
        try:
            fs_url = "https://platform.fatsecret.com/rest/foods/search/v1"
            headers = {"Authorization": f"Bearer {token}"}
            params = {
                "search_expression": termo_limpo,
                "format": "json",
                "max_results": 40,
                "region": "BR",
                "language": "pt"
            }
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(fs_url, headers=headers, params=params)
                if resp.status_code == 200:
                    fs_data = resp.json().get("foods", {}).get("food", [])
                    if isinstance(fs_data, dict):
                        fs_data = [fs_data]

                    with sqlite3.connect(DB_PATH) as conn:
                        cursor = conn.cursor()
                        for f in fs_data:
                            nome = f.get("food_name", "").strip()
                            marca = (f.get("brand_name") or "Genérico").strip()
                            desc = f.get("food_description", "")

                            kcal = prot = carb = fat = 0.0
                            for p in desc.split("-")[-1].split("|"):
                                p_str = p.lower()
                                if "calorias:" in p_str:
                                    kcal = float(''.join(c for c in p_str.split("calorias:")[1].replace("kcal","") if c.isdigit() or c == '.') or 0)
                                elif "gord:" in p_str:
                                    fat = float(''.join(c for c in p_str.split("gord:")[1].replace("g","") if c.isdigit() or c == '.') or 0)
                                elif "carb:" in p_str:
                                    carb = float(''.join(c for c in p_str.split("carb:")[1].replace("g","") if c.isdigit() or c == '.') or 0)
                                elif "prot:" in p_str:
                                    prot = float(''.join(c for c in p_str.split("prot:")[1].replace("g","") if c.isdigit() or c == '.') or 0)

                            if kcal > 0 or prot > 0 or carb > 0:
                                cursor.execute("SELECT id FROM alimentos WHERE LOWER(nome) = ? AND LOWER(marca) = ?", (nome.lower(), marca.lower()))
                                if not cursor.fetchone():
                                    cursor.execute("""
                                        INSERT INTO alimentos (nome, marca, calorias, proteinas, carboidratos, gorduras, fonte)
                                        VALUES (?, ?, ?, ?, ?, ?, 'FATSECRET')
                                    """, (nome, marca, round(kcal, 1), round(prot, 1), round(carb, 1), round(fat, 1)))
                                    conn.commit()

                                novos_itens.append({
                                    "nome": nome,
                                    "marca": marca,
                                    "calorias": round(kcal, 1),
                                    "proteinas": round(prot, 1),
                                    "carboidratos": round(carb, 1),
                                    "gorduras": round(fat, 1),
                                    "fonte": "FATSECRET"
                                })
        except Exception as e:
            print(f"Erro na busca FatSecret: {e}")

    nomes_vistos = set()
    resultado_final = []
    for item in resultados_locais + novos_itens:
        chave = (remover_acentos(item["nome"]), remover_acentos(item.get("marca", "")))
        if chave not in nomes_vistos:
            nomes_vistos.add(chave)
            resultado_final.append(item)

    return {"origem": "hibrido_taco_fatsecret", "total": len(resultado_final), "itens": resultado_final}
