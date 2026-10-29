# InkLab

이미지·PDF에 담긴 개인 필기 샘플을 등록하고, LaTeX 수식과 텍스트를 기존 PDF 위에 배치하는 **Windows 로컬 앱 + MCP 서버**입니다.

현재는 **동작 가능한 초기 버전**입니다. 등록한 글자 이미지를 수식의 해당 글자 위치에 실제로 넣습니다. 개인 필기체를 신경망으로 학습하거나, 몇 장의 노트에서 모든 한글·수학 기호를 자동 복제하는 모델은 아닙니다. 등록하지 않은 글자는 기본 글꼴로 표시하고 목록을 알려줍니다.

## 실행

Python 3.11 이상이 필요합니다. 이 프로젝트의 `.venv`와 `node_modules`가 이미 준비되어 있으면 `start.cmd`를 더블클릭하세요.

처음 설치하는 컴퓨터에서는 PowerShell에서:

```powershell
cd "프로젝트 폴더"
powershell -ExecutionPolicy Bypass -File .\setup.ps1
.\start.cmd
```

브라우저에서 **http://127.0.0.1:8765** 를 엽니다. 서버는 이 컴퓨터의 루프백 주소에만 바인딩됩니다. 종료는 실행 창에서 Ctrl+C입니다. 설치에는 인터넷이 필요하며, 필기 등록·수식 렌더링·PDF 저장은 설치 후 오프라인에서도 동작합니다.

## 사용 순서

1. **나의 필기체**에서 노트 이미지(PNG/JPG/WEBP) 또는 필기 PDF를 가져옵니다.
2. 글자 하나를 드래그해서 선택하고 **선택한 영역 사용**을 누릅니다. 해당 글자를 입력하고 **필기 등록**을 누릅니다. 화면에 직접 쓸 수도 있습니다.
3. 자주 쓰는 `0~9`, 영문 변수, 그리스 문자와 기호부터 등록하세요. 같은 글자는 최대 12개 변형을 보관합니다. 한글은 완성된 음절 단위로 등록합니다.
4. **PDF 작업실**에서 과제 PDF를 올립니다. **예제 문서로 둘러보기**로 먼저 시험할 수도 있습니다.
5. 텍스트·수식 블록을 추가하고 내용과 위치를 정합니다. 수식은 LaTeX를 사용합니다. 마우스로 블록을 옮길 수 있습니다.
6. **필기 미리보기**를 누르면 실제 PDF를 생성하고 그 PDF를 렌더링해 보여줍니다. 적용하지 못한 글자와 블록 겹침을 확인한 뒤 다운로드합니다.

수식 예:

```tex
\int_0^1 x^2\,dx=\frac{1}{3}
\begin{bmatrix}1&2\\3&4\end{bmatrix}\begin{bmatrix}x\\y\end{bmatrix}
\begin{aligned}F&=ma\\a&=\frac{F}{m}\end{aligned}
\frac{\partial^2 u}{\partial t^2}=c^2\nabla^2u
```

수식에 한글 문장을 섞는 대신 별도의 텍스트 블록을 사용하세요. 좌표는 PDF 왼쪽 위 기준 pt, 페이지 번호는 내부 API에서 0부터 시작합니다. 수식·텍스트가 블록을 넘으면 잘라 저장하지 않고 오류로 알려줍니다. 배치를 저장하면 문서를 다시 열 때 복원됩니다.

## MCP 연결

`setup.ps1`이 현재 컴퓨터 경로를 넣은 다음 예제 파일들을 생성합니다. 기존 클라이언트 설정을 자동 변경하지 않습니다.

- `codex-mcp.example.toml`: Codex 설정에 추가할 `[mcp_servers.inklab]` 항목
- `mcp-config.example.json`: `mcpServers` 형식을 쓰는 다른 로컬 클라이언트용

MCP가 실행하는 명령은 프로젝트의 Python과 `scripts/run_mcp.py`입니다. 절대 경로로 작성되어 다른 작업 디렉터리에서도 실행됩니다. 프로젝트를 이동했다면 `scripts/write_config.py`를 다시 실행하세요.

대화 예:

> InkLab에 올린 과제 PDF를 확인하고 1번 문제의 풀이를 만들어줘. 페이지 이미지를 보고 빈 공간에 LaTeX 수식과 설명을 배치한 뒤, 내 필기 프로필로 PDF를 생성하고 결과 이미지를 확인해줘.

제공 도구:

| 도구 | 기능 |
|---|---|
| `list_documents` / `inspect_pdf` | 업로드 문서·페이지 크기·텍스트 조회 |
| `import_pdf` | `data/inbox` 안에 사용자가 넣은 PDF 가져오기 |
| `get_page_image` | 원본 페이지를 모델이 볼 수 있는 이미지로 반환 |
| `list_handwriting_profiles` | 등록 글자와 변형 개수 조회 |
| `register_glyph` | 실제 필기 PNG 및 S펜 원본 획 등록 |
| `start_handwriting_session` | 적응형 필체 학습 세션 시작 및 부족한 자모/기호 추천 |
| `get_handwriting_profile_status` | 등록 글자·원본 획·자모 커버리지·개인 스타일 메트릭 조회 |
| `generate_handwriting_sentence` | 미등록 한글 문장 AI 개인화 필체 생성 (Job ID) |
| `suggest_annotation_positions` | PDF 페이지 내 빈 공간(주석 배치 영역) 자동 탐지 |
| `analyze_and_solve_pdf` | PDF 내용 분석·풀이 초안 생성 및 빈 공간 자동 배치 (Job ID) |
| `get_job_status` | 장시간 AI 필체 생성·PDF 분석 작업 상태 조회 |
| `get_export_preview` | 생성된 PDF 메타데이터·필체 사용 통계·다운로드 URL 조회 |
| `load_layout` | 저장한 배치 불러오기 |
| `render_pdf` | 수식·설명을 필기로 렌더링하고 편집 배치 저장 |
| `get_export_page_image` | 생성된 결과의 페이지 이미지 확인 |

MCP에 연결한 대화 모델이 풀이를 작성하는 경우 InkLab 자체에는 별도 OpenAI API 키가 필요하지 않습니다. 모델·클라이언트의 요금과 권한은 별개입니다. 다운로드 URL을 열려면 웹 서버도 실행되어 있어야 합니다.

로컬 MCP는 **stdio**, 친구와 함께 쓰는 공용 버전은 **OAuth 인증을 사용하는 HTTPS MCP**입니다. 공용 버전 배포 절차와 제한은 [deploy/README.md](deploy/README.md)를 참고하세요. 학교 LMS 제출 기능은 아직 없습니다. 내려받은 PDF를 직접 제출할 수 있습니다.

## 앱 안의 GPT 초안 기능

원하는 경우 서버를 실행하기 전에 환경변수를 설정합니다. PDF 입력과 structured outputs를 지원하고 본인 API 계정에서 사용 가능한 모델 ID를 넣으세요.

```powershell
$env:OPENAI_API_KEY = "내 API 키"
$env:OPENAI_MODEL = "사용 가능한 모델 ID"
.\start.ps1
```

**PDF 전송 · 초안 생성**을 누를 때만 과제 PDF와 요청 내용을 OpenAI Responses API에 전송합니다. 필기 샘플은 이 요청에 포함하지 않습니다. 키를 프런트엔드나 프로젝트 파일에 저장하지 않습니다. API 비용은 별도이며, API 키가 없더라도 나머지 기능과 MCP 서버는 사용할 수 있습니다. GPT가 만든 초안의 수학적 정답과 배치가 자동 검증되는 것은 아닙니다.

## 구현과 한계

- MathJax가 분수·적분·행렬·첨자 구조를 배치합니다. 등록한 글자 이미지는 각 글자의 경계 상자에 맞춰 교체합니다. 반복 변형은 seed로 재현됩니다.
- 필기 원본의 기울기·획 모양은 이미지로 유지되지만 글자 간 연결, 문맥에 따른 운필, 전체 필기 리듬을 학습하지 않습니다. 수학 구조선과 늘어나는 괄호 일부는 기본 렌더링을 유지합니다.
- 흰 종이에 진한 필기를 권장합니다. 격자·밑줄·그림자·옆 글자가 crop 안에 들어오면 함께 등록될 수 있습니다. 글자를 확인하고 잘라주세요.
- 원본 PDF는 보관하고 새 PDF에 투명 이미지를 덧씌웁니다. 추가한 필기 부분은 검색 가능한 텍스트나 PDF 펜 주석이 아닙니다. 기존 전자서명·특수 양식의 유지가 필요한 문서는 별도 확인이 필요합니다.
- PDF 최대 30MB/200페이지, 샘플 PDF 최대 30MB/30페이지, GPT 입력 PDF 최대 10MB/10페이지입니다.
- 한국어 기본 글꼴은 Windows 맑은 고딕을 사용합니다. 다른 OS에서는 `INKLAB_FONT`로 한글 TTF/TTC 경로를 지정하세요.
- 문서와 필기는 기본적으로 `data/`에 저장됩니다. `.gitignore`에서 제외되어 있습니다. `INKLAB_DATA_DIR`로 별도 저장 위치를 지정할 수 있습니다.
- 다음 단계는 실제 사용자 샘플로 유사도 평가, 노트에서 글자 자동 분할·인식, 문맥별 필기 합성, LMS별 제출 연동입니다. 현재 화면은 이를 완료된 기능으로 표시하지 않습니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

테스트는 임시 저장소를 사용합니다. 공학 수식, 실제 글자 교체에 따른 픽셀 변화, PDF 회전 좌표, 원본 보존, 영역 넘침 거부, 한글 렌더링, 이미지/PDF 샘플 업로드, HTTP 요청, MCP 호출을 검증합니다. API 키를 사용하는 실제 GPT 요청은 자동 테스트에 포함하지 않습니다.

참고 문서: [MathJax 서버 렌더링](https://docs.mathjax.org/en/v3.2/server/direct.html), [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/), [OpenAI MCP](https://developers.openai.com/api/docs/guides/tools-connectors-mcp), [OpenAI 이미지 생성의 한계](https://developers.openai.com/api/docs/guides/image-generation).

PyMuPDF는 AGPL/상용 이중 라이선스를 사용합니다. 배포 제품으로 전환할 때 의존성 라이선스를 검토해야 합니다.
