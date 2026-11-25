"""古い名前の互換：Python のパッケージ ccpy（2026-11-12 に mittler に改名した。本体は隣の pyengine/mittler/）。
今までの作品の effects/*.py（`from ccpy.helpers import …`・`from ccpy.lib import look`）と、作品の CLAUDE.md・手順に書いてある
`python -m ccpy …`・`python -m ccpy.analyze …` を、直さずにそのまま動かすための受け口。新しく書くものは mittler を使う。

しくみ：`ccpy.<名前>` を import すると、`mittler.<名前>` を import して**同じモジュールそのもの**を返す（写しを作らない。
マスクのキャッシュなど、モジュールが持っている状態が ccpy 側と mittler 側で二重にならないように）。
`python -m ccpy …` は mittler/__main__.py を、`python -m ccpy.analyze …` は mittler/analyze.py を、そのまま __main__ として動かす。
互換を外すときは、この pyengine/ccpy/ のフォルダごと消す（ほかに ccpy を読むところは無い）。
"""
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys

_NEW = 'mittler'
_OLD = __name__  # 'ccpy'


class _AliasLoader(importlib.abc.Loader):
    """ccpy.<名前> の中身として、mittler.<名前> のモジュールそのものを渡す"""

    def __init__(self, real):
        self.real = real
        self._spec = None

    def create_module(self, spec):
        mod = importlib.import_module(self.real)
        self._spec = getattr(mod, '__spec__', None)
        return mod

    def exec_module(self, module):
        # import の仕組みは、渡したモジュールの __spec__ を ccpy.<名前> のものに書きかえる。本物（mittler.<名前>）のものに戻す
        if self._spec is not None:
            module.__spec__ = self._spec

    def get_code(self, fullname):  # python -m ccpy・python -m ccpy.analyze（runpy が読む）
        spec = importlib.util.find_spec(self.real)
        return spec.loader.get_code(self.real)

    def get_source(self, fullname):
        spec = importlib.util.find_spec(self.real)
        return spec.loader.get_source(self.real)

    def is_package(self, fullname):
        spec = importlib.util.find_spec(self.real)
        return spec.submodule_search_locations is not None


class _AliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(_OLD + '.'):
            return None
        real = _NEW + fullname[len(_OLD):]
        try:
            rs = importlib.util.find_spec(real)
        except ModuleNotFoundError:
            rs = None
        if rs is None:
            return None  # mittler に無い名前：ふつうの「見つからない」になる
        spec = importlib.machinery.ModuleSpec(fullname, _AliasLoader(real), origin=rs.origin, is_package=rs.submodule_search_locations is not None)
        if rs.submodule_search_locations is not None:
            spec.submodule_search_locations = list(rs.submodule_search_locations)
        spec.has_location = rs.has_location
        return spec


if not any(isinstance(f, _AliasFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _AliasFinder())
