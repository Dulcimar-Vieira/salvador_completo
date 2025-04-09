import json
import os

pasta = 'json_parts'
arquivos = sorted([
    f for f in os.listdir(pasta)
    if f.startswith('part_') and f.endswith('.json')
])

print(f"🔍 Arquivos encontrados: {arquivos}")

dados_totais = []
erros = 0

for arquivo in arquivos:
    caminho_completo = os.path.join(pasta, arquivo)
    try:
        with open(caminho_completo, 'r', encoding='utf-8') as f:
            dados = json.load(f)
            if isinstance(dados, list):
                dados_totais.extend(dados)
            else:
                print(f"⚠️ {arquivo} não contém uma lista.")
    except Exception as e:
        erros += 1
        print(f"❌ Erro ao processar {arquivo}: {e}")

if dados_totais:
    with open('merged.json', 'w', encoding='utf-8') as f:
        json.dump(dados_totais, f, ensure_ascii=False, indent=2)
    print(f"✅ Arquivo 'merged.json' gerado com {len(dados_totais)} registros.")
else:
    print("⚠️ Nenhum dado válido encontrado para gerar o 'merged.json'.")

if erros > 0:
    print(f"⚠️ {erros} arquivo(s) com erro foram ignorados.")
    print(f"Total de arquivos mesclados: {len(json_files)}")
print(f"Total de vagas finais: {len(all_jobs)}")
print(f"✅ merged.json criado com sucesso!")
