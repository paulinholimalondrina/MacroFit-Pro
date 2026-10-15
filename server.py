import sqlite3
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(title="MacroFit Proxy & Cache API")

# Permite que a calculadora no navegador comunique com a API sem bloqueios de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "alimentos_cache.db"

def init_db():
    """Cria a tabela SQLite local para guardar o cache dos alimentos."""
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
                fonte TEXT DEFAULT 'CACHE'
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_nome ON alimentos(nome);")
        conn.commit()

init_db()

@app.get("/")
def home():
    """Rota para verificar se a API está online."""
    return {"status": "ok", "mensagem": "MacroFit API está online e pronta!"}

@app.get("/api/alimentos")
async def buscar_alimentos(q: str = Query(..., min_length=2, description="Nome do alimento")):
    termo = q.strip().lower()
    resultados = []

    # 1. Procura primeiro no cache local SQLite
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT nome, marca, calorias, proteinas, carboidratos, gorduras, fonte 
            FROM alimentos 
            WHERE LOWER(nome) LIKE ? 
            LIMIT 15
        """, (f"%{termo}%",))
        rows = cursor.fetchall()
        for r in rows:
            resultados.append(dict(r))

    # Se já encontrou pelo menos 3 itens locais, devolve logo
    if len(resultados) >= 3:
        return {"origem": "local_cache", "total": len(resultados), "itens": resultados}

    # 2. Se não encontrou o suficiente, pesquisa na API externa enviando o User-Agent oficial
    headers = {
        "User-Agent": "MacroFitPro/1.0 (suporte@macrofit.local)"
    }
    url = (
        f"https://br.openfoodfacts.org/cgi/search.pl"
        f"?search_terms={termo}&search_simple=1&action=process&json=1&page_size=12"
        f"&fields=product_name,brands,nutriments"
    )

    novos_itens = []
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                produtos = data.get("products", [])

                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.cursor()
                    for p in produtos:
                        nome = p.get("product_name")
                        if not nome:
                            continue

                        marca = p.get("brands", "Genérico") or "Genérico"
                        nutri = p.get("nutriments", {})

                        # Extrai energia e macronutrientes por 100g/100ml
                        kcal = float(nutri.get("energy-kcal_100g") or nutri.get("energy-kcal") or 0)
                        prot = float(nutri.get("proteins_100g") or 0)
                        carb = float(nutri.get("carbohydrates_100g") or 0)
                        fat = float(nutri.get("fat_100g") or 0)

                        cursor.execute("SELECT id FROM alimentos WHERE LOWER(nome) = ?", (nome.lower(),))
                        if not cursor.fetchone():
                            cursor.execute("""
                                INSERT INTO alimentos (nome, marca, calorias, proteinas, carboidratos, gorduras, fonte)
                                VALUES (?, ?, ?, ?, ?, ?, 'OPEN_FOOD_FACTS')
                            """, (nome, marca, kcal, prot, carb, fat))
                            conn.commit()

                        novos_itens.append({
                            "nome": nome,
                            "marca": marca,
                            "calorias": kcal,
                            "proteinas": prot,
                            "carboidratos": carb,
                            "gorduras": fat,
                            "fonte": "OPEN_FOOD_FACTS"
                        })
    except Exception as e:
        print(f"Erro ao consultar API externa: {e}")

    todos = resultados + novos_itens
    return {"origem": "hibrido", "total": len(todos), "itens": todos}