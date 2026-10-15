import sqlite3
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(title="MacroFit Proxy & Cache API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "alimentos_cache.db"

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
                fonte TEXT DEFAULT 'CACHE'
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_nome ON alimentos(nome);")
        conn.commit()

init_db()

@app.get("/")
def home():
    return {"status": "ok", "mensagem": "MacroFit API está online e pronta!"}

@app.get("/api/alimentos")
async def buscar_alimentos(q: str = Query(..., min_length=2, description="Nome do alimento")):
    termo = q.strip().lower()
    resultados_cache = []

    # 1. Procura primeiro no SQLite local
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT nome, marca, calorias, proteinas, carboidratos, gorduras, fonte 
            FROM alimentos 
            WHERE LOWER(nome) LIKE ? 
            LIMIT 40
        """, (f"%{termo}%",))
        for r in cursor.fetchall():
            resultados_cache.append(dict(r))

    # Se já tiver mais de 8 opções guardadas no cache, devolve imediatamente
    if len(resultados_cache) >= 8:
        return {"origem": "local_cache", "total": len(resultados_cache), "itens": resultados_cache}

    # 2. Pesquisa ampla na API v2 com ordenação por popularidade
    headers = {
        "User-Agent": "MacroFitPro/1.0 (suporte@macrofit.local)"
    }
    
    # Endpoint v2 mais completo, trazendo até 50 produtos com tags do Brasil / Português
    url = (
        f"https://world.openfoodfacts.org/api/v2/search"
        f"?categories_tags_en={termo}"
        f"&fields=product_name,product_name_pt,brands,nutriments"
        f"&page_size=50"
        f"&sort_by=unique_scans_n"
    )

    novos_itens = []
    try:
        async with httpx.AsyncClient(timeout=7.0) as client:
            resp = await client.get(
                f"https://world.openfoodfacts.org/cgi/search.pl?search_terms={termo}&search_simple=1&action=process&json=1&page_size=40&fields=product_name,product_name_pt,brands,nutriments",
                headers=headers
            )
            
            if resp.status_code == 200:
                data = resp.json()
                produtos = data.get("products", [])

                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.cursor()
                    for p in produtos:
                        nome = p.get("product_name_pt") or p.get("product_name")
                        if not nome or len(nome.strip()) < 3:
                            continue

                        marca = p.get("brands") or "Genérico"
                        nutri = p.get("nutriments", {})

                        # Procura valores energéticos em diferentes chaves possíveis
                        kcal = float(
                            nutri.get("energy-kcal_100g") or 
                            nutri.get("energy-kcal_value") or 
                            nutri.get("energy-kcal") or 
                            0
                        )
                        prot = float(nutri.get("proteins_100g") or nutri.get("proteins_value") or 0)
                        carb = float(nutri.get("carbohydrates_100g") or nutri.get("carbohydrates_value") or 0)
                        fat = float(nutri.get("fat_100g") or nutri.get("fat_value") or 0)

                        # Ignora itens com dados nutricionais totalmente vazios
                        if kcal == 0 and prot == 0 and carb == 0 and fat == 0:
                            continue

                        # Guarda no cache SQLite para pesquisas futuras ficarem instantâneas
                        cursor.execute("SELECT id FROM alimentos WHERE LOWER(nome) = ?", (nome.strip().lower(),))
                        if not cursor.fetchone():
                            cursor.execute("""
                                INSERT INTO alimentos (nome, marca, calorias, proteinas, carboidratos, gorduras, fonte)
                                VALUES (?, ?, ?, ?, ?, ?, 'OPEN_FOOD_FACTS')
                            """, (nome.strip(), marca.strip(), kcal, prot, carb, fat))
                            conn.commit()

                        novos_itens.append({
                            "nome": nome.strip(),
                            "marca": marca.strip(),
                            "calorias": round(kcal, 1),
                            "proteinas": round(prot, 1),
                            "carboidratos": round(carb, 1),
                            "gorduras": round(fat, 1),
                            "fonte": "OPEN_FOOD_FACTS"
                        })
    except Exception as e:
        print(f"Erro na consulta externa: {e}")

    # Junta o que já estava em cache com os novos dados
    todos = resultados_cache + novos_itens
    return {"origem": "hibrido", "total": len(todos), "itens": todos}
