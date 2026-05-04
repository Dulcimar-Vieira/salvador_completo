import requests
import gzip
import xml.etree.ElementTree as ET
import io
import json
import os
import hashlib

# URL do feed
feed_url = "https://feeds.whatjobs.com/sinerj/sinerj_pt_BR.xml.gz"

# Criar pasta para os arquivos JSON
json_folder = "json_parts"
os.makedirs(json_folder, exist_ok=True)

# Contador de arquivos
file_count = 1

# Cidades desejadas
cidades_desejadas = [
    "lauro de freitas",
    "salvador",
    "simões filho",
    "camaçari",
    "feira de santana"
]

def normalizar(texto):
    return texto.strip().lower()

# Função para gerar ID único
def gerar_id_unico(titulo, empresa, cidade):
    base = f"{titulo}-{empresa}-{cidade}"
    return hashlib.md5(base.encode()).hexdigest()

# Baixar o feed
try:
    response = requests.get(feed_url, stream=True, timeout=60)
except requests.exceptions.RequestException as e:
    print(f"Erro ao baixar o feed: {e}")
    exit(1)

if response.status_code == 200:
    with gzip.open(io.BytesIO(response.content), "rt", encoding="utf-8") as f:
        jobs = []

        for event, elem in ET.iterparse(f, events=("end",)):
            if elem.tag == "job":

                location_elem = elem.find("locations/location")
                city = location_elem.findtext("city", "").strip() if location_elem is not None else ""
                state = location_elem.findtext("state", "").strip() if location_elem is not None else ""

                if not city or not state:
                    elem.clear()
                    continue

                city_lower = normalizar(city)

                # FILTRO DAS 5 CIDADES
                if city_lower in cidades_desejadas:

                    title = elem.findtext("title", "").strip()
                    description = elem.findtext("description", "").strip()

                    company = elem.findtext("company/name", "").strip()
                    if not company:
                        company = "Confidencial"

                    url = elem.findtext("urlDeeplink", "").strip()
                    tipo = elem.findtext("jobType", "").strip()

                    # 🔥 PARÁGRAFO SEO (NÃO ALTERA TÍTULO)
                    intro = f"Confira esta oportunidade para {title} em {city}. Veja os detalhes da vaga, requisitos e como se candidatar."

                    # 🔥 DESCRIÇÃO FINAL (mais única)
                    descricao_final = intro + "\n\n" + description

                    # 🔥 ID ÚNICO
                    job_id = gerar_id_unico(title, company, city)

                    job_data = {
                        "id": job_id,
                        "title": title,  # NÃO ALTERA O TÍTULO
                        "description": descricao_final,
                        "company": company,
                        "city": city,
                        "state": state,
                        "url": url,
                        "tipo": tipo,
                    }

                    jobs.append(job_data)

                elem.clear()

                # Salvar a cada 1000 vagas
                if len(jobs) >= 1000:
                    json_path = os.path.join(json_folder, f"part_{file_count}.json")
                    with open(json_path, "w", encoding="utf-8") as json_file:
                        json.dump(jobs, json_file, ensure_ascii=False, indent=2)

                    print(f"Arquivo salvo: {json_path}")
                    jobs = []
                    file_count += 1

        # Salvar restante
        if jobs:
            json_path = os.path.join(json_folder, f"part_{file_count}.json")
            with open(json_path, "w", encoding="utf-8") as json_file:
                json.dump(jobs, json_file, ensure_ascii=False, indent=2)

            print(f"Arquivo final salvo: {json_path}")

    print(f"JSONs gerados: {os.listdir(json_folder)}")

else:
    print(f"Erro ao baixar o feed: código HTTP {response.status_code}")
    exit(1)
