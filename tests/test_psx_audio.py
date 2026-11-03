"""Regression for the emitted PS1 mixer's CD and reverb contributions."""
import os
import shutil

import pytest

from decompnet.psx_native import _run, _sdk, runtime_patch


FIXTURE = r'''
#include "audio_shadow.h"
#include "spu.h"
#include "spu_shadow.h"
#undef NDEBUG
#include <assert.h>
#include <string.h>

static SpuShadowFrameTapPub tap;
static int frames = 1;
const void *spu_shadow_tap_buffer(void) { return &tap; }
int spu_shadow_tap_count(void) { return frames; }

/* Qualify the alternate render independently of the time needed to prove it. */
void shadow_verifier_init(ShadowVerifier *verifier) {
    memset(verifier, 0, sizeof(*verifier));
    verifier->gain = 1.0f;
    verifier->proven = true;
}

ShadowJudgement shadow_verifier_judge(ShadowVerifier *verifier, float l, float r,
                                     float alternative_l, float alternative_r) {
    (void)verifier; (void)l; (void)r; (void)alternative_l; (void)alternative_r;
    return SHADOW_JUDGE_PASS;
}

int main(void) {
    int16_t mix[2] = {111, -222};
    tap.enabled = 1;
    tap.main_l = tap.main_r = 0x4000;
    tap.other_l = 4000;
    tap.other_r = -5000;
    SpuShadowVoiceTapPub *voice = &tap.voice[0];
    for (int k = 0; k < 4; ++k) voice->s[k] = 8000;
    voice->active = 1;
    voice->env = 0x4000;
    voice->vol_l = 0x4000;
    voice->vol_r = 0x2000;
    spu_shadow_set_enabled(0);
    spu_shadow_reset();
    spu_shadow_process(mix, 1);
    assert(mix[0] == 111 && mix[1] == -222);

    spu_shadow_set_enabled(1);
    spu_shadow_reset();
    spu_shadow_process(mix, 1);
    assert(mix[0] == 3000 && mix[1] == -2000);
    tap.other_l = 40000;
    spu_shadow_process(mix, 1);
    assert(mix[0] == 16383 && mix[1] == -2000);

    frames = 0;
    mix[0] = 1234;
    spu_shadow_process(mix, 1);
    assert(mix[0] == 1234);
    SpuShadowInfo info;
    spu_shadow_get_info(&info);
    assert(info.proven && info.applied_frames == 2);
    return 0;
}
'''


def test_enhanced_mixer_preserves_cd_reverb_and_saturation(tmp_path, monkeypatch):
    if not os.environ.get('DECOMP_REQUIRE_PSX_NATIVE'):
        pytest.skip('pinned PS1 runtime SDK required')
    monkeypatch.delenv('PSX_AUDIO_SHADOW', raising=False)
    sdk = _sdk()
    for name in ('runtime/include/spu.h', 'runtime/include/spu_shadow.h',
                 'runtime/include/audio_shadow.h', 'runtime/src/spu.c', 'runtime/src/spu_shadow.c'):
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sdk / name, destination)
    runtime_patch.shadow_audio(tmp_path)
    (tmp_path / 'fixture.c').write_text(FIXTURE)
    (tmp_path / 'CMakeLists.txt').write_text(
        'cmake_minimum_required(VERSION 3.24)\n'
        'project(Ps1Mixer LANGUAGES C)\nset(CMAKE_C_STANDARD 11)\n'
        'add_executable(mixer fixture.c runtime/src/spu_shadow.c)\n'
        'target_include_directories(mixer PRIVATE runtime/include)\n'
    )
    _run(['cmake', '-S', tmp_path, '-B', tmp_path / 'build'], 'Configure the SPU mixer fixture')
    _run(['cmake', '--build', tmp_path / 'build', '--config', 'Release'], 'Build the SPU mixer fixture')
    player = next(path for path in (tmp_path / 'build/mixer', tmp_path / 'build/Release/mixer.exe')
                  if path.is_file())
    _run([player], 'Verify the alternate mixer buses')
