"""Qualification must preserve failures and check the actual GPU capture."""
import json

import pytest

from tools import qualify_gba_hardware as tool


def player(width=9,height=9):
    return dict(gpu_rendering=True,renderer='opengl',interpreted_cycles=0,
        misses=[],frames=120,drawable=[width,height])


def capture(path, pixels, width=9, height=9):
    path.write_bytes(f'P6\n{width} {height}\n255\n'.encode()+pixels)
    return path


def test_odd_drawable_checks_bottom_origin_letterboxing_and_every_pixel(tmp_path):
    # A 9x9 drawable contains a 9x6 viewport: two rows above, one below.
    pixels=b'\0\0\0'*18+b'\xff\0\0'*54+b'\0\0\0'*9
    image=capture(tmp_path/'gpu.ppm',pixels)
    tool.verify_player(player(),image)
    image=capture(image,pixels[:80]+b'\x01'+pixels[81:])
    with pytest.raises(ValueError,match='GPU picture differs'):
        tool.verify_player(player(),image)


def test_dpi_scaled_capture_is_checked_at_its_actual_pixel_size(tmp_path):
    image=capture(tmp_path/'gpu.ppm',b'\xff\0\0'*(600*400),600,400)
    tool.verify_player(player(600,400),image)
    with pytest.raises(ValueError,match='dimensions differ'):
        tool.verify_player(player(480,320),image)


@pytest.mark.parametrize('field,value',[
    ('gpu_rendering',False),('renderer','software'),('interpreted_cycles',1),
    ('misses',[0x08000000]),('frames',119),
])
def test_fallback_or_incomplete_execution_cannot_pass_a_gpu_assessment(field, value, tmp_path):
    report=player();report[field]=value
    with pytest.raises(ValueError,match='strict native OpenGL'):
        tool.verify_player(report,tmp_path/'unused.ppm')


def test_interruption_leaves_an_unqualified_report(tmp_path,monkeypatch):
    def interrupt():
        raise KeyboardInterrupt
    monkeypatch.setattr(tool,'vulkan_devices',interrupt)
    out=tmp_path/'interrupted'
    with pytest.raises(KeyboardInterrupt):
        tool.assess(out)
    report=json.loads((out/'hardware-assessment.json').read_text())
    assert report['interrupted'] and not report['hardware_qualified']
    assert not report['original_fixture_passed']


def test_reusing_an_assessment_cannot_overwrite_existing_work(tmp_path):
    record=tmp_path/'hardware-assessment.json';record.write_text('existing work')
    with pytest.raises(ValueError,match='existing work is preserved'):
        tool.assess(tmp_path)
    assert record.read_text()=='existing work'
