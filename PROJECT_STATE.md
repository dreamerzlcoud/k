# PROJECT_STATE ??InkLab 2.0

## 1. Git & 泥댄겕?ъ씤???곹깭
- 珥덇린 泥댄겕?ъ씤?? `68e6ec3` (`checkpoint-v0.2`)
- 理쒖떊 ?뺤긽 而ㅻ컠: `d0f3bbe` (Phase 1~5 ?꾩껜 ?꾨즺)
- 洹쒖튃 紐⑤뱶: **Ponytail Full** (`AGENTS.md` 蹂묓빀 ?꾨즺)

## 2. ?꾩옱 ?꾨즺 ?④퀎
- **Phase 1 (?섍꼍쨌泥댄겕?ъ씤??**: Git 珥덇린?? `checkpoint-v0.2` ?쒓렇 ?앹꽦, Ponytail `AGENTS.md` 蹂묓빀, 湲곗〈 24媛??뚯뒪???듦낵 ?뺤씤.
- **Phase 2 (?꾩껜 ?듭떖 湲곕뒫)**:
  - ?쒕툝由?S??Pointer Events(`x`, `y`, `t`, `pressure`, `tilt_x`, `tilt_y`, `stroke_id`, `pen_lift`, `getCoalescedEvents`) ?섏쭛 諛??먮낯 ??`profile["strokes"]`) 蹂댁〈.
  - 遺議깊븳 ?쒓? ?먮え(珥덉꽦 19쨌以묒꽦 21쨌醫낆꽦 28) 諛??섑븰 湲고샇 而ㅻ쾭由ъ? 湲곕컲 ?곸쓳???섑뵆 異붿쿇(`GET /api/profiles/{id}/adaptive-prompts`).
  - ?ㅽ뵂?뚯뒪 ?꾨낫 4醫?鍮꾧탳 ??MIT ?쇱씠?좎뒪 諛??ъ쟾?숈뒿 媛以묒튂(`1.4MB`)媛 ?ы븿??**`Hilokal/korean-handwriting`**(68?먮え 遺꾪빐 GRU + Sliding Gaussian Attention + 20-MDN) 梨꾪깮 諛??댁옣(`inklab/weights/korean_handwriting_eot.pt`).
  - ?ъ슜??S?????쒗???꾨씪?대컢(`seed_seq`) + 媛쒖씤 ?ㅽ???硫뷀듃由?`slant`, `aspect`, `pressure_mean`, `stroke_width_scale`, `letter_spacing`, `baseline_rhythm`) 蹂댁젙 + `perfect-freehand` ?ㅽ???媛蹂 ?꾩븬 ?ㅽ뵆?쇱씤 ?뚮뜑留곸쑝濡?誘몃벑濡??쒓? ?뚯젅/臾몄옣 ?앹꽦 援ы쁽.
  - 吏곸젒 ??湲???ъ궗??`custom_glyphs_used`)怨?AI 媛쒖씤???앹꽦(`ai_glyphs_used`, `ai_generated_glyphs`)??紐낇솗??援щ텇?섍퀬 ?좎궗??`similarity_score`) ?곗텧.
- **Phase 3 (異붾줎 ?쒕쾭 & PDF ?곌껐)**:
  - ?낅┰ ?ㅽ뻾 媛?ν븳 FastAPI 異붾줎쨌Job ???쒕퉬??`inklab/inference_server.py`, `Dockerfile.inference`) 遺꾨━: CPU 湲곕낯 ?묐룞, CUDA GPU ?먮룞 媛먯?, ?먭꺽 GPU(`INKLAB_INFERENCE_URL`) ?꾩엫, 紐⑤뜽/?뚯젅 罹먯떛, Job ?곹깭 議고쉶(`GET /jobs/{job_id}`).
  - PDF 鍮?怨듦컙 ?먮룞 ?먯?(`find_blank_spaces`), ?섏떇 ?깊샇쨌?뺤쟻遺??섏튂 寃??`verify_math_expression`), ?먮낯 PDF 臾닿껐??蹂댁〈.
  - ?좊즺 API ???놁씠???숈옉?섎뒗 ?댁옣 怨듯븰 PDF 臾몄젣 遺꾩꽍쨌鍮?怨듦컙 珥덉븞 ?앹꽦湲?`create_local_draft`) 諛??좏깮??Gemini(`GEMINI_API_KEY`) / OpenAI ?곕룞.
- **Phase 4 (MCP ?뺤옣)**:
  - 濡쒖뺄 stdio 諛??대씪?곕뱶 OAuth HTTPS MCP??7媛??꾧뎄 異붽?: `start_handwriting_session`, `get_handwriting_profile_status`, `generate_handwriting_sentence`, `suggest_annotation_positions`, `analyze_and_solve_pdf`, `get_job_status`, `get_export_preview`.
- **Phase 5 (蹂묐ぉ ?닿껐 & 寃利?**:
  - ?대씪?곕뱶 ?꾩뿭 `asyncio.Lock` ???ъ슜?먮퀎 Lock(`user_locks`)?쇰줈 遺꾨━.
  - Supabase ?ъ슜?먮퀎 ZIP ?ㅻ깄??踰꾩쟾 罹먯떆(`SupabaseWorkspace._cache`) ?꾩엯?쇰줈 諛섎났 ?ㅼ슫濡쒕뱶 ?쒓굅.
  - `tint_sample` 諛?`page_png` LRU 罹먯떆 ?곸슜.

## 3. 蹂寃?諛?異붽? ?뚯씪
- 異붽?: `AGENTS.md`, `PROJECT_STATE.md`, `Dockerfile.inference`, `inklab/handwriting_ai.py`, `inklab/inference_server.py`, `inklab/weights/korean_handwriting_eot.pt`, `inklab/weights/LICENSE`
- ?섏젙: `inklab/models.py`, `inklab/render.py`, `inklab/service.py`, `inklab/ai.py`, `inklab/app.py`, `inklab/mcp_server.py`, `inklab/cloud_app.py`, `inklab/cloud_storage.py`, `static/index.html`, `static/app.js`, `scripts/deploy_files.py`, `README.md`, `tests/test_pipeline.py`, `tests/test_cloud.py`

## 4. ?ㅽ뻾 ?뚯뒪?몄? 寃곌낵
- 紐낅졊: `.\.venv\Scripts\python.exe -m pytest -q -o cache_dir=.pytest_cache_local --basetemp=.pytest_tmp`
- 寃곌낵: **26 passed** (S??????Β룸났?? 誘몃벑濡??쒓? 臾몄옣 ?앹꽦, ?먮낯쨌?앹꽦 ?꾩껜 ?좎궗??鍮꾧탳, ?섏떇 ?뚮뜑留겶룰??? PDF ?먮낯 蹂댁〈, 濡쒖뺄/?먭꺽 MCP ?꾧뎄, ?대씪?곕뱶 ?몄쬆쨌寃⑸━ ?꾩껜 ?듦낵)

## 5. ?ㅻ쪟 諛?誘몄셿猷??ы빆
- 濡쒖뺄 ?섍꼍??NVIDIA GPU媛 ?놁뼱 CUDA 寃쎈줈???먮룞 媛먯? 肄붾뱶濡?援ы쁽 ??CPU 諛깆뿏?쒕줈 ?ㅼ젣 異붾줎 寃利??꾨즺.
- ?숆탳蹂?LMS 吏곸젒 ?쒖텧 湲곕뒫? 踰붿쐞 ?몃줈 ?쒖쇅(?ㅼ슫濡쒕뱶 PDF ?쒓났).

## 6. ?ㅼ쓬 援ъ껜???묒뾽
- ?댁쁺 諛고룷 ??Render ?섍꼍蹂???좏깮??`INKLAB_INFERENCE_URL` ?먮뒗 `GEMINI_API_KEY`) ?곌껐 諛??ㅼ궗?⑹옄 S???섑뵆 ?쇰뱶諛??섏쭛.



