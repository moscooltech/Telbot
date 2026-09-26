"""
Offline unit tests for the ImageGenerator fallback chain (no network, no API keys).
Run: python test_image_gen_unit.py
"""
import os
import shutil
from unittest import mock

import config
from config import TEMP_DIR
import services.image_generator as ig_mod
from services.image_generator import ImageGenerator, JPEG_MAGIC, PNG_MAGIC

passed = 0
failed = 0

def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS {name}")
    else:
        failed += 1
        print(f"  FAIL {name} -> {detail}")

JOB = "verify_image_unit"


def make_gen(style_bible="watercolor style"):
    return ImageGenerator(JOB, style_bible=style_bible)


def fake_response(status=200, body=JPEG_MAGIC + b"x" * 5000):
    resp = mock.Mock()
    resp.status_code = status
    resp.content = body
    return resp


print("== 1. provider chain composition ==")
with mock.patch.object(ig_mod, "GEMINI_API_KEY", ""), \
     mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", ""), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""):
    gen = make_gen()
    chain = gen._provider_chain()
    check("keyless chain is legacy only", [c[0] for c in chain] == ["pollinations-legacy"],
          str([c[0] for c in chain]))

with mock.patch.object(ig_mod, "GEMINI_API_KEY", "g"), \
     mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", ""), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""):
    gen = make_gen()
    chain = gen._provider_chain()
    check("gemini first when key set", [c[0] for c in chain][0] == "gemini",
          str([c[0] for c in chain]))
    check("gemini models from config", [c[2] for c in chain][:len(config.GEMINI_IMAGE_MODELS)]
          == [m.strip() for m in config.GEMINI_IMAGE_MODELS], str([c[2] for c in chain]))

with mock.patch.object(ig_mod, "GEMINI_API_KEY", ""), \
     mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", "k"), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""):
    gen = make_gen()
    chain = gen._provider_chain()
    check("pollinations key adds gen models", [c[0] for c in chain] ==
          ["pollinations-legacy", "pollinations-gen", "pollinations-gen"],
          str([c[0] for c in chain]))
    check("gen models are flux then turbo", [c[2] for c in chain][1:] == ["flux", "turbo"],
          str([c[2] for c in chain]))

with mock.patch.object(ig_mod, "GEMINI_API_KEY", ""), \
     mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", "k"), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", "b"):
    gen = make_gen()
    chain = gen._provider_chain()
    check("bytez is last in chain", chain[-1][0] == "bytez", str([c[0] for c in chain]))

print("== 2. image payload validation ==")
check("valid jpeg accepted", ImageGenerator._is_image(fake_response()))
check("png accepted",
      ImageGenerator._is_image(fake_response(body=PNG_MAGIC + b"x" * 5000)))
check("http error rejected", not ImageGenerator._is_image(fake_response(status=500)))
check("tiny body rejected",
      not ImageGenerator._is_image(fake_response(body=JPEG_MAGIC + b"x" * 100)))
check("html error page rejected",
      not ImageGenerator._is_image(fake_response(body=b"<html>error</html>")))

print("== 3. failure cooldown ==")
with mock.patch.object(ig_mod, "GEMINI_API_KEY", ""), \
     mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", "test-key"), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""):
    gen = make_gen()
    legacy_key = gen._provider_key("pollinations-legacy", config.IMAGE_LEGACY_MODEL)
    gen_key = gen._provider_key("pollinations-gen", "flux")
    check("multi-provider chain built", len(gen._provider_chain()) == 3)

    gen._mark_provider_failure(legacy_key)
    check("one failure does not trigger cooldown",
          gen._provider_stats[legacy_key]["cooldown_until"] == 0.0)
    check("still in chain after one failure", len(gen._provider_chain()) == 3)

    gen._mark_provider_failure(legacy_key)
    check("cooldown set after threshold failures",
          gen._provider_stats[legacy_key]["cooldown_until"] > 0)
    remaining = [c[0] for c in gen._provider_chain()]
    check("cooling provider skipped from chain",
          remaining == ["pollinations-gen", "pollinations-gen"], str(remaining))

    # Cool down the remaining gen providers too -> last-ditch: full chain comes back
    gen._mark_provider_failure(gen._provider_key("pollinations-gen", "flux"))
    gen._mark_provider_failure(gen._provider_key("pollinations-gen", "flux"))
    gen._mark_provider_failure(gen._provider_key("pollinations-gen", "turbo"))
    gen._mark_provider_failure(gen._provider_key("pollinations-gen", "turbo"))
    full = gen._provider_chain()
    check("last-ditch returns full chain when ALL providers cool down",
          len(full) == 3 and full[0][0] == "pollinations-legacy", str([c[0] for c in full]))

    # Success resets stats
    gen._provider_stats = {}
    check("reset clears cooldown", len(gen._provider_chain()) == 3)

print("== 4. generate_image end to end (mocked network) ==")
with mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", ""), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""), \
     mock.patch.object(ig_mod.time, "sleep", lambda s: None), \
     mock.patch.object(ig_mod.requests, "get", return_value=fake_response()):
    gen = make_gen()
    path = gen.generate_image("a fox in a forest", 0)
    check("returns filepath on success", path is not None and os.path.exists(path), str(path))
    if path and os.path.exists(path):
        check("file starts with jpeg magic", open(path, "rb").read(3) == JPEG_MAGIC)
    built = gen._build_prompt("a fox, running, forest")
    check("style bible fused", "watercolor style" in built, built)

print("== 5. generate_image when every provider fails ==")
with mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", ""), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""), \
     mock.patch.object(ig_mod.time, "sleep", lambda s: None), \
     mock.patch.object(ig_mod.requests, "get", side_effect=Exception("boom")):
    gen = make_gen()
    path = gen.generate_image("a fox in a forest", 1)
    check("returns None when all providers fail", path is None, str(path))

shutil.rmtree(os.path.join(TEMP_DIR, JOB), ignore_errors=True)

print(f"\nRESULT: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
print("ALL CHECKS PASSED")
