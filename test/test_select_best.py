import os
import sys
import os.path as osp

# ensure project root is on sys.path for imports
ROOT = osp.abspath(osp.join(osp.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from select_best import quality_score, group_files, choose_best


def test_quality_score_numeric_and_tokens():
    assert quality_score('avc-1080.mp4') >= 1080
    assert quality_score('xxl') == 1500
    assert quality_score('unknown') == 0


def test_group_and_choose(tmp_path):
    src = tmp_path
    prefix = 'KiKA - Series - Ep1'
    files = [
        (prefix + ' - 0001.avc-360.mp4', 100),
        (prefix + ' - 0001.avc-720.mp4', 200),
        (prefix + ' - 0001.avc-1080.mp4', 300),
    ]
    for fname, size in files:
        p = src / fname
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'\0' * size)

    # add a non-video file that should be ignored
    (src / 'notes.txt').write_text('ignore')

    groups = group_files(str(src))
    assert prefix in groups
    items = groups[prefix]
    assert len(items) == 3
    best_fname, score, ssize = choose_best(items)
    assert best_fname.endswith('avc-1080.mp4')
