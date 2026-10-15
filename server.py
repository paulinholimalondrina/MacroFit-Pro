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
# CONFIGURAÇÕES E CHAVES
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
    genero: Optional[str] = "m"
    idade: Optional[float] = 30.0
    peso: Optional[float] = 75.0
    altura: Optional[float] = 175.0
    atividade: Optional[float] = 1.55
    objetivo: Optional[float] = 0.0

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

def hash_senha(senha: str) -> str:
    return hashlib.sha256(senha.encode()).hexdigest()

def remover_acentos(texto: str) -> str:
    if not texto:
        return ""
    nfkd = unicodedata.normalize('NFKD', str(texto))
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower().strip()

# ==============================================================================
# BASE DE ALIMENTOS COMPLETA (TACO & MARCAS POPULARES)
# ==============================================================================
BASE_TACO_EXPANDIDA = [
    # Cereais e Grãos
    ("Arroz Branco Cozido", "Cereais / TACO", 128.0, 2.5, 28.1, 0.2),
    ("Arroz Integral Cozido", "Cereais / TACO", 124.0, 2.6, 25.8, 1.0),
    ("Feijão Carioca Cozido", "Leguminosas / TACO", 76.0, 4.8, 13.6, 0.5),
    ("Feijão Preto Cozido", "Leguminosas / TACO", 77.0, 4.5, 14.0, 0.5),
    ("Lentilha Cozida", "Leguminosas / TACO", 93.0, 6.3, 16.3, 0.5),
    ("Grão de Bico Cozido", "Leguminosas / TACO", 140.0, 8.4, 23.2, 2.1),
    ("Aveia em Flocos Finos", "Quaker / TACO", 394.0, 13.9, 66.6, 8.5),
    ("Farinha de Aveia", "Genérico", 380.0, 14.0, 65.0, 7.5),
    ("Pão de Forma Tradicional", "Panificação / TACO", 265.0, 8.0, 50.0, 3.2),
    ("Pão de Forma Integral", "Panificação / TACO", 247.0, 9.4, 46.0, 3.7),
    ("Pão Francês Tradicional", "Padaria / TACO", 300.0, 8.0, 58.7, 3.1),
    ("Goma de Tapioca Hidratada", "Típico", 240.0, 0.1, 60.0, 0.0),
    ("Macarrão de Sêmola Cozido", "Massas / TACO", 140.0, 4.6, 28.8, 0.5),

    # Carnes, Aves, Peixes e Ovos
    ("Peito de Frango Grelhado", "Aves / TACO", 159.0, 32.0, 0.0, 2.5),
    ("Peito de Frango Cozido Desfiado", "Aves / TACO", 163.0, 31.5, 0.0, 3.2),
    ("Sobrecoxa de Frango sem Pele Grelhada", "Aves / TACO", 167.0, 28.8, 0.0, 5.0),
    ("Carne Bovina Patinho Grelhado", "Carnes / TACO", 219.0, 35.9, 0.0, 7.3),
    ("Carne Bovina Alcatra Grelhada", "Carnes / TACO", 241.0, 31.9, 0.0, 11.6),
    ("Carne Moída Patinho Refogada", "Preparo Caseiro", 225.0, 32.0, 0.0, 10.0),
    ("Carne Bovina Músculo Cozido", "Carnes / TACO", 194.0, 31.2, 0.0, 6.7),
    ("Carne Bovina Filé Mignon Grelhado", "Carnes / TACO", 220.0, 32.8, 0.0, 8.8),
    ("Lombo Suíno Assado", "Carnes / TACO", 210.0, 35.7, 0.0, 6.4),
    ("Tilápia Filé Grelhado", "Pescados / TACO", 128.0, 26.0, 0.0, 2.6),
    ("Salmão Filé Grelhado", "Pescados / TACO", 229.0, 23.9, 0.0, 14.0),
    ("Atum em Pedaços em Água", "Conservas", 116.0, 26.0, 0.0, 0.8),
    ("Ovo de Galinha Inteiro Cozido", "Ovos / TACO", 146.0, 13.3, 0.6, 9.5),
    ("Clara de Ovo Cozida", "Ovos / TACO", 52.0, 11.0, 0.7, 0.2),
    ("Ovo de Galinha Frito", "Preparo Caseiro", 240.0, 15.6, 1.2, 18.6),

    # Vegetais, Legumes e Frutas
    ("Brócolis Cozido", "Hortifrúti / TACO", 25.0, 2.1, 4.4, 0.5),
    ("Brócolis Cru", "Hortifrúti / TACO", 25.0, 3.6, 4.0, 0.3),
    ("Couve-Flor Cozida", "Hortifrúti / TACO", 19.0, 1.2, 3.9, 0.2),
    ("Espinafre Cozido", "Hortifrúti / TACO", 16.0, 2.7, 1.4, 0.2),
    ("Alface Crespa Crua", "Hortifrúti / TACO", 11.0, 1.3, 1.7, 0.2),
    ("Tomate Cru com Semente", "Hortifrúti / TACO", 15.0, 1.1, 3.1, 0.2),
    ("Cenoura Cozida", "Hortifrúti / TACO", 30.0, 0.8, 6.7, 0.2),
    ("Cenoura Crua", "Hortifrúti / TACO", 34.0, 1.3, 7.7, 0.2),
    ("Abobrinha Cozida", "Hortifrúti / TACO", 15.0, 1.1, 3.0, 0.2),
    ("Batata Doce Cozida", "Hortifrúti / TACO", 77.0, 0.6, 18.4, 0.1),
    ("Batata Inglesa Cozida", "Hortifrúti / TACO", 52.0, 1.2, 11.9, 0.1),
    ("Mandioca / Aipim Cozido", "Hortifrúti / TACO", 125.0, 0.6, 30.1, 0.3),
    ("Banana Prata Crua", "Fruta / TACO", 98.0, 1.3, 26.0, 0.1),
    ("Banana Nanica Crua", "Fruta / TACO", 92.0, 1.4, 23.8, 0.1),
    ("Maçã Fuji com Casca", "Fruta / TACO", 56.0, 0.3, 15.2, 0.2),
    ("Mamão Papaya Cru", "Fruta / TACO", 40.0, 0.5, 10.4, 0.1),
    ("Abacate Cru", "Fruta / TACO", 96.0, 1.2, 6.0, 8.4),
    ("Laranja Pera Crua", "Fruta / TACO", 37.0, 1.0, 8.9, 0.1),
    ("Melancia Crua", "Fruta / TACO", 33.0, 0.9, 8.1, 0.0),
    ("Manga Tommy Crua", "Fruta / TACO", 51.0, 0.5, 12.8, 0.2),
    ("Uva Niágara Crua", "Fruta / TACO", 53.0, 0.7, 13.6, 0.2),

    # Laticínios
    ("Leite Integral UHT", "Piracanjuba", 61.0, 3.1, 4.7, 3.2),
    ("Leite Desnatado UHT", "Piracanjuba", 35.0, 3.2, 4.9, 0.0),
    ("Leite Semidesnatado UHT", "Piracanjuba", 46.0, 3.1, 4.8, 1.5),
    ("Leite Integral UHT", "Itambé", 60.0, 3.0, 4.5, 3.2),
    ("Leite Desnatado UHT", "Itambé", 34.0, 3.1, 4.8, 0.0),
    ("Leite Integral", "Batavo", 60.0, 3.0, 4.5, 3.2),
    ("Leite Desnatado", "Batavo", 35.0, 3.1, 4.9, 0.0),
    ("Iogurte Grego Tradicional", "Vigor", 130.0, 4.8, 14.0, 6.2),
    ("Iogurte Grego Zero Gordura", "Vigor", 65.0, 7.0, 9.0, 0.0),
    ("Requeijão Tradicional", "Vigor", 257.0, 9.6, 3.0, 23.0),
    ("Requeijão Light", "Vigor", 170.0, 11.0, 3.5, 12.0),
    ("Queijo Minas Frescal", "Laticínios / TACO", 264.0, 17.4, 3.2, 20.2),
    ("Queijo Mussarela Fatiado", "Laticínios / TACO", 330.0, 22.0, 2.0, 26.0),
    ("Queijo Prato Fatiado", "Laticínios / TACO", 360.0, 23.0, 1.5, 29.0),
    ("Queijo Cottage Tradicional", "Laticínios", 98.0, 11.0, 3.4, 4.3),
    ("Iogurte Natural Desnatado", "Nestlé", 42.0, 4.5, 5.8, 0.3),
    ("Iogurte Natural Integral", "Nestlé", 66.0, 3.8, 4.8, 3.6),
    ("Leite em Pó Integral Ninho", "Nestlé", 497.0, 25.0, 39.0, 27.0),
    ("Leite em Pó Desnatado Molico", "Nestlé", 350.0, 34.0, 52.0, 0.5),

    # Suplementos
    ("100% Whey Concentrate", "Growth Supplements", 400.0, 80.0, 9.0, 5.0),
    ("100% Whey Isolate", "Growth Supplements", 365.0, 90.0, 2.0, 0.5),
    ("Creatina Creapure 100% Pura", "Growth Supplements", 0.0, 0.0, 0.0, 0.0),
    ("Pasta de Amendoim Integral", "Growth Supplements", 588.0, 28.0, 18.0, 49.0),
    ("100% Pure Whey", "Probiótica", 405.0, 76.0, 10.0, 6.0),
    ("100% Whey Refil", "Max Titanium", 400.0, 75.0, 11.0, 5.5),
    ("100% Whey Gold Standard", "Optimum Nutrition", 398.0, 78.0, 8.0, 4.0),
    ("Nescau 2.0 Achocolatado em Pó", "Nestlé", 380.0, 3.5, 85.0, 2.8),
    ("Toddy Original Achocolatado", "PepsiCo", 400.0, 2.0, 90.0, 2.5),
    ("Azeite de Oliva Extra Virgem", "Gorduras / TACO", 884.0, 0.0, 0.0, 100.0)
]

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
                genero TEXT DEFAULT 'm',
                idade REAL DEFAULT 30.0,
                peso REAL DEFAULT 75.0,
                altura REAL DEFAULT 175.0,
                atividade REAL DEFAULT 1.55,
                objetivo REAL DEFAULT 0.0,
                FOREIGN KEY (user_id) REFERENCES usuarios(id)
            )
        """)

        # Migração transparente: adiciona as colunas novas sem recriar tabela nem apagar dados
        cursor.execute("PRAGMA table_info(metas_usuario)")
        colunas_existentes = [col[1] for col in cursor.fetchall()]
        novas_colunas = [
            ("genero", "TEXT DEFAULT 'm'"),
            ("idade", "REAL DEFAULT 30.0"),
            ("peso", "REAL DEFAULT 75.0"),
            ("altura", "REAL DEFAULT 175.0"),
            ("atividade", "REAL DEFAULT 1.55"),
            ("objetivo", "REAL DEFAULT 0.0")
        ]
        for nome_col, tipo_col in novas_colunas:
            if nome_col not in colunas_existentes:
                cursor.execute(f"ALTER TABLE metas_usuario ADD COLUMN {nome_col} {tipo_col}")

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

        for nome, marca, kcal, prot, carb, fat in BASE_TACO_EXPANDIDA:
            cursor.execute("SELECT id FROM alimentos WHERE LOWER(nome) = ? AND LOWER(marca) = ?", (nome.lower(), marca.lower()))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO alimentos (nome, marca, calorias, proteinas, carboidratos, gorduras, fonte)
                    VALUES (?, ?, ?, ?, ?, ?, 'TACO_LOCAL')
                """, (nome, marca, kcal, prot, carb, fat))
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

        cursor.execute("""
            SELECT kcal, prot, carb, fat, agua, genero, idade, peso, altura, atividade, objetivo 
            FROM metas_usuario 
            WHERE user_id = ?
        """, (user_id,))
        metas_row = cursor.fetchone()
        metas = dict(metas_row) if metas_row else {
            "kcal": 2200, "prot": 160.0, "carb": 250.0, "fat": 60.0, "agua": 2500,
            "genero": "m", "idade": 30.0, "peso": 75.0, "altura": 175.0, "atividade": 1.55, "objetivo": 0.0
        }

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
            INSERT INTO metas_usuario (user_id, kcal, prot, carb, fat, agua, genero, idade, peso, altura, atividade, objetivo) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
            kcal=excluded.kcal, prot=excluded.prot, carb=excluded.carb, fat=excluded.fat, agua=excluded.agua,
            genero=excluded.genero, idade=excluded.idade, peso=excluded.peso, altura=excluded.altura,
            atividade=excluded.atividade, objetivo=excluded.objetivo
        """, (user_id, m.kcal, m.prot, m.carb, m.fat, m.agua, m.genero, m.idade, m.peso, m.altura, m.atividade, m.objetivo))
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

    if len(resultados_locais) >= 6:
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
