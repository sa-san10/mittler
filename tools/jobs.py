"""Mittler の「ジョブ係」：作品の work/jobs/*.json を順に生成する（標準ライブラリだけ）。生成は常にこのPCで。
  python tools/jobs.py <作品のフォルダ>        常駐（編集画面のサーバーが、動いていなければ起動する。15分なにも無ければ自分で止まる）
  python tools/jobs.py <作品のフォルダ> --once  いま待っているものを1回ずつ流して終わる（確認用）
ジョブ（編集画面のサーバーが書く。タイムラインに入れるのは編集画面＝書くのは1か所）：
  {id, kind: "image"|"video", clip, which, state: queued→running→done|failed|cancelled（video は waiting も）, created,
   image: {prompt（参照を開いた全文）, refs:[絶対パス], out（素材の根からの相対）, root（素材の根）, session（Codex のセッション記録）},
   result: {src, …}, error, cancel（true にすると止める）, applied（編集画面がテイクに入れたら true）}
- どのエンジンで作るかは、ジョブの engine（video.engine。絵は image.engine、無ければ既定）から tools/engines.json でアダプタを引いて、その submit・poll を呼ぶ
  （エンジンの決まりはアダプタの中。足し方は docs/H3受け渡し契約.md の「エンジンを足すには」）。
- 画像（開始・終了の絵）：tools/codex_jobs.py → tools/gen/codex_image.py（Codex CLI の内蔵の画像生成。同時1件。参照は5枚まで。refs_ok・spec_coverage を記録）
- 動画（🎬 の動画化）：tools/h3_jobs.py → H3 のキュー（Google ドライブの H3_tasks。docs/H3受け渡し契約.md）
- 動いている印：work/jobs/runner.json（pid・heartbeat）。ログ：work/jobs/runner.log
"""
import argparse
import importlib
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pyengine'))
from mittler.i18n import t  # noqa: E402（ジョブの error の文の言葉。環境変数 MITTLER_LANG。ログは日本語のまま）
IDLE_EXIT = float(os.environ.get('MITTLER_JOBS_IDLE') or 15 * 60)  # 何も無ければ止まるまでの秒（環境変数は確かめ用：tools/smoke_bugs.py）
ENGINES = json.loads((HERE / 'engines.json').read_text(encoding='utf-8'))  # 生成のエンジン → アダプタ（1か所）


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


class Runner:
    def __init__(self, project):
        self.project = Path(project).resolve()
        self.jobs = self.project / 'work' / 'jobs'
        self.jobs.mkdir(parents=True, exist_ok=True)
        self.lock = self.jobs / 'runner.json'
        self.log_f = open(self.jobs / 'runner.log', 'a', encoding='utf-8')
        self.proc = None
        self.stop = False

    def log(self, msg):
        self.log_f.write(f'{now()} {msg}\n'); self.log_f.flush()

    # ---- ジョブのファイル（書くときは .part に書いてから置きかえる）----
    def read(self, p):
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None

    def write(self, p, job):
        tmp = p.with_name(p.name + '.part')
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, p)

    def update(self, p, **kw):
        job = self.read(p) or {}
        job.update(kw)
        self.write(p, job)
        return job

    def all(self):
        out = []
        for p in sorted(self.jobs.glob('job_*.json')):
            j = self.read(p)
            if j:
                out.append((p, j))
        return out

    # ---- 同時に動くジョブ係は 1 つだけ（早い者勝ちの鍵。2026-11-12）----
    # 前は runner.json の heartbeat を読むだけだったので、ほぼ同時に起動した 2 つがどちらも「ほかにいない」と見て動き続け、同じジョブを両方が流しえた
    # （Codex の絵・H3 の依頼が二重に出る）。今は work/jobs/runner.lock を開いて OS の鍵をかける。かけられた 1 つだけが進む。
    # 鍵はプロセスが終われば（落ちても）OS が外すので、残った鍵のファイルで次が起動できなくなることは無い
    def acquire(self):
        self.lock_fd = os.open(str(self.jobs / 'runner.lock'), os.O_CREAT | os.O_RDWR)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.lock_fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            os.close(self.lock_fd)
            self.lock_fd = None
            return False

    # ---- 動いている印 ----
    def alive_other(self):
        j = self.read(self.lock)
        return bool(j and j.get('pid') != os.getpid() and time.time() - j.get('heartbeat', 0) < 15)

    def beat(self):
        while not self.stop:
            self.write(self.lock, {'pid': os.getpid(), 'heartbeat': time.time(), 'started': self.started})
            for _ in range(10):  # 止めるときにすぐ抜ける（抜けたあとで印を書かない）
                if self.stop:
                    return
                time.sleep(0.5)

    # ---- エンジン → アダプタ（対応表は tools/engines.json の1か所）----
    def adapter(self, job):
        """ジョブのエンジン（video.engine。絵は image.engine、無ければ既定）のアダプタ（build・submit・poll を持つモジュール）。知らなければ None"""
        kind = job.get('kind')
        engine = (job.get(kind) or {}).get('engine') or ENGINES['default'].get(kind)
        ent = ENGINES['engines'].get(engine)
        if not ent or ent.get('kind') != kind:
            return None
        return importlib.import_module(ent['adapter'])

    # ---- 1回まわす ----
    def tick(self):
        busy = False
        for p, j in self.all():
            st = j.get('state')
            if st in ('queued', 'running') and j.get('cancel'):
                self.update(p, state='cancelled', finished=now()); continue
            if st == 'running':  # 前のジョブ係が途中で止まった：最初からやり直す
                self.update(p, state='queued'); st = 'queued'
            if st == 'queued':
                busy = True
                ad = self.adapter(j)
                if ad is None:
                    self.update(p, state='failed', error=t('py.jobs.unknownKind', kind=j.get('kind'), engine=(j.get(j.get('kind')) or {}).get('engine') or t('py.jobs.default')))
                elif ad.SUBMIT_ERROR is None:  # 絵（Codex）：submit の中で終わるまで待つ（同時1件）
                    ad.submit(self, p, j)
                else:  # 動画（H3）：依頼を置いて waiting に。置けなければ失敗（絵を写せない・声を作れない など）
                    try:
                        ad.submit(self, p, j)
                    except Exception as e:
                        self.update(p, state='failed', finished=now(), error=f'{ad.SUBMIT_ERROR}{e}')
                        self.log(f"失敗 {j['id']} {e}")
                return True  # 1件ずつ（画像は同時1件）
            if st == 'waiting':
                busy = True
                ad = self.adapter(j)
                if ad is not None:
                    ad.poll(self, p, j)
        return busy

    def main(self, once=False):
        # 鍵を取れなければ、もう動いている。heartbeat も見る（鍵をかけない前の版のジョブ係が動いているとき）
        if not self.acquire() or self.alive_other():
            print('もう別のジョブ係が動いている'); return 0
        self.started = time.time()
        beat = threading.Thread(target=self.beat, daemon=True)
        beat.start()
        self.log(f'ジョブ係を起動（pid {os.getpid()}）')
        last = time.time()
        try:
            while True:
                try:
                    busy = self.tick()
                except Exception:  # 思いがけないエラー：書き残して続ける（止まると、ジョブが残ったままになる）
                    self.log('エラー：' + traceback.format_exc()[-1500:])
                    busy = False
                    time.sleep(5)
                if busy:
                    last = time.time()
                elif once or time.time() - last > IDLE_EXIT:
                    break
                time.sleep(0.5 if busy else 2)
        finally:
            self.stop = True
            beat.join(timeout=7)  # 印を書いている途中なら待ってから消す（消したあとに書かれると、動いていないのに動いているように見える）
            try:
                self.lock.unlink()
            except OSError:
                pass
            self.log('ジョブ係を止めた')
        return 0


if __name__ == '__main__':
    sys.path.insert(0, str(HERE))
    ap = argparse.ArgumentParser()
    ap.add_argument('project')
    ap.add_argument('--once', action='store_true')
    a = ap.parse_args()
    raise SystemExit(Runner(a.project).main(a.once))
