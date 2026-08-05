# Radar de Virais — página de aprovação por cliente

Página web que junta, **de hora em hora**, o que está viralizando / virando notícia no nicho de um cliente
(notícias + vídeos virais) e transforma cada item num **card com ângulo pronto pra Reels no estilo dele**,
pra o cliente (ou o time) **aprovar / descartar / comentar**. Aprovou → vira pauta de conteúdo rápido.

**1ª instância: Marcelo Telles** (Instituto Gaia Soul — oceano, ciência marinha, conservação).

## Arquitetura (mesmo padrão do validador de palavras-chave e dos cortes de podcast)
- **Frontend estático** no GitHub Pages (`mediagrowthmkt-debug/radar-virais`): `index.html` + `app.js` + `style.css`.
  Lê o seed `seed/<slug>.json` e sincroniza as decisões com o backend.
- **Backend PHP por slug** na Hostinger (`mediagrowth.com.br/virais-api/api.php`, 1 deploy serve todos):
  estado em `data/<slug>.json`. Decisões chaveadas pelo **ID estável do item** → aprovar
  **sobrevive à recoleta** (o seed troca, a decisão fica).
- **Coletor** `coletar_virais.py`: notícias (reusa o motor do Radar de Tendências, Google News RSS) +
  vídeos (yt-dlp, YouTube) + og:image + **ângulo determinístico na voz do cliente** (config `clientes/<slug>.json`).
  Roda em modo **append** (dedup por id, mantém a janela) → ideal pro cron horário.

## Comandos
```bash
# coleta (append) + publica
python3 publicar.py coletar marcelo --publicar

# só publicar o frontend / só o backend
python3 publicar.py publicar -m "mensagem"
python3 publicar.py backend
python3 publicar.py link marcelo
python3 publicar.py listar
```

## Atualização de hora em hora
Fluxo `.claude/flows/radar-virais-marcelo.json` (daemon `flow-scheduler`, na VPS): de hora em hora roda
`publicar.py coletar marcelo --publicar`. Aprovações não se perdem (ficam no backend por id).

## Adaptar a um novo cliente
1. `clientes/<slug>.json` — copie o do marcelo e troque: `client`, `radar_slug` (slug no `clientes.json` do Radar de Tendências),
   `video_queries`, `brand` (cores/logo), e o bloco `voice` (quem é, eixo viral, tom, fórmula de gancho, fecho, ofuscação).
2. `logos/<slug>.png`.
3. `python3 publicar.py coletar <slug> --publicar` + `python3 publicar.py backend` (1ª vez).
4. Duplique o fluxo de cron pro novo slug.

## Link do Marcelo
- Página: https://mediagrowthmkt-debug.github.io/radar-virais/?c=marcelo
- Backend: https://mediagrowth.com.br/virais-api/api.php?action=get&slug=marcelo
