"""Original Vulkan GS fixtures, separately qualified from a complete game."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tools.qualify_ps2_graphics import download, executable, fingerprint, qualify


@pytest.fixture(scope='module')
def sdk():
    root = os.environ.get('DECOMP_PS2_GS_ROOT')
    if not root:
        if os.environ.get('DECOMP_REQUIRE_PS2_GS') == '1': pytest.fail('required PS2 GS source path is missing')
        pytest.skip('set DECOMP_PS2_GS_ROOT to assess the optional Vulkan renderer')
    return Path(root)


@pytest.fixture(scope='module')
def assessment(sdk, tmp_path_factory):
    output = tmp_path_factory.mktemp('GS assessment') / 'source with spaces'
    return output, qualify(sdk, output, execute=os.environ.get('DECOMP_PS2_GS_EXECUTE', '1') == '1')


def test_original_gif_geometry_transfers_and_resolution_change(assessment):
    output, report = assessment
    assert report['native_build'] and report['descriptor_backend'] == 'sets'
    assert not report['game_runtime_qualified'] and not report['retail_qualified']
    assert not report['host_drawable_adaptation_qualified']
    if os.environ.get('DECOMP_PS2_GS_EXECUTE', '1') == '1':
        assert report['vulkan_executed']
        assert report['result']['api'] == 'vulkan'
        assert report['result']['red_pixels'] == [1176, 4656]
        assert report['result']['image_pixels'] == [4, 4]
        assert report['result']['gs_dimensions'] == [64, 128]
        assert report['result']['gif_image_flags'] == [2, 3]
    else:
        assert not report['vulkan_executed'] and report['result'] is None
    assert json.loads((output / 'assessment.json').read_text()) == report


def test_required_vulkan_does_not_silently_succeed_without_a_driver(assessment, tmp_path):
    output, _ = assessment
    env = {**os.environ, 'VK_DRIVER_FILES': str(tmp_path / 'missing-icd.json'),
           'VK_ICD_FILENAMES': str(tmp_path / 'missing-icd.json')}
    result = subprocess.run([executable(output / 'build', 'decomp_ps2_gs_probe')], env=env,
        capture_output=True, text=True, timeout=30)
    (output / 'required-device-failure.log').write_text(result.stdout + result.stderr)
    assert result.returncode != 0 and 'PS2 GS probe failed:' in result.stderr
    assert '"passed":true' not in result.stdout


def test_altered_shader_source_is_rejected_before_building(sdk, tmp_path):
    copy = tmp_path / 'altered source'; shutil.copytree(sdk, copy)
    assert fingerprint(copy) == fingerprint(sdk)
    source = copy / 'gs/gs_interface.cpp'; source.write_bytes(source.read_bytes() + b'\nchanged\n')
    output = tmp_path / 'assessment'
    with pytest.raises(ValueError, match='fingerprint differs'): qualify(copy, output, execute=False)
    assert not output.exists()


def test_existing_graphics_work_is_preserved(tmp_path):
    marker = tmp_path / 'keep.txt'; marker.write_text('existing work')
    with pytest.raises(ValueError, match='existing work'): download(tmp_path)
    with pytest.raises(ValueError, match='existing work'): qualify(tmp_path / 'absent', tmp_path)
    assert marker.read_text() == 'existing work'
