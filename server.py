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

# Base inicial com suplementos e itens clássicos do mercado brasileiro
ALIMENTOS_BASE_BR = [
    # Suplementos Growth, Max, Probiótica
    ("100% Whey Concentrate", "Growth Supplements", 400.0, 80.0, 9.0, 5.0),
    ("100% Whey Isolate", "Growth Supplements", 365.0, 90.0, 2.0, 0.5),
    ("Creatina Monohidratada 100% Pura", "Growth Supplements", 0.0, 0.0, 0.0, 0.0),
    ("100% Whey Gold Standard", "Optimum Nutrition", 398.0, 78.0, 8.0, 4.0),
    ("100% Pure Whey", "Probiótica", 405.0, 76.0, 10.0, 6.0),
    ("100% Whey", "Max Titanium", 400.0, 75.0, 11.0, 5.5),
    ("Pasta de Amendoim Integral", "Growth Supplements", 588.0, 28.0, 18.0, 49.0),
    ("Pasta de Amendoim Dr. Peanut", "Dr. Peanut", 560.0, 22.0, 28.0, 44.0),
    # Leites e Laticínios Comuns no Brasil
    ("Leite Integral", "Piracanjuba", 61.0, 3.1, 4.7, 3.2),
    ("Leite Desnatado", "Piracanjuba", 35.0, 3.2, 4.9, 0.0),
    ("Leite Semidesnatado", "Piracanjuba", 46.0, 3.1, 4.8, 1.5),
    ("Leite Integral", "Itambé", 60.0, 3.0, 4.5, 3.2),
    ("Leite Desnatado", "Itambé", 34.0, 3.1, 4.8, 0.0),
    ("Leite Semidesnatado", "Itambé", 45.0, 3.1, 4.7, 1.5),
    ("Leite Integral UHT", "Líder", 60.0, 3.0, 4.6, 3.2),
    ("Leite Desnatado UHT", "Líder", 35.0, 3.1, 4.9, 0.0),
    ("Leite em Pó Integral Ninho", "Nestlé", 497.0, 25.0, 39.0, 27.0),
    ("Leite em Pó Desnatado Molico", "Nestlé", 350.0, 34.0, 52.0, 0.5),
    ("Iogurte Natural Desnatado", "Nestlé", 42.0, 4.5, 5.8, 0.3),
    ("Queijo Minas Frescal", "Típico", 264.0, 17.4, 3.2, 20.2),
    ("Queijo Mussarela Fatiado", "Típico", 330.0, 22.0, 2.0, 26.0),
    ("Requeijão Cremoso Light", "Danone / Poços de Caldas", 160.0, 8.0, 4.0, 12.0),
    # Comidas e Carnes Básicas do Dia a Dia
    ("Peito de Frango Grelhado", "Preparo Caseiro", 159.0, 32.0, 0.0, 2.5),
    ("Carne Moída Patinho Grelhado", "Preparo Caseiro", 219.0, 35.9, 0.0, 7.3),
    ("Arroz Branco Cozido", "Preparo Caseiro", 128.0, 2.5, 28.1, 0.2),
    ("Feijão Carioca Cozido", "Preparo Caseiro", 76.0, 4.8, 13.6, 0.5),
    ("Ovo Inteiro Cozido", "Preparo Caseiro", 146.0, 13.3, 0.6, 9.5),
    ("Clara de Ovo Cozida", "Preparo Caseiro", 52.0, 11.0, 0.7, 0.2),
    ("Banana Prata Crua", "Fruta", 98.0, 1.3, 26.0, 0.1),
    ("Maçã Fuji", "Fruta", 56.0, 0.3, 15.2, 0.2),
    ("Aveia em Flocos Finos", "Quaker", 394.0, 13.9, 66.6, 8.5),
    ("Nescau 2.0 Achocolatado em Pó", "Nestlé", 380.0, 3.5, 85.0, 2.8)
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
                fonte TEXT DEFAULT 'CACHE'
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_nome ON alimentos(nome);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_marca ON alimentos(marca);")

        # Popula o banco com os itens iniciais sem duplicar
        for nome, marca, kcal, prot, carb, fat in ALIMENTOS_BASE_BR:
            cursor.execute("SELECT id FROM alimentos WHERE LOWER(nome) = ? AND LOWER(marca) = ?", (nome.lower(), marca.lower()))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO alimentos (nome, marca, calorias, proteinas, carboidratos, gorduras, fonte)
                    VALUES (?, ?, ?, ?, ?, ?, 'BASE_NACIONAL')
                """, (nome, marca, kcal, prot, carb, fat))
        conn.commit()

init_db()

@app.get("/")
def home():
    return {"status": "ok", "mensagem": "MacroFit API Brasil ativa"}

@app.get("/api/alimentos")
async def buscar_alimentos(q: str = Query(..., min_length=2, description="Nome do produto ou marca")):
    termo = q.strip().lower()
    palavras = termo.split()
    resultados_cache = []

    # 1. Busca flexível no SQLite local por nome OU marca (contendo as palavras digitadas)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Monta a query para casar todas as palavras digitadas em qualquer ordem
        filtros = " AND ".join(["(LOWER(nome) LIKE ? OR LOWER(marca) LIKE ?)"] * len(palavras))
        parametros = []
        for p in palavras:
            parametros.extend([f"%{p}%", f"%{p}%"])

        cursor.execute(f"""
            SELECT nome, marca, calorias, proteinas, carboidratos, gorduras, fonte 
            FROM alimentos 
            WHERE {filtros}
            ORDER BY id ASC
            LIMIT 30
        """, parametros)

        for r in cursor.fetchall():
            resultados_cache.append(dict(r))

    # Se encontrar 5 ou mais opções no banco local, retorna imediatamente
    if len(resultados_cache) >= 5:
        return {"origem": "local_cache", "total": len(resultados_cache), "itens": resultados_cache}

    # 2. Busca na API do Open Food Facts focada no mercado brasileiro (tag brasil)
    headers = {
        "User-Agent": "MacroFitPro/1.0 (suporte@macrofit.local)"
    }

    url = (
        f"https://br.openfoodfacts.org/cgi/search.pl"
        f"?search_terms={termo}&search_simple=1&action=process&json=1"
        f"&page_size=50"
        f"&tagtype_0=countries&tag_contains_0=contains&tag_0=brazil"
        f"&fields=product_name,product_name_pt,brands,nutriments"
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
                        nome = p.get("product_name_pt") or p.get("product_name")
                        if not nome or len(nome.strip()) < 3:
                            continue

                        marca = p.get("brands") or "Genérico"
                        nutri = p.get("nutriments", {})

                        kcal = float(
                            nutri.get("energy-kcal_100g") or 
                            nutri.get("energy-kcal_value") or 
                            nutri.get("energy-kcal") or 0
                        )
                        prot = float(nutri.get("proteins_100g") or nutri.get("proteins_value") or 0)
                        carb = float(nutri.get("carbohydrates_100g") or nutri.get("carbohydrates_value") or 0)
                        fat = float(nutri.get("fat_100g") or nutri.get("fat_value") or 0)

                        if kcal == 0 and prot == 0 and carb == 0 and fat == 0:
                            continue

                        cursor.execute("SELECT id FROM alimentos WHERE LOWER(nome) = ?", (nome.strip().lower(),))
                        if not cursor.fetchone():
                            cursor.execute("""
                                INSERT INTO alimentos (nome, marca, calorias, proteinas, carboidratos, gorduras, fonte)
                                VALUES (?, ?, ?, ?, ?, ?, 'OPEN_FOOD_FACTS_BR')
                            """, (nome.strip(), marca.strip(), round(kcal, 1), round(prot, 1), round(carb, 1), round(fat, 1)))
                            conn.commit()

                        novos_itens.append({
                            "nome": nome.strip(),
                            "marca": marca.strip(),
                            "calorias": round(kcal, 1),
                            "proteinas": round(prot, 1),
                            "carboidratos": round(carb, 1),
                            "gorduras": round(fat, 1),
                            "fonte": "OPEN_FOOD_FACTS_BR"
                        })
    except Exception as e:
        print(f"Erro ao buscar na API externa: {e}")

    # Prioriza resultados onde o termo está no início ou no nome exato
    todos = resultados_cache + novos_itens
    return {"origem": "hibrido", "total": len(todos), "itens": todos}
