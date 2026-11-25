"""書き出しボタンの動作確認（ヘッドレス、localhost だけ）。テスト用の写し（*.test.cut.json）で流すこと。サーバーの PC で本当に描く。
  <Playwright の python> -X utf8 tools\\smoke_export.py <URL> --timeline <*.test.cut.json> [--to 4] [--jobs 4] [--shot 画像]
確かめること：書き出しの窓 → 一部（0〜--to 秒）で書き出す → 進み具合が出る → output/ に MP4（長さが合う）→ 再生用の WebM ができて preview.proxy に入る
→ もう一度（全体）書き出して描いている途中で「止める」→ 止まる → 取り消しでタイムラインが最初と同じ。
サーバーがほかの PC（Remote-SSH でつなぐ描く PC）で動いていて、このPCからポートを転送して試すとき：--remote-project <向こうのプロジェクトのフォルダ> --host <PC> [--remote-ffprobe <向こうの ffprobe>]
（タイムラインはサーバーの API で読み、ファイルは --host の PC に ssh で確かめる。テストの道具。Mittler 自身は ssh しない）
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path, PureWindowsPath

from playwright.sync_api import sync_playwright

ADV = "document.querySelectorAll('#exportPanel details.xadv').forEach(d => d.open = true)"  # 書き出しの窓の詳細設定を開く（同時処理数はこの中）

ap = argparse.ArgumentParser(); ap.add_argument('url'); ap.add_argument('--timeline', required=True)
ap.add_argument('--to', type=float, default=4.0); ap.add_argument('--jobs', type=int, default=4); ap.add_argument('--shot')
ap.add_argument('--remote-project', help='サーバーがほかの PC（--host）で動いているとき、そのプロジェクトのフォルダ（向こうの絶対パス）')
ap.add_argument('--host', default='', help='--remote-project のとき、ssh でつなぐ PC の名前')
ap.add_argument('--remote-ffprobe', default='ffprobe', help='--remote-project のとき、向こうの PC の ffprobe（PATH に無ければ場所）')
a = ap.parse_args()
R = a.remote_project
if R and not a.host:
    sys.exit('--remote-project には --host（ssh でつなぐ PC）も要る')
base_url = a.url.split('/editor')[0]; token = a.url.split('token=')[-1]


def read_tl():
    if R:
        return json.loads(urllib.request.urlopen(base_url + '/api/timeline').read())['timeline']
    return json.loads(tlf.read_text(encoding='utf-8'))


def ssh(cmd):
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', a.host, cmd], capture_output=True, text=True, encoding='utf-8', errors='replace').stdout


def exists(rel):
    if R:
        return 'YES' in ssh(f'if exist "{PureWindowsPath(R, rel)}" (echo YES) else (echo NO)')
    return (tlf.parent / rel).exists()


def probe(rel, entries):
    if R:
        return ssh(f'"{a.remote_ffprobe}" -v error -show_entries {entries} -of csv=p=0 "{PureWindowsPath(R, rel)}"')
    return subprocess.run(['ffprobe', '-v', 'error', '-show_entries', entries, '-of', 'csv=p=0', str(tlf.parent / rel)], capture_output=True, text=True).stdout
if not a.url.startswith(('http://127.0.0.1:', 'http://localhost:')): sys.exit('localhost only')
if '.test.' not in Path(a.timeline).name: sys.exit('テスト用の写し（*.test.cut.json）で流す')
tlf = Path(a.timeline)
if R:
    first = read_tl()
else:
    orig = tlf.read_bytes(); first = json.loads(orig.decode('utf-8'))
fails, errors = [], []
name = 'smoke_export_' + time.strftime('%H%M%S')


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg, flush=True); (None if cond else fails.append(msg))


def saved(pg):
    pg.wait_for_function("() => !window.MITTLER_EDITOR.saveTimer && !window.MITTLER_EDITOR.saving", timeout=60000); time.sleep(0.4)
    return read_tl()


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={'width': 1600, 'height': 940})
    pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(a.url)
    pg.wait_for_function('window.MITTLER_EDITOR && window.MITTLER_EDITOR.tl && window.MITTLER_EXPORT', timeout=60000)
    pg.wait_for_selector('#exportBtn:not([hidden])', timeout=10000)
    pg.click('#exportBtn'); pg.wait_for_selector('#exportPanel:not([hidden]) #xName')
    pg.check('#exportPanel input[name=xr][value=part]')
    pg.evaluate(ADV)  # 同時処理数は詳細設定の中（たたんである）
    pg.fill('#xFrom', '0'); pg.fill('#xTo', str(a.to)); pg.fill('#xJobs', str(a.jobs)); pg.fill('#xName', name)
    t0 = time.time(); pg.click('#exportPanel [data-x=start]')
    seen = set(); pct = []
    while time.time() - t0 < 900:
        j = pg.evaluate('window.MITTLER_EXPORT.job'); seen.add(j['state'])
        if j['state'] == 'rendering': pct.append(j.get('done', 0))
        if j['state'] in ('done', 'error', 'cancelled'): break
        time.sleep(0.5)
    print('states', sorted(seen), 'progress samples', pct[:3], '…', pct[-3:], f'{time.time() - t0:.0f}s')
    check(j['state'] == 'done', f"一部を書き出せた（{j['state']} {j.get('error', '')[:300]}）")
    if j['state'] == 'done':
        r = j['result']
        print('result', {k: r.get(k) for k in ('path', 'bytes', 'where', 'proxy')})
        check(exists(r['path']) and (R or (tlf.parent / r['path']).stat().st_size == r['bytes']), f"output に MP4（{r['path']}・{r['bytes'] / 1e6:.1f}MB）")
        d = float(probe(r['path'], 'format=duration').strip() or 0)
        check(abs(d - a.to) < 0.15, f'長さ {d:.3f}秒（{a.to}秒のはず）')
        st = probe(r['path'], 'stream=codec_type').split()
        check('video' in st and 'audio' in st, f'映像と音がある {st}')
        tl = saved(pg)
        check(r.get('proxy') and tl.get('preview', {}).get('proxy') == r['proxy'] and exists(r['proxy']), f"再生用の WebM が preview.proxy に入った（{r.get('proxy')}）")
        check(pg.evaluate("document.getElementById('proxy').getAttribute('src')") == '/project/' + r['proxy'], '再生用の動画を読み込み直した')
        if a.shot:
            pg.screenshot(path=a.shot)
    # 全体を書き出して、描いている途中で止める
    pg.click('#exportPanel [data-x=again]'); pg.evaluate(ADV); pg.fill('#xName', name + '_cancel'); pg.uncheck('#xProxy'); pg.fill('#xJobs', str(a.jobs))
    pg.click('#exportPanel [data-x=start]')
    pg.wait_for_function("() => window.MITTLER_EXPORT.job.state === 'rendering' && window.MITTLER_EXPORT.job.done > 0", timeout=300000)
    pg.click('#exportPanel [data-x=cancel]')
    pg.wait_for_function("() => ['cancelled', 'done', 'error'].includes(window.MITTLER_EXPORT.job.state)", timeout=120000)
    j = pg.evaluate('window.MITTLER_EXPORT.job')
    check(j['state'] == 'cancelled', f"途中で止められる（{j['state']}）")
    check(not exists('output/' + name + '_cancel.mp4') or bool(R), '止めたものは持ってこない')
    while pg.evaluate('window.MITTLER_EDITOR.undo.length') > 0:
        pg.click('#undo')
    tl = saved(pg)
    b.close()

check(tl == first, 'タイムラインの中身が最初と同じ（取り消しで戻った）')
if read_tl() != first:
    if R:
        urllib.request.urlopen(urllib.request.Request(base_url + '/api/timeline', data=json.dumps(first, ensure_ascii=False).encode('utf-8'), method='PUT',
                                                      headers={'X-Mittler-Token': token, 'Content-Type': 'application/json'}))
    else:
        tlf.write_bytes(orig)
    print('（ファイルを最初の中身に戻した）')
check(not errors, 'コンソールエラーなし' + ('' if not errors else ': ' + ' | '.join(errors[:5])))
print('test name', name)
sys.exit(1 if fails else 0)
