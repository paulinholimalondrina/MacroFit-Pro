import sqlite3
import unicodedata
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

def remover_acentos(texto: str) -> str:
    if not texto:
        return ""
    nfkd = unicodedata.normalize('NFKD', str(texto))
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower().strip()

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
    return {"status": "ok", "mensagem": "MacroFit API Brasil ativa"}

@app.get("/api/alimentos")
async def buscar_alimentos(q: str = Query(..., min_length=2, description="Nome do produto ou marca")):
    termo_limpo = remover_acentos(q)
    palavras_busca = termo_limpo.split()
    resultados_cache = []

    # 1. Procura no banco SQLite local tratando acentos em memória
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT nome, marca, calorias, proteinas, carboidratos, gorduras, fonte FROM alimentos LIMIT 300")
            todos_locais = cursor.fetchall()
            
            for r in todos_locais:
                n_limpo = remover_acentos(r["nome"])
                m_limpo = remover_acentos(r["marca"] or "")
                
                # Confere se todas as palavras digitadas batem no nome ou na marca
                if all(p in n_limpo or p in m_limpo for p in palavras_busca):
                    resultados_cache.append(dict(r))
    except Exception as e:
        print(f"Aviso no banco local: {e}")

    # Se já tiver um volume bom no cache local, retorna direto
    if len(resultados_cache) >= 10:
        return {"origem": "local_cache", "total": len(resultados_cache), "itens": resultados_cache}

    # 2. Busca externa na API do Open Food Facts
    headers = {
        "User-Agent": "MacroFitProApp/3.0 (contato@macrofit.com.br)"
    }

    url = (
        f"https://world.openfoodfacts.org/cgi/search.pl"
        f"?search_terms={termo_limpo}"
        f"&search_simple=1"
        f"&action=process"
        f"&json=1"
        f"&page_size=60"
        f"&fields=product_name,product_name_pt,brands,countries_tags,nutriments"
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

                        # Filtra apenas itens comercializados no Brasil ou com nome em PT
                        paises = [str(c).lower() for c in p.get("countries_tags", [])]
                        eh_brasil = any("brazil" in c or "brasil" in c for c in paises)
                        if not eh_brasil and not p.get("product_name_pt"):
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

                        if kcal == 0 and prot == 0 and carb == 0 and fat == 0 and "agua" not in remover_acentos(nome):
                            continue

                        cursor.execute("SELECT id FROM alimentos WHERE LOWER(nome) = ? AND LOWER(marca) = ?", (nome.strip().lower(), marca.strip().lower()))
                        if not cursor.fetchone():
                            cursor.execute("""
                                INSERT INTO alimentos (nome, marca, calorias, proteinas, carboidratos, gorduras, fonte)
                                VALUES (?, ?, ?, ?, ?, ?, 'BRASIL')
                            """, (nome.strip(), marca.strip(), round(kcal, 1), round(prot, 1), round(carb, 1), round(fat, 1)))
                            conn.commit()

                        novos_itens.append({
                            "nome": nome.strip(),
                            "marca": marca.strip(),
                            "calorias": round(kcal, 1),
                            "proteinas": round(prot, 1),
                            "carboidratos": round(carb, 1),
                            "gorduras": round(fat, 1),
                            "fonte": "BRASIL"
                        })
    except Exception as e:
        print(f"Erro na busca externa: {e}")

    # Mescla resultados locais e novos sem itens duplicados
    nomes_vistos = set()
    lista_final = []
    for item in resultados_cache + novos_itens:
        chave = (remover_acentos(item["nome"]), remover_acentos(item.get("marca", "")))
        if chave not in nomes_vistos:
            nomes_vistos.add(chave)
            lista_final.append(item)

    return {"origem": "busca_ok", "total": len(lista_final), "itens": lista_final}
