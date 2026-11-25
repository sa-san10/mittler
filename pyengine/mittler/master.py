"""マスター書き出し（機能追加案03 v2：4K キャンバスでエフェクトも描く・ネイティブ 60fps）。
  python -m mittler master <timeline.cut.json> <出力.mp4> [--from S --to E] [--jobs N] [--force] [--check] [--fresh]
      [--master-scale 2] [--master-fps 60] [--master-out 1080] [--esrgan 場所] [--esrgan-model 名前] [--upscale anime|real|none] [--rife 場所] [--cache-gb 50]
      [--rife-model rife-v4.6] [--down area|lanczos] [--cache-fmt x264rgb10|ffv1]
      [--esrgan-j L:P:S] [--rife-j L:P:S] [--chunks N] [--threads N]   （並列・スレッド。どれも無し＝auto。下の「並列」）
流れ（提案のパイプライン①〜⑤）：
  書き出し前チェック（いつも最初に。--check ならここまで）：作品で使われている（disabled でない・隠していないトラックの）エフェクトのうち、
    META に 'scale_aware': True の無いものを名指しで一覧にして止める（MASTER_STOP の行と、人が読む文）。--force なら承知で続ける（MASTER_WARN）。
    続けて、要る道具（アプスケ・補間の exe）がこの PC に無ければ「道具が無い」と名指しで止める（描き始める前）。
  --fresh（チェックと道具の確かめが通ったあと）：この作品のキャッシュ（work/master の upscale・interp の中のファイルと hashes.json）を全部捨ててから作る。
  ① アプスケ：範囲にかかる映像クリップ（🎬 の選んだテイクも）の素材のうち、長辺がキャンバスの長辺（FHD×2 なら 3840）より小さいもの →
     Real-ESRGAN（ncnn-vulkan、-s はモデルの出せる倍率のうち足りる最小。ESRGAN_MODELS）→ 長辺をキャンバスに lanczos で合わせて work/master/upscale/<素材ハッシュ>_<モデル>_<形>.mkv。
     モデル（2026-10-31。実写とアニメから選べる。upscale_plan）：クリップの upscale → 作品（--upscale → タイムラインの
     settings.master.upscale）→ --esrgan-model（PC の設定・既定 realesr-animevideov3）。anime＝realesr-animevideov3・real＝realesrgan-x4plus（UPSCALE_KINDS）。
     同じ素材を別のモデルの2つのクリップが使えば、モデルごとに別のキャッシュを作り、クリップごとに読み替える（差し替え表の '@clips'）。
     補間する素材なら、これは②に入れる中間（形は ffv1＝可逆）で、②ができたら捨てる（補間ずみのキャッシュがあれば①はしない）。
     補間しない素材（fps が出力の fps 以上）なら、これが残すキャッシュ（形は --cache-fmt）
  ② 補間：fps が出力の fps より小さい素材 → RIFE（ncnn-vulkan、-m モデル -n 目標のコマ数＝round(コマ数×60/素材の fps)）→
     work/master/interp/<素材ハッシュ>[_<アプスケのモデル>]_60_<形>.mkv（残すキャッシュ、形は --cache-fmt。素材1本ずつなので、カットをまたぐ補間は起きない）。
     ①② は素材ごとに重ねる（tools_pass：素材 i の補間と素材 i+1 のアプスケが同時に動く。同じ道具は1本ずつ＝GPU には ESRGAN 1本と RIFE 1本まで）
  アップスケールなし（2026-10-31。アップスケールせず 60fps にするだけの版。作品の upscale が none：単体の --upscale none →
     タイムラインの settings.master.upscale。🏆 の窓の「なし（60fps だけ）」）：キャンバスはいつもの大きさ（scale 1。--master-scale は使わない）のまま 60fps で描き、
     ① はしない（Real-ESRGAN は要らない）、② は素材のいつもの大きさのまま補間（キャッシュの名前は、アプスケしない素材と同じ <素材ハッシュ>_60_<形>.mkv。
     同じ素材・同じ道具の引数なので中身も同じ。アプスケしたもの（名前にモデルが入る）とはぶつからない）、④ の縮小は無い（出力＝タイムラインの大きさ。--master-out は使わない）。
     scale 1 なので書き出し前チェックの scale_aware は見ない（止めない）。uses_fi（コマ番号で絵が変わる）の注意は 60fps なので出す。
     「なし」は作品ぜんたいの形（キャンバスが 1 倍になる）なので、クリップには書けない（クリップの upscale に none は知らない名前として止まる）。
     作品が「なし」のとき、クリップの upscale（anime・real）は使わない（どのクリップかを MASTER_WARN で知らせる）
  残すキャッシュの形（CACHE_FMTS。2026-10-30）：既定 x264rgb10＝H.264 を RGB のまま（libx264rgb・crf 10・medium）。
     前の形（FFV1、名前に形の印が無い）のキャッシュは使わない（上限の掃除で古い順に消える）。--cache-fmt ffv1 で可逆の形にもできる
  ③ 描く：エンジンを scale・fps・素材の差し替え表（①②のキャッシュ）で、いつもの書き出し（__main__.video の区間に分けた並列）と同じ形で。タイムラインは書き換えない。
     区間は並列の数より多く（render_chunks）、並列の数（render_jobs）ずつ順に流す
  ④ 縮めてエンコード：区間ごとに -vf scale=<幅>:<高さ>:flags=area（既定。--down lanczos も）→ settings.export の本番の設定（bt709 の色の変換もいつもどおり）、
     音はいつもの mix／loudnorm
  ⑤ 片付け：③④の中間（区間・コマの PNG）は消す。①②の残すキャッシュは残して、上限（--cache-gb）を超えたら古いもの（使った時刻が古い順）から消す
進み具合：PHASE check／PHASE upscale i n／PHASE interp i n／PHASE render の行と、描くあいだは PROGRESS（いつもの書き出しと同じ）。止めるのは <出力>.cancel。
既定値は下の DEFAULTS（編集画面のサーバーは server/defaults.js と PC の設定 mittler.master.* を全部渡す。docs/インストールガイド.md の 12）。
動画1本を高画質にする道具（enhance.py、python -m mittler enhance。2026-10-31）も、①② の tools_pass・道具の確かめ missing_tools・DEFAULTS をここから使う（変えるときは両方に効く）。
本物の道具で確かめたこと（2026-10-30 夜、作者のデスクトップ PC の RTX 3090。realesrgan-ncnn-vulkan 20220424・rife-ncnn-vulkan 20221029。入れ方はインストールガイドの 12）：
  RIFE の -n（目標のコマ数）で 24→60 が出る（rife-v4.6）。出力の i コマ目は入力の i×24/60 コマ目の時刻（ずれ 0.02 コマ以内）で、
  入力の最後のコマより後ろ（終わりの 2 コマ）は最後のコマのまま。×5 → 1/2 の間引きは要らない。
  出力のコマの名前はどちらも 00000001.png から（frames_of は一番小さい番号から読む）。
  models（ESRGAN の models/・RIFE の rife-v4.6/）は exe の隣にあれば、作業フォルダがどこでも読める（作業フォルダを exe のフォルダにするのは念のため）。
  GPU が2つ（内蔵＋外付け）でも、道具が自分で外付けを選ぶ（-g を付けないのと -g 1 が同じ速さ）。
並列（2026-10-30。4K のアップスケール用に並列を多くして最適化した。作者のデスクトップ PC の Ryzen 9 9900X 24 スレッド・メモリ 61.6 GB・RTX 3090 で測った。
  数と決め方は tool_threads・render_jobs・render_chunks の説明、測った道具と結果は work/features/fspeed、目安はインストールガイドの 12）：
  ① ② 道具の -j（PNG を読む・書くスレッド。既定の 1:2:2 では PNG の読み書きが詰まって GPU が 2〜3 割しか動いていなかった）と、①② を素材ごとに重ねる。
  ③ 並列の数（auto）・区間の数（auto）。OpenCV のスレッドは --threads で絞れる（既定は絞らない）。どれも絵は変えない（道具の出力の PNG・キャッシュは同じ、
     区間の数が同じなら MP4 もバイト単位で同じ）。③ は描くエフェクトの計算（4K の光のぼかしなど）で CPU が詰まっていて、途中の速さは並列 4 のときからほぼ同じ
     （偽マリア 58〜70 秒で 0.857 → 0.876 コマ/秒）。速くなるのは、区間を細かくして最後に重い区間を待つ時間を減らした分（12 秒の範囲で 1.18〜1.26 倍）。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from argparse import Namespace
from pathlib import Path

from .defaults import author
from .names import cache_root

# 既定値（単体で動かしたとき。編集画面のサーバーは server/defaults.js の master と PC の設定から全部渡す）。キーは mittler の引数の名前
DEFAULTS = {
    'esrgan': author('master', {}).get('esrgan', ''),             # アプスケ（Real-ESRGAN ncnn-vulkan）の exe。作者の PC の置き場（server/defaults.author.json）か、空＝設定で指定
    'esrgan_model': 'realesr-animevideov3',
    'rife': author('master', {}).get('rife', ''),                 # 補間（RIFE ncnn-vulkan）の exe。同じ
    'rife_model': 'rife-v4.6',                                    # 目標のコマ数（-n）を使えるのは v4 のモデルだけ
    'master_scale': 2, 'master_fps': 60, 'master_out': 1080, 'cache_gb': 50,
    'jobs': 'auto',                                               # ③ の並列の数。auto は render_jobs（CPU の数と空いているメモリから）。0 も auto
    'chunks': 'auto',                                             # ③ の区間の数。auto は render_chunks（範囲の長さから。並列の数によらない）
    'threads': 0,                                                 # ③ の区間のプロセスの OpenCV のスレッド。0＝絞らない（OpenCV の既定）。測って絞らないことにした（下の run の説明）
    'down': 'area',                                               # 縮小のフィルタ（area か lanczos）。既定は area（lanczos は星のまわりに暗い縁が出た）
    'cache_fmt': 'x264rgb10',                                     # 残すキャッシュの形（下の CACHE_FMTS）
    'esrgan_j': 'auto', 'rife_j': 'auto',                         # 道具の -j load:proc:save（PNG を読む・GPU・PNG を書くスレッド）。auto は tool_threads（CPU の数から）
}
# 残すキャッシュ（補間ずみ・補間しない素材のアプスケずみ）の形。ファイルの名前の終わりに印（キー）を付ける（形の違うものを取り違えない）。
# 残すキャッシュは、劣化のほぼ見えない高画質の H.264 でためる（2026-10-30）。
# x264rgb10＝libx264rgb（H.264 を RGB のまま。YUV への変換が無いので色の式の取り違えも丸めも起きない）・crf 10・medium。
# 本物の道具で測った（作者のデスクトップ PC、補間ずみ 4K・60fps・180 コマ、FFV1 との比べ。work/features/f03cache）：大きさは FFV1 の 1/6〜1/10（夜空のような平らな絵は 1/144）、
# マスターの最後の絵（area で 1080 に縮めたもの）の PSNR は 56〜62 dB・いちばん大きな差 14/255（拡大しても見分けられない）。
# YUV 4:4:4（8 bit）は小さい（1/23〜1/30）が、RGB との行き来の丸めで 44〜50 dB、4:2:0 は色がずれて 41〜44 dB（差が 2 を超える画素が 15〜17%）だったので使わない。
# 中間（補間に入れるアプスケずみ）はいつも ffv1（可逆。補間ができたら捨てる）。vf はエンコードの前の変換、args はエンコーダーの引数
CACHE_FMTS = {
    'ffv1': {'vf': None, 'args': ['-c:v', 'ffv1', '-level', '3', '-pix_fmt', 'bgr0']},  # 可逆（RGB のまま）。前の形
    'x264rgb10': {'vf': None, 'args': ['-c:v', 'libx264rgb', '-preset', 'medium', '-crf', '10', '-pix_fmt', 'bgr0']},
}
MID_FMT = 'ffv1'
# アップスケールのモデル（Real-ESRGAN ncnn-vulkan の -n）の決まりはここだけ（2026-10-31。実写とアニメから選べる）。
# モデル → 出せる倍率（-s）。① は足りる最小の倍率で上げて、長辺をキャンバスに lanczos で合わせる（x4 だけのモデルは x4 で上げてから縮める）。
# realesr-animevideov3 はアニメ用で、写真のような素材の細かい模様（ヒョウ柄・スパンコール・ラメの粒）を描き直して平らにする（偽マリアを 4K で通して分かった。
# 見比べは docs/インストールガイド.md の「🏆 アップスケールのモデル」）。realesrgan-x4plus は写真向け。どちらも Real-ESRGAN ncnn-vulkan 20220424（v0.2.5.0）の models に入っている
ESRGAN_MODELS = {
    'realesr-animevideov3': (2, 3, 4),   # アニメ用（models/realesr-animevideov3-x2・x3・x4.param）。今までの既定
    'realesrgan-x4plus': (4,),           # 写真向け（models/realesrgan-x4plus.param、x4 だけ）
    'realesrgan-x4plus-anime': (4,),     # アニメの絵向けの x4（x4 だけ。名前で選ぶ口は無い。--esrgan-model で）
}
ESRGAN_SCALES = (2, 3, 4)  # 上の表に無いモデルの -s（今までと同じ）
# 作品（settings.master.upscale）・クリップ（upscale）・単体の --upscale の名前 → モデル。編集画面の表示は server/defaults.js の masterUpscale（同じもの。tools/smoke_same.py が確かめる）
UPSCALE_KINDS = {'anime': 'realesr-animevideov3', 'real': 'realesrgan-x4plus'}
# アップスケールなし（60fps だけ、2026-10-31）の名前。作品（settings.master.upscale）と単体の --upscale だけ（クリップには書けない）。上の頭の説明の「アップスケールなし」。
# 編集画面は server/defaults.js の masterNoUpscale（同じもの。tools/smoke_same.py が確かめる）
UPSCALE_NONE = 'none'
DOC = 'docs/エフェクトの書き方.md'
_abort = threading.Event()   # ①② を重ねて動かすとき、片方が止まった・失敗したら、もう片方の道具も止める
_say = threading.Lock()


def say(line):
    """1行を出す（①② の2つのスレッドの行が混ざらないように）"""
    with _say:
        sys.stdout.write(line + '\n')
        sys.stdout.flush()


def tool_threads(tool, n=None):
    """道具の -j load:proc:save（PNG を読む・GPU で計算・PNG を書くスレッドの数）。CPU の論理プロセッサの数 n から決める。
    2026-10-30 作者のデスクトップ PC（Ryzen 9 9900X 24 スレッド・RTX 3090）で測った（偽マリアの素材 1344×768・96 コマ。work/features/fspeed）：
      Real-ESRGAN（×3）は既定の 1:2:2 で 24.2 秒 → 2:2:8 で 7.3 秒（読む・計算を増やしても変わらない。書く PNG が詰まっていた）、
      RIFE（4K・96→240 コマ）は 1:2:2 で 54.1 秒 → 8:2:16 で 12.2 秒（4K の PNG を読む・書くのが詰まっていた。proc を 4 にしても速くならず、VRAM だけ増える）。
    どちらも出力の PNG は -j によらずバイト単位で同じ。proc（GPU）は既定の 2 のまま（VRAM は今までと同じ）。
    n＝24 で esrgan 2:2:8・rife 8:2:16、n＝16 で 2:2:5・5:2:10、n＝4 以下は道具の既定と同じ 1:2:2"""
    n = n or os.cpu_count() or 4
    if tool == 'esrgan':
        return f'{max(1, min(2, n // 8))}:2:{max(2, min(8, n // 3))}'
    return f'{max(1, min(8, n // 3))}:2:{max(2, min(16, n * 2 // 3))}'


JOB_GB = 2.5      # ③ の区間のプロセス1本のメモリ（描く python 0.4〜1 GB＋縮めてエンコードする ffmpeg 約 1.3 GB。作者のデスクトップ PC の偽マリアで 2.2〜2.5 GB）
KEEP_GB = 4.0     # ③ を始めるとき、空いているメモリのうち残しておく分
CHUNK_MIN, CHUNK_MAX, CHUNK_N = 30, 300, 128  # ③ の区間のコマ数の下限・上限と、範囲をいくつに分けたいか（偽マリア全部の 9262 コマなら 73 コマずつ 127 区間）


def mem_avail_gb():
    """いま空いている物理メモリ（GB）。分からなければ None"""
    try:
        if os.name == 'nt':
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong)] + \
                           [(n, ctypes.c_ulonglong) for n in ('total', 'avail', 'tpf', 'apf', 'tv', 'av', 'aev')]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return None
            return m.avail / 1e9
        return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') / 1e9
    except (OSError, ValueError, AttributeError):
        return None


def render_jobs(n_cpu=None, avail_gb=None):
    """③ の並列の数（auto）：CPU の論理プロセッサの数の半分と、空いているメモリ（KEEP_GB を残して1本 JOB_GB）で入る数の小さいほう（1〜16）。
    2026-10-30 作者のデスクトップ PC（24 スレッド・メモリ 61.6 GB）の偽マリア（4K・60fps、14〜20 秒＝360 コマ、区間＝並列の数）で測った：並列 4 は 466 秒・CPU 58%、
    8 は 404 秒・75%、12 は 391〜395 秒・79〜85%、16 は 373〜398 秒・92%（12 と同じくらい。メモリだけ増える：自分のプロセスの合計 28 → 37 GB）、
    24 はメモリが足りなくなった（PC 全体で 64.6 / 66 GB。止める（.cancel）も 150 秒以上届かなかった）→ 作者のデスクトップ PC では 12。作者のノート PC（16 スレッド）は 8 まで。
    重い 14〜26 秒（720 コマ）の ③④ は、前の版（並列 4）1104 秒 → 並列 8 で 941 秒・12 で 875〜888 秒（区間 30）。
    ただし途中の速さ（全部のプロセスが動いているところ）は並列 4 とほぼ同じ（58〜70 秒：並列 4 で 0.857・12 で 0.876 コマ/秒。CPU は 57% → 87% 使うが、
    OpenCV が 1 プロセスの中で CPU を使い切っているところが多い）。速くなった分の多くは区間の数（render_chunks）から。12 にしているのは、どの測りでも 12 がいちばん速く、
    メモリに余裕がある（PC 全体で 41 GB）ため"""
    n_cpu = n_cpu or os.cpu_count() or 4
    j = max(1, n_cpu // 2)
    if avail_gb is None:
        avail_gb = mem_avail_gb()
    if avail_gb is not None:
        j = min(j, max(1, int((avail_gb - KEEP_GB) / JOB_GB)))
    return max(1, min(16, j))


def render_chunks(frames):
    """③ の区間の数（auto）：範囲を CHUNK_N に分けたいが、1区間は CHUNK_MIN〜CHUNK_MAX コマ（区間ごとの立ち上がり・頭の映像のシークの分があるので短すぎない）。
    並列の数によらないので、並列の数を変えても MP4 は同じになる（区間の切り方で x264 の絵が決まるため）。
    2026-10-30 作者のデスクトップ PC の偽マリア 14〜26 秒（720 コマ・並列 12）：区間 12（＝並列の数。今までの分け方）は 945 秒で、最後の約 200 秒は重い区間を数本待つだけだった
    （CPU 82% → 10〜20%）。区間 30 で 888 秒。区間の立ち上がり（Python・エンジン・頭の 4K の映像のシーク）は1本数秒"""
    per = min(CHUNK_MAX, max(CHUNK_MIN, -(-frames // CHUNK_N)))
    return max(1, -(-frames // per))


def tool_j(a, tool):
    """-j の値（--esrgan-j・--rife-j。auto なら tool_threads）"""
    v = str(getattr(a, f'{tool}_j', None) or 'auto')
    if v == 'auto':
        return tool_threads(tool)
    if not re.fullmatch(r'\d+:\d+:\d+', v):
        raise SystemExit(f'--{tool}-j は auto か load:proc:save の形（例 2:2:8）（{v}）')
    return v


def esrgan_scale(model, info, target):
    """① の -s：そのモデルが出せる倍率（ESRGAN_MODELS）のうち、長辺が target に足りる最小（足りなければいちばん大きい倍率）。ずれは lanczos で合わせる"""
    sc = ESRGAN_MODELS.get(model, ESRGAN_SCALES)
    long_ = max(info['w'], info['h'])
    return next((k for k in sc if long_ * k >= target), sc[-1])


def esrgan_param(model, s):
    """そのモデルを -s s で読むときに Real-ESRGAN ncnn-vulkan が開く models/ のファイル（realesr-animevideov3 だけ倍率ごとのファイル）"""
    return f'{model}-x{s}.param' if model == 'realesr-animevideov3' else f'{model}.param'


def clip_sources(eng, t0, t1):
    """範囲 [t0, t1) にかかる映像クリップ（🎬 の選んだテイクも）と、その素材：[(クリップ, [タイムラインに書いたパス…])]（画像クリップは入れない）"""
    from .engine import plan_take
    out = []
    for c in eng.video_clips:
        if c['start'] >= t1 or c['start'] + c['dur'] <= t0 or c.get('type') == 'image':
            continue
        if c.get('type') == 'plan':
            tk = plan_take(c)
            srcs = [tk['src']] if tk and (eng.root / tk['src']).is_file() else []
        else:
            srcs = [c['src']] if isinstance(c['src'], str) else list(c['src'])
        out.append((c, srcs))
    return out


def upscale_plan(a, eng, uses):
    """① のモデルを決める（2026-10-31）。→ (作品のモデル, {(クリップの id, 素材のパス): モデル})。
    クリップの upscale（anime・real）→ 作品（単体の --upscale → タイムラインの settings.master.upscale）→ --esrgan-model（PC の設定 mittler.master.esrganModel、
    既定 realesr-animevideov3）。どこにも書いていなければ今までと同じ。知らない名前は名指しで止める（描き始める前）。
    作品が none（アップスケールなし）なら、作品のモデルは UPSCALE_NONE（① はしないので、クリップの anime・real も使われない。run が up_rel を空にする）"""
    bad = []
    cli = getattr(a, 'upscale', None)
    wk = work_upscale(a, eng.settings)
    if wk and wk not in UPSCALE_KINDS and wk != UPSCALE_NONE:
        bad.append(f'{"引数 --upscale" if cli else "作品の settings.master.upscale"}「{wk}」')
    wmodel = UPSCALE_NONE if wk == UPSCALE_NONE else UPSCALE_KINDS.get(wk, a.esrgan_model) if wk else a.esrgan_model
    per = {}
    for c, ss in uses:
        k = c.get('upscale')
        if k and k not in UPSCALE_KINDS:
            bad.append(f'クリップ {c.get("id")}（{c.get("label") or ""}）の upscale「{k}」' +
                       ('（none＝アップスケールなし は作品ぜんたいの設定だけ。クリップには書けない）' if k == UPSCALE_NONE else ''))
            continue
        for s in ss:
            per[(c['id'], s)] = UPSCALE_KINDS[k] if k else wmodel
    if bad:
        stop('upscale', 'マスター書き出しできません。アップスケールの指定が分からない：\n' + ''.join(f'  {b}\n' for b in bad) +
             f'使えるのは {"・".join(UPSCALE_KINDS)}（anime＝アニメ・real＝実写。書かなければ作品の設定。docs/タイムライン形式.md）。'
             f'作品（settings.master.upscale・--upscale）には {UPSCALE_NONE}（アップスケールなし・60fps だけ）も', items=bad)
    return wmodel, per


def work_upscale(a, settings):
    """作品のアップスケールの名前：単体の --upscale（🏆 の窓から始めた書き出しは窓の選択）→ タイムラインの settings.master.upscale。無ければ None"""
    return getattr(a, 'upscale', None) or ((settings or {}).get('master') or {}).get('upscale')


def ignored_clips(eng, t0, t1):
    """アップスケールなしのとき使わない、クリップの upscale（anime・real）：['クリップの id（ラベル）：名前', …]（範囲にかかる映像クリップ・🎬 予定のクリップ）"""
    return [f'{c.get("id")}{"（" + c["label"] + "）" if c.get("label") else ""}：{c["upscale"]}'
            for c, _ in clip_sources(eng, t0, t1) if c.get('upscale') in UPSCALE_KINDS]


def effect_usage(eng):
    """作品で使われているエフェクト：[(名前, クリップの本数)]（disabled でない・隠していないトラック。ASS でない字幕は subtitle）"""
    n = {}
    for c in eng.effect_clips:
        n[c['effect']] = n.get(c['effect'], 0) + 1
    return sorted(n.items())


def scale_check(eng, scaled=True):
    """書き出し前チェック。{'ok', 'missing': [{name, file, clips, why}], 'fi': [{name, file, clips}], 'message'}。
    missing＝META に 'scale_aware': True が無い（読めないものも）、fi＝scale_aware だが META に 'uses_fi': True（ctx.fi・ctx.sfi で絵が変わる。60fps で進みが変わる）。
    scaled＝False（アップスケールなし：キャンバスは 1 倍）なら scale_aware は見ない（missing は空・ok）。fi は scale_aware によらず META に 'uses_fi': True のもの"""
    if not scaled:
        fi = []
        for name, k in effect_usage(eng):
            try:
                meta = getattr(eng.effect(name), 'META', {}) or {}
            except Exception:  # noqa: BLE001（読めないエフェクトは、描くときにいつもの書き出しと同じに扱われる。ここでは止めない）
                meta = {}
            if meta.get('uses_fi'):
                fi.append({'name': name, 'file': f'effects/{name}.py', 'clips': k})
        return {'ok': True, 'missing': [], 'fi': fi, 'message': '', 'scale_aware_needed': False}
    missing, fi = [], []
    for name, k in effect_usage(eng):
        rel = f'effects/{name}.py'
        why = ''
        try:
            meta = getattr(eng.effect(name), 'META', {}) or {}
        except FileNotFoundError:
            meta, why = {}, 'ファイルが無い'
        except Exception as e:  # noqa: BLE001（読めないエフェクトも名指しで止める）
            meta, why = {}, f'読めない：{type(e).__name__}: {e}'
        if not meta.get('scale_aware'):
            missing.append({'name': name, 'file': rel, 'clips': k, 'why': why})
        elif meta.get('uses_fi'):
            fi.append({'name': name, 'file': rel, 'clips': k})
    msg = ''
    if missing:
        msg = 'マスター書き出しできません。scale 未対応のエフェクト：\n' + ''.join(
            f"  {m['name']}（{m['file']}）… クリップ {m['clips']} 本{'（' + m['why'] + '）' if m['why'] else ''}\n" for m in missing) + \
            f"各エフェクトに ctx.scale の対応を足して META に 'scale_aware': True を宣言してください（{DOC}）"
    return {'ok': not missing, 'missing': missing, 'fi': fi, 'message': msg}


def stop(kind, message, **extra):
    """止める：編集画面のサーバーが読む1行（MASTER_STOP <JSON>）と、人が読む文"""
    say('MASTER_STOP ' + json.dumps(dict(kind=kind, message=message, **extra), ensure_ascii=False))
    say(message)
    raise SystemExit(4)


def opt(a, name):
    """コマンドの値か、無ければ DEFAULTS"""
    v = getattr(a, name, None)
    return DEFAULTS[name] if v is None else v


def num(v):
    """整数なら int（ファイルの名前・ffmpeg の引数に 60.0 と書かない）"""
    f = float(v)
    return int(f) if f.is_integer() else f


def main_master(a):
    from .engine import Engine
    for k in DEFAULTS:  # 付けなかった引数は既定値
        if getattr(a, k, None) is None:
            setattr(a, k, DEFAULTS[k])
    a.master_scale, a.master_fps, a.master_out = num(a.master_scale), num(a.master_fps), int(a.master_out)
    if a.cache_fmt not in CACHE_FMTS:
        raise SystemExit(f'--cache-fmt は {"・".join(CACHE_FMTS)} のどれか（{a.cache_fmt}）')
    # アップスケールなし（作品の upscale が none）：キャンバスはいつもの大きさ・縮めない（--master-scale・--master-out は使わない）。
    # Engine を作る前に決める（キャンバスの大きさが変わるため）。タイムラインの読み方は Engine.load と同じ
    try:
        st = json.loads(Path(a.timeline).read_text(encoding='utf-8')).get('settings')
    except (OSError, ValueError, AttributeError):
        st = None  # 読めなければ Engine が理由つきで落ちる
    a.no_up = work_upscale(a, st) == UPSCALE_NONE
    if a.no_up:
        a.master_scale, a.master_out = 1, 0
    eng = Engine(a.timeline, hwaccel=a.hwaccel, scale=a.master_scale, fps=a.master_fps)
    try:
        if a.no_up:
            say(f'upscale なし：キャンバス {eng.W}x{eng.H}（1 倍）のまま {a.master_fps}fps で描く。映像の素材は補間だけ（アップスケールしない）・書き出しは {eng.W}x{eng.H}（縮めない）')
        print('PHASE check', flush=True)
        check_only(a, eng)
        if a.check:
            return
        run(a, eng)
    finally:
        eng.close()


# ---------------------------------------------------------------- ①〜⑤
def probe(path):
    """素材の幅・高さ・fps（r_frame_rate の文字と数）"""
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,r_frame_rate', '-of', 'json', str(path)],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)['streams'][0]
    n, d = s['r_frame_rate'].split('/')
    return {'w': int(s['width']), 'h': int(s['height']), 'rate': s['r_frame_rate'], 'fps': float(n) / float(d)}


def file_hash(path, book):
    """素材のハッシュ（中身の SHA-256 の頭 16 文字）。同じパス・大きさ・更新時刻なら book（work/master/hashes.json）から"""
    st = os.stat(path)
    key = f'{Path(path).resolve()}|{st.st_size}|{st.st_mtime_ns}'
    if key not in book:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for b in iter(lambda: f.read(1 << 22), b''):
                h.update(b)
        book[key] = h.hexdigest()[:16]
    return book[key]


def sources(eng, t0, t1):
    """範囲 [t0, t1) にかかる映像クリップ（🎬 の選んだテイクも）の素材：{タイムラインに書いたパス: ファイル}（画像クリップは入れない）"""
    return {s: eng.root / s for _, ss in clip_sources(eng, t0, t1) for s in ss}


def find_tool(exe):
    """道具の exe（ファイルのパスか、PATH の名前）。無ければ None"""
    p = Path(exe)
    if p.is_file():
        return str(p)
    return shutil.which(exe) if p.parent == Path('.') else None  # 名前だけなら PATH から


def kill_tree(p):
    from .procs import kill_tree as kt  # taskkill が断られたら子孫を数えて止める
    kt(p)
    p.wait()


def run_step(cmd, cancel, log, what, cwd=None):
    """道具・ffmpeg を1つ動かす。<出力>.cancel ができたら子ごと止めて CANCELLED（終わりの番号 3）。失敗したら MASTER_STOP（何が・ログの終わり）。
    ①② を重ねているとき、もう片方の段が止まった（_abort）ときも子ごと止める"""
    with open(log, 'a', encoding='utf-8', errors='replace') as lf:
        lf.write('$ ' + ' '.join(str(x) for x in cmd) + '\n')
        lf.flush()
        p = subprocess.Popen([str(x) for x in cmd], stdout=lf, stderr=subprocess.STDOUT, cwd=cwd)
        while p.poll() is None:
            if cancel.exists() or _abort.is_set():
                kill_tree(p)
                raise Cancelled()
            time.sleep(0.3)
    if p.returncode:
        tail = Path(log).read_text(encoding='utf-8', errors='replace')[-1200:]
        stop('tool_failed', f'マスター書き出しが止まった：{what}が失敗（{p.returncode}）\n{tail}')


class Cancelled(Exception):
    pass


def frames_of(d):
    """フォルダの連番の PNG（名前の数で並べる）"""
    fs = sorted(d.glob('*.png'), key=lambda p: int(p.stem) if p.stem.isdigit() else -1)
    return [p for p in fs if p.stem.isdigit()]


def extract(src, d, cancel, log, what):
    """素材のコマを PNG に。PNG の圧縮は 3（ffmpeg の既定より軽い。PNG は可逆なので絵は同じ。作者のデスクトップ PC の 4K・96 コマで 5.4 → 3.6 秒、大きさはほぼ同じ、
    それを読む RIFE の時間も出力も同じ。0・1 はファイルが 1.6〜2.6 倍になるわりに速くならない）"""
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    run_step(['ffmpeg', '-v', 'error', '-y', '-i', src, '-map', '0:v:0', '-fps_mode', 'passthrough', '-start_number', '1', '-compression_level', '3', d / '%08d.png'],
             cancel, log, what)
    return frames_of(d)


def encode(d, rate, dst, cancel, log, what, vf=None, fmt=MID_FMT):
    """連番の PNG → mkv（形は CACHE_FMTS の fmt。既定は FFV1＝可逆・RGB のまま）。書き終えてから名前を付ける"""
    fs = frames_of(d)
    if not fs:
        stop('tool_failed', f'マスター書き出しが止まった：{what}の出力のコマが無い（{d}）')
    F = CACHE_FMTS[fmt]
    vf = ','.join(x for x in (vf, F['vf']) if x)
    part = dst.with_name(dst.name + '.part')
    run_step(['ffmpeg', '-v', 'error', '-y', '-framerate', rate, '-start_number', fs[0].stem, '-i', d / ('%0' + str(len(fs[0].stem)) + 'd.png')] +
             (['-vf', vf] if vf else []) + F['args'] + ['-f', 'matroska', part], cancel, log, what)
    os.replace(part, dst)
    return len(fs)


def upscale(a, src, info, target, dst, tmp, cancel, log, fmt, model):
    """① Real-ESRGAN（モデル model）で長辺を target に（-s は esrgan_scale、はみ出したら lanczos で合わせる）。
    fmt：補間に入れる中間なら MID_FMT（可逆）、そのまま残すなら a.cache_fmt"""
    long_ = max(info['w'], info['h'])
    s = esrgan_scale(model, info, target)
    din, dout = tmp / 'up_in', tmp / 'up_out'
    n = len(extract(src, din, cancel, log, 'アプスケの前のコマの取り出し'))
    if dout.exists():
        shutil.rmtree(dout)
    dout.mkdir(parents=True)
    exe = find_tool(a.esrgan)
    run_step([exe, '-i', din, '-o', dout, '-n', model, '-s', s, '-f', 'png', '-j', tool_j(a, 'esrgan')], cancel, log, 'アプスケ（Real-ESRGAN）',
             cwd=str(Path(exe).parent))
    got = len(frames_of(dout))
    if got != n:
        stop('tool_failed', f'マスター書き出しが止まった：アプスケの出力のコマの数が違う（{n} → {got}）')
    vf = None
    if long_ * s != target:
        vf = (f'scale={target}:-2' if info['w'] >= info['h'] else f'scale=-2:{target}') + ':flags=lanczos'
    encode(dout, info['rate'], dst, cancel, log, 'アプスケのエンコード', vf, fmt)
    shutil.rmtree(din)
    shutil.rmtree(dout)
    return {'frames': n, 'model': model, 'esrgan_scale': s, 'fit': vf, 'fmt': fmt}


def interp_frames(a, src, info, tmp, k, cancel, log):
    """② の前半：RIFE で fps を出力の fps に（-n＝目標のコマ数。素材1本ずつ）。出力のコマのフォルダは素材ごと（k）に分ける
    （エンコード＝後半 interp_encode は、次の素材の取り出し・RIFE と重ねて動くため）。→ (入力のフォルダ, 出力のフォルダ, 結果)"""
    din, dout = tmp / f'ip_in_{k}', tmp / f'ip_out_{k}'
    n = len(extract(src, din, cancel, log, '補間の前のコマの取り出し'))
    want = int(round(n * a.master_fps / info['fps']))
    if dout.exists():
        shutil.rmtree(dout)
    dout.mkdir(parents=True)
    exe = find_tool(a.rife)
    run_step([exe, '-i', din, '-o', dout, '-m', a.rife_model, '-n', want, '-j', tool_j(a, 'rife')], cancel, log, '補間（RIFE）', cwd=str(Path(exe).parent))
    got = len(frames_of(dout))
    if got != want:
        stop('tool_failed', f'マスター書き出しが止まった：補間の出力のコマの数が違う（{n} → {got}、ほしいのは {want}）')
    shutil.rmtree(din)
    return dout, {'frames_in': n, 'frames_out': want, 'fmt': a.cache_fmt}


def interp_encode(a, dout, dst, cancel, log):
    """② の後半：RIFE の出力のコマ → 残すキャッシュ（形は a.cache_fmt）"""
    encode(dout, str(a.master_fps), dst, cancel, log, '補間のエンコード', fmt=a.cache_fmt)
    shutil.rmtree(dout)


def trim_cache(mdir, cap_gb, keep):
    """⑤ キャッシュの上限：upscale・interp の *.mkv の合計が cap を超えたら、使った時刻（更新時刻）が古いものから消す（今回使ったものは消さない）"""
    files = [p for d in ('upscale', 'interp') for p in (mdir / d).glob('*.mkv')]
    total = sum(p.stat().st_size for p in files)
    cap = cap_gb * 1e9
    gone = []
    for p in sorted(files, key=lambda p: p.stat().st_mtime):
        if total <= cap:
            break
        if str(p.resolve()) in keep:
            continue
        total -= p.stat().st_size
        p.unlink()
        gone.append(p.name)
    return total, gone


def fresh(mdir):
    """--fresh：この作品のキャッシュを全部捨てる（作品の work/master の upscale・interp の中のファイルと hashes.json だけ。
    フォルダの中のフォルダ・リンクの先・ほかの作品・tmp（ほかの書き出しの途中かもしれない）には触らない）。→ (本数, バイト)"""
    n = b = 0
    targets = [p for d in ('upscale', 'interp') if (mdir / d).is_dir() for p in (mdir / d).iterdir()] + [mdir / 'hashes.json']
    for p in targets:
        if p.is_file() and not p.is_symlink():
            b += p.stat().st_size
            p.unlink()
            n += 1
    return n, b


def tools_pass(a, srcs, infos, need_up, need_ip, ip_dst, hashes, target, mdir, tmp, cancel, files, used, report, rk):
    """①② アプスケと補間。2026-10-30 から素材ごとに重ねる（4K のアップスケール用の並列）：
    ① アプスケは別のスレッドで素材の順に、② 補間はこのスレッドで素材の順に（その素材の①が終わってから）、② のエンコード（RIFE の出力 → キャッシュ）は
    もう1つのスレッドで（次の素材のコマの取り出し・RIFE と重ねる。1本ずつ）。同じ道具は1本ずつなので、
    GPU に同時にいるのは Real-ESRGAN 1本と RIFE 1本まで（VRAM は RIFE（4K）＋ESRGAN の約 3.5 GB まで）。素材 i の補間と、素材 i+1 のアプスケ・
    コマの取り出し・エンコード（CPU）が重なる。キャッシュの名前・中身・中間の扱いは前と同じ（道具を呼ぶ引数は -j、取り出す PNG の圧縮だけが変わった）。
    進み具合の行は前と同じ順（PHASE upscale 0..n のあと PHASE interp k..n）：アプスケが全部終わるまではアプスケの数、そのあとは補間の数。
    need_up・need_ip・ip_dst の鍵は (素材のパス, アプスケのモデル)（2026-10-31〜。アプスケしない素材はモデル None。同じ素材でもモデルが違えば別のもの）。
    できたファイルは files[鍵]（③ の差し替え表は run が作る）、report の鍵は rk(鍵)"""
    fmt = a.cache_fmt
    up = {}                                        # 補間に入れる中間（可逆）
    ready = {k: threading.Event() for k in need_up}
    st = {'n_up': 0, 'n_ip': 0, 'err': None}
    lock = threading.Lock()

    def phase():
        if st['n_up'] < len(need_up):
            say(f'PHASE upscale {st["n_up"]} {len(need_up)}')
        elif need_ip:
            say(f'PHASE interp {st["n_ip"]} {len(need_ip)}')

    def stage_up():
        log = tmp / 'tools_up.log'
        try:
            for k in need_up:
                rel, model = k
                keep = k not in ip_dst  # 補間しない素材：アプスケずみが残すキャッシュ
                dst = mdir / 'upscale' / f'{hashes[rel]}_{model}_{fmt if keep else MID_FMT}.mkv'
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not keep and ip_dst[k].exists():  # 補間ずみがある：アプスケは要らない（前に止めたときの中間が残っていれば捨てる）
                    dst.unlink(missing_ok=True)
                    r = '要らない（補間ずみのキャッシュがある）'
                    say(f'upscale {rel} → 要らない（補間ずみのキャッシュがある）')
                else:
                    r = 'キャッシュ' if dst.exists() else upscale(a, srcs[rel], infos[rel], target, dst, tmp, cancel, log, fmt if keep else MID_FMT, model)
                    os.utime(dst)
                    say(f'upscale {rel} → {dst.name}（{r}）')
                with lock:
                    rep = report.setdefault(rk(k), {})
                    rep['model'] = model
                    rep['upscale'] = r
                    if r != '要らない（補間ずみのキャッシュがある）':
                        if keep:
                            used.add(str(dst.resolve()))
                            files[k] = str(dst)
                        else:
                            up[k] = dst
                    st['n_up'] += 1
                    if st['n_up'] == len(need_up):
                        say(f'PHASE upscale {len(need_up)} {len(need_up)}')
                    phase()
                ready[k].set()
        except BaseException as e:  # noqa: BLE001（止める・失敗は、補間のスレッドが受け取って投げ直す）
            st['err'] = e
            _abort.set()
            for ev in ready.values():
                ev.set()

    def finish(k, dst, r):
        """補間ずみができた（かキャッシュがあった）：入れた中間（アプスケずみ）を捨てて、差し替え表に入れる"""
        with lock:
            if k in up:
                up.pop(k).unlink(missing_ok=True)
        os.utime(dst)
        say(f'interp {k[0]} → {dst.name}（{r}）')
        with lock:
            report.setdefault(rk(k), {})['interp'] = r
            used.add(str(dst.resolve()))
            files[k] = str(dst)
            st['n_ip'] += 1
            if st['n_up'] == len(need_up):
                phase()

    enc = {'th': None, 'err': None}  # 補間のエンコード（1本ずつ。次の素材のコマの取り出し・RIFE と重ねる）

    def encode_bg(k, dout, dst, r):
        try:
            interp_encode(a, dout, dst, cancel, tmp / 'tools_enc.log')
            finish(k, dst, r)
        except BaseException as e:  # noqa: BLE001（このスレッドの止める・失敗は、補間のスレッドが受け取って投げ直す）
            enc['err'] = e
            _abort.set()

    def wait_enc():
        if enc['th']:
            enc['th'].join()
            enc['th'] = None
        if enc['err']:
            raise enc['err']

    _abort.clear()
    phase()
    th = threading.Thread(target=stage_up, daemon=True) if need_up else None
    if th:
        th.start()
    try:
        log = tmp / 'tools_ip.log'
        for i, k in enumerate(need_ip):
            dst = ip_dst[k]
            dst.parent.mkdir(parents=True, exist_ok=True)
            if k in ready:
                while not ready[k].wait(0.3):
                    if cancel.exists():
                        raise Cancelled()
                if st['err']:
                    raise st['err']
            if dst.exists():
                finish(k, dst, 'キャッシュ')
                continue
            with lock:
                src = up.get(k, srcs[k[0]])
            dout, r = interp_frames(a, src, probe(src), tmp, i, cancel, log)
            wait_enc()  # 前の素材のエンコードが終わってから、この素材のエンコードを始める
            enc['th'] = threading.Thread(target=encode_bg, args=(k, dout, dst, r), daemon=True)
            enc['th'].start()
        wait_enc()
        if th:
            th.join()
        if st['err']:
            raise st['err']
    except BaseException:
        _abort.set()  # アプスケのスレッド・エンコードのスレッドの道具も止める
        for t in (th, enc['th']):
            if t:
                t.join()
        for e in (st['err'], enc['err']):  # ほかのスレッドの失敗（MASTER_STOP 済み）を、そのせいで止めた Cancelled より先に
            if isinstance(e, SystemExit):
                raise e
        raise


def missing_tools(a, need_up, need_ip, infos, target, fps):
    """道具の確かめ（描き始める前）：要る道具・モデルのファイルが無いもの [{tool, path, clips, text}]（無ければ []）。
    need_up・need_ip の鍵は (素材のパス, モデル)。run と、動画1本を高画質にする道具（enhance.py）が使う"""
    miss = []
    n_up, n_ip = len({k[0] for k in need_up}), len({k[0] for k in need_ip})
    if need_up and not find_tool(a.esrgan):
        miss.append({'tool': 'esrgan', 'path': a.esrgan, 'clips': n_up,
                     'text': f'アプスケ（Real-ESRGAN ncnn-vulkan）：{a.esrgan} が無い（長辺が {target} より小さい映像の素材 {n_up} 本に要る）'})
    elif need_up:  # モデルのファイル（exe の隣の models/ があるときだけ見る。無ければ道具に任せる）
        mdl = Path(find_tool(a.esrgan)).parent / 'models'
        lack = {}
        for rel, m in need_up:
            lack.setdefault(esrgan_param(m, esrgan_scale(m, infos[rel], target)), set()).add(rel)
        lack = {f: r for f, r in lack.items() if mdl.is_dir() and not (mdl / f).is_file()}
        for f, r in lack.items():
            miss.append({'tool': 'esrgan_model', 'path': str(mdl / f), 'clips': len(r),
                         'text': f'アプスケのモデル：{mdl / f} が無い（映像の素材 {len(r)} 本に要る。モデルは exe の隣の models/ に置く。インストールガイドの 12）'})
    if need_ip and not find_tool(a.rife):
        miss.append({'tool': 'rife', 'path': a.rife, 'clips': n_ip,
                     'text': f'補間（RIFE ncnn-vulkan）：{a.rife} が無い（fps が {fps} より小さい映像の素材 {n_ip} 本に要る）'})
    return miss


def run(a, eng):
    from .__main__ import video
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cancel = Path(str(out) + '.cancel')
    cancel.unlink(missing_ok=True)  # 前に止めたときの印
    t1 = a.t1 if a.t1 is not None else eng.duration
    mdir = cache_root(eng.dir) / 'master'  # ふつうは作品の work/master（names.py の cache_root）
    target = max(eng.W, eng.H)  # キャンバスの長辺（FHD×2 なら 3840）
    fps = a.master_fps
    uses = clip_sources(eng, a.t0, t1)
    srcs = {s: eng.root / s for _, ss in uses for s in ss}
    infos = {rel: probe(p) for rel, p in srcs.items()}
    # アップスケールなし（a.no_up）：① はしない（補間は素材のいつもの大きさのまま。キャッシュの名前はアプスケしない素材と同じ）
    up_rel = set() if getattr(a, 'no_up', False) else {rel for rel in srcs if max(infos[rel]['w'], infos[rel]['h']) < target}
    ip_rel = {rel for rel in srcs if infos[rel]['fps'] < fps - 0.01}
    # アプスケのモデル（クリップ → 作品 → PC の設定）。鍵＝(素材のパス, モデル)：アプスケしない素材はモデル None。並びは素材が最初に出てくる順（今までと同じ）
    wmodel, per = upscale_plan(a, eng, uses)
    keys = []
    for (_, rel), m in per.items():
        k = (rel, m if rel in up_rel else None)
        if k not in keys:
            keys.append(k)
    need_up = [k for k in keys if k[0] in up_rel]
    need_ip = [k for k in keys if k[0] in ip_rel]

    def rk(k):  # 記録（MASTER_DONE の sources）の鍵：作品のモデルなら素材のパスだけ（今までと同じ）、クリップで変えたものは「パス（モデル）」
        return k[0] if k[1] in (None, wmodel) else f'{k[0]}（{k[1]}）'
    # 道具の確かめ（描き始める前）
    n_up, n_ip = len({k[0] for k in need_up}), len({k[0] for k in need_ip})
    miss = missing_tools(a, need_up, need_ip, infos, target, fps)
    if miss:
        stop('tools', 'マスター書き出しできません。道具が無い：\n' + ''.join(f"  {m['text']}\n" for m in miss) +
             '場所は設定 mittler.master.esrgan・mittler.master.rife（単体は --esrgan・--rife）で決める（docs/インストールガイド.md の 12）', tools=miss)
    if a.fresh:  # キャッシュを捨てて新規で（チェックと道具の確かめが通ってから。止まるときは捨てない）
        n, b = fresh(mdir)
        print(f'fresh この作品のキャッシュを捨てた：{n} 本・{b / 1e9:.2f} GB（work/master の upscale・interp・hashes.json）', flush=True)
    tmp = mdir / 'tmp' / f'run_{os.getpid()}'
    tmp.mkdir(parents=True, exist_ok=True)
    book_f = mdir / 'hashes.json'
    try:
        book = json.loads(book_f.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        book = {}
    files, used, report = {}, set(), {}
    fmt = a.cache_fmt
    try:
        hashes = {rel: file_hash(srcs[rel], book) for rel in srcs if rel in up_rel or rel in ip_rel}
        book_f.write_text(json.dumps(book, indent=1), encoding='utf-8')
        # 残すキャッシュの名前（形の印つき）。補間する素材は補間ずみだけを残し（A）、補間しない素材はアプスケずみを残す。アプスケした素材はモデルの名前が入る
        # （アップスケールなしの補間ずみは、アプスケしない素材と同じ <ハッシュ>_60_<形>.mkv：同じ素材を同じ引数で補間したものなので、4K のマスターと使い回せる）
        ip_dst = {(rel, m): mdir / 'interp' / (f'{hashes[rel]}_{m}_{fps}_{fmt}.mkv' if m else f'{hashes[rel]}_{fps}_{fmt}.mkv')
                  for rel, m in need_ip}
        if need_up:
            other = sorted({k[1] for k in need_up} - {wmodel})
            say(f'upscale モデル：作品 {wmodel}' + (f'・クリップで変えたもの {"・".join(other)}' if other else '') +
                f'（素材 {n_up} 本・{len(need_up)} 通り）')
        # ①② アプスケと補間（素材ごとに重ねる。tools_pass）
        tools_pass(a, srcs, infos, need_up, need_ip, ip_dst, hashes, target, mdir, tmp, cancel, files, used, report, rk)
        # ③ の差し替え表：作品のモデルのもの（とアプスケしない素材）は素材のパスで、クリップでモデルを変えたものはそのクリップだけ（'@clips'。engine.src_path）
        src_map, clip_map = {}, {}
        for (cid, rel), m in per.items():
            k = (rel, m if rel in up_rel else None)
            if k not in files:
                continue
            if k[1] in (None, wmodel):
                src_map[rel] = files[k]
            else:
                clip_map.setdefault(cid, {})[rel] = files[k]
        sm = dict(src_map, **({'@clips': clip_map} if clip_map else {}))
        # ③④ 描く（いつもの書き出しの区間の並列のまま。区間ごとに縮めてエンコード）・音
        eng.src_map, eng.clip_src_map = dict(src_map), clip_map
        mp = tmp / 'src_map.json'
        mp.write_text(json.dumps(sm, ensure_ascii=False, indent=1), encoding='utf-8')
        print('PHASE render', flush=True)
        seg_extra = ['--master-scale', str(a.master_scale), '--master-fps', str(fps), '--src-map', str(mp), '--down', a.down]
        if a.master_out:
            seg_extra += ['--master-out', str(a.master_out)]
        frames = int(round(t1 * fps)) - int(round(a.t0 * fps))
        jobs = render_jobs() if str(a.jobs) == 'auto' or int(a.jobs) <= 0 else int(a.jobs)
        chunks = render_chunks(frames) if str(a.chunks) == 'auto' or int(a.chunks) <= 0 else int(a.chunks)
        # OpenCV のスレッド（--threads N で区間のプロセスごとに絞れる。既定は絞らない）。2026-10-30 作者のデスクトップ PC の偽マリアで測った：
        # 14〜26 秒・並列 12・区間 30 で、絞らない 875 秒・2 で 888 秒（同じくらい）、並列 16・1 は 1723 秒（CPU が 67% しか使われず倍おそい）、
        # 14〜20 秒では 2 のほうが 1〜6% 速かった。はっきり効かないので絞らない。絵は同じ（絞らないものと 2 の MP4 がバイト単位で同じ）
        threads = int(a.threads or 0)
        if threads > 0:
            seg_extra += ['--threads', str(threads)]
        av = mem_avail_gb()
        say(f'render {jobs} 並列・区間 {chunks}' + (f'・OpenCV のスレッド {threads}' if threads > 0 else '') + f'（{frames} コマ。CPU {os.cpu_count()}' +
            (f'・空きメモリ {av:.1f} GB）' if av is not None else '）'))
        va = Namespace(timeline=a.timeline, out=str(out), t0=a.t0, t1=t1, jobs=jobs, chunks=chunks, encoder=a.encoder, scale=1.0, draft=False, step=1,
                       hwaccel=a.hwaccel, seg_extra=seg_extra)
        video(va, eng)
    except Cancelled:
        print('CANCELLED', flush=True)
        cancel.unlink(missing_ok=True)
        raise SystemExit(3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # ⑤ 中間（コマの PNG・差し替え表）を消す
    total, gone = trim_cache(mdir, a.cache_gb, used)
    print(f'cache {total / 1e9:.2f} GB（上限 {a.cache_gb} GB）' + (f'・古いもの {len(gone)} 本を消した' if gone else ''), flush=True)
    from .__main__ import master_size
    ow, oh = master_size(eng.W0, eng.H0, a.master_out) if a.master_out else (eng.W, eng.H)   # master_out は短い辺（縦長の作品は幅）
    print('MASTER_DONE ' + json.dumps({'out': str(out), 'size': f'{ow}x{oh}', 'fps': fps, 'canvas': f'{eng.W}x{eng.H}', 'upscale': wmodel, 'sources': report},
                                      ensure_ascii=False), flush=True)


def check_only(a, eng):
    """--check：書き出し前チェックだけ（結果の JSON を1行。止めるなら MASTER_STOP）。アップスケールなし（a.no_up）なら scale_aware は見ない"""
    no_up = getattr(a, 'no_up', False)
    r = scale_check(eng, scaled=not no_up)
    print('MASTER_CHECK ' + json.dumps(r, ensure_ascii=False), flush=True)
    if not r['ok'] and not a.force:
        stop('effects', r['message'], effects=r['missing'])
    notes = []
    if not r['ok']:  # --force：承知で続ける
        notes.append('scale 未対応のまま描く（位置・大きさがずれることがある）：' + '・'.join(m['name'] for m in r['missing']))
    if r['fi']:
        notes.append('コマ番号で絵が変わるエフェクト（60fps で進みが変わる）：' + '・'.join(m['name'] for m in r['fi']))
    if no_up:  # クリップの欄のアップスケール（anime・real）は、作品が「なし」なら使わない
        ign = ignored_clips(eng, a.t0, a.t1 if a.t1 is not None else eng.duration)
        if ign:
            notes.append('アップスケールなしなので、クリップのアップスケールは使わない：' + '・'.join(ign))
    if notes:
        print('MASTER_WARN ' + ' / '.join(notes), flush=True)
    return r


