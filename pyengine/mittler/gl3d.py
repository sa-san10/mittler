"""GPU（OpenGL 3.3、moderngl）で描く 3D の土台（2026-11-13、3D 強化）。3D のエフェクト（effects_lib/common/gl_*.py）が使う。

  from mittler import gl3d
  rgba = gl3d.render(ctx.W, ctx.H, build, samples=gl3d.samples_for(ctx))   # build(sc) が sc に物を置く。返るのは H×W×4 の uint8（色は alpha を掛けたもの）
  f = gl3d.over(f, rgba, opacity)                                          # 'v7' 段の絵（float32 0〜255）に重ねる

決まり：
- moderngl はここで初めて読む（3D のエフェクトを使わない作品は、moderngl が入っていなくても今までどおり動く）。
- GL の文脈はプロセスに 1 つ。作るのも描くのも、このモジュールの GL 用のスレッド 1 本だけ（描画サーバーは頼みごとに別のスレッドで描くが、
  WGL の文脈は1つのスレッドにしか付かないため）。作れなければ GLUnavailable（理由つき）で止まる（黙って抜かさない）。
- 絵は build に渡したものだけで決まる（前のコマを覚えない）。描き先（MSAA の描き先・シェーダー）は使い回すが、毎回消してから描く。
  同じ PC・同じドライバー・同じ設定なら、同じ入力は同じ絵（確かめた）。別の PC・別の GPU では画素が少し違うことがある
  （3D のエフェクトがある作品だけの例外）。
- どの GPU で描くかは OS とドライバーが決める（作者のデスクトップ PC：画面の無い ssh のセッションでは AMD の内蔵 GPU（GL 4.3）、画面のあるセッションでは
  画面がつながっている GPU）。info() で分かる。
- 座標：右手系・y が上。カメラは camera(eye, target)。長さの単位は自由（エフェクトは「画面の高さ＝だいたい 1〜2」で組んでいる）。
"""
import math
import os
import queue
import threading

import numpy as np

VERSION = 1  # 描き方を変えたら上げる（キャッシュの鍵などに使える）


class GLUnavailable(RuntimeError):
    """この PC・このプロセスで GPU の 3D（OpenGL 3.3）が使えない"""


def _t(key, **kw):
    try:
        from .i18n import t
        return t(key, **kw)
    except Exception:
        return key


# ---------------------------------------------------------------- GL のスレッド
class _Worker:
    def __init__(self):
        self.q = queue.Queue()
        self.ctx = None
        self.err = None
        self.info = {}
        self.cache = {}  # 描き先・シェーダー（GL のスレッドの中だけで触る）
        self.th = threading.Thread(target=self._loop, name='mittler-gl3d', daemon=True)
        self.th.start()

    def _loop(self):
        while True:
            fn, args, box, ev = self.q.get()
            try:
                box['v'] = fn(*args)
            except BaseException as e:  # noqa: BLE001（呼んだ側のスレッドで投げ直す）
                box['e'] = e
            ev.set()

    def call(self, fn, *args):
        if threading.current_thread() is self.th:
            return fn(*args)
        box, ev = {}, threading.Event()
        self.q.put((fn, args, box, ev))
        ev.wait()
        if 'e' in box:
            raise box['e']
        return box.get('v')


_W = None
_WL = threading.Lock()


def _worker():
    global _W
    with _WL:
        if _W is None:
            _W = _Worker()
        return _W


def _open():
    """GL の文脈を作る（GL のスレッドの中で）。作れなければ理由を覚えて GLUnavailable"""
    w = _W
    if w.ctx is not None:
        return w.ctx
    if w.err:
        raise GLUnavailable(w.err)
    if os.environ.get('MITTLER_NO_GL'):  # 確かめ用：GL が無い PC のふり
        w.err = _t('gl3d.off')
        raise GLUnavailable(w.err)
    try:
        import moderngl
    except Exception as e:  # noqa: BLE001
        w.err = _t('gl3d.noModule', err=f'{type(e).__name__}: {e}')
        raise GLUnavailable(w.err) from None
    try:
        ctx = moderngl.create_standalone_context(require=330)
    except Exception as e:  # noqa: BLE001
        w.err = _t('gl3d.noContext', err=f'{type(e).__name__}: {e}')
        raise GLUnavailable(w.err) from None
    info = ctx.info
    w.info = {'renderer': info.get('GL_RENDERER'), 'version': info.get('GL_VERSION'), 'vendor': info.get('GL_VENDOR'),
              'moderngl': moderngl.__version__, 'max_samples': ctx.max_samples}
    if 'GDI Generic' in str(w.info['renderer']):  # Windows の CPU の GL（1.1）。3.3 は無いので、ふつうはここまで来ない
        w.err = _t('gl3d.noContext', err=str(w.info['renderer']))
        ctx.release()
        raise GLUnavailable(w.err)
    w.ctx = ctx
    return ctx


def available():
    """(使えるか, 理由または GL の名前)。文脈を作ってみる（1 回目は 1〜2 秒）"""
    try:
        _worker().call(_open)
        return True, f"{_W.info.get('renderer')} / {_W.info.get('version')}"
    except GLUnavailable as e:
        return False, str(e)


def info():
    """GL の名前・版（作ったあと。作れていなければ {}）"""
    return dict(_W.info) if _W else {}


def require():
    """使えなければ GLUnavailable（エフェクトの頭で呼ぶと、理由つきで止まる）"""
    _worker().call(_open)


def samples_for(ctx, full=4):
    """MSAA の数：ドラフトは 0（ctx.draft）、いつもは full"""
    return 0 if getattr(ctx, 'draft', False) else int(full)


# ---------------------------------------------------------------- 行列（行優先の numpy。列ベクトルに掛ける）
def _v3(v):
    return np.asarray(v, dtype=np.float64).reshape(3)


def _n(v):
    v = _v3(v)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def identity():
    return np.eye(4)


def translate(x, y=0.0, z=0.0):
    if not np.isscalar(x):
        x, y, z = _v3(x)
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def scale(sx, sy=None, sz=None):
    sy = sx if sy is None else sy
    sz = sx if sz is None else sz
    return np.diag([sx, sy, sz, 1.0])


def rot_x(deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]], dtype=np.float64)


def rot_y(deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]], dtype=np.float64)


def rot_z(deg):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=np.float64)


def chain(*ms):
    """左から順に掛ける（chain(T, R, S) は T·R·S＝S が先にかかる）"""
    out = np.eye(4)
    for m in ms:
        out = out @ m
    return out


def perspective(fov_deg, aspect, near, far):
    f = 1.0 / math.tan(math.radians(fov_deg) / 2)
    return np.array([[f / aspect, 0, 0, 0], [0, f, 0, 0], [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)], [0, 0, -1, 0]], dtype=np.float64)


def look_at(eye, target, up=(0, 1, 0)):
    eye, target = _v3(eye), _v3(target)
    z = _n(eye - target)
    x = _n(np.cross(_v3(up), z))
    if np.linalg.norm(x) < 1e-9:
        x = _n(np.cross((0, 0, 1), z))
    y = np.cross(z, x)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = x, y, z
    m[:3, 3] = (-x @ eye, -y @ eye, -z @ eye)
    return m


def orbit(target=(0, 0, 0), yaw=0.0, pitch=10.0, dist=5.0):
    """target のまわりを回るカメラの位置（yaw：y 軸のまわりの角度・度、pitch：上からの角度・度）"""
    a, b = math.radians(yaw), math.radians(pitch)
    tx, ty, tz = _v3(target)
    return (tx + dist * math.cos(b) * math.sin(a), ty + dist * math.sin(b), tz + dist * math.cos(b) * math.cos(a))


# ---------------------------------------------------------------- 時間の曲線（エフェクトで使う）
def clamp01(x):
    return min(1.0, max(0.0, float(x)))


def smooth(x):
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def ease_out(x, k=3.0):
    x = clamp01(x)
    return 1 - (1 - x) ** k


def back_out(x, s=1.7):
    x = clamp01(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


# ---------------------------------------------------------------- 形（三角形の並び：x y z nx ny nz u v の float32）
def _tri_array(pos, nrm, uv):
    return np.concatenate([np.asarray(pos, np.float32), np.asarray(nrm, np.float32), np.asarray(uv, np.float32)], axis=1)


def quad(w=1.0, h=1.0):
    """真ん中が原点の、z=0 の面の四角（正面が +z）。u は左→右、v は下→上"""
    x, y = w / 2, h / 2
    p = [(-x, -y, 0), (x, -y, 0), (x, y, 0), (-x, -y, 0), (x, y, 0), (-x, y, 0)]
    t = [(0, 0), (1, 0), (1, 1), (0, 0), (1, 1), (0, 1)]
    return _tri_array(p, [(0, 0, 1)] * 6, t)


def box(w=1.0, h=1.0, d=1.0):
    """直方体（真ん中が原点）"""
    out = []
    faces = [((0, 0, 1), (1, 0, 0), (0, 1, 0)), ((0, 0, -1), (-1, 0, 0), (0, 1, 0)), ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
             ((-1, 0, 0), (0, 0, 1), (0, 1, 0)), ((0, 1, 0), (1, 0, 0), (0, 0, -1)), ((0, -1, 0), (1, 0, 0), (0, 0, 1))]
    half = np.array([w, h, d]) / 2
    for n, u, v in faces:
        n, u, v = np.array(n), np.array(u), np.array(v)
        c = n * half
        su, sv = np.abs(u) @ half, np.abs(v) @ half
        corners = [c - u * su - v * sv, c + u * su - v * sv, c + u * su + v * sv, c - u * su + v * sv]
        uvs = [(0, 0), (1, 0), (1, 1), (0, 1)]
        for i in (0, 1, 2, 0, 2, 3):
            out.append(list(corners[i]) + list(n) + list(uvs[i]))
    return np.asarray(out, np.float32)


# ---------------------------------------------------------------- 板に貼る絵（作品の絵・動画のコマ）
VIDEO_EXT = ('.mp4', '.mov', '.webm', '.mkv', '.m4v', '.avi')


def _probe_dur(path):
    import subprocess
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(path)],
                           capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip())
    except Exception:  # noqa: BLE001
        return 0.0


def media_frame(cache, root, rel, sec=0.0, fps=30.0, max_w=1280):
    """作品の絵（png・jpg…）か動画のコマ（sec 秒。長さをこえたら頭から繰り返す）を uint8 の RGB(A) で。
    動画は ffmpeg でその時刻へ正確に飛んで 1 コマ取る（どこから描いても同じコマ）。cache は ctx.cache（キーは 'gl3d.media'）"""
    import subprocess
    from pathlib import Path
    box = cache.setdefault('gl3d.media', {})
    p = Path(rel) if Path(rel).is_absolute() else Path(root) / rel
    if p.suffix.lower() not in VIDEO_EXT:
        if p not in box:
            from PIL import Image
            im = Image.open(p)
            im = im.convert('RGBA') if im.mode in ('RGBA', 'LA', 'P') else im.convert('RGB')
            if im.width > max_w:
                im = im.resize((max_w, max(1, round(im.height * max_w / im.width))), Image.LANCZOS)
            box[p] = np.asarray(im)
        return box[p]
    dk = ('dur', p)
    if dk not in box:
        box[dk] = _probe_dur(p)
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', str(p)],
                           capture_output=True, text=True, timeout=60)
        w0, h0 = (int(x) for x in r.stdout.strip().split(',')[:2])
        w = min(max_w, w0) // 2 * 2
        box[('size', p)] = (w, max(2, round(h0 * w / w0) // 2 * 2))
    dur = box[dk]
    n = int(round(float(sec) * fps))
    if dur > 0:
        n %= max(1, int(dur * fps))
    key = ('f', p, n, fps)
    if key not in box:
        w, h = box[('size', p)]
        r = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{n / fps:.6f}', '-i', str(p), '-frames:v', '1', '-vf', f'scale={w}:{h}:flags=area',
                            '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, timeout=120)
        if len(r.stdout) < w * h * 3:
            raise RuntimeError(f'{p} の {n / fps:.3f} 秒のコマを読めない：' + r.stderr.decode('utf-8', 'replace')[-300:])
        frames = [k for k in box if isinstance(k, tuple) and k[0] == 'f']
        if len(frames) > 64:  # 覚えておくコマは 64 枚まで（古いものから）
            for k in frames[:len(frames) - 64]:
                box.pop(k, None)
        box[key] = np.frombuffer(r.stdout[:w * h * 3], np.uint8).reshape(h, w, 3)
    return box[key]


# ---------------------------------------------------------------- 書体と立体の文字
FONT_CANDIDATES = [  # 書体の指定が無いとき（Windows の書体。日本語が出るものを先に）
    'C:/Windows/Fonts/YuGothB.ttc', 'C:/Windows/Fonts/meiryob.ttc', 'C:/Windows/Fonts/BIZ-UDGothicB.ttc',
    'C:/Windows/Fonts/msgothic.ttc', 'C:/Windows/Fonts/arialbd.ttf', 'C:/Windows/Fonts/segoeuib.ttf',
]


def find_font(font=None, root=None):
    """書体のファイル：font（作品の root からの相対か絶対）→ OS の書体。無ければ None"""
    if font:
        for p in ([os.path.join(str(root), font)] if root else []) + [font, os.path.join('C:/Windows/Fonts', font)]:
            if os.path.isfile(p):
                return p
    for p in FONT_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


_GLYPHS = {}
_GLYPH_PX = 320  # 1 字を描く大きさ（px）。形の細かさ


class Glyph:
    """立体の 1 字：側面（三角形の並び）・表と裏の板（字の形の絵を貼って、形の外は描かない）。単位は「1＝字の大きさ（em）」"""
    def __init__(self, side, w, h, mask, cx, cy):
        self.side, self.w, self.h, self.mask, self.cx, self.cy = side, w, h, mask, cx, cy


def glyph(ch, font_path, depth=0.25):
    """字 ch（1 字）を厚み depth で立体にする。形は字の輪郭（OpenCV の輪郭）から作るので、日本語の字もそのまま。空白は None"""
    key = (ch, font_path, round(float(depth), 4))
    if key in _GLYPHS:
        return _GLYPHS[key]
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    S = _GLYPH_PX
    font = ImageFont.truetype(font_path, S)
    pad = S // 4
    l, t, r, b = font.getbbox(ch)
    if r - l <= 0 or b - t <= 0 or not ch.strip():
        _GLYPHS[key] = None
        return None
    W, H = r - l + 2 * pad, b - t + 2 * pad
    im = Image.new('L', (W, H), 0)
    ImageDraw.Draw(im).text((pad - l, pad - t), ch, font=font, fill=255)
    m = np.asarray(im)
    cnts, _ = cv2.findContours((m >= 128).astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    # 字の真ん中（板の真ん中）を原点に。y は上が +
    cx, cy = W / 2.0, H / 2.0
    k = 1.0 / S
    z0, z1 = depth / 2, -depth / 2
    tris = []
    for c in cnts:
        c = cv2.approxPolyDP(c, 0.7, True)[:, 0, :].astype(np.float64)
        n = len(c)
        if n < 3:
            continue
        P = np.stack([(c[:, 0] - cx) * k, (cy - c[:, 1]) * k], axis=1)
        E = np.roll(P, -1, axis=0) - P                     # 辺
        En = np.stack([E[:, 1], -E[:, 0]], axis=1)          # 辺の法線（向きはあとで直す）
        En /= np.maximum(np.linalg.norm(En, axis=1, keepdims=True), 1e-12)
        # 法線が字の外を向くように：辺の真ん中から法線の向きに少し出た所が字の中なら、全部の向きを逆に
        mid = (P + np.roll(P, -1, axis=0)) / 2
        probe = mid + En * (2.0 * k)
        px = np.clip((probe[:, 0] / k + cx).astype(int), 0, W - 1)
        py = np.clip((cy - probe[:, 1] / k).astype(int), 0, H - 1)
        if np.mean(m[py, px] >= 128) > 0.5:
            En = -En
        Vn = En + np.roll(En, 1, axis=0)                    # 角はとなりの辺の平均（なめらかに見せる。鋭い角は辺の向き）
        sharp = np.sum(En * np.roll(En, 1, axis=0), axis=1) < 0.5
        Vn /= np.maximum(np.linalg.norm(Vn, axis=1, keepdims=True), 1e-12)
        for i in range(n):
            j = (i + 1) % n
            ni = En[i] if sharp[i] else Vn[i]
            nj = En[i] if sharp[j] else Vn[j]
            a0, a1 = (P[i, 0], P[i, 1], z0), (P[i, 0], P[i, 1], z1)
            b0, b1 = (P[j, 0], P[j, 1], z0), (P[j, 0], P[j, 1], z1)
            na, nb = (ni[0], ni[1], 0.0), (nj[0], nj[1], 0.0)
            for p_, n_ in ((a0, na), (b0, nb), (b1, nb), (a0, na), (b1, nb), (a1, na)):
                tris.append(p_ + n_ + (0.0, 0.0))
    side = np.asarray(tris, np.float32) if tris else np.zeros((0, 8), np.float32)
    g = Glyph(side, W * k, H * k, m, cx * k, cy * k)
    _GLYPHS[key] = g
    return g


def text_layout(text, font_path, tracking=0.0):
    """1 行の字の並び：[(字, 字の真ん中の x（em）)]。全体の真ん中が 0"""
    from PIL import ImageFont
    font = ImageFont.truetype(font_path, _GLYPH_PX)
    out = []
    x = 0.0
    for i, ch in enumerate(text):
        l, t, r, b = font.getbbox(ch) if ch.strip() else (0, 0, 0, 0)
        adv = font.getlength(ch) / _GLYPH_PX
        center = x + ((l + r) / 2 / _GLYPH_PX if r > l else adv / 2)
        out.append((ch, center, adv))
        x += adv + tracking
    total = x - tracking if out else 0.0
    return [(ch, c - total / 2) for ch, c, _ in out], total


# ---------------------------------------------------------------- シェーダー
_LIT_VS = """
#version 330
uniform mat4 u_vp; uniform mat4 u_model; uniform mat3 u_nmat;
in vec3 in_pos; in vec3 in_nrm; in vec2 in_uv;
out vec3 v_pos; out vec3 v_nrm; out vec2 v_uv;
void main(){ vec4 w = u_model * vec4(in_pos, 1.0); v_pos = w.xyz; v_nrm = u_nmat * in_nrm; v_uv = in_uv; gl_Position = u_vp * w; }
"""
_LIT_FS = """
#version 330
uniform vec3 u_eye; uniform vec3 u_ldir; uniform vec3 u_lcol; uniform vec3 u_amb; uniform vec3 u_fill;
uniform vec3 u_color; uniform float u_alpha; uniform float u_metal; uniform float u_spec; uniform float u_shine;
uniform vec3 u_emit; uniform float u_rim; uniform vec3 u_rimcol;
uniform sampler2D u_tex; uniform int u_texmode;   // 0 なし・1 色の絵（RGBA）・2 形の絵（R が形。外は描かない）
uniform float u_radius; uniform vec2 u_size;      // 板の角の丸み（板の短い辺に対する割合。0 で四角）・板の大きさ
uniform vec3 u_fogcol; uniform float u_fog;       // 遠くを暗く（0 でなし）
uniform int u_mode;                               // 0 ふつう・1 影の型（白で塗るだけ）
uniform vec4 u_clip;                              // 映り込み：この面（xyz・w）より下だけ描く（w=0 で使わない）
in vec3 v_pos; in vec3 v_nrm; in vec2 v_uv;
out vec4 o;
// 金属に映るまわりの光（撮影所のような：上が明るく、地平に明るい帯、斜め前に大きな光の箱が 2 つ）
vec3 sky(vec3 r){
  float k = smoothstep(-0.35, 0.8, r.y);
  vec3 c = mix(vec3(0.10,0.10,0.12), vec3(0.95,0.95,1.0), k);
  c += vec3(1.0) * 0.8 * exp(-pow(r.y * 7.0, 2.0));
  c += vec3(1.0,0.97,0.92) * 2.2 * smoothstep(0.82, 0.95, dot(r, normalize(vec3(-0.55,0.35,0.75))));
  c += vec3(0.85,0.92,1.0) * 1.4 * smoothstep(0.86, 0.97, dot(r, normalize(vec3(0.6,0.15,0.8))));
  return c;
}
void main(){
  if (u_clip.w != 0.0 && dot(v_pos, u_clip.xyz) > u_clip.w) discard;
  float a = u_alpha; vec3 base = u_color;
  if (u_texmode == 1) { vec4 c = texture(u_tex, v_uv); base *= c.rgb; a *= c.a; }
  if (u_texmode == 2) { float m = texture(u_tex, v_uv).r; a *= smoothstep(0.35, 0.65, m); }
  if (u_radius > 0.0) {   // 角を丸めた板
    vec2 p = (v_uv - 0.5) * u_size; vec2 h = u_size * 0.5; float r = u_radius * min(u_size.x, u_size.y);
    vec2 q = abs(p) - (h - vec2(r)); float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
    float px = fwidth(d); a *= 1.0 - smoothstep(-px, px, d);
  }
  if (a < 0.004) discard;
  if (u_mode == 1) { o = vec4(1.0, 1.0, 1.0, a); return; }
  vec3 n = normalize(v_nrm); vec3 vdir = normalize(u_eye - v_pos);
  if (!gl_FrontFacing) n = -n;
  vec3 l = normalize(u_ldir);
  float dif = max(dot(n, l), 0.0); float dif2 = max(dot(n, -l * vec3(1.0, 0.2, 1.0)), 0.0) * 0.35;
  vec3 h = normalize(l + vdir); float sp = pow(max(dot(n, h), 0.0), u_shine) * u_spec;
  vec3 diffuse = base * (u_amb + u_lcol * dif + u_fill * dif2);
  vec3 env = sky(reflect(-vdir, n)) * base;
  vec3 c = mix(diffuse, env * (0.55 + 0.45 * dif), u_metal) + u_lcol * sp;
  float rim = pow(1.0 - max(dot(n, vdir), 0.0), 3.0) * u_rim; c += u_rimcol * rim;
  c += u_emit;
  if (u_fog > 0.0) { float f = 1.0 - exp(-u_fog * length(u_eye - v_pos)); c = mix(c, u_fogcol, f); }
  o = vec4(c * a, a);
}
"""
_FLOOR_FS = """
#version 330
uniform vec3 u_eye; uniform vec3 u_color; uniform float u_alpha; uniform float u_fade; uniform vec3 u_center;
uniform sampler2D u_shadow; uniform float u_shadowk; uniform vec2 u_screen;
in vec3 v_pos; in vec3 v_nrm; in vec2 v_uv;
out vec4 o;
void main(){
  float d = length(v_pos.xz - u_center.xz);
  float a = u_alpha * exp(-u_fade * d * d);
  float s = texture(u_shadow, gl_FragCoord.xy / u_screen).r * u_shadowk;
  float ao = a + (1.0 - a) * s * exp(-u_fade * d * d);   // 影は、床の透けている所にも落とす（下の絵を暗くする）
  vec3 c = u_color * (1.0 - s) * a;
  o = vec4(c, ao);
}
"""
_ADD_VS = """
#version 330
uniform mat4 u_vp;
in vec3 in_pos; in vec2 in_uv; in vec4 in_col;
out vec2 v_uv; out vec4 v_col;
void main(){ v_uv = in_uv; v_col = in_col; gl_Position = u_vp * vec4(in_pos, 1.0); }
"""
_ADD_FS = """
#version 330
uniform int u_shape;   // 0 丸い光・1 筋（u に沿って薄れる・v で太さ）
in vec2 v_uv; in vec4 v_col;
out vec4 o;
void main(){
  float k;
  if (u_shape == 0) { vec2 p = v_uv * 2.0 - 1.0; float r2 = dot(p, p); if (r2 > 1.0) discard; k = exp(-r2 * 4.0) + 0.35 * exp(-r2 * 30.0); }
  else { float v = abs(v_uv.y * 2.0 - 1.0); k = exp(-v * v * 6.0) * smoothstep(0.0, 0.35, v_uv.x) * (1.0 - smoothstep(0.85, 1.0, v_uv.x)) ; k *= 0.25 + 0.75 * v_uv.x; }
  o = vec4(v_col.rgb * v_col.a * k, 0.0);   // 足すだけ（下の絵を明るくする。不透明の度合いは変えない）
}
"""


def _prog(ctx, name):
    w = _W
    p = w.cache.get(('prog', name))
    if p is None:
        if name == 'lit':
            p = ctx.program(vertex_shader=_LIT_VS, fragment_shader=_LIT_FS)
        elif name == 'floor':
            p = ctx.program(vertex_shader=_LIT_VS, fragment_shader=_FLOOR_FS)
        else:
            p = ctx.program(vertex_shader=_ADD_VS, fragment_shader=_ADD_FS)
        w.cache[('prog', name)] = p
    return p


def _set(p, name, v):
    """uniform を入れる（シェーダーで使われずに消えた名前は飛ばす）"""
    if name not in p:
        return
    u = p[name]
    if isinstance(v, np.ndarray) and v.ndim == 2:
        u.write(np.ascontiguousarray(v.T, dtype=np.float32).tobytes())  # GL は列優先
    else:
        u.value = v


# ---------------------------------------------------------------- 場面
class Scene:
    """1 コマぶんの物を集めて、render() の中で描く（エフェクトの build(sc) が置く）"""
    def __init__(self, W, H):
        self.W, self.H = W, H
        self.eye, self.target, self.up, self.fov, self.near, self.far = (0, 0, 5), (0, 0, 0), (0, 1, 0), 40.0, 0.05, 200.0
        self.ldir, self.lcol, self.amb, self.fill = (-0.45, 0.75, 0.6), (1.0, 0.98, 0.95), (0.16, 0.17, 0.2), (0.35, 0.4, 0.5)
        self.rimcol = (0.55, 0.75, 1.0)
        self.fogcol, self.fog = (0.0, 0.0, 0.0), 0.0
        self.meshes, self.adds, self.floor_ = [], [], None

    def camera(self, eye, target=(0, 0, 0), fov=40.0, up=(0, 1, 0), near=0.05, far=200.0):
        self.eye, self.target, self.fov, self.up, self.near, self.far = tuple(_v3(eye)), tuple(_v3(target)), float(fov), tuple(_v3(up)), near, far

    def light(self, dir=None, color=None, ambient=None, fill=None, rim_color=None):
        if dir is not None:
            self.ldir = tuple(_v3(dir))
        if color is not None:
            self.lcol = tuple(_v3(color))
        if ambient is not None:
            self.amb = tuple(_v3(ambient))
        if fill is not None:
            self.fill = tuple(_v3(fill))
        if rim_color is not None:
            self.rimcol = tuple(_v3(rim_color))

    def fog_(self, density, color=(0, 0, 0)):
        self.fog, self.fogcol = float(density), tuple(_v3(color))

    def mesh(self, tris, model=None, color=(1, 1, 1), alpha=1.0, metal=0.0, spec=0.5, shine=40.0, emit=(0, 0, 0), rim=0.0,
             tex=None, texmode=None, radius=0.0, size=(1, 1), shadow=True, reflect=True):
        """三角形の並び（x y z nx ny nz u v）を置く。tex：uint8 の絵（H×W×3／4 は色の絵、H×W は形の絵）"""
        if tris is None or len(tris) == 0:
            return
        if tex is not None and texmode is None:
            texmode = 2 if tex.ndim == 2 else 1
        self.meshes.append(dict(tris=tris, model=np.eye(4) if model is None else np.asarray(model, np.float64), color=tuple(_v3(color)),
                                alpha=float(alpha), metal=float(metal), spec=float(spec), shine=float(shine), emit=tuple(_v3(emit)),
                                rim=float(rim), tex=tex, texmode=int(texmode or 0), radius=float(radius), size=tuple(map(float, size)),
                                shadow=bool(shadow), reflect=bool(reflect)))

    def card(self, img, model=None, w=1.6, h=0.9, radius=0.03, emit=0.0, alpha=1.0, light=0.35, shadow=True, reflect=True):
        """絵（uint8 の H×W×3／4）を貼った板（真ん中が原点・正面が +z）。light：光の当たり方（0 で絵のまま、1 でほかの物と同じ）"""
        k = float(light)
        self.mesh(quad(w, h), model, color=(1, 1, 1), alpha=alpha, spec=0.25 * k, shine=60, emit=(emit, emit, emit), tex=img, texmode=1,
                  radius=radius, size=(w, h), shadow=shadow, reflect=reflect, rim=0.15 * k, metal=0.0)
        self.meshes[-1]['lightk'] = k

    def text(self, text, font_path, model=None, depth=0.25, color=(1, 1, 1), side=None, metal=0.6, spec=0.8, emit=(0, 0, 0),
             rim=0.4, letter=None, tracking=0.02, shadow=True, reflect=True, alpha=1.0):
        """立体の文字 1 行（1＝字の大きさ）。letter(i, n, 字) が 4×4 の行列を返すと、字ごとに動かせる（ロゴの組み上がり）。
        side：側面の色（無ければ color を暗くしたもの）"""
        lay, total = text_layout(text, font_path, tracking)
        n = len(lay)
        sidec = tuple(_v3(side)) if side is not None else tuple(0.55 * _v3(color))
        M = np.eye(4) if model is None else np.asarray(model, np.float64)
        for i, (ch, x) in enumerate(lay):
            g = glyph(ch, font_path, depth)
            if g is None:
                continue
            L = letter(i, n, ch) if letter else np.eye(4)
            if L is None:
                continue
            la = 1.0
            if isinstance(L, tuple):  # (行列, 透明度)
                L, la = L
            if la <= 0:
                continue
            m = M @ translate(x, 0, 0) @ L
            a = alpha * la
            self.mesh(g.side, m, color=sidec, metal=metal, spec=spec, emit=emit, rim=rim, shadow=shadow, reflect=reflect, alpha=a)
            q = quad(g.w, g.h)
            # 表と裏の面：裏は左右を反転させずに向きだけ裏返す（反転すると、表の字の穴から裏返った字が見えた）
            for z, sz in ((depth / 2, 1.0), (-depth / 2, -1.0)):
                self.mesh(q, m @ translate(0, 0, z) @ scale(1.0, 1.0, sz), color=color, metal=metal, spec=spec, emit=emit, rim=rim * 0.5,
                          tex=g.mask, texmode=2, shadow=shadow, reflect=reflect, alpha=a)
        return total

    def points(self, P, size, color, alpha=1.0):
        """丸い光の粒（足して明るくする）。P：N×3、size：N か 1 つ（世界の長さ）、color：N×3 か 1 つ（0〜1、1 より大きくてもよい）"""
        P = np.asarray(P, np.float64).reshape(-1, 3)
        if not len(P):
            return
        self.adds.append(('pts', P, np.broadcast_to(np.asarray(size, np.float64), (len(P),)),
                          np.broadcast_to(np.asarray(color, np.float64), (len(P), 3)), np.broadcast_to(np.asarray(alpha, np.float64), (len(P),))))

    def streaks(self, P0, P1, width, color, alpha=1.0):
        """光の筋（P0 → P1。P1 の側が明るい頭）。足して明るくする"""
        P0 = np.asarray(P0, np.float64).reshape(-1, 3)
        P1 = np.asarray(P1, np.float64).reshape(-1, 3)
        if not len(P0):
            return
        n = len(P0)
        self.adds.append(('str', P0, P1, np.broadcast_to(np.asarray(width, np.float64), (n,)), np.broadcast_to(np.asarray(color, np.float64), (n, 3)),
                          np.broadcast_to(np.asarray(alpha, np.float64), (n,))))

    def floor(self, y=0.0, color=(0.02, 0.02, 0.03), alpha=0.8, reflect=0.35, shadow=0.55, fade=0.01, size=60.0, center=(0, 0, 0)):
        """床（y の高さの水平の面）：物の映り込み（reflect）と影（shadow）。fade で遠くほど透ける"""
        self.floor_ = dict(y=float(y), color=tuple(_v3(color)), alpha=float(alpha), reflect=float(reflect), shadow=float(shadow),
                           fade=float(fade), size=float(size), center=tuple(_v3(center)))

    # ---- 描く（GL のスレッドの中）
    def _vp(self):
        return perspective(self.fov, self.W / self.H, self.near, self.far) @ look_at(self.eye, self.target, self.up)


def _vao(ctx, prog, data, fmt, names):
    # シェーダーが使っていない属性は、GL の最適化で消えていることがある（NVIDIA のドライバーで床の in_nrm が消え、moderngl が KeyError。2026-11-14 作者の PC で見つかった）。
    # 消えた属性は同じ幅の詰め物（'3f' → '12x'）にして飛ばす。並びとデータは変えないので、描く絵は同じ
    vbo = ctx.buffer(np.ascontiguousarray(data, np.float32).tobytes())
    parts, keep = [], []
    for tok, name in zip(fmt.split(), names):
        if prog.get(name, None) is None:
            parts.append(f'{int(tok[:-1]) * 4}x')
        else:
            parts.append(tok); keep.append(name)
    return vbo, ctx.vertex_array(prog, [(vbo, ' '.join(parts), *keep)])


def _texture(ctx, img):
    img = np.ascontiguousarray(img)
    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)
    if img.ndim == 2:
        tex = ctx.texture((img.shape[1], img.shape[0]), 1, np.flipud(img).tobytes())
    else:
        c = img.shape[2]
        tex = ctx.texture((img.shape[1], img.shape[0]), c, np.ascontiguousarray(np.flipud(img)).tobytes())
    tex.build_mipmaps()
    import moderngl
    tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
    tex.anisotropy = 8.0
    tex.repeat_x = tex.repeat_y = False
    return tex


def _targets(ctx, W, H, samples):
    w = _W
    key = ('fbo', W, H, samples)
    got = w.cache.get(key)
    if got is None:
        for k in [k for k in w.cache if k[0] == 'fbo']:  # 大きさが変わったら前のものを捨てる（GPU のメモリをためない）
            for o in w.cache.pop(k):
                o.release()
        s = min(int(samples), ctx.max_samples) if samples else 0
        col = ctx.renderbuffer((W, H), 4, samples=s)
        dep = ctx.depth_renderbuffer((W, H), samples=s)
        fbo = ctx.framebuffer(color_attachments=[col], depth_attachment=dep)
        rcol = ctx.renderbuffer((W, H), 4)
        rfbo = ctx.framebuffer(color_attachments=[rcol])
        stex = ctx.texture((W, H), 1)        # 影の型
        sdep = ctx.depth_renderbuffer((W, H))
        sfbo = ctx.framebuffer(color_attachments=[stex], depth_attachment=sdep)
        got = (fbo, col, dep, rfbo, rcol, sfbo, stex, sdep)
        w.cache[key] = got
    return got


def _draw_meshes(ctx, sc, vp, items, reflect_plane=None, mode=0, tex_cache=None):
    import moderngl
    p = _prog(ctx, 'lit')
    _set(p, 'u_vp', vp)
    _set(p, 'u_eye', tuple(map(float, sc.eye)))
    _set(p, 'u_ldir', tuple(map(float, sc.ldir)))
    _set(p, 'u_lcol', tuple(map(float, sc.lcol)))
    _set(p, 'u_amb', tuple(map(float, sc.amb)))
    _set(p, 'u_fill', tuple(map(float, sc.fill)))
    _set(p, 'u_rimcol', tuple(map(float, sc.rimcol)))
    _set(p, 'u_fogcol', tuple(map(float, sc.fogcol)))
    _set(p, 'u_fog', float(sc.fog))
    _set(p, 'u_mode', int(mode))
    _set(p, 'u_tex', 0)
    R = np.eye(4)
    if reflect_plane is not None:  # y=Y の面で映す
        Y = reflect_plane
        R = np.array([[1, 0, 0, 0], [0, -1, 0, 2 * Y], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=np.float64)
        _set(p, 'u_clip', (0.0, 1.0, 0.0, float(Y) + 1e-4))
    else:
        _set(p, 'u_clip', (0.0, 0.0, 0.0, 0.0))
    junk = []
    for it in items:
        M = R @ it['model']
        N = np.eye(3) if mode == 1 else np.linalg.inv(M[:3, :3]).T  # 影の型は面へつぶした行列（逆が無い。法線は使わない）
        _set(p, 'u_model', M)
        _set(p, 'u_nmat', N)
        lk = it.get('lightk')
        if lk is not None:  # 絵の板：光の当たり方を弱める（絵の色をなるべくそのまま）
            _set(p, 'u_amb', tuple(float(1 - lk + lk * a) for a in sc.amb))
            _set(p, 'u_lcol', tuple(float(lk * a) for a in sc.lcol))
            _set(p, 'u_fill', tuple(float(lk * a) for a in sc.fill))
        else:
            _set(p, 'u_amb', tuple(map(float, sc.amb)))
            _set(p, 'u_lcol', tuple(map(float, sc.lcol)))
            _set(p, 'u_fill', tuple(map(float, sc.fill)))
        _set(p, 'u_color', it['color'])
        _set(p, 'u_alpha', it['alpha'] * (it.get('_ra', 1.0)))
        _set(p, 'u_metal', it['metal'])
        _set(p, 'u_spec', it['spec'])
        _set(p, 'u_shine', it['shine'])
        _set(p, 'u_emit', it['emit'])
        _set(p, 'u_rim', it['rim'])
        _set(p, 'u_texmode', it['texmode'])
        _set(p, 'u_radius', it['radius'])
        _set(p, 'u_size', it['size'])
        if it['tex'] is not None:
            k = id(it['tex'])
            tex = tex_cache.get(k)
            if tex is None:
                tex = tex_cache[k] = _texture(ctx, it['tex'])
            tex.use(0)
        vbo, vao = _vao(ctx, p, it['tris'], '3f 3f 2f', ('in_pos', 'in_nrm', 'in_uv'))
        vao.render(moderngl.TRIANGLES)
        junk += [vao, vbo]
    for o in junk:
        o.release()


def _draw_adds(ctx, sc, vp, view):
    import moderngl
    p = _prog(ctx, 'add')
    _set(p, 'u_vp', vp)
    right, up, fwd = view[0, :3], view[1, :3], -view[2, :3]
    eye = np.asarray(sc.eye, np.float64)
    junk = []
    for a in sc.adds:
        if a[0] == 'pts':
            _, P, S, C, A = a
            r = S[:, None] / 2
            c4 = np.concatenate([C, A[:, None]], axis=1)
            corners = [(-1, -1, 0, 0), (1, -1, 1, 0), (1, 1, 1, 1), (-1, -1, 0, 0), (1, 1, 1, 1), (-1, 1, 0, 1)]
            V = []
            for sx, sy, u, v in corners:
                pos = P + r * (sx * right + sy * up)
                V.append(np.concatenate([pos, np.tile((u, v), (len(P), 1)), c4], axis=1))
            data = np.stack(V, axis=1).reshape(-1, 9)
            _set(p, 'u_shape', 0)
        else:
            _, P0, P1, Wd, C, A = a
            d = P1 - P0
            mid = (P0 + P1) / 2
            vdir = eye[None, :] - mid
            side = np.cross(d, vdir)
            side /= np.maximum(np.linalg.norm(side, axis=1, keepdims=True), 1e-12)
            side *= Wd[:, None] / 2
            c4 = np.concatenate([C, A[:, None]], axis=1)
            q = [(P0 - side, 0, 0), (P1 - side, 1, 0), (P1 + side, 1, 1), (P0 - side, 0, 0), (P1 + side, 1, 1), (P0 + side, 0, 1)]
            V = [np.concatenate([pos, np.tile((u, v), (len(P0), 1)), c4], axis=1) for pos, u, v in q]
            data = np.stack(V, axis=1).reshape(-1, 9)
            _set(p, 'u_shape', 1)
        vbo, vao = _vao(ctx, p, data, '3f 2f 4f', ('in_pos', 'in_uv', 'in_col'))
        vao.render(moderngl.TRIANGLES)
        junk += [vao, vbo]
    for o in junk:
        o.release()


def _render(W, H, build, samples, bg):
    ctx = _open()  # 先に文脈（moderngl が無い・GL が無いときは、ここで理由つきの GLUnavailable）
    import moderngl
    sc = Scene(W, H)
    build(sc)
    fbo, col, dep, rfbo, rcol, sfbo, stex, sdep = _targets(ctx, W, H, samples)
    vp = sc._vp()
    view = look_at(sc.eye, sc.target, sc.up)
    tex_cache = {}
    ctx.disable(moderngl.CULL_FACE)
    try:
        fl = sc.floor_
        # 影の型（床があって、影を落とす物があるとき）：物を床の面へつぶして、白で塗る
        if fl and fl['shadow'] > 0:
            sfbo.use()
            sfbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
            ctx.disable(moderngl.DEPTH_TEST)
            ctx.enable(moderngl.BLEND)
            ctx.blend_equation = moderngl.MAX
            ctx.blend_func = moderngl.ONE, moderngl.ONE
            L = _n(sc.ldir)
            Y = fl['y'] + 1e-3
            # y=Y の面へ、光の向き L に沿ってつぶす行列
            Sm = np.array([[1, -L[0] / L[1], 0, L[0] / L[1] * Y], [0, 0, 0, Y], [0, -L[2] / L[1], 1, L[2] / L[1] * Y], [0, 0, 0, 1]], dtype=np.float64) if abs(L[1]) > 1e-3 else None
            if Sm is not None:
                items = [dict(it, model=Sm @ it['model']) for it in sc.meshes if it['shadow']]
                _draw_meshes(ctx, sc, vp, items, mode=1, tex_cache=tex_cache)
            ctx.blend_equation = moderngl.FUNC_ADD
        fbo.use()
        fbo.clear(*bg, depth=1.0)
        ctx.enable(moderngl.BLEND)
        # 色は alpha を掛けた形で積む（下の絵に重ねるとき out = 下 × (1 − a) + 色）
        ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        if fl:
            if fl['reflect'] > 0:  # 映り込み（床の下へ映した物）
                ctx.enable(moderngl.DEPTH_TEST)
                items = [dict(it, _ra=fl['reflect']) for it in sc.meshes if it['reflect']]
                _draw_meshes(ctx, sc, vp, items, reflect_plane=fl['y'], tex_cache=tex_cache)
            # 床は深さも書く（映した物は床の面の向こうにあるので、床がいつも手前。床の上の物は、このあと深さで決まる）
            ctx.enable(moderngl.DEPTH_TEST)
            pf = _prog(ctx, 'floor')
            _set(pf, 'u_vp', vp)
            S = fl['size']
            cx, _, cz = fl['center']
            M = translate(cx, fl['y'], cz) @ rot_x(-90)
            _set(pf, 'u_model', M)
            _set(pf, 'u_nmat', np.eye(3))
            _set(pf, 'u_eye', tuple(map(float, sc.eye)))
            _set(pf, 'u_color', fl['color'])
            _set(pf, 'u_alpha', fl['alpha'])
            _set(pf, 'u_fade', fl['fade'])
            _set(pf, 'u_center', fl['center'])
            _set(pf, 'u_shadowk', fl['shadow'])
            _set(pf, 'u_screen', (float(W), float(H)))
            _set(pf, 'u_shadow', 1)
            stex.use(1)
            vbo, vao = _vao(ctx, pf, quad(S, S), '3f 3f 2f', ('in_pos', 'in_nrm', 'in_uv'))
            vao.render(moderngl.TRIANGLES)
            vao.release(); vbo.release()
        # 物（奥の物から描く必要は無い：深さで決まる。半透明の物は置いた順）
        ctx.enable(moderngl.DEPTH_TEST)
        _draw_meshes(ctx, sc, vp, sc.meshes, tex_cache=tex_cache)
        # 光の粒・筋：足すだけ（深さは見るが書かない）
        if sc.adds:
            ctx.blend_func = moderngl.ONE, moderngl.ONE
            fbo.depth_mask = False
            _draw_adds(ctx, sc, vp, view)
            fbo.depth_mask = True
        ctx.copy_framebuffer(rfbo, fbo)  # MSAA をならす
        raw = rfbo.read(components=4, alignment=1)
    finally:
        for t in tex_cache.values():
            t.release()
        ctx.disable(moderngl.BLEND)
        ctx.disable(moderngl.DEPTH_TEST)
    return np.flipud(np.frombuffer(raw, np.uint8).reshape(H, W, 4)).copy()


def render(W, H, build, samples=4, bg=(0.0, 0.0, 0.0, 0.0)):
    """build(sc) で物を置いた場面を、W×H で描く（GL のスレッドで）。返すのは H×W×4 の uint8（RGB は alpha を掛けたもの）。
    GL が使えなければ GLUnavailable"""
    return _worker().call(_render, int(W), int(H), build, int(samples), tuple(map(float, bg)))


def over(f, rgba, opacity=1.0):
    """'v7' 段の絵 f（float32 0〜255、H×W×3）に、render() の絵を重ねる（f を書きかえて返す）"""
    a = rgba[..., 3:4].astype(np.float32) * (float(opacity) / 255.0)
    if not a.any():
        return f
    rgb = rgba[..., :3].astype(np.float32) * float(opacity)
    f *= (1.0 - a)
    f += rgb
    return f


def lighten(f, rgba, opacity=1.0):
    """足して明るくする（光の粒・筋だけの絵。alpha は見ない）"""
    f += rgba[..., :3].astype(np.float32) * float(opacity)
    return f
