#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Radar de Virais — deploy/orquestracao (MediaGrowth).
Coleta o seed, publica o frontend no GitHub Pages e faz o deploy do backend na Hostinger.
Stdlib pura. Roda no Mac e na VPS.

Uso:
  publicar.py coletar <slug> [--publicar] [--no-video] [--no-img]   # roda o coletor (append) e opcionalmente publica
  publicar.py publicar [-m "mensagem"]                             # git push -> GitHub Pages
  publicar.py backend                                              # scp api.php -> Hostinger (1 deploy serve todos)
  publicar.py link <slug>                                          # imprime os links
  publicar.py listar                                               # lista os clientes
"""
import os, sys, json, subprocess

REPO = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable or "/usr/bin/python3"
GH_OWNER = os.environ.get("RV_GH_OWNER", "mediagrowthmkt-debug")
GH_REPO  = os.environ.get("RV_GH_REPO",  "radar-virais")
PAGES    = os.environ.get("RV_PAGES_URL", f"https://{GH_OWNER}.github.io/{GH_REPO}")
SSH      = os.environ.get("MG_HOSTINGER_SSH", "hostinger-mg")
REMOTE   = os.environ.get("RV_HOSTINGER_DIR", "domains/mediagrowth.com.br/public_html/virais-api")
API_URL  = os.environ.get("RV_API_URL", "https://mediagrowth.com.br/virais-api/api.php")


def sh(cmd, cwd=REPO, check=True):
    print("· " + " ".join(cmd))
    return subprocess.run(cmd, cwd=cwd, check=check)


def git(args):
    base = ["git", "-c", "user.name=MediaGrowth Deploy", "-c", "user.email=mediagrowthmkt@gmail.com"]
    return sh(base + args)


def links(slug):
    print(f"  Cliente : {PAGES}/?c={slug}")
    print(f"  Backend : {API_URL}?action=get&slug={slug}")


def cmd_coletar(slug, publicar=False, no_video=False, no_img=False):
    cmd = [PY, os.path.join(REPO, "coletar_virais.py"), "--cliente", slug]
    if no_video: cmd.append("--no-video")
    if no_img: cmd.append("--no-img")
    sh(cmd)
    if publicar:
        cmd_publicar(f"radar de virais: atualiza seed do {slug}")


def cmd_publicar(msg=None):
    git(["add", "-A"])
    r = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True)
    if not r.stdout.strip():
        print("Nada novo para publicar.")
        return
    git(["commit", "-m", msg or "atualiza radar de virais"])
    git(["push", "origin", "main"])
    print(f"✅ Publicado. Pages: {PAGES}/  (pode levar ~1 min pra atualizar)")


def cmd_backend():
    sh(["ssh", "-o", "ConnectTimeout=15", SSH,
        f"mkdir -p {REMOTE}/data && chmod 775 {REMOTE}/data && echo OK"])
    sh(["scp", "-o", "ConnectTimeout=15", os.path.join(REPO, "api", "api.php"), f"{SSH}:{REMOTE}/api.php"])
    print(f"✅ Backend no ar: {API_URL}  (1 deploy serve todos os slugs)")


def cmd_listar():
    d = os.path.join(REPO, "clientes")
    for f in sorted(os.listdir(d)):
        if f.endswith(".json") and not f.startswith("_"):
            slug = f[:-5]
            try:
                nome = json.load(open(os.path.join(d, f), encoding="utf-8")).get("client", "")
            except Exception:
                nome = "?"
            print(f"  {slug:20} {nome}")


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return
    c = a[0]
    if c == "coletar":
        cmd_coletar(a[1], publicar="--publicar" in a, no_video="--no-video" in a, no_img="--no-img" in a)
    elif c == "publicar":
        msg = a[a.index("-m") + 1] if "-m" in a else None
        cmd_publicar(msg)
    elif c == "backend":
        cmd_backend()
    elif c == "link":
        links(a[1])
    elif c == "listar":
        cmd_listar()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
