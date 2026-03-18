import os
import sys
import os.path as osp

# ensure project root is on sys.path for imports
ROOT = osp.abspath(osp.join(osp.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from downloader import _sanitize_filename


def test_sanitize_replaces_slash_and_removes_forbidden():
    s = 'a/b:c*?"<>|\x00test'
    out = _sanitize_filename(s)
    assert '/' not in out
    for ch in ':*?"<>|':
        assert ch not in out
    assert '\x00' not in out


def test_sanitize_trims_length():
    long = 'a' * 500
    out = _sanitize_filename(long)
    assert len(out) <= 200
