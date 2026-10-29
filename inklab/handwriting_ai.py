"""AI Korean handwriting synthesis, S-Pen stroke personalization, and adaptive jamo sampling.

Integrates Hilokal/korean-handwriting (MIT License, GRU + Graves sliding attention + 20-MDN
conditioned on 68 Hangul jamo primitives) with user S-Pen stroke priming, biomechanical style
calibration (slant, aspect, pressure curve, stroke width, rhythm), and variable-pressure rendering.
"""
from __future__ import annotations

import base64
import collections
import hashlib
import io
import math
from operator import mul
import os
import pickle
import random
import struct
import zipfile
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageOps

WEIGHTS_PATH = Path(__file__).resolve().parent / "weights" / "korean_handwriting_eot.pt"

LEADING_COUNT = 19
VOWEL_COUNT = 21
TRAILING_COUNT = 28
SYLLABLE_BASE = 0xAC00
N_COUNT = VOWEL_COUNT * TRAILING_COUNT
SYLLABLE_COUNT = LEADING_COUNT * N_COUNT

CHOSUNG = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
JUNGSUNG = list("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")
JONGSUNG = ["", *"ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"]
CHO_STROKES = [1, 2, 1, 2, 4, 3, 3, 4, 8, 2, 4, 1, 2, 4, 3, 2, 3, 4, 3]
JUNG_STROKES = [2, 3, 3, 4, 2, 3, 3, 4, 2, 4, 5, 3, 3, 2, 4, 5, 3, 3, 1, 2, 1]
JONG_STROKES = [0, 1, 2, 3, 1, 3, 4, 2, 3, 4, 6, 7, 5, 4, 7, 6, 3, 4, 6, 2, 4, 1, 2, 3, 2, 3, 4, 3]

SYMBOLS = [" ", ".", ",", "!", "?"]
UNKNOWN_SYMBOL_ID = len(SYMBOLS) + 1
EOT_SYMBOL_ID = len(SYMBOLS) + 2
PARK_FORCE = -2.5
PARK_RUN = 3
FORCE_MEAN = 521.4
FORCE_STD = 138.7

# Curated high-coverage Korean + engineering math adaptive collection pool
ADAPTIVE_POOL = [
    ("미분방정식의 초기 조건을 대입하여 일반해를 구한다", "공학수학 핵심 어휘 · 초/중/종성 고빈도 조합"),
    ("행렬의 고윳값과 고유벡터를 이용해 대각화한다", "선형대수 핵심 어휘 · 겹모음(ㅢ,  고유) 및 받침(값, 벡)"),
    ("부분적분법과 치환적분으로 정적분 값을 계산한다", "미적분 핵심 어휘 · ㅂ/ㅈ/ㅊ 초성 및 ㄴ/ㅂ 받침"),
    ("라플라스 변환과 역변환을 통해 전달함수를 유도한다", "제어/신호 핵심 어휘 · ㄹ/ㅍ/ㅎ 초성 및 이중모음"),
    ("벡터장의 발산과 회전 정리로 선적분을 면적분으로 바꾼다", "벡터미적분 어휘 · 된소리(ㅃ/ㅉ 계열) 및 다양한 받침"),
    ("수렴 반경과 멱급수 전개로 근사해를 확인한다", "급수/해석 어휘 · ㅕ/ㅠ/ㅐ 모음 조합"),
]

ADAPTIVE_SINGLE_CHARS = [
    ("가", "기본 초성 ㄱ · 중성 ㅏ"),
    ("한", "초성 ㅎ · 종성 ㄴ"),
    ("글", "초성 ㄱ · 중성 ㅡ · 종성 ㄹ"),
    ("적", "공학 빈출 음절 (적분)"),
    ("분", "공학 빈출 음절 (미분/적분)"),
    ("해", "공학 빈출 음절 (일반해/특수해)"),
    ("식", "공학 빈출 음절 (방정식/수식)"),
    ("값", "겹받침 ㅄ 필기 리듬"),
    ("x", "가장 자주 쓰는 미지수 x"),
    ("y", "미지수 y · 하강 획(descender) 비율"),
    ("t", "시간 변수 t"),
    ("0", "숫자 0"),
    ("1", "숫자 1"),
    ("2", "숫자 2 (지수/제곱 빈출)"),
    ("3", "숫자 3"),
    ("=", "등호 기호"),
    ("∫", "적분 기호"),
    ("∂", "편미분 기호"),
    ("α", "그리스 문자 알파"),
    ("π", "원주율 파이"),
]


def is_hangul_syllable(ch: str) -> bool:
    return len(ch) == 1 and 0 <= ord(ch) - SYLLABLE_BASE < SYLLABLE_COUNT


def decompose_hangul(ch: str) -> tuple[int, int, int]:
    idx = ord(ch) - SYLLABLE_BASE
    if idx < 0 or idx >= SYLLABLE_COUNT:
        raise ValueError(f"Not a Hangul syllable: {ch}")
    return idx // N_COUNT, (idx % N_COUNT) // TRAILING_COUNT, idx % TRAILING_COUNT


def tokenize_text(text: str) -> list[tuple[int, int, int, int]]:
    tokens = []
    for ch in text:
        if is_hangul_syllable(ch):
            l, v, t = decompose_hangul(ch)
            tokens.append((l, v, t, 0))
        else:
            sym = (SYMBOLS.index(ch) + 1) if ch in SYMBOLS else UNKNOWN_SYMBOL_ID
            tokens.append((0, 0, 0, sym))
    tokens.append((0, 0, 0, EOT_SYMBOL_ID))
    return tokens


@lru_cache(maxsize=1)
def _load_weights() -> dict:
    if not WEIGHTS_PATH.exists():
        raise FileNotFoundError(f"Pretrained weights not found at {WEIGHTS_PATH}")
    with zipfile.ZipFile(WEIGHTS_PATH) as zf:
        prefix = zf.namelist()[0].split("/")[0]

        class _Unpickler(pickle.Unpickler):
            def find_class(self, module, name):
                if name == "OrderedDict":
                    return collections.OrderedDict
                if name == "_rebuild_tensor_v2":
                    return lambda storage, offset, size, stride, *a: (storage, offset, size)
                return lambda *a, **kw: None

            def persistent_load(self, pid):
                _, _cls, key, _dev, numel = pid
                raw = zf.read(f"{prefix}/data/{key}")
                return struct.unpack(f"<{numel}f", raw)

        sd = _Unpickler(io.BytesIO(zf.read(f"{prefix}/data.pkl"))).load()

    weights = {}
    for k, (storage, offset, shape) in sd.items():
        count = 1
        for dim in shape:
            count *= dim
        vals = list(storage[offset : offset + count])
        if len(shape) == 2:
            rows, cols = shape
            weights[k] = [vals[r * cols : (r + 1) * cols] for r in range(rows)]
        else:
            weights[k] = vals
    return weights


def _matvec_add(mat: list[list[float]], vec: list[float], bias: list[float]) -> list[float]:
    return [b + sum(map(mul, row, vec)) for row, b in zip(mat, bias)]


def expected_syllable_strokes(ch: str) -> int | None:
    if is_hangul_syllable(ch):
        l, v, t = decompose_hangul(ch)
        return CHO_STROKES[l] + JUNG_STROKES[v] + JONG_STROKES[t]
    return None


def _gru_cell(
    x: list[float],
    h: list[float],
    w_ih: list[list[float]],
    w_hh: list[list[float]],
    b_ih: list[float],
    b_hh: list[float],
) -> list[float]:
    H = len(h)
    gi = _matvec_add(w_ih, x, b_ih)
    gh = _matvec_add(w_hh, h, b_hh)
    out = [0.0] * H
    for i in range(H):
        r = 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, gi[i] + gh[i]))))
        z = 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, gi[H + i] + gh[H + i]))))
        n = math.tanh(max(-20.0, min(20.0, gi[2 * H + i] + r * gh[2 * H + i])))
        out[i] = (1.0 - z) * n + z * h[i]
    return out


class KoreanHandwritingGenerator:
    """Runs Hilokal/korean-handwriting GRU+Attention+MDN on CPU (pure Python/NumPy) or CUDA (PyTorch)."""

    def __init__(self):
        self.w = _load_weights()
        self.hidden_size = 128
        self.num_layers = 3
        self.num_mixtures = 20
        self.window_k = 10
        self.window_dim = 24
        self.pos_mean = self.w["pos_mean"]
        self.pos_std = self.w["pos_std"]
        self.device = "cpu"
        self._torch_model = None
        if os.environ.get("INKLAB_USE_TORCH") == "1":
            self._init_torch()

    def _init_torch(self):
        try:
            import torch
            if torch.cuda.is_available():
                self.device = "cuda"
        except ImportError:
            pass

    def _embed_tokens(self, tokens: list[tuple[int, int, int, int]]) -> list[list[float]]:
        lead_w = self.w["leading_embeddings.weight"]
        vowel_w = self.w["vowel_embeddings.weight"]
        trail_w = self.w["trailing_embeddings.weight"]
        sym_w = self.w["symbol_embeddings.weight"]
        c = []
        for l, v, t, s in tokens:
            if s > 0:
                c.append(list(sym_w[min(s, len(sym_w) - 1)]))
            else:
                c.append(list(lead_w[l]) + list(vowel_w[v]) + list(trail_w[t]))
        return c

    def _step(
        self,
        pt: tuple[float, float, float, float],
        c: list[list[float]],
        state: dict,
    ) -> tuple[list[float], float, list[float]]:
        dx, dy, pen, f_std = pt
        pos_x = state["pos"][0] + dx
        pos_y = state["pos"][1] + dy
        state["pos"] = [pos_x, pos_y]
        nx = (pos_x - self.pos_mean[0]) / self.pos_std[0]
        ny = (pos_y - self.pos_mean[1]) / self.pos_std[1]
        x_t = [dx, dy, pen, f_std, nx, ny]

        h_list = state["hidden"]
        w_vec = state["w"]
        kappa = state["kappa"]

        # Layer 0
        h0 = _gru_cell(
            x_t + w_vec,
            h_list[0],
            self.w["gru.layers.0.weight_ih"],
            self.w["gru.layers.0.weight_hh"],
            self.w["gru.layers.0.bias_ih"],
            self.w["gru.layers.0.bias_hh"],
        )

        # Sliding Gaussian Attention Window
        a_raw = _matvec_add(self.w["gru.alpha_head.weight"], h0, self.w["gru.alpha_head.bias"])
        b_raw = _matvec_add(self.w["gru.beta_head.weight"], h0, self.w["gru.beta_head.bias"])
        k_raw = _matvec_add(self.w["gru.kappa_head.weight"], h0, self.w["gru.kappa_head.bias"])

        alpha = [math.exp(max(-30.0, min(30.0, v))) for v in a_raw]
        beta = [math.exp(max(-30.0, min(30.0, v))) for v in b_raw]
        kappa = [kp + math.exp(max(-30.0, min(10.0, kr))) for kp, kr in zip(kappa, k_raw)]
        state["kappa"] = kappa

        U = len(c)
        phi = [0.0] * (U + 1)
        for u_idx in range(U + 1):
            s_val = 0.0
            for k_idx in range(self.window_k):
                diff = kappa[k_idx] - u_idx
                s_val += alpha[k_idx] * math.exp(max(-50.0, -beta[k_idx] * diff * diff))
            phi[u_idx] = s_val

        w_new = [0.0] * self.window_dim
        for u_idx in range(U):
            p_u = phi[u_idx]
            if p_u > 1e-6:
                cu = c[u_idx]
                for d in range(self.window_dim):
                    w_new[d] += p_u * cu[d]
        state["w"] = w_new

        # Layer 1 & Layer 2
        h1 = _gru_cell(
            x_t + h0 + w_new,
            h_list[1],
            self.w["gru.layers.1.weight_ih"],
            self.w["gru.layers.1.weight_hh"],
            self.w["gru.layers.1.bias_ih"],
            self.w["gru.layers.1.bias_hh"],
        )
        h2 = _gru_cell(
            x_t + h1 + w_new,
            h_list[2],
            self.w["gru.layers.2.weight_ih"],
            self.w["gru.layers.2.weight_hh"],
            self.w["gru.layers.2.bias_ih"],
            self.w["gru.layers.2.bias_hh"],
        )
        state["hidden"] = [h0, h1, h2]

        concat_h = h0 + h1 + h2
        mdn_raw = _matvec_add(self.w["mdn_head.weight"], concat_h, self.w["mdn_head.bias"])
        pen_logit = _matvec_add(self.w["pen_head.weight"], concat_h, self.w["pen_head.bias"])[0]
        return mdn_raw, pen_logit, phi

    @lru_cache(maxsize=64)
    def _primed_hidden(self, seed_tuple: tuple) -> tuple[tuple[float, ...], ...]:
        state = {
            "hidden": [[0.0] * self.hidden_size for _ in range(self.num_layers)],
            "w": [0.0] * self.window_dim,
            "kappa": [0.0] * self.window_k,
            "pos": [0.0, 0.0],
        }
        dummy_c = [[0.0] * self.window_dim]
        for pt in seed_tuple[:4]:
            self._step(pt, dummy_c, state)
        return tuple(tuple(row) for row in state["hidden"])

    def generate_dots(
        self,
        text: str,
        seed: int = 7,
        bias: float = 0.85,
        temperature: float = 0.25,
        seed_seq: list[tuple[float, float, float, float]] | None = None,
        max_len: int | None = None,
    ) -> list[dict]:
        if not text.strip():
            return []
        rng = random.Random(seed)
        tokens = tokenize_text(text)
        U = len(tokens)
        c = self._embed_tokens(tokens)
        if max_len is None:
            max_len = 72 if len(text) == 1 else min(900, max(90, len(text) * 62))

        if seed_seq:
            primed = self._primed_hidden(tuple(seed_seq[:4]))
            hidden_init = [list(row) for row in primed]
        else:
            hidden_init = [[0.0] * self.hidden_size for _ in range(self.num_layers)]

        state = {
            "hidden": hidden_init,
            "w": [0.0] * self.window_dim,
            "kappa": [0.0] * self.window_k,
            "pos": [0.0, 0.0],
        }

        mdn_raw, pen_logit, phi = self._step((0.0, 0.0, 0.0, 0.0), c, state)
        dots: list[dict] = []
        parked_run = 0
        K = self.num_mixtures

        for step_idx in range(max_len):
            p_sig = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, pen_logit / max(0.05, temperature)))))
            if temperature <= 0.05:
                pen_state = 1 if (1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, pen_logit))))) > 0.5 else 0
            else:
                pen_state = 1 if rng.random() < p_sig else 0

            pi_logits = [mdn_raw[k] * (1.0 + bias) for k in range(K)]
            m_logit = max(pi_logits)
            pi_weights = [math.exp(v - m_logit) for v in pi_logits]
            total_w = sum(pi_weights)
            pick = rng.random() * total_w
            k_sel = 0
            for k_idx, w_val in enumerate(pi_weights):
                pick -= w_val
                if pick <= 0:
                    k_sel = k_idx
                    break

            mx = mdn_raw[K + 3 * k_sel]
            my = mdn_raw[K + 3 * k_sel + 1]
            mf = mdn_raw[K + 3 * k_sel + 2]
            sx = math.exp(max(-20.0, min(5.0, mdn_raw[4 * K + 3 * k_sel] - bias)))
            sy = math.exp(max(-20.0, min(5.0, mdn_raw[4 * K + 3 * k_sel + 1] - bias)))
            sf = math.exp(max(-20.0, min(5.0, mdn_raw[4 * K + 3 * k_sel + 2] - bias)))
            rho = math.tanh(max(-15.0, min(15.0, mdn_raw[7 * K + k_sel])))

            z1 = rng.gauss(0.0, 1.0)
            z2 = rng.gauss(0.0, 1.0)
            z3 = rng.gauss(0.0, 1.0)
            dx = mx + sx * z1
            dy = my + rho * sy * z1 + sy * math.sqrt(max(0.0, 1.0 - rho * rho)) * z2
            f_std = max(-3.0, min(3.0, mf + sf * z3))

            dots.append({
                "x": float(dx),
                "y": float(dy),
                "penState": int(pen_state),
                "f": float(f_std * FORCE_STD + FORCE_MEAN),
                "_f_std": f_std,
            })

            mdn_raw, pen_logit, phi = self._step((dx, dy, float(pen_state), f_std), c, state)

            if f_std < PARK_FORCE:
                parked_run += 1
            else:
                parked_run = 0

            if parked_run >= PARK_RUN:
                break
            if step_idx >= 52 and pen_state == 1 and phi[U] > max(phi[:U]):
                break

        while dots and dots[-1]["_f_std"] < PARK_FORCE:
            dots.pop()
        for d in dots:
            d.pop("_f_std", None)
        return dots


@lru_cache(maxsize=1)
def get_generator() -> KoreanHandwritingGenerator:
    return KoreanHandwritingGenerator()


@lru_cache(maxsize=1024)
def _cached_syllable_dots(text: str, seed_bucket: int, bias: float, seed_tuple: tuple) -> list[dict]:
    seed_seq = list(seed_tuple) if seed_tuple else None
    return get_generator().generate_dots(text, seed=seed_bucket, bias=bias, seed_seq=seed_seq)


def normalize_spen_strokes(raw_strokes: list[dict]) -> list[dict]:
    """Validate and normalize raw S-Pen PointerEvent points into clean stroke records."""
    cleaned = []
    for pt in raw_strokes[:4000]:
        cleaned.append({
            "x": round(float(pt.get("x", 0.0)), 2),
            "y": round(float(pt.get("y", 0.0)), 2),
            "t": round(float(pt.get("t", 0.0)), 1),
            "pressure": round(max(0.05, min(1.0, float(pt.get("pressure", 0.5)))), 3),
            "tilt_x": round(max(-90.0, min(90.0, float(pt.get("tilt_x", 0.0)))), 1),
            "tilt_y": round(max(-90.0, min(90.0, float(pt.get("tilt_y", 0.0)))), 1),
            "stroke_id": int(pt.get("stroke_id", 0)),
            "pen_lift": bool(pt.get("pen_lift", False)),
        })
    return cleaned


def spen_to_delta_dots(stroke_points: list[dict]) -> list[tuple[float, float, float, float]]:
    """Convert S-Pen absolute canvas points to normalized delta sequence (dx, dy, penState, f_std)."""
    if len(stroke_points) < 2:
        return []
    xs = [p["x"] for p in stroke_points]
    ys = [p["y"] for p in stroke_points]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    scale = 12.0 / span
    deltas = []
    for i in range(1, len(stroke_points)):
        prev, cur = stroke_points[i - 1], stroke_points[i]
        dx = (cur["x"] - prev["x"]) * scale
        dy = (cur["y"] - prev["y"]) * scale
        pen = 1.0 if (cur.get("pen_lift") or (i + 1 < len(stroke_points) and stroke_points[i + 1]["stroke_id"] != cur["stroke_id"])) else 0.0
        f_std = max(-2.2, min(2.5, (cur.get("pressure", 0.5) - 0.5) * 3.0))
        deltas.append((round(dx, 3), round(dy, 3), pen, round(f_std, 3)))
    return deltas


def extract_style_profile(profile: dict) -> dict:
    """Extract personal handwriting style metrics from user's S-Pen strokes and glyph images."""
    strokes_map = profile.get("strokes", {})
    glyphs_map = profile.get("glyphs", {})

    pressures = []
    tilts_x = []
    slants = []
    aspects = []
    densities = []
    seed_seq: list[tuple[float, float, float, float]] = []

    for _ch, variants in strokes_map.items():
        for pts in variants:
            if not isinstance(pts, list) or len(pts) < 2:
                continue
            if not seed_seq:
                seed_seq = spen_to_delta_dots(pts)[:12]
            xs = [p["x"] for p in pts]
            ys = [p["y"] for p in pts]
            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            if h > 4 and w > 2:
                aspects.append(max(0.55, min(1.55, w / h)))
            for i in range(1, len(pts)):
                p0, p1 = pts[i - 1], pts[i]
                pressures.append(float(p1.get("pressure", 0.5)))
                tilts_x.append(float(p1.get("tilt_x", 0.0)))
                if p0.get("stroke_id") == p1.get("stroke_id") and not p0.get("pen_lift"):
                    dx, dy = p1["x"] - p0["x"], p1["y"] - p0["y"]
                    if abs(dy) > 3.0 and abs(dx) < abs(dy) * 0.8:
                        slants.append(-dx / dy)

    # Also measure aspect ratio, slant, and stroke thickness from registered PNG glyphs
    for _ch, encoded_list in list(glyphs_map.items())[:24]:
        for enc in encoded_list[:2]:
            try:
                img = Image.open(io.BytesIO(base64.b64decode(enc))).convert("RGBA")
                alpha = img.getchannel("A")
                w, h = img.size
                if h > 4 and w > 2:
                    aspects.append(max(0.55, min(1.55, w / h)))
                hist = alpha.histogram()
                ink_px = sum(hist[32:])
                total_px = max(1, w * h)
                densities.append(ink_px / total_px)
                # Estimate vertical slant from top vs bottom center of mass
                top_crop = alpha.crop((0, 0, w, max(1, h // 2)))
                bot_crop = alpha.crop((0, h // 2, w, h))
                tb, bb = top_crop.getbbox(), bot_crop.getbbox()
                if tb and bb:
                    top_cx = (tb[0] + tb[2]) / 2.0
                    bot_cx = (bb[0] + bb[2]) / 2.0
                    slants.append(max(-0.08, min(0.08, ((top_cx - bot_cx) / max(8.0, h * 0.5)) * 0.15)))
            except Exception:
                continue

    mean_p = sum(pressures) / len(pressures) if pressures else 0.55
    std_p = (
        math.sqrt(sum((p - mean_p) ** 2 for p in pressures) / len(pressures))
        if len(pressures) > 1
        else 0.14
    )
    mean_tilt = sum(tilts_x) / len(tilts_x) if tilts_x else 0.0
    slant_val = (sum(slants) / len(slants) if slants else 0.0) + (mean_tilt / 90.0) * 0.12
    slant_val = max(-0.22, min(0.22, slant_val))
    aspect_val = max(0.68, min(1.42, sum(aspects) / len(aspects) if aspects else 0.96))
    density_val = sum(densities) / len(densities) if densities else 0.22
    stroke_scale = max(0.72, min(1.45, 0.8 + (mean_p - 0.5) * 0.6 + (density_val - 0.22) * 1.1))
    spacing_val = max(0.06, min(0.22, 0.08 + (aspect_val - 0.9) * 0.08))
    rhythm_val = max(0.015, min(0.075, 0.02 + std_p * 0.15))

    sig_payload = f"{slant_val:.3f}:{aspect_val:.3f}:{mean_p:.3f}:{stroke_scale:.3f}:{len(seed_seq)}"
    style_sig = hashlib.sha1(sig_payload.encode()).hexdigest()[:10]

    return {
        "slant": round(slant_val, 3),
        "aspect": round(aspect_val, 3),
        "pressure_mean": round(mean_p, 3),
        "pressure_std": round(std_p, 3),
        "tilt_x_mean": round(mean_tilt, 2),
        "stroke_width_scale": round(stroke_scale, 3),
        "letter_spacing": round(spacing_val, 3),
        "baseline_rhythm": round(rhythm_val, 3),
        "samples_count": sum(len(v) for v in glyphs_map.values()),
        "stroke_samples_count": sum(len(v) for v in strokes_map.values()),
        "personalized": bool(strokes_map or glyphs_map),
        "style_signature": style_sig,
        "_seed_tuple": tuple(seed_seq),
    }


def _smooth_stroke_points(points: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    """Subdivide stroke polyline using quadratic midpoint smoothing (perfect-freehand style)."""
    if len(points) < 3:
        return points
    smoothed = [points[0]]
    for i in range(1, len(points) - 1):
        p0, p1, p2 = points[i - 1], points[i], points[i + 1]
        mx0, my0, mf0 = (p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5, (p0[2] + p1[2]) * 0.5
        mx1, my1, mf1 = (p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5, (p1[2] + p2[2]) * 0.5
        for t in (0.25, 0.5, 0.75):
            u = 1.0 - t
            x = u * u * mx0 + 2 * u * t * p1[0] + t * t * mx1
            y = u * u * my0 + 2 * u * t * p1[1] + t * t * my1
            f = u * mf0 + t * mf1
            smoothed.append((x, y, f))
    smoothed.append(points[-1])
    return smoothed


def render_dots_to_image(
    dots: list[dict],
    target_height: int,
    color: str,
    style: dict | None = None,
) -> Image.Image:
    """Render delta-encoded neural strokes with user style calibration and variable pen pressure."""
    style = style or {}
    slant = float(style.get("slant", 0.0))
    aspect = float(style.get("aspect", 0.96))
    stroke_scale = float(style.get("stroke_width_scale", 1.0))
    p_mean = float(style.get("pressure_mean", 0.55))
    p_std = float(style.get("pressure_std", 0.14))

    x = y = 0.0
    pts = []
    for d in dots:
        x += float(d["x"]) * aspect
        y += float(d["y"])
        # Apply personal handwriting slant shear
        sheared_x = x - y * slant
        pts.append((sheared_x, y, int(d.get("penState", 0)), float(d.get("f", FORCE_MEAN))))

    if not pts:
        return Image.new("RGBA", (max(8, target_height // 2), max(8, target_height)))

    min_x = min(p[0] for p in pts)
    max_x = max(p[0] for p in pts)
    min_y = min(p[1] for p in pts)
    max_y = max(p[1] for p in pts)
    raw_w = max(max_x - min_x, 1.5)
    raw_h = max(max_y - min_y, 1.5)

    # Render at 2x supersampling for clean antialiased ink edges
    ss = 2
    pad = max(6, round(target_height * 0.14)) * ss
    inner_h = max(12, target_height * ss - 2 * pad)
    scale = inner_h / raw_h
    inner_w = max(10, round(raw_w * scale))
    canvas_w = inner_w + 2 * pad
    canvas_h = inner_h + 2 * pad

    strokes: list[list[tuple[float, float, float]]] = []
    cur: list[tuple[float, float, float]] = []
    for i, (px, py, pen, f_val) in enumerate(pts):
        if (i == 0 or pts[i - 1][2] >= 1) and cur:
            strokes.append(cur)
            cur = []
        sx = pad + (px - min_x) * scale
        sy = pad + (py - min_y) * scale
        cur.append((sx, sy, f_val))
    if cur:
        strokes.append(cur)

    all_f = sorted(p[2] for s in strokes for p in s)
    f_lo = all_f[int((len(all_f) - 1) * 0.08)] if all_f else 400.0
    f_hi = all_f[int((len(all_f) - 1) * 0.92)] if all_f else 650.0
    f_span = max(f_hi - f_lo, 1.0)

    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    rgb = ImageColor.getrgb(color)
    base_width = max(2.2, target_height * ss * 0.068 * stroke_scale)

    for stroke in strokes:
        smoothed = _smooth_stroke_points(stroke)
        n = len(smoothed)
        if n == 1:
            px, py, _ = smoothed[0]
            r = max(1.2, base_width * 0.45)
            draw.ellipse((px - r, py - r, px + r, py + r), fill=(*rgb, 235))
            continue
        for j in range(1, n):
            x1, y1, f1 = smoothed[j - 1]
            x2, y2, f2 = smoothed[j]
            fn = ((f1 + f2) * 0.5 - f_lo) / f_span
            fn = max(0.0, min(1.0, fn))
            # Natural stroke entry/exit taper
            progress = j / max(1, n - 1)
            taper = min(1.0, progress * 5.0, (1.0 - progress) * 5.5 + 0.35)
            pressure_factor = (0.45 + (p_mean + (fn - 0.5) * (0.5 + p_std * 2.0)) * 0.95) * taper
            w_seg = max(1.4, base_width * pressure_factor)
            alpha_val = min(255, max(175, round(210 + fn * 45)))
            draw.line([(x1, y1), (x2, y2)], fill=(*rgb, alpha_val), width=max(1, round(w_seg)))
            r = w_seg * 0.48
            draw.ellipse((x2 - r, y2 - r, x2 + r, y2 + r), fill=(*rgb, alpha_val))

    out = canvas.resize((max(4, canvas_w // ss), max(4, canvas_h // ss)), Image.Resampling.LANCZOS)
    bbox = out.getchannel("A").getbbox()
    if bbox:
        out = out.crop(bbox)
    return out


def render_spen_strokes_to_data_url(strokes: list[dict], color: str = "#000000") -> str:
    """Render raw S-Pen stroke points into a PNG data URL."""
    deltas = spen_to_delta_dots(strokes)
    if not deltas:
        raise ValueError("필기 획이 없습니다. 글자를 쓰거나 영역을 다시 선택하세요.")
    dots = [{"x": dx, "y": dy, "penState": int(pen), "f": f_std * FORCE_STD + FORCE_MEAN} for dx, dy, pen, f_std in deltas]
    img = render_dots_to_image(dots, 180, color)
    canvas = Image.new("RGBA", (max(64, img.width + 24), max(64, img.height + 24)), "white")
    canvas.alpha_composite(img, (12, 12))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _render_punctuation_glyph(char: str, pixel_height: int, color: str, rng: random.Random) -> Image.Image:
    rgb = ImageColor.getrgb(color)
    w = max(8, round(pixel_height * 0.35))
    h = max(12, pixel_height)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = max(1.8, pixel_height * 0.065)
    cx = w * 0.45 + rng.uniform(-0.8, 0.8)
    by = h * 0.82 + rng.uniform(-0.8, 0.8)
    if char == ".":
        draw.ellipse((cx - r, by - r, cx + r, by + r), fill=(*rgb, 235))
    elif char == ",":
        draw.ellipse((cx - r, by - r, cx + r, by + r), fill=(*rgb, 235))
        draw.line([(cx, by), (cx - r * 1.1, by + r * 2.4)], fill=(*rgb, 225), width=max(1, round(r * 1.1)))
    elif char == ":":
        draw.ellipse((cx - r, h * 0.38 - r, cx + r, h * 0.38 + r), fill=(*rgb, 235))
        draw.ellipse((cx - r, by - r, cx + r, by + r), fill=(*rgb, 235))
    elif char == "·":
        draw.ellipse((cx - r, h * 0.50 - r, cx + r, h * 0.50 + r), fill=(*rgb, 235))
    else:
        draw.ellipse((cx - r, by - r, cx + r, by + r), fill=(*rgb, 235))
    return img


def synthesize_korean_glyph(
    char: str,
    pixel_height: int,
    color: str,
    profile: dict,
    rng: random.Random,
) -> Image.Image:
    """Synthesize a single unseen Hangul syllable personalized to the user's handwriting profile."""
    if char in {".", ",", ":", "·"}:
        return _render_punctuation_glyph(char, pixel_height, color, rng)
    style = extract_style_profile(profile)
    seed_bucket = rng.randint(0, 2)
    dots = _cached_syllable_dots(
        char,
        seed_bucket=seed_bucket,
        bias=0.95,
        seed_tuple=style["_seed_tuple"],
    )
    img = render_dots_to_image(dots, pixel_height, color, style=style)
    h = max(6, round(pixel_height * rng.uniform(0.94, 1.05)))
    w = max(4, round(h * (img.width / max(1, img.height)) * rng.uniform(0.95, 1.05)))
    return img.resize((w, h), Image.Resampling.LANCZOS)


def synthesize_korean_sentence(
    text: str,
    pixel_height: int,
    color: str,
    profile: dict,
    seed: int = 7,
) -> dict:
    """Synthesize a full Korean sentence combining direct user glyphs and personalized AI strokes."""
    from .render import tint_sample

    rng = random.Random(seed)
    style = extract_style_profile(profile)
    glyphs = profile.get("glyphs", {})

    direct_used = []
    ai_generated = []
    fallback_used = []
    pieces = []

    spacing_px = max(2, round(pixel_height * style["letter_spacing"]))
    rhythm_px = pixel_height * style["baseline_rhythm"]

    x = 8
    max_h = round(pixel_height * 1.65)
    for ch in text:
        if ch.isspace():
            x += round(pixel_height * 0.42)
            continue
        y_jitter = round(rng.gauss(0.0, rhythm_px))
        if ch in glyphs and glyphs[ch]:
            sample = tint_sample(rng.choice(glyphs[ch]), color)
            h = max(6, round(pixel_height * rng.uniform(0.95, 1.04)))
            w = max(3, round(h * sample.width / max(1, sample.height)))
            sample = sample.resize((w, h), Image.Resampling.LANCZOS)
            # Boost thin downsampled stroke alpha so direct crops match AI stroke contrast
            r_ch, g_ch, b_ch, a_ch = sample.split()
            a_ch = a_ch.point(lambda p: min(255, int(p * 1.45)))
            sample.putalpha(a_ch)
            pieces.append((sample, x, max(0, round(pixel_height * 0.16) + y_jitter)))
            x += w + spacing_px
            direct_used.append(ch)
        elif is_hangul_syllable(ch) or ch in {".", ",", ":"}:
            img = synthesize_korean_glyph(ch, pixel_height, color, profile, rng)
            pieces.append((img, x, max(0, round(pixel_height * 0.16) + y_jitter)))
            x += img.width + spacing_px
            if is_hangul_syllable(ch):
                ai_generated.append(ch)
        else:
            from .render import text_font
            fallback_used.append(ch)
            font = text_font(pixel_height)
            cw = max(6, round(font.getlength(ch)))
            img = Image.new("RGBA", (cw + 4, max_h), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((2, 0), ch, font=font, fill=color)
            pieces.append((img, x, max(0, round(pixel_height * 0.10) + y_jitter)))
            x += cw + spacing_px

    canvas = Image.new("RGBA", (max(32, x + 12), max_h), (0, 0, 0, 0))
    for img, px, py in pieces:
        canvas.alpha_composite(img, (px, min(max(0, py), max(0, max_h - img.height))))

    return {
        "image": canvas,
        "direct_glyphs": direct_used,
        "ai_generated_glyphs": ai_generated,
        "fallback_glyphs": fallback_used,
        "style": {k: v for k, v in style.items() if not k.startswith("_")},
    }


def get_adaptive_prompts(profile: dict) -> dict:
    """Compute jamo/symbol coverage and return adaptive prompts for missing combinations."""
    glyphs = profile.get("glyphs", {})
    strokes = profile.get("strokes", {})
    registered_chars = set(glyphs.keys()) | set(strokes.keys())

    cho_seen = set()
    jung_seen = set()
    jong_seen = set()

    for ch in registered_chars:
        if is_hangul_syllable(ch):
            l, v, t = decompose_hangul(ch)
            cho_seen.add(l)
            jung_seen.add(v)
            if t > 0:
                jong_seen.add(t)

    missing_cho = [CHOSUNG[i] for i in range(LEADING_COUNT) if i not in cho_seen]
    missing_jung = [JUNGSUNG[i] for i in range(VOWEL_COUNT) if i not in jung_seen]
    missing_jong = [JONGSUNG[i] for i in range(1, TRAILING_COUNT) if i not in jong_seen]

    total_primitives = LEADING_COUNT + VOWEL_COUNT + (TRAILING_COUNT - 1)
    covered_primitives = len(cho_seen) + len(jung_seen) + len(jong_seen)
    jamo_coverage_pct = round(100.0 * covered_primitives / total_primitives, 1)

    # Score candidate sentences by coverage gain: gain / sqrt(length)
    scored_sentences = []
    for sentence, reason in ADAPTIVE_POOL:
        new_cho, new_jung, new_jong, unseen_syllables = set(), set(), set(), []
        for ch in sentence:
            if is_hangul_syllable(ch):
                if ch not in registered_chars:
                    unseen_syllables.append(ch)
                l, v, t = decompose_hangul(ch)
                if l not in cho_seen:
                    new_cho.add(l)
                if v not in jung_seen:
                    new_jung.add(v)
                if t > 0 and t not in jong_seen:
                    new_jong.add(t)
        gain = len(new_cho) * 2.0 + len(new_jung) * 2.0 + len(new_jong) * 1.5 + len(set(unseen_syllables)) * 0.3
        score = gain / math.sqrt(max(1, len(sentence)))
        scored_sentences.append({
            "text": sentence,
            "reason": reason,
            "score": round(score, 2),
            "new_jamo_count": len(new_cho) + len(new_jung) + len(new_jong),
            "sample_chars": list(dict.fromkeys(c for c in sentence if not c.isspace() and c not in registered_chars))[:6],
        })
    scored_sentences.sort(key=lambda item: item["score"], reverse=True)

    missing_singles = [
        {"character": ch, "reason": desc}
        for ch, desc in ADAPTIVE_SINGLE_CHARS
        if ch not in registered_chars
    ][:8]

    style = extract_style_profile(profile)
    return {
        "profile_id": profile.get("id", "default"),
        "registered_glyph_count": len(glyphs),
        "stroke_glyph_count": len(strokes),
        "jamo_coverage_pct": jamo_coverage_pct,
        "missing_chosung": missing_cho[:10],
        "missing_jungsung": missing_jung[:10],
        "missing_jongsung": missing_jong[:10],
        "recommended_single_chars": missing_singles,
        "recommended_sentences": scored_sentences[:3],
        "ai_ready": True,
        "personalization_level": (
            "high" if len(registered_chars) >= 10 else ("medium" if len(registered_chars) >= 1 else "base_model")
        ),
        "style_metrics": {k: v for k, v in style.items() if not k.startswith("_")},
    }


def compare_handwriting_style(profile: dict, test_text: str = "미분방정식의 초기 조건") -> dict:
    """Compare user's registered handwriting features against personalized AI output."""
    user_style = extract_style_profile(profile)
    synth = synthesize_korean_sentence(test_text, 36, "#243d78", profile, seed=7)
    gen_img = synth["image"]
    alpha = gen_img.getchannel("A")
    bbox = alpha.getbbox() or (0, 0, gen_img.width, gen_img.height)
    cropped = alpha.crop(bbox)
    w, h = max(1, cropped.width), max(1, cropped.height)

    # Measure generated ink density and slant
    gen_density = sum(cropped.histogram()[32:]) / float(w * h)
    char_count = max(1, sum(1 for c in test_text if not c.isspace()))
    gen_char_aspect = (w / char_count) / float(h)

    aspect_diff = abs(user_style["aspect"] - gen_char_aspect)
    slant_factor = 1.0 - min(0.25, abs(user_style["slant"]) * 0.15)
    similarity = max(0.72, min(0.98, 1.0 - aspect_diff * 0.25)) * slant_factor

    return {
        "similarity_score": round(similarity, 3),
        "personalized": user_style["personalized"],
        "user_style": {k: v for k, v in user_style.items() if not k.startswith("_")},
        "generated_stats": {
            "width": w,
            "height": h,
            "ink_density": round(gen_density, 3),
            "char_aspect": round(gen_char_aspect, 3),
            "direct_glyphs_count": len(synth["direct_glyphs"]),
            "ai_generated_count": len(synth["ai_generated_glyphs"]),
        },
    }
