# Guide de déploiement — DATAFORENSIC AI sur DigitalOcean

## The Organizational Memory Engine for DataHub · Next.js 16 + FastAPI + PostgreSQL

Ce guide suit la structure du guide FIELDREEL et réutilise le même proxy
mutualisé. Les différences tiennent à ce que DATAFORENSIC fait réellement : il
n'y a **ni file d'attente, ni Redis, ni stockage objet** — l'agent travaille en
mémoire pendant une requête, et tout ce qui persiste tient dans PostgreSQL et
dans DataHub. En revanche le navigateur consomme un **flux SSE** en direct, ce
qui impose deux réglages Nginx que rien d'autre ne réclame.

---

## Architecture cible

| Service | Domaine | Technologie | Port interne |
|---|---|---|---|
| Frontend | `dataforensic.vylantic.com` | Next.js 16 (App Router, standalone) | 3000 |
| API + agent | `api.dataforensic.vylantic.com` | FastAPI + Python 3.12 | 8000 |
| DataHub | `datahub.dataforensic.vylantic.com` | DataHub Core 1.6 (quickstart) | 9002 (UI) / 8080 (GMS) |
| MCP *(optionnel)* | `mcp.dataforensic.vylantic.com` | mcp-server-datahub derrière un pont HTTP | 8000 |
| Base de données | (interne) | PostgreSQL 16 | 5432 |

> **Trois domaines nécessaires, un quatrième optionnel.** `mcp.` n'est requis
> par personne : l'agent joint le pont MCP par le réseau Docker
> (`http://dataforensic-mcp:8000/mcp`), et la preuve que l'intégration MCP
> fonctionne est déjà servie par `api.` (`/api/v1/datahub/status` liste les
> outils). Le domaine n'existe que si vous voulez brancher un client MCP externe
> — Claude Desktop, Cursor — sur l'instance. Voir la section 5 avant de le
> publier : ce pont porte le jeton DataHub et n'a aucune authentification propre.

> **Quatre domaines, et l'agent n'en a pas.** Il tourne dans le process FastAPI,
> en tâche de fond, et diffuse son avancement par SSE. Le sortir dans un
> container à lui n'apporterait rien tant qu'une investigation dure quelques
> secondes.

> **`datahub.` pointe sur l'interface DataHub, pas sur GMS.** C'est l'écran qui
> rend la soumission vérifiable : un juge y voit le tag `DataForensic:SCHEMA_DRIFT`
> posé sur `sales_daily` et le lien de mémoire institutionnelle, écrits par
> l'agent. GMS (8080) reste sur le réseau interne — c'est une API, pas une
> démonstration.

> **Le serveur MCP auto-hébergé ne parle pas HTTP.** C'est le point qui
> conditionne tout ce déploiement, et il n'est pas évident : `mcp-server-datahub`
> est un serveur **stdio**, conçu pour Claude Desktop et Cursor. L'endpoint
> Streamable HTTP documenté (`/integrations/ai/mcp`) est une fonctionnalité
> DataHub **Cloud**. Sur DataHub Core il faut donc un pont stdio → HTTP
> (section 3.3), sinon `DATAHUB_MCP_URL` n'a rien à joindre.

> **Pas de Redis.** Le flux SSE est servi par un bus asyncio en mémoire, et
> chaque événement est **persisté en base avant d'être publié** — un client qui
> se reconnecte rejoue depuis son `Last-Event-ID`. Ajouter Redis pour ça
> reviendrait à installer un broker pour transporter des messages déjà écrits
> dans PostgreSQL.

> **Pas de stockage objet.** Aucun média, aucun fichier utilisateur. La mémoire
> institutionnelle est écrite dans DataHub, pas dans un bucket.

---

## 1. Architecture globale

```text
Internet
   │
   ▼
Cloudflare (optionnel)
   │
   ▼
┌────────────────────────────────────────────┐
│ Droplet Ubuntu 24.04                       │
│                                            │
│ ┌────────────────────────────────────────┐ │
│ │ proxy-network                          │ │
│ │  proxy-nginx        80 / 443           │ │
│ └────────────────────────────────────────┘ │
│                                            │
│ ┌─── dataforensic-network ───────────────┐ │
│ │  dataforensic-web       :3000  Next.js │ │
│ │  dataforensic-api       :8000  FastAPI │ │
│ │  dataforensic-postgres  :5432          │ │
│ │  dataforensic-mcp       :8000  pont    │ │
│ │        │ stdio                          │ │
│ │        ▼                                │ │
│ │  uvx mcp-server-datahub                 │ │
│ └────────┬───────────────────────────────┘ │
│          │ GMS 8080 (GraphQL + Timeline)   │
│ ┌────────▼───────────────────────────────┐ │
│ │ quickstart DataHub (réseau rattaché)   │ │
│ │  frontend (alias datahub-frontend):9002│ │
│ │  gms      (alias datahub-gms)     :8080│ │
│ │  opensearch · kafka · mysql · actions  │ │
│ └────────────────────────────────────────┘ │
└────────────────────────────────────────────┘
```

**Le navigateur parle directement à l'API.** C'est un choix, pas un oubli :
l'interface est une application cliente qui ouvre un `EventSource` sur
`/investigations/{id}/events`, et l'API publique est une surface que les juges
doivent pouvoir interroger au `curl`. Conséquence directe : **`CORS_ORIGINS`
doit contenir l'origine du frontend** (section 6). C'est la seule surface CORS
du projet, et son oubli ne se voit que dans la console du navigateur.

---

## 2. Prérequis droplet

Si le droplet existe déjà (Kynara ou FIELDREEL installés), passer à la section 4.

- **Plan** : **4 vCPU / 16 Go RAM / 100 Go SSD**. DATAFORENSIC lui-même tient
  dans 2 Go ; ce sont OpenSearch et Kafka, embarqués par le quickstart DataHub,
  qui dimensionnent la machine. En dessous de 16 Go, GMS démarre puis se fait
  tuer par l'OOM killer au premier chargement de datapack — un échec qui
  ressemble à un bug applicatif et n'en est pas.
- **Swap** : en ajouter 4 Go. Ce n'est pas une solution, c'est un filet pendant
  les pics de démarrage.
- **OS** : Ubuntu 24.04 LTS
- **Région** : Frankfurt (`fra1`) ou Amsterdam (`ams3`)

Hardening, firewall et installation Docker : identiques au guide Kynara §3–4.

---

## 3. DataHub embarqué

DataHub Core n'est pas un container : le quickstart démarre GMS, le frontend,
Elasticsearch, Kafka, MySQL et plusieurs jobs d'initialisation. C'est lui qui
dimensionne le droplet, et c'est aussi la raison pour laquelle ce guide ne
réécrit pas son compose — un stack de dix services qu'on n'a pas testé soi-même
n'a pas sa place dans un guide de déploiement.

### 3.1 Démarrer DataHub avec son propre outil

```bash
# uv fournit uvx, utilisé aussi par le serveur MCP
curl -LsSf https://astral.sh/uv/install.sh | sh

# Réseau partagé, créé avant DataHub pour pouvoir l'y rattacher
docker network create dataforensic-network 2>/dev/null || true

# DataHub Core, via sa CLI officielle
uvx --from acryl-datahub datahub docker quickstart
```

Le quickstart démarre **14 conteneurs** : GMS, frontend, MySQL, OpenSearch,
Kafka, les actions et les jobs de mise à jour. Compter **5 à 10 minutes** au
premier démarrage. La commande rend la main quand l'interface répond sur
`http://localhost:9002` (identifiants `datahub` / `datahub`).

Rattacher ensuite les deux conteneurs utiles au réseau de l'application. Les
noms réels du quickstart sont longs et versionnés ; l'option `--alias` donne un
nom stable côté application, ce qui évite de figer un nom de conteneur dans
`.env` :

```bash
docker ps --format '{{.Names}}' | grep datahub

docker network connect --alias datahub-gms \
  dataforensic-network datahub-datahub-gms-quickstart-1
docker network connect --alias datahub-frontend \
  dataforensic-network datahub-frontend-quickstart-1
```

> **Ne pas deviner ces noms.** Ce sont ceux publiés par le guide quickstart
> officiel (`datahub-datahub-gms-quickstart-1`,
> `datahub-frontend-quickstart-1`), et ils diffèrent des `datahub-gms` /
> `datahub-frontend-react` qu'on voit souvent recopiés ailleurs. Un
> `docker network connect` sur un nom inexistant échoue tout de suite — c'est
> préférable à une erreur de résolution DNS trois étapes plus loin. Toujours
> confirmer avec la commande `docker ps` ci-dessus.

### 3.2 Créer le jeton

L'agent et le serveur MCP s'authentifient par **personal access token**.

1. Initialiser la CLI, qui sert aussi au chargement du datapack :

   ```bash
   uvx --from acryl-datahub datahub init --username datahub --password datahub
   ```

2. Ouvrir `http://localhost:9002`, se connecter (`datahub` / `datahub` par
   défaut — **à changer avant d'exposer le domaine**).
3. **Settings → Access Tokens → Generate new token**.
4. Copier la valeur dans `.env` (`DATAHUB_TOKEN`).

Pour un agent qui tourne sans humain, DataHub recommande un **service account**
plutôt qu'un jeton personnel : *Settings → Users & Groups → Service Accounts*.
Le jeton survit alors au départ de la personne qui l'a créé.

### 3.3 Le pont MCP

`mcp-server-datahub` est un serveur **stdio**. `LiveDataHubProvider` est un
client **Streamable HTTP**. Il manque donc une pièce, et elle est standard :
`supergateway` lance le serveur stdio et l'expose en HTTP.

```yaml
  mcp:
    # Image construite depuis le dépôt, pas tirée. L'image supergateway publiée
    # est basée sur Alpine, et `mcp-server-datahub` ne s'y installe pas : sa
    # dépendance `google-re2` ne publie que des wheels manylinux (glibc). Sur
    # musl, pip les refuse, tente une compilation, et échoue faute de
    # compilateur C++. Détails : datahub/mcp-bridge/README.md
    build:
      context: ./datahub/mcp-bridge
    container_name: dataforensic-mcp
    restart: unless-stopped
    environment:
      DATAHUB_GMS_URL: http://datahub-gms:8080
      DATAHUB_GMS_TOKEN: ${DATAHUB_TOKEN}
      # Les mutations restent désactivées : le write-back de l'agent passe par
      # GraphQL, disponible sans opt-in. Une capacité d'écriture ouverte sur un
      # serveur exposé n'a pas de contrepartie ici.
      TOOLS_IS_MUTATION_ENABLED: "false"
    networks: [dataforensic-network, proxy-network]
```

Le serveur MCP est installé **au moment du build**, pas au premier appel. C'est
le second défaut de l'approche `uvx <paquet>@latest` : elle télécharge une
vingtaine de mégaoctets *pendant* la poignée de main `initialize`, assez pour
dépasser `DATAHUB_TIMEOUT_SECONDS` à froid — et elle recommence après chaque
redémarrage du conteneur.

`--stateful` n'est pas décoratif : le client négocie une session
(`Mcp-Session-Id`) à l'`initialize` et la réutilise pour `tools/list` et
`tools/call`. En mode sans état, chaque appel repart d'une poignée de main et le
serveur répond des erreurs de session.

L'endpoint devient `http://dataforensic-mcp:8000/mcp` sur le réseau interne —
c'est cette valeur qui va dans `DATAHUB_MCP_URL`, pas le domaine public.

### 3.4 Ce que l'agent utilise réellement

Le serveur MCP couvre une partie des besoins, pas la totalité. La répartition
est explicite dans le code (`app/services/datahub/live.py`) :

| Opération de l'agent | Outil MCP | Repli |
|---|---|---|
| contexte d'un asset | `get_entities` | GraphQL |
| schéma | `list_schema_fields` | GraphQL |
| lineage | `get_lineage` | GraphQL `searchAcrossLineage` |
| recherche / assets liés | `search` | GraphQL |
| ownership | `get_entities` | GraphQL |
| signaux qualité | — | GraphQL `assertions` |
| historique des changements | — | Timeline API |
| write-back | — | GraphQL `createTag` + `addTags` + `addLink` |

Deux dimensions n'ont **pas** d'équivalent MCP : l'historique des changements et
les assertions. Elles passent par GraphQL et la Timeline API, ce qui est
mentionné ici parce que la corrélation temporelle — le fait qu'un changement de
schéma précède l'incident — en dépend entièrement.

### 3.5 Charger le jeu de données

```bash
uvx --from acryl-datahub datahub datapack list
uvx --from acryl-datahub datahub datapack load showcase-ecommerce
```

`showcase-ecommerce` fournit environ **1 050 entités** couvrant Snowflake,
Looker, PowerBI, Tableau, dbt et Spark, avec lineage, gouvernance, termes de
glossaire et domaines. Les deux autres scénarios du projet s'appuient sur
`nyc-taxi` (pipeline en trois étapes avec un problème de fraîcheur planté) et
`healthcare` (problèmes de qualité plantés).

> La commande `datapack` est marquée **expérimentale** par DataHub : sa surface
> peut changer. `datahub datapack list` dit ce que la version installée connaît
> réellement, et `--dry-run` permet de vérifier avant d'écrire.

Vérifier ensuite que l'asset cible existe :

```bash
curl -sG http://localhost:8000/api/v1/datahub/search \
  --data-urlencode "query=sales_daily" | python3 -m json.tool
```

### 3.6 Le mode reste explicite

```ini
DATAHUB_MODE=live
```

`live` exige un DataHub joignable et **échoue bruyamment** sinon : une
investigation lancée pendant que GMS démarre encore est *bloquée* et l'annonce.
C'est le comportement voulu — le repli silencieux (`auto`) est fait pour le
développement, où basculer sur le graphe déterministe est confortable.

Le badge de l'interface affiche alors `LIVE DATAHUB`. Il n'est jamais déduit :
il rend ce que l'API rapporte, et chaque evidence porte son `source_mode`.

### DNS

```
A   dataforensic.vylantic.com          → <IP droplet>   # requis
A   api.dataforensic.vylantic.com      → <IP droplet>   # requis
A   datahub.dataforensic.vylantic.com  → <IP droplet>   # fortement recommandé
```

N'ajouter l'enregistrement `mcp.` que si vous décidez d'exposer le pont
(section 5). Un domaine sans vhost dédié tombe sur le premier `server` du proxy,
ce qui sert le mauvais site plutôt que rien.

---

## 4. Structure serveur et réseaux

```bash
sudo mkdir -p /var/www/dataforensic
sudo chown -R $USER:$USER /var/www/dataforensic

# Réseau proxy (existe déjà si un autre projet est installé)
docker network create proxy-network 2>/dev/null || true

# Réseau dédié DATAFORENSIC
docker network create dataforensic-network
```

---

## 5. Reverse proxy Nginx

Deux vhosts dans `/var/www/proxy/nginx/conf.d/`.

### `dataforensic-nextjs.conf`

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name dataforensic.vylantic.com;

    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name dataforensic.vylantic.com;

    ssl_certificate     /etc/letsencrypt/live/dataforensic.vylantic.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dataforensic.vylantic.com/privkey.pem;

    include /etc/nginx/snippets/ssl.conf;
    include /etc/nginx/snippets/security.conf;

    access_log /var/log/nginx/dataforensic-nextjs-access.log main;
    error_log  /var/log/nginx/dataforensic-nextjs-error.log warn;

    location /_next/static/ {
        proxy_pass http://dataforensic-web:3000;
        include /etc/nginx/snippets/proxy.conf;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

    location / {
        proxy_pass http://dataforensic-web:3000;
        include /etc/nginx/snippets/proxy.conf;
    }
}
```

### `dataforensic-fastapi.conf`

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name api.dataforensic.vylantic.com;

    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name api.dataforensic.vylantic.com;

    ssl_certificate     /etc/letsencrypt/live/api.dataforensic.vylantic.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.dataforensic.vylantic.com/privkey.pem;

    include /etc/nginx/snippets/ssl.conf;
    include /etc/nginx/snippets/security.conf;

    # L'API ne reçoit que du JSON : un incident fait quelques centaines d'octets.
    client_max_body_size 2M;

    access_log /var/log/nginx/dataforensic-fastapi-access.log main;
    error_log  /var/log/nginx/dataforensic-fastapi-error.log warn;

    # ─── Le flux d'investigation ────────────────────────────────────────
    # Sans ces trois lignes, la timeline n'apparaît pas progressivement : elle
    # surgit d'un bloc à la fin, et toute la démonstration tombe à plat.
    # L'application envoie déjà `X-Accel-Buffering: no`, mais le timeout de
    # lecture, lui, ne se règle que côté proxy : une investigation silencieuse
    # pendant 60 secondes verrait sa connexion coupée.
    location ~ ^/api/v1/investigations/[^/]+/events$ {
        proxy_pass http://dataforensic-api:8000;
        include /etc/nginx/snippets/proxy.conf;

        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        chunked_transfer_encoding on;
    }

    # ─── Remise à zéro de la démo ───────────────────────────────────────
    # L'endpoint efface les incidents, les patterns appris et la mémoire.
    # Utile en répétition, désastreux si un visiteur le déclenche pendant
    # qu'un juge regarde. Il reste accessible par `docker compose exec`.
    location = /api/v1/demo/reset { return 403; }

    location / {
        proxy_pass http://dataforensic-api:8000;
        include /etc/nginx/snippets/proxy.conf;
    }
}
```

### `dataforensic-datahub.conf`

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name datahub.dataforensic.vylantic.com;

    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name datahub.dataforensic.vylantic.com;

    ssl_certificate     /etc/letsencrypt/live/datahub.dataforensic.vylantic.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/datahub.dataforensic.vylantic.com/privkey.pem;

    include /etc/nginx/snippets/ssl.conf;
    include /etc/nginx/snippets/security.conf;

    access_log /var/log/nginx/dataforensic-datahub-access.log main;
    error_log  /var/log/nginx/dataforensic-datahub-error.log warn;

    # L'interface DataHub, pas GMS. C'est l'écran qui prouve le write-back :
    # le tag DataForensic:<pattern> et le lien de mémoire posés sur l'asset.
    # GMS (8080) reste joignable uniquement depuis le réseau Docker.
    client_max_body_size 32M;

    # Exposer ce domaine, c'est laisser une instance DataHub ouverte pendant
    # toute la fenêtre de jugement. Trois précautions, section 5.1.

    location / {
        proxy_pass http://datahub-frontend:9002;
        include /etc/nginx/snippets/proxy.conf;
    }
}
```

### `dataforensic-mcp.conf` — optionnel

**À ne créer que si vous en avez besoin.** Le pont MCP porte le jeton DataHub
dans son environnement et n'a aucune authentification propre : quiconque atteint
`/mcp` emprunte ce jeton. Rien dans le produit ne passe par ce domaine, et
l'intégration MCP est déjà démontrable via `/api/v1/datahub/status`.

Le seul motif valable de l'exposer : permettre à un juge de brancher son propre
client MCP sur l'instance. C'est une belle démonstration — mais elle se paie
d'une surface d'écriture publique sur votre catalogue, et elle ne rapporte aucun
point sur les critères de jugement que `api.` ne rapporte déjà.

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name mcp.dataforensic.vylantic.com;

    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name mcp.dataforensic.vylantic.com;

    ssl_certificate     /etc/letsencrypt/live/mcp.dataforensic.vylantic.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.dataforensic.vylantic.com/privkey.pem;

    include /etc/nginx/snippets/ssl.conf;
    include /etc/nginx/snippets/security.conf;

    access_log /var/log/nginx/dataforensic-mcp-access.log main;
    error_log  /var/log/nginx/dataforensic-mcp-error.log warn;

    # Le serveur MCP n'a pas d'authentification propre : il porte le jeton
    # DataHub dans son environnement, et quiconque atteint /mcp emprunte ce
    # jeton. Le domaine existe pour prouver que l'intégration est réelle,
    # pas pour ouvrir le catalogue.
    location = /healthz {
        proxy_pass http://dataforensic-mcp:8000/healthz;
        include /etc/nginx/snippets/proxy.conf;
    }

    location / { return 404; }
}
```

> Pour rendre `/mcp` réellement joignable pendant le jugement — brancher Claude
> Desktop dessus fait une démonstration convaincante — remplacer le `return 404`
> par un `proxy_pass` **et** exiger un secret :
>
> ```nginx
> location /mcp {
>     if ($http_authorization != "Bearer <secret-long-et-propre>") { return 401; }
>     proxy_pass http://dataforensic-mcp:8000/mcp;
>     include /etc/nginx/snippets/proxy.conf;
>     proxy_buffering off;
>     proxy_read_timeout 3600s;
> }
> ```
>
> Le `proxy_buffering off` est obligatoire ici aussi : le transport Streamable
> HTTP renvoie des flux SSE.

### 5.1 Exposer DataHub sans le laisser casser

Le domaine `datahub.` est ce qui rend la soumission vérifiable : un juge y voit
le tag écrit par l'agent, ce qu'aucune capture d'écran ne remplace. Mais il
restera ouvert du 17 au 31 août sans surveillance, et une métadonnée modifiée par
un visiteur casserait la démonstration en silence.

1. **Changer `datahub` / `datahub`.** Le mot de passe par défaut est publié dans
   la documentation officielle ; le laisser revient à ne pas avoir de mot de
   passe.
2. **Créer un compte de consultation** et publier ses identifiants dans les
   instructions de test, plutôt que le compte administrateur. DataHub gère des
   rôles et des politiques d'accès — vérifier le nom exact du rôle en lecture
   seule dans *Settings → Permissions* de la version installée avant de
   l'annoncer.
3. **Savoir revenir en arrière.** `datahub datapack unload showcase-ecommerce`
   puis un rechargement remettent le catalogue à plat en une commande. Le tester
   une fois avant la soumission, pas le jour où c'est nécessaire.

Certificats Let's Encrypt : procédure identique au guide Kynara §13, avec les
**trois** domaines requis — et le quatrième seulement s'il est exposé.

---

## 6. CORS — l'étape à ne pas oublier

Le frontend appelle l'API depuis le navigateur, en `fetch` et en `EventSource`.
Sans autorisation d'origine, l'interface se charge parfaitement et reste vide :

```
Access to fetch at 'https://api.dataforensic.vylantic.com/api/v1/incidents'
from origin 'https://dataforensic.vylantic.com' has been blocked by CORS policy
```

Aucun log serveur ne le mentionne. Le réglage tient dans une variable :

```ini
CORS_ORIGINS=https://dataforensic.vylantic.com
```

Pour garder aussi le développement local, la variable accepte une liste :

```ini
CORS_ORIGINS=https://dataforensic.vylantic.com,http://localhost:3000
```

> Ne mettez pas `*`. Le middleware est configuré avec
> `allow_credentials=True`, et un navigateur refuse la combinaison joker +
> credentials : vous obtiendriez une erreur CORS *plus* obscure que celle que
> vous cherchiez à corriger.

---

## 7. Variables d'environnement

### `/var/www/dataforensic/.env`

```ini
# ─── Application ────────────────────────────────────
ENVIRONMENT=production
LOG_LEVEL=INFO
API_PREFIX=/api/v1

# La seule surface CORS du projet (section 6).
CORS_ORIGINS=https://dataforensic.vylantic.com

# ─── PostgreSQL ─────────────────────────────────────
# Nom du container, jamais localhost : sous Docker localhost désigne l'API
# elle-même.
DATABASE_URL=postgresql+asyncpg://dataforensic:CHANGEME@dataforensic-postgres:5432/dataforensic
DB_PASSWORD=                    # openssl rand -hex 24, recopié dans DATABASE_URL

# ─── DataHub ────────────────────────────────────────
# live    = exige un DataHub joignable et échoue bruyamment sinon.
# fixture = graphe déterministe embarqué, étiqueté DEMO_FIXTURE partout.
# auto    = sonde live, bascule sur le graphe et étiquette la bascule.
DATAHUB_MODE=live

# Noms de containers du quickstart, joignables une fois le réseau rattaché
# (section 3.1). Jamais localhost : sous Docker il désigne l'API elle-même.
DATAHUB_URL=http://datahub-gms:8080
DATAHUB_TOKEN=                  # personal access token, section 3.2

# Le pont stdio → HTTP, pas le domaine public : l'agent joint le MCP par le
# réseau Docker et ne sort jamais.
DATAHUB_MCP_URL=http://dataforensic-mcp:8000/mcp

# GMS met plusieurs minutes à répondre au premier démarrage, et une requête de
# lineage sur un graphe fraîchement indexé n'est pas instantanée.
DATAHUB_TIMEOUT_SECONDS=30
DATAHUB_WRITEBACK_ENABLED=true

# ─── LLM (optionnel, strictement consultatif) ───────
# Le moteur déterministe décide toujours de la cause racine. Un LLM ne peut que
# proposer des hypothèses supplémentaires citant des evidence réellement
# collectées, et narrer. `none` garde la démo parfaitement reproductible.
LLM_PROVIDER=none
LLM_MODEL=
LLM_API_KEY=

# ─── Agent ──────────────────────────────────────────
AGENT_LINEAGE_DEPTH=4
AGENT_LOOKBACK_MINUTES=720
CONFIDENCE_CONFIRM_THRESHOLD=0.85
CONFIDENCE_SUPPORT_THRESHOLD=0.60

# ─── Sûreté ─────────────────────────────────────────
# Reste false. La remédiation réelle est refusée côté serveur même si l'agent
# la demande ; sur une instance publique, ce n'est pas une case à décocher.
ALLOW_REAL_REMEDIATION=false
```

> Les chemins des scénarios et du graphe déterministe **ne sont pas dans ce
> fichier** : ils sont figés dans l'image (`SCENARIOS_PATH`,
> `DATAHUB_FIXTURE_PATH`, `DATAHUB_MEMORY_STORE_PATH`), parce qu'ils décrivent
> la disposition interne du container et non l'environnement. Les monter
> ailleurs que sur `/srv/...` casserait le chargement des scénarios.

> Les assets de marque (`apps/web/public/`, `apps/web/app/icon.png`,
> `apple-icon.png`, `favicon.ico`) sont **versionnés**, pas générés au build :
> l'image web n'a donc pas besoin de Pillow. Si vous modifiez le logo, relancez
> `make brand` et committez le résultat avant de déployer.

### Aucun `.env` côté web

Le frontend n'a pas de configuration à l'exécution : `NEXT_PUBLIC_API_URL` est
**inliné dans le bundle au build**. Il se passe donc en `args` du compose, pas
en `environment`. Le modifier impose de reconstruire l'image — le changer dans
un `.env` n'aurait aucun effet, et c'est le genre de piège où l'on perd une
heure à se demander pourquoi l'interface interroge toujours `localhost:8000`.

---

## 8. `docker-compose.prod.yml`

Le `docker-compose.yml` du dépôt est un fichier de développement : il publie
tous les ports sur l'hôte, y compris PostgreSQL, et pointe le frontend vers
`localhost:8000`. En production, aucun de ces choix n'est correct.

### `/var/www/dataforensic/docker-compose.prod.yml`

```yaml
name: dataforensic

services:
  api:
    build:
      context: ./apps/api
    container_name: dataforensic-api
    restart: unless-stopped
    env_file: [.env]
    depends_on:
      postgres: {condition: service_healthy}
      mcp: {condition: service_started}
    networks: [dataforensic-network, proxy-network]
    # Pas de ports: publiés — Nginx joint le container par le réseau proxy.
    # DataHub n'est pas déclaré ici : son quickstart tourne dans son propre
    # compose et a été rattaché au réseau (section 3.1). Le déclarer en
    # `depends_on` créerait une dépendance sur des containers que ce fichier ne
    # gère pas.
    volumes:
      # Les chemins correspondent aux ENV figés dans l'image. Les scénarios et
      # le graphe sont montés en lecture seule : ce sont des données de
      # référence, l'application n'a aucune raison de les modifier.
      - ./scenarios:/srv/scenarios:ro
      - ./datahub/seed:/srv/datahub/seed:ro
      # La mémoire du provider fixture doit survivre à un redéploiement, sinon
      # l'organisation « oublie » ce qu'elle a appris à chaque `up -d`.
      - dataforensic-state:/srv/state
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request;urllib.request.urlopen('http://localhost:8000/api/v1/health')\""]
      interval: 15s
      timeout: 5s
      retries: 10

  web:
    build:
      context: ./apps/web
      args:
        # Inliné au build. C'est l'URL publique de l'API : le navigateur
        # l'appelle directement, y compris pour le flux SSE.
        NEXT_PUBLIC_API_URL: https://api.dataforensic.vylantic.com/api/v1
    container_name: dataforensic-web
    restart: unless-stopped
    depends_on:
      api: {condition: service_healthy}
    networks: [dataforensic-network, proxy-network]

  mcp:
    # Le serveur MCP officiel est stdio ; supergateway l'expose en Streamable
    # HTTP. L'image est construite ici : voir section 3.3.
    build:
      context: ./datahub/mcp-bridge
    container_name: dataforensic-mcp
    restart: unless-stopped
    environment:
      DATAHUB_GMS_URL: http://datahub-gms:8080
      DATAHUB_GMS_TOKEN: ${DATAHUB_TOKEN}
      TOOLS_IS_MUTATION_ENABLED: "false"
    networks: [dataforensic-network, proxy-network]

  postgres:
    image: postgres:16-alpine
    container_name: dataforensic-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: dataforensic
      POSTGRES_USER: dataforensic
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    networks: [dataforensic-network]
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U dataforensic"]
      interval: 10s
      timeout: 3s
      retries: 20

networks:
  dataforensic-network:
    external: true
  proxy-network:
    external: true

volumes:
  postgres-data:
  dataforensic-state:
```

### DataHub n'est pas dans ce fichier

Volontairement. Son quickstart est un compose de dix services maintenu par
DataHub ; le recopier ici reviendrait à en maintenir une copie qui divergera à
la première mise à jour. Il tourne à côté, rattaché au même réseau, et ce
compose ne décrit que ce que ce projet possède.

Conséquence pratique : `docker compose -f docker-compose.prod.yml down` n'arrête
pas DataHub, et `datahub docker quickstart --stop` n'arrête pas l'application.
Deux cycles de vie séparés, ce qui est aussi ce qu'on veut le jour où il faut
redémarrer l'un sans l'autre.

---

## 9. Premier déploiement

L'ordre compte : DataHub d'abord, parce que le jeton n'existe pas avant lui et
que le reste en dépend.

```bash
# 1. DataHub (section 3.1), puis le jeton (3.2)
uvx --from acryl-datahub datahub docker quickstart
uvx --from acryl-datahub datahub init --username datahub --password datahub
docker network connect --alias datahub-gms \
  dataforensic-network datahub-datahub-gms-quickstart-1

# 2. L'application
cd /var/www/dataforensic
git clone <votre-repo> .
cp .env.example .env
# éditer .env : DB_PASSWORD, DATABASE_URL, CORS_ORIGINS, DATAHUB_TOKEN

docker compose -f docker-compose.prod.yml config >/dev/null
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

# 3. Le contexte
uvx --from acryl-datahub datahub datapack load showcase-ecommerce
```

**Aucune migration à lancer.** Le schéma est créé au démarrage
(`init_db()` → `create_all`) : c'est un choix assumé de MVP, adapté à un
modèle qui n'évolue plus, et il évite d'embarquer Alembic pour sept tables. La
contrepartie est réelle et il faut la connaître : **un changement de schéma
après un déploiement ne sera pas appliqué à une base existante.** Le jour où
cela arrive, la manœuvre honnête est de sauvegarder, supprimer le volume et
laisser la base se recréer.

Vérifier immédiatement que les scénarios sont visibles depuis le container —
c'est le point où une erreur de montage se manifeste :

```bash
docker compose -f docker-compose.prod.yml exec api \
  python -c "from app.services.scenario import get_registry; print([s.id for s in get_registry().all()])"
```

```
['healthcare-quality', 'pipeline-freshness', 'revenue-collapse']
```

Une liste vide signifie que `./scenarios` n'est pas monté sur `/srv/scenarios`.

Créer ensuite l'incident de démonstration :

```bash
curl -sS -X POST https://api.dataforensic.vylantic.com/api/v1/incidents \
  -H 'Content-Type: application/json' \
  -d @scenarios/revenue-collapse/incident.json | python3 -m json.tool
```

---

## 10. Vérifications

```bash
# Les deux domaines répondent
curl -sS https://dataforensic.vylantic.com | head -5
curl -sS https://api.dataforensic.vylantic.com/api/v1/health | python3 -m json.tool
```

La santé doit annoncer la base, la source de contexte et le moteur :

```json
{
  "status": "ok",
  "database": "ok",
  "datahub": {"mode": "fixture", "source_mode": "DEMO_FIXTURE", "connected": true},
  "llm": {"provider": "none", "enabled": false}
}
```

### La chaîne DataHub — à vérifier avant tout le reste

Trois maillons, trois commandes. Chacun échoue différemment, et les confondre
coûte une heure.

```bash
# 1. GMS répond
docker compose -f docker-compose.prod.yml exec api \
  python -c "import urllib.request;print(urllib.request.urlopen('http://datahub-gms:8080/health').status)"

# 2. Le pont MCP est vivant
docker compose -f docker-compose.prod.yml exec api \
  python -c "import urllib.request;print(urllib.request.urlopen('http://dataforensic-mcp:8000/healthz').read())"

# 3. Le serveur MCP annonce ses outils — c'est ici que le jeton se valide
curl -sS https://api.dataforensic.vylantic.com/api/v1/datahub/status | python3 -m json.tool
```

La réponse doit annoncer `LIVE_DATAHUB` **et** lister les outils :

```json
{
  "mode": "live",
  "source_mode": "LIVE_DATAHUB",
  "connected": true,
  "tools": ["search", "get_entities", "list_schema_fields", "get_lineage", "..."]
}
```

Une liste `tools` vide avec `connected: true` est le cas le plus trompeur : GMS
répond, mais la poignée de main MCP a échoué. Regarder les logs du pont —
`docker compose -f docker-compose.prod.yml logs mcp` — où un jeton invalide
apparaît en clair comme un 401 au premier `tools/list`.

### Le flux SSE — la vérification qui compte

C'est le seul endroit où le proxy peut casser la démonstration sans casser
l'application. Lancer une investigation et regarder les événements **arriver un
par un** :

```bash
INC=$(curl -sS -X POST https://api.dataforensic.vylantic.com/api/v1/incidents \
  -H 'Content-Type: application/json' \
  -d @scenarios/revenue-collapse/incident.json | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")

INV=$(curl -sS -X POST https://api.dataforensic.vylantic.com/api/v1/incidents/$INC/investigate \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['investigation_id'])")

curl -N https://api.dataforensic.vylantic.com/api/v1/investigations/$INV/events
```

Les lignes doivent se dérouler progressivement. Si elles apparaissent toutes
d'un coup à la fin, `proxy_buffering off` n'est pas pris en compte : le vhost
n'a pas été rechargé, ou la requête ne tombe pas dans le bloc `location`.

Puis le résultat complet :

```bash
curl -sS https://api.dataforensic.vylantic.com/api/v1/investigations/$INV \
  | python3 -c "
import json,sys
d = json.load(sys.stdin)
print('cause  :', d['root_cause']['pattern'], round(d['root_cause']['confidence']*100), '%')
print('trust  :', d['trust']['score'], d['trust']['decision'])
print('impact :', d['blast_radius']['total_affected_assets'], 'assets')
print('verify :', d['verification']['status'])
print('memory :', d['memory']['write_back_status'])
print('source :', d['datahub_source_mode'])
"
```

```
cause  : SCHEMA_DRIFT 97 %
trust  : 85.0 HIGH_CONFIDENCE
impact : 9 assets
verify : PASS
memory : VERIFIED
source : DEMO_FIXTURE
```

### La boucle d'apprentissage

Rejouer le **même** incident et vérifier que l'organisation a appris :

```bash
curl -sS https://api.dataforensic.vylantic.com/api/v1/patterns | python3 -m json.tool
```

Le pattern `SCHEMA_DRIFT` doit exister, avec sa remédiation vérifiée. La seconde
investigation doit afficher `matched_pattern`, `remediation_source:
knowledge_pattern:SCHEMA_DRIFT`, et un trust score plus élevé.

---

## 11. Déploiement continu

### `/usr/local/bin/deploy-dataforensic.sh`

```bash
#!/bin/bash
set -euo pipefail

cd /var/www/dataforensic
COMPOSE="docker compose -f docker-compose.prod.yml"

git pull --ff-only
$COMPOSE build
$COMPOSE up -d

# Le schéma est créé au démarrage : rien à migrer. En revanche l'image web doit
# être reconstruite dès que l'URL de l'API change, puisqu'elle y est inlinée.

$COMPOSE ps
curl -sSf https://api.dataforensic.vylantic.com/api/v1/health >/dev/null \
  && echo "api ok" || echo "API KO — voir logs api"

docker image prune -f
```

```bash
sudo chmod +x /usr/local/bin/deploy-dataforensic.sh
```

---

## 12. Sauvegardes

### `/usr/local/bin/backup-dataforensic.sh`

```bash
#!/bin/bash
set -euo pipefail

DEST=/var/backups/dataforensic
STAMP=$(date +%F-%H%M)
mkdir -p "$DEST"

# PostgreSQL : incidents, investigations, evidence, patterns appris. C'est la
# mémoire de l'organisation côté application.
docker exec dataforensic-postgres pg_dump -U dataforensic dataforensic \
  | gzip > "$DEST/db-$STAMP.sql.gz"

# En mode fixture, le write-back vit dans un volume et non dans DataHub :
# sans lui, l'instance oublie ce qu'elle a écrit.
docker run --rm -v dataforensic_dataforensic-state:/state -v "$DEST":/backup alpine \
  tar czf "/backup/state-$STAMP.tar.gz" -C /state .

find "$DEST" -name '*.gz' -mtime +7 -delete
```

```bash
sudo chmod +x /usr/local/bin/backup-dataforensic.sh
sudo crontab -e
# 0 3 * * * /usr/local/bin/backup-dataforensic.sh >> /var/log/backup-dataforensic.log 2>&1
```

> En mode `live`, la mémoire institutionnelle est dans DataHub et c'est
> **DataHub** qu'il faut sauvegarder. Le volume `dataforensic-state` n'y sert
> plus à rien.

---

## 13. Dépannage

### L'interface se charge et reste vide

CORS. Ouvrir la console du navigateur : le message est explicite alors
qu'aucun log serveur ne mentionne rien. Vérifier que `CORS_ORIGINS` contient
exactement `https://dataforensic.vylantic.com` — schéma compris, sans barre
oblique finale — puis redémarrer l'API.

Si la console ne montre pas de CORS mais des appels vers `localhost:8000`,
l'image web a été construite sans l'argument : reconstruire avec
`--build-arg NEXT_PUBLIC_API_URL=…`.

### La timeline arrive d'un bloc à la fin

Le proxy tamponne. Vérifier que la requête tombe bien dans le bloc `location ~
^/api/v1/investigations/[^/]+/events$`, puis `nginx -t && nginx -s reload`.
L'application envoie déjà `X-Accel-Buffering: no`, donc si le comportement
persiste c'est que le vhost chargé n'est pas celui que vous éditez.

### `Investigation blocked` au lieu d'une cause racine

C'est le comportement correct, pas une panne : l'agent refuse de nommer une
cause qu'il ne peut pas prouver. Le champ `blocked_reason` dit laquelle des
deux situations s'applique :

- contexte DataHub indisponible → vérifier `DATAHUB_URL` et `DATAHUB_MCP_URL`,
  ou basculer en `fixture` ;
- aucune hypothèse au-dessus du seuil de preuve → l'incident vise un asset sans
  signal, ce qui arrive si l'`asset_urn` n'existe pas dans le graphe chargé.

### La liste des scénarios est vide

Montage. Les chemins de l'image sont `/srv/scenarios` et
`/srv/datahub/seed` ; un compose recopié d'une ancienne version pointe peut-être
encore sur `/app/...`.

### `tools` est vide alors que DataHub répond

État le plus trompeur du déploiement : GMS renvoie 200, `/healthz` du pont
renvoie `ok`, `connected` vaut `true` — et la liste d'outils est vide. Les deux
vérifications vertes portent sur des choses différentes de celle qui a échoué.

**Lire d'abord `/api/v1/datahub/status`**, qui rapporte désormais la poignée de
main elle-même :

```json
"mcp": { "configured": true, "ready": false, "tools": [],
         "error": "...", "detail": "..." }
```

Puis les logs du pont, où la vraie cause apparaît en clair :

```bash
docker compose -f docker-compose.prod.yml logs mcp | tail -40
```

Causes, par ordre de fréquence :

1. **Le processus enfant est mort au démarrage.** Signature dans les logs :

   ```
   error: command 'c++' failed: No such file or directory
   help: `google-re2` was included because `mcp-server-datahub` depends on it
   [supergateway] Child exited: code=1
   ```

   C'est le symptôme d'une image de pont basée sur Alpine. `google-re2` ne
   publie que des wheels **manylinux** (glibc) ; sur musl, pip les refuse et
   tente une compilation qui échoue faute de toolchain C++. Le pont continue
   pourtant de répondre `ok` sur `/healthz`, parce que supergateway est bien
   vivant — c'est son enfant qui ne l'est pas. Solution : utiliser l'image
   construite depuis `datahub/mcp-bridge/` (section 3.3), qui est basée sur
   Debian et installe le serveur au build.

2. **`DATAHUB_TOKEN` absent ou expiré** — le pont le transmet en
   `DATAHUB_GMS_TOKEN`, et le serveur échoue au premier appel authentifié.

3. **`--stateful` oublié** : le client négocie une session à l'`initialize`, et
   sans état chaque appel repart d'une poignée de main.

> Dans les trois cas, l'investigation **fonctionne quand même** : chaque lecture
> retombe sur GraphQL, et le badge affiche toujours `LIVE DATAHUB` parce que le
> contexte vient bien d'un DataHub réel. Ce qui se perd, c'est la démonstration
> que le chemin MCP est emprunté — d'où l'intérêt de regarder ce champ avant la
> vidéo plutôt qu'après.

### L'agent trouve l'asset mais aucun lineage

Le datapack n'a pas fini d'être indexé. Elasticsearch rend les entités
consultables avant que le graphe de lineage ne soit complet ; réessayer après
quelques minutes plutôt que de conclure à un bug de l'agent.

### GMS redémarre en boucle

Mémoire. `docker stats` pendant le démarrage : si OpenSearch approche la
limite, le droplet est sous-dimensionné. C'est le mode d'échec numéro un d'un
DataHub embarqué, et il ne ressemble pas à un problème de RAM depuis les logs
applicatifs.

### 502 Bad Gateway

`dataforensic-web`, `dataforensic-api` et le frontend DataHub doivent être dans
`proxy-network` :

```bash
docker network inspect proxy-network | grep -E "dataforensic|datahub"
```

Le frontend DataHub doit y être rattaché explicitement, avec le même alias :

```bash
docker network connect --alias datahub-frontend \
  proxy-network datahub-frontend-quickstart-1
```

Le rattachement ne survit pas à un `datahub docker quickstart --stop` suivi d'un
redémarrage : il faut le rejouer.

### Les patterns appris ont disparu après un redéploiement

Le volume `dataforensic-state` n'est pas monté, ou un `docker compose down -v`
est passé par là. En mode `fixture`, c'est là que vit la mémoire écrite.

---

## 14. Checklist avant de donner l'URL aux juges

- [ ] Les **trois** domaines requis répondent en HTTPS, certificats valides
      (`mcp.` seulement s'il a été délibérément exposé)
- [ ] `datahub.` affiche l'interface DataHub, et le mot de passe par défaut
      `datahub/datahub` a été changé
- [ ] `/api/v1/datahub/status` liste des outils MCP non vides
- [ ] Le tag `DataForensic:SCHEMA_DRIFT` est visible sur `sales_daily` dans
      l'interface DataHub — c'est la preuve du write-back
- [ ] `/api/v1/health` renvoie `status: ok` et une base `ok`
- [ ] Le badge de l'interface affiche `LIVE DATAHUB` — et le discours de la démo
      correspond au badge
- [ ] `curl -N` sur `/events` déroule les événements progressivement
- [ ] Une investigation complète a été jouée **sur l'instance déployée**, pas
      seulement en local
- [ ] `/api/v1/patterns` contient au moins un pattern vérifié, pour que la
      seconde investigation démontre l'apprentissage
- [ ] `ALLOW_REAL_REMEDIATION=false`
- [ ] `/api/v1/demo/reset` renvoie 403 depuis Internet
- [ ] Un compte de consultation DataHub existe, et ses identifiants sont dans les
      instructions de test
- [ ] `datapack unload` + rechargement a été testé une fois
- [ ] `openssl rand` a servi pour le mot de passe PostgreSQL — aucun mot de
      passe du `.env.example` ne survit
- [ ] Les scénarios sont listés depuis le container, pas seulement sur disque
