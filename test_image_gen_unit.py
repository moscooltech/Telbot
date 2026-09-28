"""
Offline unit tests for the ImageGenerator fallback chain (no network, no API keys).
Run: python test_image_gen_unit.py
"""
import os
import logging
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
print("== 1a. static chain plan (used by /status) ==")
with mock.patch.object(ig_mod, "CLOUDFLARE_ACCOUNT_ID", ""), \
     mock.patch.object(ig_mod, "CLOUDFLARE_API_TOKEN", ""), \
     mock.patch.object(ig_mod, "GEMINI_API_KEY", ""), \
     mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", "k"), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""):
    plan = ImageGenerator._chain_plan()
    check("plan works without an instance", [c[0] for c in plan] ==
          ["pollinations-gen", "pollinations-gen", "pollinations-legacy"],
          str([c[0] for c in plan]))
with mock.patch.object(ig_mod, "CLOUDFLARE_ACCOUNT_ID", ""), \
     mock.patch.object(ig_mod, "CLOUDFLARE_API_TOKEN", ""), \
     mock.patch.object(ig_mod, "GEMINI_API_KEY", ""), \
     mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", ""), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""):
    plan = ImageGenerator._chain_plan()
    check("plan falls back to legacy keyless", [c[0] for c in plan] ==
          ["pollinations-legacy"], str([c[0] for c in plan]))

print("== 1b. provider chain composition ==")
with mock.patch.object(ig_mod, "CLOUDFLARE_ACCOUNT_ID", ""), \
     mock.patch.object(ig_mod, "CLOUDFLARE_API_TOKEN", ""), \
     mock.patch.object(ig_mod, "GEMINI_API_KEY", ""), \
     mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", ""), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""):
    gen = make_gen()
    chain = gen._provider_chain()
    check("keyless chain is legacy only", [c[0] for c in chain] == ["pollinations-legacy"],
          str([c[0] for c in chain]))

with mock.patch.object(ig_mod, "CLOUDFLARE_ACCOUNT_ID", "acc"), \
     mock.patch.object(ig_mod, "CLOUDFLARE_API_TOKEN", "tok"), \
     mock.patch.object(ig_mod, "GEMINI_API_KEY", ""), \
     mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", ""), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""):
    gen = make_gen()
    chain = gen._provider_chain()
    check("cloudflare first when key set", [c[0] for c in chain][0] == "cloudflare",
          str([c[0] for c in chain]))
    check("klein models lead the cloudflare chain",
          [c[2] for c in chain][:len(config.CLOUDFLARE_KLEIN_MODELS)]
          == config.CLOUDFLARE_KLEIN_MODELS, str([c[2] for c in chain]))
    check("sdxl trails klein as json fallback",
          chain[len(config.CLOUDFLARE_KLEIN_MODELS)][2] == config.CLOUDFLARE_IMAGE_MODEL,
          str([c[2] for c in chain]))
    check("klein detection works",
          all(ImageGenerator._is_klein(m) for m in config.CLOUDFLARE_KLEIN_MODELS)
          and not ImageGenerator._is_klein(config.CLOUDFLARE_IMAGE_MODEL),
          str(config.CLOUDFLARE_KLEIN_MODELS))

CF_ENTRIES = len(config.CLOUDFLARE_KLEIN_MODELS) + 1  # klein models + SDXL fallback

with mock.patch.object(ig_mod, "CLOUDFLARE_ACCOUNT_ID", "acc"), \
     mock.patch.object(ig_mod, "CLOUDFLARE_API_TOKEN", "tok"), \
     mock.patch.object(ig_mod, "GEMINI_API_KEY", "g"), \
     mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", ""), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""):
    gen = make_gen()
    chain = gen._provider_chain()
    check("gemini after cloudflare, before legacy",
          [c[0] for c in chain][:CF_ENTRIES + 1] == ["cloudflare"] * CF_ENTRIES + ["gemini"],
          str([c[0] for c in chain]))
    check("gemini models from config",
          [c[2] for c in chain][CF_ENTRIES:CF_ENTRIES + len(config.GEMINI_IMAGE_MODELS)]
          == [m.strip() for m in config.GEMINI_IMAGE_MODELS], str([c[2] for c in chain]))

with mock.patch.object(ig_mod, "CLOUDFLARE_ACCOUNT_ID", ""), \
     mock.patch.object(ig_mod, "CLOUDFLARE_API_TOKEN", ""), \
     mock.patch.object(ig_mod, "GEMINI_API_KEY", ""), \
     mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", "k"), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""):
    gen = make_gen()
    chain = gen._provider_chain()
    check("pollinations key chain without cloudflare creds", [c[0] for c in chain] ==
          ["pollinations-gen", "pollinations-gen", "pollinations-legacy"],
          str([c[0] for c in chain]))

with mock.patch.object(ig_mod, "CLOUDFLARE_ACCOUNT_ID", "acc"), \
     mock.patch.object(ig_mod, "CLOUDFLARE_API_TOKEN", "tok"), \
     mock.patch.object(ig_mod, "GEMINI_API_KEY", ""), \
     mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", "k"), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""):
    gen = make_gen()
    chain = gen._provider_chain()
    cf_count = len(config.CLOUDFLARE_KLEIN_MODELS) + 1
    check("cloudflare leads even with pollinations key",
          [c[0] for c in chain][:cf_count] == ["cloudflare"] * cf_count, str([c[0] for c in chain]))
    check("keyed pollinations backs up cloudflare",
          [c[0] for c in chain][cf_count:cf_count + 2] == ["pollinations-gen"] * 2,
          str([c[0] for c in chain]))
    check("gen models are flux then z-image-turbo after cloudflare",
          [c[2] for c in chain][2:4] == ["flux", "z-image-turbo"], str([c[2] for c in chain]))
    check("keyless legacy is the safety net", chain[-1][0] == "pollinations-legacy",
          str([c[0] for c in chain]))

with mock.patch.object(ig_mod, "CLOUDFLARE_ACCOUNT_ID", ""), \
     mock.patch.object(ig_mod, "CLOUDFLARE_API_TOKEN", ""), \
     mock.patch.object(ig_mod, "GEMINI_API_KEY", ""), \
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


def cf_json_response(b64_img=None, status=200):
    import base64 as b64mod
    if b64_img is None:
        b64_img = b64mod.b64encode(JPEG_MAGIC + b"x" * 5000).decode()
    resp = mock.Mock()
    resp.status_code = status
    resp.headers = {"Content-Type": "application/json"}
    resp.json = lambda: {"success": True, "result": {"image": b64_img}}
    return resp


print("== 2b. cloudflare request shapes ==")
img_b64 = __import__("base64").b64encode(JPEG_MAGIC + b"x" * 5000).decode()
with mock.patch.object(ig_mod, "CLOUDFLARE_ACCOUNT_ID", "acc"), \
     mock.patch.object(ig_mod, "CLOUDFLARE_API_TOKEN", "tok"), \
     mock.patch.object(ig_mod.requests, "post", return_value=cf_json_response()) as post_mock:
    gen = make_gen()
    klein_model = config.CLOUDFLARE_KLEIN_MODELS[0]
    out = gen._generate_cloudflare("a smart meter on a wall", 42, klein_model, 30)
    check("klein returns decoded image", out[:3] == JPEG_MAGIC, str(out[:10]))
    kwargs = post_mock.call_args.kwargs
    check("klein uses multipart form data (data=, not json=)",
          "data" in kwargs and "json" not in kwargs, str(list(kwargs)))
    form = kwargs.get("data", {})
    check("klein sends clamped width/height",
          form.get("width") == str(gen.width) and form.get("height") == str(gen.height), str(form))
    check("klein sends seed", form.get("seed") == "42", str(form))
    with mock.patch.object(ig_mod, "IMAGE_WIDTH", 2560), \
         mock.patch.object(gen, "width", 2560):
        gen._generate_cloudflare("x", None, klein_model, 30)
        clamped = post_mock.call_args.kwargs["data"]["width"]
        check("klein clamps width to 1920", clamped == "1920", clamped)

with mock.patch.object(ig_mod, "CLOUDFLARE_ACCOUNT_ID", "acc"), \
     mock.patch.object(ig_mod, "CLOUDFLARE_API_TOKEN", "tok"), \
     mock.patch.object(ig_mod.requests, "post", return_value=cf_json_response()) as post_mock:
    gen = make_gen()
    gen._generate_cloudflare("a fox", 7, config.CLOUDFLARE_IMAGE_MODEL, 30)
    payload = post_mock.call_args.kwargs.get("json", {})
    check("sdxl uses json payload with steps + negative prompt",
          payload.get("num_steps") == 12 and payload.get("negative_prompt")
          and payload.get("seed") == 7, str(payload))

print("== 3. failure cooldown ==")
with mock.patch.object(ig_mod, "CLOUDFLARE_ACCOUNT_ID", ""), \
     mock.patch.object(ig_mod, "CLOUDFLARE_API_TOKEN", ""), \
     mock.patch.object(ig_mod, "GEMINI_API_KEY", ""), \
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
    gen._mark_provider_failure(gen._provider_key("pollinations-gen", "z-image-turbo"))
    gen._mark_provider_failure(gen._provider_key("pollinations-gen", "z-image-turbo"))
    full = gen._provider_chain()
    check("last-ditch returns full chain when ALL providers cool down",
          len(full) == 3 and full[0][0] == "pollinations-gen", str([c[0] for c in full]))

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
    check("winning provider recorded", gen.provider_usage ==
          {f"pollinations-legacy ({config.IMAGE_LEGACY_MODEL})": 1}, str(gen.provider_usage))

print("== 5. generate_image when every provider fails ==")
with mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", ""), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""), \
     mock.patch.object(ig_mod.time, "sleep", lambda s: None), \
     mock.patch.object(ig_mod.requests, "get", side_effect=Exception("boom")):
    gen = make_gen()
    path = gen.generate_image("a fox in a forest", 1)
    check("returns None when all providers fail", path is None, str(path))
    check("no usage recorded on failure", gen.provider_usage == {}, str(gen.provider_usage))

print("== 6. job summary logging ==")
with mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", ""), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""), \
     mock.patch.object(ig_mod.time, "sleep", lambda s: None), \
     mock.patch.object(ig_mod.requests, "get", return_value=fake_response()):
    gen = make_gen()
    paths = gen.generate_all_images(["a fox in a forest", "a city at night"])
    check("all scenes generated", len(paths) == 2, str(paths))
    check("usage counts both scenes", gen.provider_usage ==
          {f"pollinations-legacy ({config.IMAGE_LEGACY_MODEL})": 2}, str(gen.provider_usage))
    captured = []
    handler = logging.Handler()
    handler.emit = lambda record: captured.append(record.getMessage())
    old_level = ig_mod.logger.level
    ig_mod.logger.setLevel(logging.INFO)
    ig_mod.logger.addHandler(handler)
    try:
        gen._log_provider_summary(2, 2)
    finally:
        ig_mod.logger.removeHandler(handler)
        ig_mod.logger.setLevel(old_level)
    summary = " ".join(captured)
    check("summary names winner and counts",
          f"winners: pollinations-legacy ({config.IMAGE_LEGACY_MODEL}) x2" in summary,
          summary)

empty_gen = make_gen()
captured_empty = []
handler_empty = logging.Handler()
handler_empty.emit = lambda record: captured_empty.append(record.getMessage())
old_level_empty = ig_mod.logger.level
ig_mod.logger.setLevel(logging.INFO)
ig_mod.logger.addHandler(handler_empty)
try:
    empty_gen._log_provider_summary(3, 0)
finally:
    ig_mod.logger.removeHandler(handler_empty)
    ig_mod.logger.setLevel(old_level_empty)
check("empty summary warns when nothing succeeded",
      any("no provider" in msg for msg in captured_empty), str(captured_empty))

shutil.rmtree(os.path.join(TEMP_DIR, JOB), ignore_errors=True)

print(f"\nRESULT: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
print("ALL CHECKS PASSED")
