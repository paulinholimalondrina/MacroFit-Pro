import sqlite3
import unicodedata
import os
import time
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(title="MacroFit Hybrid TACO + FatSecret API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "alimentos_cache.db"

# ==============================================================================
# CONFIGURAÇÃO DAS CHAVES FATSECRET INSERIDAS
# ==============================================================================
FATSECRET_CLIENT_ID = os.getenv("FATSECRET_CLIENT_ID", "fe6063cade4b4ca3ba6487f3d521c556")
FATSECRET_CLIENT_SECRET = os.getenv("FATSECRET_CLIENT_SECRET", "a4833d40ca15452392896fb1efa1bc64")

token_cache = {
    "access_token": None,
    "expires_at": 0
}

def remover_acentos(texto: str) -> str:
    if not texto:
        return ""
    nfkd = unicodedata.normalize('NFKD', str(texto))
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower().strip()

# ==============================================================================
# BASE TACO & ESSENCIAIS BRASILEIROS EMBUTIDOS
# ==============================================================================
BASE_TACO_EXPANDIDA = [
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

    # Grãos, Cereais e Leguminosas
    ("Arroz Branco Cozido", "Cereais / TACO", 128.0, 2.5, 28.1, 0.2),
    ("Arroz Integral Cozido", "Cereais / TACO", 124.0, 2.6, 25.8, 1.0),
    ("Feijão Carioca Cozido (50% Grão 50% Caldo)", "Leguminosas / TACO", 76.0, 4.8, 13.6, 0.5),
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

    # Laticínios e Derivados
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

    # Suplementos e Marcas Populares
    ("100% Whey Concentrate", "Growth Supplements", 400.0, 80.0, 9.0, 5.0),
    ("100% Whey Isolate", "Growth Supplements", 365.0, 90.0, 2.0, 0.5),
    ("Creatina Creapure 100% Pura", "Growth Supplements", 0.0, 0.0, 0.0, 0.0),
    ("Pasta de Amendoim Integral Torrado", "Growth Supplements", 588.0, 28.0, 18.0, 49.0),
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
        
        for nome, marca, kcal, prot, carb, fat in BASE_TACO_EXPANDIDA:
            cursor.execute("SELECT id FROM alimentos WHERE LOWER(nome) = ? AND LOWER(marca) = ?", (nome.lower(), marca.lower()))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO alimentos (nome, marca, calorias, proteinas, carboidratos, gorduras, fonte)
                    VALUES (?, ?, ?, ?, ?, ?, 'TACO_LOCAL')
                """, (nome, marca, kcal, prot, carb, fat))
        conn.commit()

init_db()

async def obter_token_fatsecret():
    """Gera ou reaproveita o token OAuth2 da FatSecret."""
    agora = time.time()
    if token_cache["access_token"] and token_cache["expires_at"] > agora:
        return token_cache["access_token"]

    auth_url = "https://oauth.fatsecret.com/connect/token"
    data = {
        "grant_type": "client_credentials",
        "scope": "basic"
    }

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.post(auth_url, data=data, auth=(FATSECRET_CLIENT_ID, FATSECRET_CLIENT_SECRET))
            if resp.status_code == 200:
                token_data = resp.json()
                token_cache["access_token"] = token_data.get("access_token")
                token_cache["expires_at"] = agora + float(token_data.get("expires_in", 86400)) - 60
                return token_cache["access_token"]
            else:
                print(f"Erro auth FatSecret: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Erro ao autenticar no FatSecret: {e}")
    return None

@app.get("/")
def home():
    return {"status": "ok", "mensagem": "MacroFit API Híbrida (TACO + FatSecret) Ativa"}

@app.get("/api/alimentos")
async def buscar_alimentos(q: str = Query(..., min_length=2, description="Nome do alimento ou marca")):
    termo_limpo = remover_acentos(q)
    palavras_busca = termo_limpo.split()
    resultados_locais = []

    # 1. Busca primeiro em toda a base TACO / Cache Local (Instantânea, sem acento)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT nome, marca, calorias, proteinas, carboidratos, gorduras, fonte FROM alimentos")
            todos = cursor.fetchall()

            for r in todos:
                n_limpo = remover_acentos(r["nome"])
                m_limpo = remover_acentos(r["marca"] or "")
                if all(p in n_limpo or p in m_limpo for p in palavras_busca):
                    resultados_locais.append(dict(r))
    except Exception as e:
        print(f"Erro na consulta local: {e}")

    # Se já tem 8 ou mais itens locais, retorna de imediato
    if len(resultados_locais) >= 8:
        return {"origem": "taco_local", "total": len(resultados_locais), "itens": resultados_locais}

    # 2. Consulta à API FatSecret Brasil
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

                            # Extração dos macronutrientes da descrição retornada
                            kcal = prot = carb = fat = 0.0
                            partes = desc.split("-")[-1].split("|")
                            for p in partes:
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

    # Mescla base TACO local com as novidades da FatSecret
    nomes_vistos = set()
    resultado_final = []
    for item in resultados_locais + novos_itens:
        chave = (remover_acentos(item["nome"]), remover_acentos(item.get("marca", "")))
        if chave not in nomes_vistos:
            nomes_vistos.add(chave)
            resultado_final.append(item)

    return {"origem": "hibrido_taco_fatsecret", "total": len(resultado_final), "itens": resultado_final}
