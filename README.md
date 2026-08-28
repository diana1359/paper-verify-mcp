# paper-verify-mcp

PubMed · Crossref · OpenAlex **세 곳의 데이터베이스로 논문의 실재 여부를 교차 검증**하는 MCP 서버입니다.
환각(hallucinated)·오기재 인용을 걸러낼 때 씁니다. 공개 데이터만 읽으므로 **인증(OAuth) 불필요**합니다.

## 제공하는 툴

| 툴 | 설명 |
|---|---|
| `verify_by_doi(doi)` | DOI로 세 DB 동시 조회 |
| `verify_by_title(title, author?, year?)` | 제목으로 퍼지 매칭 조회 (유사도 0~1) |
| `check_citation(citation)` | 자유 형식 인용 문자열에서 DOI/제목 자동 추출 후 조회 |

### 판정(verdict) 값
- `LIKELY_REAL` — 2곳 이상에서 확인 (실재 가능성 높음)
- `POSSIBLY_REAL` — 1곳에서만 확인 (색인 시차이거나 제목 유사도 매칭 → 메타데이터 대조 권장)
- `NOT_FOUND` — 어디에도 없음 (환각 인용 의심)
- `UNKNOWN` — 전부 조회 실패 (네트워크/요청 한도 → 재시도)

응답에는 각 소스별 `title / authors / year / journal / url / match_score` 가 함께 담겨,
검증하려는 인용과 직접 대조할 수 있습니다.

---

## 1. 로컬 실행 & 테스트

```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # CONTACT_EMAIL 등 채우기 (선택)
python server.py            # http://0.0.0.0:8000/mcp
```

`fastmcp` 내장 인스펙터로 툴을 직접 호출해 볼 수 있습니다:

```bash
fastmcp dev server.py       # 브라우저에서 툴 실행/스키마 확인
```

> ⚠️ Claude 커넥터는 **Anthropic 클라우드에서** 서버로 접속합니다.
> `localhost`·사내망·VPN 뒤 주소는 등록해도 연결되지 않습니다. 반드시 **공개 HTTPS URL** 이 필요합니다.

---

## 2. 공개 서버로 배포하기

> ⚠️ **중요 — Claude 웹/앱 커넥터로 연결하려면 상시 실행형 호스트를 쓰세요 (Vercel ✗ / Render ✓).**
>
> Claude의 커스텀 커넥터는 "연결(Connect)" 시 **OAuth 자동 등록(DCR)** 을 반드시 시도합니다.
> 서버에 OAuth 가 전혀 없으면 *"Couldn't register with … sign-in service"* 오류로 연결이 실패합니다
> (인증 없는 서버라도 마찬가지 — Claude의 알려진 동작).
>
> 그래서 이 서버는 **`PUBLIC_URL`(또는 Render 의 자동 변수)이 설정되면, 로그인 없이 자동 승인되는
> 공개용 OAuth 를 스스로 켜서** 이 문제를 해결합니다. 단, 이 OAuth 는 등록정보를 **메모리**에 담으므로
> **단일 상시 프로세스**(Render / Railway / Fly)에서만 동작합니다.
> **Vercel 서버리스는 요청마다 인스턴스가 초기화돼 OAuth 흐름이 깨지므로, 커넥터 연결 용도로는 쓰지 마세요.**
> (Vercel 배포 자체는 되지만, Claude UI 에서 "연결" 버튼이 실패합니다.)
>
> → **결론: 커넥터로 쓰려면 아래 "옵션 B) Render" 를 따르세요.**

> ❓ **"GitHub에 sources.py만 올리면 되나요?"** → 아니요.
> `sources.py` 는 `server.py` 가 불러 쓰는 모듈일 뿐입니다. 아래 파일 전체를 올려야 합니다:
> ```
> paper-verify-mcp/
> ├── api/index.py        ← Vercel 진입점 (서버리스)
> ├── server.py           ← MCP 서버 + 툴 정의
> ├── sources.py          ← 세 DB 조회 로직
> ├── requirements.txt    ← 의존성 (Vercel이 이걸로 설치)
> ├── vercel.json         ← Vercel 라우팅
> ├── .env.example
> └── README.md
> ```
> (`Dockerfile`, `render.yaml` 은 Render/Railway/Fly 용이라 Vercel만 쓸 거면 없어도 되지만, 있어도 무방합니다.)

### 옵션 A) Vercel + GitHub  (⚠️ authless 전용 — Claude 커넥터 연결은 실패)

> Vercel 은 서버리스라 위에서 설명한 OAuth 를 유지하지 못합니다. 서버는 뜨지만 Claude "연결" 버튼에서
> *"Couldn't register with sign-in service"* 로 실패합니다. **커넥터로 쓸 거면 옵션 B(Render) 로 가세요.**
> (Vercel 은 다른 MCP 클라이언트나 authless 테스트 용도로만 참고.)

Vercel은 **서버리스**라 이 저장소는 그에 맞게 이미 구성돼 있습니다
(`api/index.py` 진입점 + stateless 모드 + lifespan 자동 초기화 + 단일 JSON 응답).

**1) GitHub에 올리기** (로컬에서)
```bash
cd paper-verify-mcp
git init
git add .
git commit -m "paper verify mcp"
git branch -M main
git remote add origin https://github.com/<본인아이디>/<저장소>.git
git push -u origin main
```
> 이미 GitHub 웹의 빈 저장소에 들어와 있다면, 그 페이지의 **"uploading an existing file"** 링크로
> 위 파일들을 **폴더 구조 그대로**(특히 `api/index.py` 는 `api` 폴더 안에) 드래그해 올려도 됩니다.

**2) Vercel에서 배포**
1. [vercel.com](https://vercel.com) 로그인 → **Add New… → Project**.
2. 방금 push한 GitHub 저장소를 **Import**.
3. Framework Preset 은 **Other**(자동 감지) 그대로 두기. Vercel이 `requirements.txt` + `api/` 를 보고 Python으로 인식합니다.
4. **Environment Variables** 에 (선택) `CONTACT_EMAIL`, `NCBI_API_KEY` 추가.
5. **Deploy** 클릭.

**3) 커넥터 URL**
배포되면 `https://<프로젝트>.vercel.app` 이 발급됩니다. 커넥터 URL은 여기에 `/mcp` 를 붙인 것:
```
https://<프로젝트>.vercel.app/mcp
```

**Vercel 주의점**
- **실행 시간 제한**: Hobby(무료) 플랜은 함수 실행 시간 제한이 있습니다(대체로 문제 없지만, 세 DB가 느릴 때 드물게 걸릴 수 있음). 필요하면 `vercel.json` 에 아래를 추가하세요(플랜이 허용하는 값 내에서):
  ```json
  { "functions": { "api/index.py": { "maxDuration": 60 } },
    "rewrites": [ { "source": "/(.*)", "destination": "/api/index" } ] }
  ```
  (배포가 maxDuration 관련 에러를 내면 그 줄을 빼면 됩니다.)
- **콜드 스타트**: 유휴 후 첫 호출이 몇백 ms~1초 느릴 수 있습니다.
- 이 서버는 이미 stateless + Vercel 호스트 허용으로 맞춰져 있어 별도 수정 없이 동작합니다.

---

### 옵션 B) Render  ★ 커넥터로 쓰려면 이 경로 (무료 티어)

상시 실행형 단일 프로세스라, 위에서 설명한 자동 OAuth 가 제대로 동작합니다.

1. 이 폴더를 GitHub 저장소로 push.
2. [render.com](https://render.com) → **New → Web Service** → 저장소 선택.
3. Runtime 이 **Docker** 로 잡히는지 확인 (`render.yaml` 자동 인식).
4. Environment 에 `CONTACT_EMAIL`(권장), `NCBI_API_KEY`(선택) 입력 → **Create**.
   - **`PUBLIC_URL` 은 설정할 필요 없음** — Render 가 `RENDER_EXTERNAL_URL` 을 자동 주입하고,
     서버가 그걸 감지해 OAuth 를 자동으로 켭니다.
5. 배포 완료 후 발급되는 주소 뒤에 `/mcp` 를 붙인 게 커넥터 URL:
   `https://<서비스이름>.onrender.com/mcp`

> 무료 티어는 유휴 시 슬립 → 첫 호출이 몇 초 느릴 수 있고(콜드 스타트),
> **서버가 재시작되면 기존 OAuth 등록이 초기화**되어 Claude 에서 한 번 재연결이 필요할 수 있습니다
> (공개 도구라 재연결도 로그인 없이 자동 승인되어 클릭 한 번이면 됩니다).

### 옵션 C) Railway
1. [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**.
2. Dockerfile 자동 인식 → Variables 에 `CONTACT_EMAIL` 등 추가.
3. **Settings → Networking → Generate Domain** 으로 공개 도메인 발급.
4. **Variables 에 `PUBLIC_URL=https://<발급된도메인>` 을 추가**(Railway 는 자동 주입이 없으므로 수동 설정) → 재배포.
5. 커넥터 URL: `https://<도메인>/mcp`

### 옵션 D) Fly.io (CLI)
```bash
fly launch --no-deploy                                   # fly.toml 생성 (내부 포트 8000 확인)
fly secrets set CONTACT_EMAIL=you@example.com
fly secrets set PUBLIC_URL=https://<앱이름>.fly.dev       # OAuth용 (수동 설정)
fly deploy
```
커넥터 URL: `https://<앱이름>.fly.dev/mcp`

### 배포 검증
공개 URL이 나오면 아래로 핸드셰이크가 되는지 확인하세요(정상이면 JSON-RPC 결과가 옴):
```bash
curl -sL -X POST https://<당신-도메인>/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

---

## 3. Claude 커넥터로 등록

**Pro / Max 개인 플랜**
1. Claude → **Settings(설정) → Connectors(커넥터)**.
2. Connectors 옆 **`+`** → **Add custom connector**.
3. 이름(예: `Paper Verifier`)과 URL(`https://<도메인>/mcp`) 입력.
4. **Advanced/OAuth 클라이언트 ID·시크릿 칸은 비워둡니다** — 서버가 자동 등록(DCR)을 처리합니다.
5. **Add** → 커넥터 옆 **Connect** 클릭 → (로그인 화면 없이 자동 승인되어) 연결됨 → 대화창 `+` 메뉴에서 켜서 사용.

> "연결"이 여전히 실패한다면: (a) Render 등 **상시 실행형 호스트**인지, (b) `/mcp` 로 요청 시 **401**이 오는지
> (= OAuth 가 켜졌다는 뜻) 확인하세요. 200 이 오면 authless 상태라 `PUBLIC_URL` 이 설정 안 된 것입니다.

**Team / Enterprise 플랜**
- 개인은 추가 불가. **Owner/Primary Owner** 가 **Organization settings → Connectors → Add → Custom → Web** 에서 URL 등록 후, 구성원이 각자 **Connect**.

등록 후 Claude 에게 이렇게 시키면 됩니다:
> "이 DOI가 실재하는 논문인지 확인해줘: 10.1038/nature12373"
> "다음 참고문헌들이 진짜인지 세 DB로 검증해줘: …"

---

## 참고 / 주의
- **색인 시차**: 아주 최신 논문이나 특정 분야는 한 DB에만 있을 수 있습니다 → `POSSIBLY_REAL` 이면 메타데이터를 꼭 대조하세요.
- **분야 편중**: PubMed는 생의학 중심이라, 비의학 논문은 Crossref/OpenAlex 위주로 확인됩니다.
- **요청 한도**: 대량 검증 시 `NCBI_API_KEY` 설정과 `CONTACT_EMAIL`(polite pool) 지정을 권장합니다.
- **read-only**: 이 서버는 조회만 하며 어떤 데이터도 변경하지 않습니다.
