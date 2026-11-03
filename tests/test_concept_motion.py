"""Run the browser's planned-pause interpolation, not a hardware simulation."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = (Path(__file__).resolve().parents[1] / 'web/src/conceptMotion.ts').as_uri()


def test_planned_pauses_and_return():
    script = f'''
import {{conceptDuration, conceptTravelAt}} from {json.dumps(MODULE)};
const stops = [0, .25, .75, 1], duration = conceptDuration(stops);
const sample = seconds => conceptTravelAt(seconds / duration, stops);
const pauses = stops.map((stop, i) => [sample(2 * stop + i * .6 + .1),
                                      sample(2 * stop + i * .6 + .5)]);
process.stdout.write(JSON.stringify({{duration, pauses, start: sample(0), end: sample(duration),
  returned: sample(duration - 1), noStops: [conceptTravelAt(0, []),
  conceptTravelAt(.5, []), conceptTravelAt(1, [])]}}));
'''
    result = subprocess.run([shutil.which('node'), '--input-type=module', '--eval', script],
                            capture_output=True, text=True, timeout=20, check=True)
    data = json.loads(result.stdout)
    assert data['duration'] == pytest.approx(6.4)
    for expected, samples in zip([0, .25, .75, 1], data['pauses']):
        assert samples == pytest.approx([expected, expected])
    assert data['start'] == pytest.approx(0)
    assert data['end'] == pytest.approx(0)
    assert 0 < data['returned'] < 1
    assert data['noStops'] == pytest.approx([0, 1, 0], abs=1e-9)


def test_indexed_moves_hold_the_end_and_preserve_signed_wrap():
    script = f'''
import {{conceptIndexAngle, conceptIndexDuration, conceptIndexTravelAt}} from {json.dumps(MODULE)};
const stops = [1], duration = conceptIndexDuration(stops);
const path = [0, .25, .5, .75, 1].map(p => conceptIndexAngle(180, 90, p, stops));
const pause = [2.1, 2.3, 2.5].map(s => conceptIndexTravelAt(s / duration, stops));
process.stdout.write(JSON.stringify({{duration, path, pause}}));
'''
    result = subprocess.run([shutil.which('node'), '--input-type=module', '--eval', script],
                            capture_output=True, text=True, timeout=20, check=True)
    data = json.loads(result.stdout)
    assert data['duration'] == pytest.approx(2.6)
    assert data['path'][0] == pytest.approx(180)
    assert data['path'][-1] == pytest.approx(270)
    assert data['path'] == sorted(data['path'])
    assert data['pause'] == pytest.approx([1, 1, 1])
