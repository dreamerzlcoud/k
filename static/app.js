const $ = (id) => document.getElementById(id);
const state = {
  doc: null,
  page: 0,
  blocks: [],
  selected: -1,
  profiles: [],
  profile: "default",
  output: null,
  color: "#243d78",
  seed: 7,
  preview: false,
  crop: null,
  sampleImage: null,
  revision: 0,
};
let toastTimer;
function toast(message, error = false) {
  $("toast").textContent = message;
  $("toast").className = error ? "error" : "";
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(
    () => ($("toast").hidden = true),
    error ? 12000 : 4000,
  );
}
async function api(path, options = {}) {
  const response = await fetch("/api" + path, options);
  if (!response.ok) {
    let data;
    try {
      data = await response.json();
    } catch {
      throw Error("서버에 연결할 수 없습니다.");
    }
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  }
  return response.json();
}
const jsonOptions = (method, body) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
async function busy(button, work) {
  const text = button.textContent;
  button.disabled = true;
  button.textContent = "처리 중…";
  try {
    return await work();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = text;
  }
}
function showTab(tab) {
  document
    .querySelectorAll(".tab")
    .forEach((e) => e.classList.toggle("active", e.id === tab));
  document
    .querySelectorAll(".nav")
    .forEach((e) => e.classList.toggle("active", e.dataset.tab === tab));
  $("tab-title").textContent = {
    workspace: "PDF 작업실",
    handwriting: "나의 필기체",
    connect: "GPT · MCP 연결",
  }[tab];
}
document
  .querySelectorAll(".nav")
  .forEach((button) => (button.onclick = () => showTab(button.dataset.tab)));
function invalidate() {
  state.revision++;
  state.output = null;
  state.preview = false;
  $("download").classList.add("disabled");
  $("download").removeAttribute("href");
  $("report").hidden = true;
  updatePaper();
}
function layout() {
  return {
    document_id: state.doc.id,
    profile_id: state.profile,
    color: state.color,
    seed: state.seed,
    blocks: state.blocks,
  };
}
async function refreshDocuments() {
  const docs = await api("/documents");
  $("recent-documents").replaceChildren();
  docs
    .slice(-8)
    .reverse()
    .forEach((doc) => {
      const button = document.createElement("button");
      button.className = "recent";
      button.textContent = "▧  " + doc.name;
      button.onclick = () =>
        openDocument(doc).catch((e) => toast(e.message, true));
      $("recent-documents").append(button);
    });
}
async function openDocument(doc) {
  const saved = await api("/layouts/" + doc.id);
  state.doc = doc;
  state.page = 0;
  state.blocks = saved?.blocks || [];
  state.profile = saved?.profile_id || state.profile;
  state.color = saved?.color || "#243d78";
  state.seed = saved?.seed ?? 7;
  state.selected = -1;
  $("empty-state").hidden = true;
  $("editor").hidden = false;
  $("document-name").textContent = doc.name;
  $("ink-color").value = state.color;
  showTab("workspace");
  refreshProfilesUI();
  invalidate();
  updateBlocks();
}
$("pdf-upload").onchange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    toast("PDF를 가져오는 중…");
    const doc = await api("/documents", { method: "POST", body: form });
    await openDocument(doc);
    await refreshDocuments();
    toast("PDF를 가져왔습니다. 수식이나 텍스트 블록을 추가하세요.");
  } catch (e) {
    toast(e.message, true);
  }
  event.target.value = "";
};
$("demo").onclick = () =>
  busy($("demo"), async () => {
    const doc = await api("/demo", { method: "POST" });
    await openDocument(doc);
    await refreshDocuments();
  });
function updatePaper() {
  if (!state.doc) return;
  const src =
    state.preview && state.output
      ? `/api/exports/${state.output.id}/pages/${state.page}.png`
      : `/api/documents/${state.doc.id}/pages/${state.page}.png`;
  if ($("page-image").getAttribute("src") !== src) $("page-image").src = src;
  $("page-number").textContent =
    `${state.page + 1} / ${state.doc.pages.length}`;
  $("prev-page").disabled = state.page === 0;
  $("next-page").disabled = state.page === state.doc.pages.length - 1;
  $("preview-mode").textContent = state.preview ? "필기 미리보기" : "배치 모드";
  drawOverlays();
}
function drawOverlays() {
  const layer = $("block-overlays");
  layer.replaceChildren();
  if (state.preview || !state.doc) return;
  const page = state.doc.pages[state.page];
  state.blocks.forEach((block, i) => {
    if (block.page !== state.page) return;
    const element = document.createElement("div");
    element.className =
      "block-overlay" + (i === state.selected ? " selected" : "");
    Object.assign(element.style, {
      left: (block.x / page.width) * 100 + "%",
      top: (block.y / page.height) * 100 + "%",
      width: (block.width / page.width) * 100 + "%",
      height: (block.height / page.height) * 100 + "%",
    });
    const label = document.createElement("span");
    label.textContent = `${i + 1} · ${block.kind === "math" ? "수식" : "텍스트"}`;
    element.append(label);
    element.onpointerdown = (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      state.selected = i;
      updateBlocks(false);
      drawOverlays();
      const surface = $("paper");
      const rect = surface.getBoundingClientRect();
      const startX = event.clientX,
        startY = event.clientY,
        bx = block.x,
        by = block.y;
      const move = (e) => {
        block.x = Math.round(
          Math.max(
            0,
            Math.min(
              page.width - block.width,
              bx + ((e.clientX - startX) * page.width) / rect.width,
            ),
          ),
        );
        block.y = Math.round(
          Math.max(
            0,
            Math.min(
              page.height - block.height,
              by + ((e.clientY - startY) * page.height) / rect.height,
            ),
          ),
        );
        syncFields();
        drawOverlays();
      };
      const end = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", end);
        invalidate();
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", end, { once: true });
    };
    layer.append(element);
  });
}
function updateBlocks(redraw = true) {
  $("block-count").textContent = state.blocks.length + "개";
  $("block-list").replaceChildren();
  state.blocks.forEach((block, i) => {
    if (block.page !== state.page) return;
    const button = document.createElement("button");
    button.className =
      "block-list-item" + (i === state.selected ? " selected" : "");
    const tag = document.createElement("span");
    tag.textContent = block.kind === "math" ? "ƒx" : "Aa";
    button.append(tag, document.createTextNode(block.content.slice(0, 30)));
    button.onclick = () => {
      state.selected = i;
      state.preview = false;
      updateBlocks();
      updatePaper();
    };
    $("block-list").append(button);
  });
  $("block-editor").hidden = state.selected < 0;
  if (state.selected >= 0) syncFields();
  if (redraw) drawOverlays();
}
function syncFields() {
  const block = state.blocks[state.selected];
  if (!block) return;
  $("content").value = block.content;
  $("content-type").textContent = block.kind === "math" ? "LaTeX" : "텍스트";
  for (const key of ["x", "y", "width", "height", "size"])
    $("field-" + key).value = block[key];
  document.querySelector(".math-shortcuts").hidden = block.kind !== "math";
}
function addBlock(kind) {
  if (!state.doc) return;
  const page = state.doc.pages[state.page];
  state.blocks.push({
    page: state.page,
    kind,
    content:
      kind === "math"
        ? String.raw`\int_0^1 x^2\,dx=\frac{1}{3}`
        : "풀이를 입력하세요.",
    x: Math.min(50, page.width * 0.1),
    y: Math.min(150, page.height * 0.25),
    width: Math.min(450, page.width * 0.8),
    height: Math.min(100, page.height * 0.25),
    size: 18,
  });
  state.selected = state.blocks.length - 1;
  invalidate();
  updateBlocks();
}
$("add-math").onclick = () => addBlock("math");
$("add-text").onclick = () => addBlock("text");
$("content").oninput = () => {
  const block = state.blocks[state.selected];
  if (block) {
    block.content = $("content").value;
    invalidate();
  }
};
for (const key of ["x", "y", "width", "height", "size"])
  $("field-" + key).oninput = () => {
    const block = state.blocks[state.selected];
    if (block) {
      block[key] = Number($("field-" + key).value);
      invalidate();
    }
  };
$("ink-color").oninput = () => {
  state.color = $("ink-color").value;
  invalidate();
};
$("delete-block").onclick = () => {
  state.blocks.splice(state.selected, 1);
  state.selected = -1;
  invalidate();
  updateBlocks();
};
const snippets = {
  fraction: String.raw`\frac{a+b}{c}`,
  integral: String.raw`\int_0^{\infty} e^{-st}f(t)\,dt`,
  matrix: String.raw`\begin{bmatrix} a & b \\ c & d \end{bmatrix}`,
  aligned: String.raw`\begin{aligned} F &= ma \\ a &= \frac{F}{m} \end{aligned}`,
};
document.querySelectorAll("[data-math]").forEach(
  (button) =>
    (button.onclick = () => {
      state.blocks[state.selected].content = snippets[button.dataset.math];
      syncFields();
      invalidate();
    }),
);
function changePage(delta) {
  state.page += delta;
  state.selected = -1;
  updatePaper();
  updateBlocks();
}
$("prev-page").onclick = () => changePage(-1);
$("next-page").onclick = () => changePage(1);
$("original").onclick = () => {
  state.preview = false;
  updatePaper();
};
$("save-layout").onclick = () =>
  busy($("save-layout"), async () => {
    await api("/layouts", jsonOptions("PUT", layout()));
    toast("배치를 저장했습니다.");
  });
$("render").onclick = () =>
  busy($("render"), async () => {
    if (!state.blocks.length)
      throw Error("수식 또는 텍스트 블록을 먼저 추가하세요.");
    const revision = state.revision;
    const body = layout();
    const result = await api("/render", jsonOptions("POST", body));
    if (revision !== state.revision) {
      toast("처리 중 내용이 바뀌었습니다. 미리보기를 다시 눌러주세요.");
      return;
    }
    await api("/layouts", jsonOptions("PUT", body));
    state.output = result;
    state.preview = true;
    $("download").href = result.url;
    $("download").classList.remove("disabled");
    $("report").textContent =
      `직접 쓴 글자 적용: ${result.custom_glyphs_used}회\n` +
      (result.missing_glyphs.length
        ? `기본 글꼴로 표시한 글자: ${result.missing_glyphs.join(" ")}\n이 글자들을 필기 라이브러리에 등록하면 더 많은 부분에 내 필기가 적용됩니다.`
        : "사용된 글자에 등록 샘플을 적용했습니다.") +
      (result.warnings.length ? "\n" + result.warnings.join("\n") : "") +
      "\n원본 문제와의 겹침, 수식 내용은 미리보기에서 확인하세요.";
    $("report").hidden = false;
    updatePaper();
    toast("PDF가 생성되었습니다. 미리보기를 확인하고 다운로드하세요.");
  });
$("ai-draft").onclick = () =>
  busy($("ai-draft"), async () => {
    const instructions = $("ai-instructions").value.trim();
    if (!instructions) throw Error("GPT에 요청할 내용을 입력하세요.");
    const documentId = state.doc.id,
      revision = state.revision;
    const result = await api(
      "/draft",
      jsonOptions("POST", { document_id: documentId, instructions }),
    );
    if (state.doc.id !== documentId || state.revision !== revision)
      throw Error(
        "생성 중 문서 또는 배치가 변경되었습니다. 다시 요청해주세요.",
      );
    state.blocks.push(...result.blocks);
    state.selected = -1;
    invalidate();
    updateBlocks();
    $("ai-status").textContent = result.notes;
    toast("초안을 추가했습니다. 배치와 풀이를 확인하세요.");
  });
function activeProfile() {
  return (
    state.profiles.find((p) => p.id === state.profile) || state.profiles[0]
  );
}
function refreshProfilesUI() {
  for (const id of ["profile-select", "library-profile"]) {
    const select = $(id);
    select.replaceChildren();
    state.profiles.forEach((p) => {
      const option = document.createElement("option");
      option.value = p.id;
      option.textContent = p.name;
      select.append(option);
    });
    select.value = state.profile;
  }
  const profile = activeProfile();
  if (!profile) return;
  $("profile-name").textContent = profile.name;
  const glyphs = Object.entries(profile.glyphs);
  $("glyph-badge").textContent = glyphs.length;
  $("library-count").textContent = glyphs.length;
  $("library-empty").hidden = !!glyphs.length;
  $("glyph-library").replaceChildren();
  glyphs.forEach(([char, images]) => {
    const button = document.createElement("button");
    button.className = "glyph";
    button.title = `${char} 샘플 ${images.length}개 삭제`;
    const img = document.createElement("img");
    img.src = "data:image/png;base64," + images[0];
    img.alt = char;
    const label = document.createElement("small");
    label.textContent = `${char} · ${images.length}개`;
    button.append(img, label);
    button.onclick = async () => {
      if (!confirm(`‘${char}’의 등록 샘플 ${images.length}개를 삭제할까요?`))
        return;
      try {
        const p = await api(
          `/profiles/${state.profile}/glyphs/${char.codePointAt(0)}`,
          { method: "DELETE" },
        );
        replaceProfile(p);
        invalidate();
      } catch (e) {
        toast(e.message, true);
      }
    };
    $("glyph-library").append(button);
  });
}
function replaceProfile(profile) {
  const index = state.profiles.findIndex((p) => p.id === profile.id);
  if (index >= 0) state.profiles[index] = profile;
  else state.profiles.push(profile);
  refreshProfilesUI();
}
$("profile-select").onchange = () => {
  state.profile = $("profile-select").value;
  refreshProfilesUI();
  invalidate();
};
$("library-profile").onchange = () => {
  state.profile = $("library-profile").value;
  refreshProfilesUI();
  invalidate();
};
$("new-profile").onclick = async () => {
  const name = prompt("새 필기 프로필의 이름을 입력하세요.");
  if (!name?.trim()) return;
  try {
    const profile = await api(
      "/profiles",
      jsonOptions("POST", { name: name.trim() }),
    );
    state.profile = profile.id;
    replaceProfile(profile);
    invalidate();
  } catch (e) {
    toast(e.message, true);
  }
};
const pad = $("draw-pad"),
  ctx = pad.getContext("2d");
let drawing = false,
  lastPoint;
function point(event, canvas) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) * canvas.width) / rect.width,
    y: ((event.clientY - rect.top) * canvas.height) / rect.height,
  };
}
pad.onpointerdown = (e) => {
  e.preventDefault();
  drawing = true;
  pad.setPointerCapture(e.pointerId);
  lastPoint = point(e, pad);
  ctx.fillStyle = "#243d78";
  ctx.beginPath();
  ctx.arc(lastPoint.x, lastPoint.y, 2.2, 0, Math.PI * 2);
  ctx.fill();
};
pad.onpointermove = (e) => {
  if (!drawing) return;
  const p = point(e, pad);
  ctx.strokeStyle = "#243d78";
  ctx.lineWidth =
    4.4 * (e.pointerType === "pen" ? Math.max(0.5, e.pressure * 2) : 1);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.moveTo(lastPoint.x, lastPoint.y);
  ctx.lineTo(p.x, p.y);
  ctx.stroke();
  lastPoint = p;
};
pad.onpointerup = pad.onpointercancel = () => (drawing = false);
$("clear-pad").onclick = () => ctx.clearRect(0, 0, pad.width, pad.height);
$("register-sample").onclick = () =>
  busy($("register-sample"), async () => {
    const char = $("sample-character").value.trim();
    if ([...char].length !== 1) throw Error("등록할 글자 하나를 입력하세요.");
    const profile = await api(
      `/profiles/${state.profile}/samples`,
      jsonOptions("POST", {
        character: char,
        image: pad.toDataURL("image/png"),
      }),
    );
    replaceProfile(profile);
    invalidate();
    toast(`‘${char}’ 필기를 등록했습니다.`);
    ctx.clearRect(0, 0, pad.width, pad.height);
    $("sample-character").value = "";
  });
const sampleCanvas = $("sample-canvas"),
  sampleCtx = sampleCanvas.getContext("2d");
let cropStart = null;
function paintSheet() {
  if (!state.sampleImage) return;
  sampleCtx.clearRect(0, 0, sampleCanvas.width, sampleCanvas.height);
  sampleCtx.drawImage(state.sampleImage, 0, 0);
  if (state.crop) {
    const { x, y, w, h } = state.crop;
    sampleCtx.fillStyle = "#347a6030";
    sampleCtx.fillRect(x, y, w, h);
    sampleCtx.strokeStyle = "#2d6451";
    sampleCtx.lineWidth = Math.max(2, sampleCanvas.width / 450);
    sampleCtx.strokeRect(x, y, w, h);
  }
}
let sampleZoom = 100;
function setSampleZoom(value) {
  sampleZoom = Math.max(100, Math.min(400, value));
  sampleCanvas.style.width = sampleZoom + "%";
  $("zoom-label").textContent = sampleZoom + "%";
  $("zoom-out").disabled = sampleZoom === 100;
  $("zoom-in").disabled = sampleZoom === 400;
}
$("zoom-in").onclick = () => setSampleZoom(sampleZoom + 50);
$("zoom-out").onclick = () => setSampleZoom(sampleZoom - 50);
function loadSheet(id) {
  const image = new Image();
  image.onload = () => {
    state.sampleImage = image;
    state.crop = null;
    sampleCanvas.width = image.width;
    sampleCanvas.height = image.height;
    sampleCanvas.hidden = false;
    $("sample-empty").hidden = true;
    $("sample-viewport").hidden = false;
    $("sample-zoom").hidden = false;
    $("use-crop").disabled = true;
    setSampleZoom(100);
    $("sample-viewport").scrollTo(0, 0);
    paintSheet();
  };
  image.onerror = () => toast("샘플 페이지를 불러오지 못했습니다.", true);
  image.src = `/api/sample-sheets/${id}.png`;
}
$("sample-upload").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  try {
    toast("필기 샘플을 불러오는 중…");
    const result = await api("/sample-sheets", { method: "POST", body });
    $("sample-page").replaceChildren();
    result.pages.forEach((id, i) => {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = `샘플 ${i + 1}페이지`;
      $("sample-page").append(option);
    });
    $("sample-page").hidden = result.pages.length < 2;
    loadSheet(result.pages[0]);
    toast("글자 하나를 드래그해 선택하세요.");
  } catch (err) {
    toast(err.message, true);
  }
  e.target.value = "";
};
$("sample-page").onchange = () => loadSheet($("sample-page").value);
sampleCanvas.onpointerdown = (e) => {
  e.preventDefault();
  sampleCanvas.setPointerCapture(e.pointerId);
  cropStart = point(e, sampleCanvas);
  state.crop = null;
};
sampleCanvas.onpointermove = (e) => {
  if (!cropStart) return;
  const p = point(e, sampleCanvas);
  p.x = Math.max(0, Math.min(sampleCanvas.width, p.x));
  p.y = Math.max(0, Math.min(sampleCanvas.height, p.y));
  state.crop = {
    x: Math.min(cropStart.x, p.x),
    y: Math.min(cropStart.y, p.y),
    w: Math.abs(p.x - cropStart.x),
    h: Math.abs(p.y - cropStart.y),
  };
  paintSheet();
};
sampleCanvas.onpointerup = sampleCanvas.onpointercancel = () => {
  cropStart = null;
  $("use-crop").disabled = !state.crop || state.crop.w < 3 || state.crop.h < 3;
};
$("use-crop").onclick = () => {
  const { x, y, w, h } = state.crop;
  ctx.clearRect(0, 0, pad.width, pad.height);
  const ratio = Math.min((pad.width - 80) / w, (pad.height - 60) / h);
  ctx.drawImage(
    state.sampleImage,
    x,
    y,
    w,
    h,
    (pad.width - w * ratio) / 2,
    (pad.height - h * ratio) / 2,
    w * ratio,
    h * ratio,
  );
  $("sample-character").focus();
  toast("선택한 글자를 확인하고 어떤 글자인지 입력하세요.");
};
async function init() {
  try {
    const [profiles, status] = await Promise.all([
      api("/profiles"),
      api("/status"),
    ]);
    state.profiles = profiles;
    refreshProfilesUI();
    await refreshDocuments();
    if ($("connection-status")) $("connection-status").textContent = status.ai_configured
      ? `API 설정됨 · ${status.model}`
      : "API 미설정 · PDF 편집과 필기 등록은 바로 사용할 수 있습니다.";
    $("ai-status").textContent = status.ai_configured
      ? `사용 모델: ${status.model}`
      : "GPT 초안을 사용하려면 연결 탭의 환경변수를 설정하세요.";
  } catch (e) {
    toast(e.message, true);
  }
}
Promise.resolve(window.inklabAuthReady).then(init).catch(error => toast(error.message, true));
