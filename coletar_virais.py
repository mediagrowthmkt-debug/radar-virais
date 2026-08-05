#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Radar de Virais — coletor (MediaGrowth).

Monta o SEED da pagina de aprovacao de um cliente juntando:
  - NOTICIAS/LINKS: reusa o motor do Radar de Tendencias (Google News RSS multi-locale,
    clustering + validacao por fonte) -> 1 card por tema, com os links extras dentro.
  - VIDEOS: busca no YouTube (yt-dlp) por queries do nicho -> cards de video virais.
  - IMAGEM: og:image das noticias do topo (best-effort) pra cada card ter capa.
  - ANGULO: gera, deterministicamente, um angulo de Reels no ESTILO do cliente
    (gancho em CAIXA ALTA + numero/superlativo/'cientistas' + ancora no oceano).

ATUALIZACAO DE HORA EM HORA: roda em modo APPEND — carrega o seed atual, mantem os itens
dentro da janela, funde os novos (dedup por id ESTAVEL = sha1(tipo|url|titulo)). Como as
decisoes de aprovacao vivem no backend por id, aprovar nunca se perde ao recoletar.

Stdlib apenas + yt-dlp (opcional, --no-video pula). Roda no Mac e na VPS.

Uso:
  coletar_virais.py --cliente marcelo
  coletar_virais.py --cliente marcelo --janela 30 --top 40 --max-videos 20
  coletar_virais.py --cliente marcelo --no-video --no-img       (rapido, so noticias)
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable or "/usr/bin/python3"
# motor de noticias do Radar de Tendencias (sibling nos scripts da MG)
RADAR_COLETAR = os.path.abspath(os.path.join(
    HERE, "..", "..", "scripts", "iris-radar-tendencias", "coletar.py"))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")


def log(m):
    print(m, file=sys.stderr, flush=True)


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")


def norm_url(u):
    u = (u or "").strip()
    u = re.sub(r"[#?].*$", "", u)          # tira query/fragment
    u = re.sub(r"/+$", "", u)              # tira barra final
    return u.lower()


def item_id(tipo, *keys):
    base = tipo + "|" + "|".join(strip_accents(k).lower().strip() for k in keys if k)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def fetch(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(400000)  # cap: so o <head> nos interessa
    return raw.decode("utf-8", "ignore")


# ---------------------------------------------------------------- TRADUCAO (PT-BR)
_TR_CACHE = {}
# palavras-funcao do ingles que NAO aparecem em PT — sinal de que o texto e ingles
_EN_WORDS = set((
    "the of and for with could that this from than ever been are was will into over about "
    "how why what when who they their its should would which while more most best world see "
    "help helps warns grows faster record hottest year years scientists could found reveals "
    "brutal predators strongest recorded spy hide friend deep sea ocean shark whale"
).split())


def parece_ingles(t):
    toks = re.findall(r"[a-zA-Z']+", (t or "").lower())
    if len(toks) < 3:
        return False
    en = sum(1 for w in toks if w in _EN_WORDS)
    return en >= 2


def traduzir_pt(text):
    """Traduz pra PT-BR via endpoint gratis do Google (gtx) so quando o texto parece ingles.
    Cacheia por run. Falhou -> devolve o original (nunca quebra)."""
    text = (text or "").strip()
    if not text or not parece_ingles(text):
        return text
    if text in _TR_CACHE:
        return _TR_CACHE[text]
    out = text
    try:
        u = ("https://translate.googleapis.com/translate_a/single?client=gtx"
             "&sl=auto&tl=pt&dt=t&q=" + urllib.parse.quote(text))
        raw = fetch(u, timeout=15)
        d = json.loads(raw)
        joined = "".join(seg[0] for seg in d[0] if seg and seg[0])
        out = joined.strip() or text
    except Exception:
        out = text
    _TR_CACHE[text] = out
    time.sleep(0.12)
    return out


# ---------------------------------------------------------------- DATA / BUCKET
ORDEM_BUCKET = {"hoje": 0, "ontem": 1, "semana": 2, "mes": 3}
BUCKET_ROTULO = {"hoje": "🔥 hoje", "ontem": "🔥 de ontem", "semana": "📅 esta semana", "mes": "🗓️ este mês"}


def bucket_from_date(dstr):
    """hoje / ontem / semana / mes a partir da data (YYYY-MM-DD). None se sem data."""
    if not dstr:
        return None
    try:
        d = datetime.strptime(dstr[:10], "%Y-%m-%d").date()
    except Exception:
        return None
    diff = (datetime.now().astimezone().date() - d).days
    if diff <= 0:
        return "hoje"
    if diff == 1:
        return "ontem"
    if diff <= 7:
        return "semana"
    return "mes"


def fmt_data_br(dstr):
    """05/08/2026 (ou '' se invalida)."""
    try:
        return datetime.strptime(dstr[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return ""


# ---------------------------------------------------------------- NOTICIAS
def _local_label(mercados):
    """Rotulo de origem/local da noticia a partir dos mercados que a surfaram."""
    lab = {"Brasil": "Brasil", "USA/Mundo": "EUA / Mundo"}
    nomes = [lab.get(x, x) for x in (mercados or []) if x]
    return " · ".join(nomes)


def _sem_fonte(titulo, fonte):
    """Tira o ' - Publisher' que o Google News anexa no fim do titulo."""
    t = (titulo or "").strip()
    f = (fonte or "").strip()
    if f and t.endswith(" - " + f):
        return t[: -(len(f) + 3)].strip()
    if " - " in t and t.rsplit(" - ", 1)[-1].strip() == f:
        return t.rsplit(" - ", 1)[0].strip()
    return t


def heat_from(bucket, num_fontes):
    """Calor 1..3 a partir de recencia + validacao cruzada."""
    if bucket in ("hoje", "ontem") and num_fontes >= 2:
        return 3
    if num_fontes >= 4 or bucket == "hoje":
        return 3
    if num_fontes >= 2 or bucket in ("ontem", "semana"):
        return 2
    return 1


def collect_news(radar_slug, janela, top, tmp_out):
    if not os.path.exists(RADAR_COLETAR):
        log(f"  [noticias] motor do radar nao encontrado em {RADAR_COLETAR} — pulando noticias")
        return []
    cmd = [PY, RADAR_COLETAR, "--cliente", radar_slug,
           "--janela", str(janela), "--top", str(top), "--out", tmp_out]
    log(f"  [noticias] rodando motor do radar ({radar_slug}, {janela}d)...")
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, timeout=600)
    except Exception as e:
        log(f"  [noticias] motor do radar falhou: {e}")
        return []
    try:
        data = json.load(open(tmp_out, encoding="utf-8"))
    except Exception as e:
        log(f"  [noticias] nao consegui ler o JSON do radar: {e}")
        return []
    items = []
    for t in data.get("temas", []):
        hs = t.get("headlines", [])
        if not hs:
            continue
        lead = hs[0]
        fonte = lead.get("fonte", "") or ""
        titulo_orig = _sem_fonte(lead.get("titulo", "").strip(), fonte)
        iid = item_id("noticia", norm_url(lead.get("url", "")), titulo_orig)  # id estavel (nao muda com traducao)
        items.append({
            "id": iid,
            "tipo": "noticia",
            "titulo": traduzir_pt(titulo_orig),
            "fonte": fonte,
            "local": _local_label(t.get("mercados", [])),
            "url": lead.get("url", ""),
            "thumb": "",
            "data": lead.get("data", ""),
            "bucket": t.get("bucket", "mes"),
            "calor": heat_from(t.get("bucket", "mes"), t.get("num_fontes", 1)),
            "num_fontes": t.get("num_fontes", 1),
            "keywords": t.get("keywords", []),
            "fontes_extra": [
                {"titulo": traduzir_pt(_sem_fonte(h.get("titulo", ""), h.get("fonte", ""))),
                 "fonte": h.get("fonte", ""), "url": h.get("url", "")}
                for h in hs[1:6]
            ],
            "score": t.get("score", 0),
        })
    log(f"  [noticias] {len(items)} temas viraram cards")
    return items


# ---------------------------------------------------------------- VIDEOS
def collect_videos(queries, max_videos):
    if not queries:
        return []
    try:
        subprocess.run(["yt-dlp", "--version"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True, timeout=20)
    except Exception:
        log("  [videos] yt-dlp indisponivel — pulando videos")
        return []
    seen = set()
    raw = []
    for q in queries:
        try:
            r = subprocess.run(
                ["yt-dlp", "-J", "--flat-playlist", "--no-warnings",
                 f"ytsearch8:{q}"],
                capture_output=True, text=True, timeout=90)
            if r.returncode != 0 or not r.stdout.strip():
                log(f"  [videos] '{q}' -> sem resultado")
                continue
            data = json.loads(r.stdout)
        except Exception as e:
            log(f"  [videos] '{q}' falhou: {e}")
            continue
        n = 0
        for e in (data.get("entries") or []):
            if not e:
                continue
            vid = e.get("id")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            views = e.get("view_count") or 0
            dur = e.get("duration") or 0
            raw.append({
                "id_yt": vid,
                "titulo": (e.get("title") or "").strip(),
                "fonte": e.get("channel") or e.get("uploader") or "YouTube",
                "url": f"https://www.youtube.com/watch?v={vid}",
                "views": views,
                "dur": dur,
                "query": q,
            })
            n += 1
        log(f"  [videos] '{q}' -> {n} videos")
    # ranqueia por views (viral), depois por menor duracao (Reels-friendly)
    raw.sort(key=lambda v: (v["views"], -v["dur"]), reverse=True)
    kept = raw[:max_videos]
    datas = fetch_video_dates([v["url"] for v in kept])
    out = []
    for v in kept:
        iid = item_id("video", v["id_yt"])
        dstr = datas.get(v["id_yt"], "")
        out.append({
            "id": iid,
            "tipo": "video",
            "titulo": traduzir_pt(v["titulo"]),
            "fonte": v["fonte"],
            "url": v["url"],
            "thumb": f"https://i.ytimg.com/vi/{v['id_yt']}/hqdefault.jpg",
            "data": dstr,
            "bucket": bucket_from_date(dstr) or "mes",
            "calor": 3 if v["views"] >= 500000 else 2 if v["views"] >= 50000 else 1,
            "num_fontes": 1,
            "keywords": [v["query"]],
            "views": v["views"],
            "dur": v["dur"],
            "fontes_extra": [],
            "score": v["views"],
        })
    log(f"  [videos] {len(out)} videos no seed (de {len(raw)} coletados) · {len(datas)} com data")
    return out


def fetch_video_dates(urls):
    """Data de publicacao (YYYY-MM-DD) dos videos mantidos, numa unica chamada yt-dlp."""
    if not urls:
        return {}
    try:
        r = subprocess.run(
            ["yt-dlp", "--no-warnings", "--skip-download", "--ignore-errors",
             "--print", "%(id)s|%(upload_date)s"] + list(urls),
            capture_output=True, text=True, timeout=240)
    except Exception as e:
        log(f"  [videos] datas falharam: {e}")
        return {}
    out = {}
    for line in r.stdout.splitlines():
        if "|" not in line:
            continue
        vid, ud = line.split("|", 1)
        ud = ud.strip()
        if len(ud) == 8 and ud.isdigit():
            out[vid] = f"{ud[:4]}-{ud[4:6]}-{ud[6:]}"
    return out


def _yt_search1(query):
    try:
        r = subprocess.run(
            ["yt-dlp", "-J", "--flat-playlist", "--no-warnings", f"ytsearch1:{query}"],
            capture_output=True, text=True, timeout=45)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return (json.loads(r.stdout).get("entries") or [None])[0]
    except Exception:
        return None


def related_media(query):
    """Acha 1 video do YouTube sobre o tema -> thumbnail real + link 'assista tambem'.
    Tenta o titulo cheio; se falhar (throttle/sem match), tenta uma query encurtada."""
    e = _yt_search1(query)
    if not (e and e.get("id")):
        curta = " ".join((query or "").split()[:7])
        if curta and curta != query:
            time.sleep(0.8)
            e = _yt_search1(curta)
    if not (e and e.get("id")):
        return None
    vid = e["id"]
    return {
        "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "url": f"https://www.youtube.com/watch?v={vid}",
        "titulo": traduzir_pt((e.get("title") or "").strip()),
        "fonte": e.get("channel") or e.get("uploader") or "YouTube",
        "views": e.get("view_count") or 0,
    }


def radar_keywords(radar_slug):
    """Palavras-chave de busca cadastradas no Radar de Tendencias (pra mostrar 'como pesquisamos')."""
    p = os.path.join(os.path.dirname(RADAR_COLETAR), "clientes.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
        return d.get("clientes", {}).get(radar_slug, {}).get("keywords", [])
    except Exception:
        return []


# ---------------------------------------------------------------- OG:IMAGE
_OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)',
    re.I)
_OG_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']',
    re.I)


def og_image(url):
    try:
        html = fetch(url, timeout=8)
    except Exception:
        return ""
    m = _OG_RE.search(html) or _OG_RE2.search(html)
    if not m:
        return ""
    img = m.group(1).strip()
    if img.startswith("//"):
        img = "https:" + img
    if img.startswith("http"):
        return img
    return ""


def enrich_images(items, limit):
    done = 0
    for it in items:
        if done >= limit:
            break
        if it["tipo"] != "noticia" or it.get("thumb") or not it.get("url"):
            continue
        img = og_image(it["url"])
        if img:
            it["thumb"] = img
        done += 1
    log(f"  [imagens] capas de noticia resolvidas em {done} cards (best-effort)")


def enrich_news_media(items, limit):
    """Cada noticia (topo) ganha imagem REAL do tema + 1 video 'assista tambem', via YouTube.
    Robusto (yt-dlp) — resolve o problema das URLs do Google News sem og:image."""
    alvo = [it for it in items if it["tipo"] == "noticia" and not it.get("thumb")]
    alvo = alvo[:limit]
    done = 0
    for it in alvo:
        rel = related_media(it["titulo"])
        if rel and rel.get("thumb"):
            it["thumb"] = rel["thumb"]
            it["video_relacionado"] = {"titulo": rel["titulo"], "url": rel["url"],
                                       "fonte": rel["fonte"], "views": rel["views"]}
            done += 1
        time.sleep(0.5)   # educado com o YouTube pra nao tomar throttle
    log(f"  [imagens] {done}/{len(alvo)} noticias com imagem+video do tema (YouTube)")


# ---------------------------------------------------------------- ANGULO (voz do cliente)
def _num_or_super(title):
    m = re.search(r"\b(\d{1,4})\b", title or "")
    if m:
        return m.group(1)
    return ""


# Sub-eixos GENERICOS (fallback). Cada cliente define os seus em clientes/<slug>.json -> voice.subeixos
# (key + gatilhos + hooks). Assim o gerador de angulo serve QUALQUER nicho sem tocar no codigo.
_SUBEIXOS_GENERICO = [
    ("descoberta", ["descobr", "estudo", "cientistas", "pesquisa", "revela", "inedit",
                    "primeira vez", "raro", "novo"],
     ["O QUE OS ESPECIALISTAS ACABARAM DE DESCOBRIR",
      "O QUE NINGUÉM TE CONTOU SOBRE ISSO"]),
    ("alerta", ["risco", "perigo", "alerta", "cuidado", "aumenta", "cresce", "recorde", "crise"],
     ["O QUE ESTE ALERTA SIGNIFICA PRA VOCÊ",
      "POR QUE ISSO ESTÁ ACONTECENDO AGORA"]),
]


def _build_subeixos(voice):
    """Sub-eixos vindos do config do cliente (voice.subeixos) ou o fallback generico."""
    se = (voice or {}).get("subeixos")
    if se:
        out = []
        for s in se:
            gat = [strip_accents(g).lower() for g in s.get("gatilhos", [])]
            hooks = s.get("hooks", []) or ["O QUE ISSO REVELA"]
            out.append((s.get("key", "x"), gat, hooks))
        return out
    return _SUBEIXOS_GENERICO


def _obfuscar(txt, mapa):
    if not mapa:
        return txt
    out = txt
    for k, v in mapa.items():
        out = re.sub(r"\b" + re.escape(k) + r"\b", v, out, flags=re.I)
    return out


def gerar_angulo(item, voice):
    """Gera o angulo de Reels na VOZ do cliente. Tudo (sub-eixos, alvo, corpo, fecho,
    gancho default, ofuscacao) vem de voice (config do cliente); ha defaults genericos."""
    voice = voice or {}
    title = item.get("titulo", "")
    tnorm = strip_accents(title).lower()
    n = _num_or_super(title)
    default_hook = voice.get("gancho_default", "O QUE ISSO REVELA SOBRE O SEU NICHO")
    eixo, hooks = "default", [default_hook]
    for key, gatilhos, hh in _build_subeixos(voice):
        if any(g in tnorm for g in gatilhos):
            eixo, hooks = key, hh
            break
    # escolhe o hook de forma deterministica (varia por id)
    idx = int(item.get("id", "0")[:6] or "0", 16) % len(hooks)
    hook = hooks[idx]
    alvo = voice.get("alvo_default", "ISSO")
    for k, v in (voice.get("alvo") or {}).items():
        if strip_accents(k).lower() in tnorm:
            alvo = v
            break
    hook = hook.replace("{alvo}", alvo).replace("{n}", n or "3")
    hook = _obfuscar(hook, voice.get("ofuscar"))
    corpo = voice.get("angulo_corpo",
                      "Puxa o fato pela fonte, explica em linguagem simples por que acontece e "
                      "conecta com o universo da marca, com a sua autoridade no comando.")
    fecho = voice.get("angulo_fecho", "Fecha com um convite alinhado ao propósito da marca.")
    formato = voice.get("formato_card", "Reels")
    if item.get("tipo") == "video":
        corpo = voice.get("angulo_corpo_video",
                          "Recria a ideia deste vídeo no seu estilo: mesmo tema, com o selo de "
                          "autoridade da marca. Não copie, traduza pra sua voz.")
    return {"gancho": hook, "corpo": corpo, "fecho": fecho, "formato": formato, "eixo": eixo}


# ---------------------------------------------------------------- MERGE / SEED
def carregar_seed(path):
    if not os.path.exists(path):
        return None
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def dentro_janela(item, janela):
    """Mantem itens sem data (videos) e noticias dentro da janela."""
    d = item.get("data", "")
    if not d:
        return True
    try:
        dt = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return True
    return (datetime.now(timezone.utc) - dt).days <= janela + 2


def main():
    ap = argparse.ArgumentParser(description="Radar de Virais — coletor")
    ap.add_argument("--cliente", required=True, help="slug do cliente (clientes/<slug>.json)")
    ap.add_argument("--janela", type=int, default=30)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--max-videos", type=int, default=20)
    ap.add_argument("--img-limit", type=int, default=24, help="quantas noticias enriquecer com imagem+video do tema")
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--no-img", action="store_true")
    ap.add_argument("--out", help="caminho do seed (default seed/<slug>.json)")
    args = ap.parse_args()

    cfg_path = os.path.join(HERE, "clientes", f"{args.cliente}.json")
    if not os.path.exists(cfg_path):
        raise SystemExit(f"Config nao encontrada: {cfg_path}")
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    voice = cfg.get("voice", {})
    out = args.out or os.path.join(HERE, "seed", f"{args.cliente}.json")

    now = datetime.now(timezone.utc)
    log(f"== Radar de Virais :: {cfg.get('client')} :: {now.astimezone().strftime('%d/%m %H:%M')} ==")

    tmp = os.path.join(os.path.dirname(out) or ".", f".radar-tmp-{args.cliente}.json")
    novos = collect_news(cfg.get("radar_slug", args.cliente), args.janela, args.top, tmp)
    if not args.no_video:
        novos += collect_videos(cfg.get("video_queries", []), args.max_videos)
    if os.path.exists(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass

    # merge com seed anterior (append + dedup por id, mantem janela)
    anterior = carregar_seed(out)
    por_id = {}
    if anterior:
        for it in anterior.get("itens", []):
            if dentro_janela(it, args.janela):
                por_id[it["id"]] = it
    apareceu_agora = set()
    for it in novos:
        apareceu_agora.add(it["id"])
        prev = por_id.get(it["id"])
        if prev:
            # atualiza dados frescos mas preserva 'primeira_vez'
            it["primeira_vez"] = prev.get("primeira_vez", now.astimezone().isoformat())
        else:
            it["primeira_vez"] = now.astimezone().isoformat()
        it["angulo"] = gerar_angulo(it, voice)
        por_id[it["id"]] = it
    # garante que itens antigos preservados tenham angulo
    for it in por_id.values():
        if "angulo" not in it:
            it["angulo"] = gerar_angulo(it, voice)

    itens = list(por_id.values())

    # recomputa bucket + calor de TODOS pela data (adiciona 'hoje'; item que era 'hoje' ontem vira 'ontem')
    for it in itens:
        bkt = bucket_from_date(it.get("data", ""))
        if bkt:
            it["bucket"] = bkt
        if it["tipo"] == "noticia":
            it["calor"] = heat_from(it.get("bucket", "mes"), it.get("num_fontes", 1))
        elif it.get("bucket") in ("hoje", "ontem"):
            it["calor"] = 3
        it["data_br"] = fmt_data_br(it.get("data", ""))

    # imagem + video do tema pras noticias novas sem capa (YouTube — robusto)
    if not args.no_img:
        enrich_news_media([it for it in itens if it["id"] in apareceu_agora], args.img_limit)

    # ordena: recencia (hoje>ontem>semana>mes), depois calor, depois score
    itens.sort(key=lambda it: (ORDEM_BUCKET.get(it.get("bucket", "mes"), 4),
                               -it.get("calor", 1),
                               -it.get("score", 0)))

    stats = {
        "total": len(itens),
        "novos_agora": len(apareceu_agora),
        "noticias": len([i for i in itens if i["tipo"] == "noticia"]),
        "videos": len([i for i in itens if i["tipo"] == "video"]),
        "hoje": len([i for i in itens if i.get("bucket") == "hoje"]),
        "ontem": len([i for i in itens if i.get("bucket") == "ontem"]),
        "semana": len([i for i in itens if i.get("bucket") == "semana"]),
        "mes": len([i for i in itens if i.get("bucket") == "mes"]),
    }

    seed = {
        "slug": args.cliente,
        "client": cfg.get("client"),
        "title": cfg.get("title", "Radar de Virais"),
        "subtitle": cfg.get("subtitle", ""),
        "intro": cfg.get("intro", ""),
        "brand": cfg.get("brand", {}),
        "gerado_em": now.astimezone().isoformat(),
        "janela_dias": args.janela,
        "search_terms": {
            "noticias": radar_keywords(cfg.get("radar_slug", args.cliente)),
            "videos": cfg.get("video_queries", []),
        },
        "stats": stats,
        "itens": itens,
    }
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(seed, f, ensure_ascii=False, indent=2)

    log(f"\n== SEED salvo: {out}")
    log(f"   {stats['total']} itens ({stats['noticias']} noticias, {stats['videos']} videos) | "
        f"hoje {stats['hoje']} · ontem {stats['ontem']} · semana {stats['semana']} · mes {stats['mes']}")
    print(out)


if __name__ == "__main__":
    main()
