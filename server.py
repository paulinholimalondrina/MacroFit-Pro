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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_marca ON alimentos(marca);")
        conn.commit()

init_db()

@app.get("/")
def home():
    return {"status": "ok", "mensagem": "MacroFit API ativa"}

@app.get("/api/alimentos")
async def buscar_alimentos(q: str = Query(..., min_length=2, description="Nome do produto ou marca")):
    termo = q.strip().lower()
    palavras = termo.split()
    resultados_cache = []

    # 1. Procura primeiro no banco local SQLite
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        filtros = " AND ".join(["(LOWER(nome) LIKE ? OR LOWER(marca) LIKE ?)"] * len(palavras))
        parametros = []
        for p in palavras:
            parametros.extend([f"%{p}%", f"%{p}%"])

        cursor.execute(f"""
            SELECT nome, marca, calorias, proteinas, carboidratos, gorduras, fonte 
            FROM alimentos 
            WHERE {filtros}
            LIMIT 50
        """, parametros)

        for r in cursor.fetchall():
            resultados_cache.append(dict(r))

    # Se já tem um catálogo razoável no cache para esse termo, entrega na hora
    if len(resultados_cache) >= 12:
        return {"origem": "local_cache", "total": len(resultados_cache), "itens": resultados_cache}

    # 2. Busca externa otimizada no Open Food Facts
    headers = {
        "User-Agent": "MacroFitProApp/2.0 (contato@macrofit.com.br)"
    }

    # Endpoint moderno com busca por texto livre em produtos do Brasil
    url = (
        f"https://world.openfoodfacts.org/cgi/search.pl"
        f"?search_terms={termo}"
        f"&search_simple=1"
        f"&action=process"
        f"&json=1"
        f"&page_size=60"
        f"&fields=product_name,product_name_pt,brands,nutriments"
    )

    novos_itens = []
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                produtos = data.get("products", [])

                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.cursor()
                    for p in produtos:
                        nome = p.get("product_name_pt") or p.get("product_name")
                        if not nome or len(nome.strip()) < 2:
                            continue

                        marca = p.get("brands") or "Genérico"
                        nutri = p.get("nutriments", {})

                        # Tenta coletar calorias e macronutrientes por 100g/ml
                        kcal = float(
                            nutri.get("energy-kcal_100g") or 
                            nutri.get("energy-kcal_value") or 
                            nutri.get("energy-kcal") or 0
                        )
                        prot = float(nutri.get("proteins_100g") or nutri.get("proteins_value") or 0)
                        carb = float(nutri.get("carbohydrates_100g") or nutri.get("carbohydrates_value") or 0)
                        fat = float(nutri.get("fat_100g") or nutri.get("fat_value") or 0)

                        # Se todos os macros forem 0 e não for água, ignora
                        if kcal == 0 and prot == 0 and carb == 0 and fat == 0 and "agua" not in nome.lower():
                            continue

                        # Salva no cache para nunca mais precisar buscar na rede
                        cursor.execute("SELECT id FROM alimentos WHERE LOWER(nome) = ? AND LOWER(marca) = ?", (nome.strip().lower(), marca.strip().lower()))
                        if not cursor.fetchone():
                            cursor.execute("""
                                INSERT INTO alimentos (nome, marca, calorias, proteinas, carboidratos, gorduras, fonte)
                                VALUES (?, ?, ?, ?, ?, ?, 'ONLINE')
                            """, (nome.strip(), marca.strip(), round(kcal, 1), round(prot, 1), round(carb, 1), round(fat, 1)))
                            conn.commit()

                        novos_itens.append({
                            "nome": nome.strip(),
                            "marca": marca.strip(),
                            "calorias": round(kcal, 1),
                            "proteinas": round(prot, 1),
                            "carboidratos": round(carb, 1),
                            "gorduras": round(fat, 1),
                            "fonte": "ONLINE"
                        })
    except Exception as e:
        print(f"Aviso na busca externa: {e}")

    # Mescla os locais com os novos encontrados (sem duplicar nomes idênticos)
    nomes_vistos = set()
    lista_final = []
    for item in resultados_cache + novos_itens:
        chave = (item["nome"].lower(), item["marca"].lower())
        if chave not in nomes_vistos:
            nomes_vistos.add(chave)
            lista_final.append(item)

    return {"origem": "hibrido", "total": len(lista_final), "itens": lista_final}
