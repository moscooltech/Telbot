"""
Offline unit tests for the ImageGenerator fallback chain (no network, no API keys).
Run: python test_image_gen_unit.py
"""
import os
import re
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

print("== 7. klein multi-reference anchor (opt-in: it clones scene 1 otherwise) ==")
check("anchor is OFF by default so scenes keep their own frame",
      config.ENABLE_IMAGE_ANCHOR is False, str(config.ENABLE_IMAGE_ANCHOR))
with mock.patch.object(ig_mod, "CLOUDFLARE_ACCOUNT_ID", "acc"), \
     mock.patch.object(ig_mod, "CLOUDFLARE_API_TOKEN", "tok"), \
     mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", ""), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""), \
     mock.patch.object(ig_mod, "ENABLE_IMAGE_ANCHOR", False), \
     mock.patch.object(ig_mod.time, "sleep", lambda s: None), \
     mock.patch.object(ig_mod.requests, "post", return_value=cf_json_response()) as _post_off:
    _gen_off = make_gen()
    _gen_off.generate_image("a fox in a forest", 0)
    _gen_off.generate_image("a fox by a river", 1)
    check("disabled -> no reference image offered to klein",
          "files" not in _post_off.call_args.kwargs, str(list(_post_off.call_args.kwargs)))
    check("disabled -> _use_anchor stays False and no anchor is remembered",
          _gen_off._use_anchor is False and _gen_off.anchor_image_path is None,
          str((_gen_off._use_anchor, _gen_off.anchor_image_path)))

with mock.patch.object(ig_mod, "ENABLE_IMAGE_ANCHOR", True), \
     mock.patch.object(ig_mod, "POLLINATIONS_API_KEY", ""), \
     mock.patch.object(ig_mod, "BYTEZ_API_KEY", ""), \
     mock.patch.object(ig_mod.time, "sleep", lambda s: None), \
     mock.patch.object(ig_mod.requests, "get", return_value=fake_response()):
    gen = make_gen()
    check("anchor unset before first image", gen.anchor_image_path is None, str(gen.anchor_image_path))
    gen.generate_image("a fox in a forest", 0)
    expected_anchor = os.path.join(TEMP_DIR, JOB, "images", "scene_000.jpg")
    check("enabled -> anchor set to first successful image",
          gen.anchor_image_path == expected_anchor, str(gen.anchor_image_path))
    check("enabled -> photo scene is anchor-eligible", gen._use_anchor is True, str(gen._use_anchor))

    klein_model = config.CLOUDFLARE_KLEIN_MODELS[0]
    with mock.patch.object(ig_mod.requests, "post", return_value=cf_json_response()) as post_mock:
        gen._generate_cloudflare("the same fox", 1, klein_model, 30)
        check("klein request includes anchor as input_image_0",
              "files" in post_mock.call_args.kwargs
              and "input_image_0" in post_mock.call_args.kwargs["files"],
              str(list(post_mock.call_args.kwargs)))

    gen.anchor_image_path = None
    with mock.patch.object(ig_mod.requests, "post", return_value=cf_json_response()) as post_mock:
        gen._generate_cloudflare("the same fox", 2, klein_model, 30)
        check("no anchor -> plain multipart klein request",
              "files" not in post_mock.call_args.kwargs, str(list(post_mock.call_args.kwargs)))

    gen.anchor_image_path = "/nonexistent/anchor.jpg"
    with mock.patch.object(ig_mod.requests, "post", return_value=cf_json_response()) as post_mock:
        gen._generate_cloudflare("the same fox", 3, klein_model, 30)
        check("missing anchor file is ignored safely",
              "files" not in post_mock.call_args.kwargs, str(list(post_mock.call_args.kwargs)))

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

print("== 8. inline /mode directives (illustration / design / decompose / diagram / poster) ==")
from services.image_generator import parse_image_mode
from services.scene_generator import SceneGenerator, mode_directive_help
import services.scene_generator as sg_mod

print("== 8a. directive parsing ==")
check("plain prompt has no mode", parse_image_mode("a fox in a forest") == (None, "a fox in a forest"))
check("explicit /photo parsed", parse_image_mode("/photo a fox") == ("photo", "a fox"))
check("/illustration parsed",
      parse_image_mode("/illustration the water cycle") == ("illustration", "the water cycle"))
check("/decompose parsed",
      parse_image_mode("/decompose a diesel engine") == ("decompose", "a diesel engine"))
check("/spec alias maps to design", parse_image_mode("/spec sheet layout") == ("design", "sheet layout"))
check("colon separator tolerated", parse_image_mode("/diagram: a flow") == ("diagram", "a flow"))
check("backtick-wrapped directive tolerated",
      parse_image_mode("`/poster` retro travel") == ("poster", "retro travel"))
check("leading whitespace tolerated",
      parse_image_mode("   /decomposition engine parts") == ("decompose", "engine parts"))
check("bare directive yields an empty body", parse_image_mode("/diagram") == ("diagram", ""))
check("unknown /word left untouched", parse_image_mode("/specify a fox") == (None, "/specify a fox"))
check("mid-prompt slash ignored", parse_image_mode("a fox /illustration") == (None, "a fox /illustration"))

print("== 8b. mode table ==")
check("all six modes configured",
      set(config.IMAGE_MODES) == {"photo", "illustration", "design", "decompose", "diagram", "poster"},
      str(sorted(config.IMAGE_MODES)))
check("photo mode == the pre-mode behavior",
      config.IMAGE_MODES["photo"]["style"] == config.IMAGE_STYLE_SUFFIX
      and config.IMAGE_MODES["photo"]["negative"] == config.IMAGE_NEGATIVE_PROMPT)
check("every mode has style + negative + anchor flag",
      all(m.get("style") and m.get("negative") and isinstance(m.get("anchor"), bool)
          for m in config.IMAGE_MODES.values()))
check("non-photo negatives stop banning drawings",
      all("illustration" not in config.IMAGE_MODES[m]["negative"]
          for m in config.IMAGE_MODES if m != "photo"))
check("non-photo negatives stop blanket-banning text/labels",
      all(not re.search(r"(^|,\s*)(text|words|labels)(\s*,|$)",
                        config.IMAGE_MODES[m]["negative"])
          for m in config.IMAGE_MODES if m != "photo"),
      str({m: config.IMAGE_MODES[m]["negative"] for m in config.IMAGE_MODES if m != "photo"}))
check("photo negative still bans illustration + text",
      "illustration" in config.IMAGE_MODES["photo"]["negative"]
      and "text" in config.IMAGE_MODES["photo"]["negative"])
check("photo keeps the klein anchor, schematics drop it",
      config.IMAGE_MODES["photo"]["anchor"] and not config.IMAGE_MODES["diagram"]["anchor"])

print("== 8c. per-scene mode resolution ==")
_gen = make_gen()
check("default mode is photo", _gen.default_mode == "photo")
check("no directive -> job default", _gen._resolve_mode("a fox") == ("photo", "a fox"))
_gen_art = ImageGenerator("verify_image_unit_art", style_bible="s", default_mode="illustration")
check("job default applies without a directive",
      _gen_art._resolve_mode("a fox") == ("illustration", "a fox"))
check("inline directive overrides the job default",
      _gen_art._resolve_mode("/diagram a circuit") == ("diagram", "a circuit"))
check("explicit /photo overrides a non-photo job default",
      _gen_art._resolve_mode("/photo a fox") == ("photo", "a fox"))
check("alias default_mode is normalised",
      ImageGenerator("verify_image_unit_alias", default_mode="art").default_mode == "illustration")
check("unknown default_mode falls back to photo",
      ImageGenerator("verify_image_unit_bad", default_mode="nope").default_mode == "photo")

print("== 8d. prompt + negative swap per mode ==")
_photo_prompt = _gen._build_prompt("a fox", mode="photo")
_art_prompt = _gen._build_prompt("a fox", mode="illustration")
check("photo prompt keeps the photo suffix",
      config.IMAGE_STYLE_SUFFIX.split(",")[0] in _photo_prompt, _photo_prompt)
check("illustration prompt swaps the style",
      "digital illustration" in _art_prompt
      and "photorealistic, candid documentary" not in _art_prompt, _art_prompt)
check("directive text never reaches the provider",
      "/illustration" not in _art_prompt, _art_prompt)
check("quality tail always present",
      _art_prompt.endswith("high quality, detailed, professional, 4k"), _art_prompt)
check("style bible still fused in non-photo modes",
      "watercolor style" in _art_prompt, _art_prompt)

print("== 8e. mode reaches the provider request ==")
with mock.patch.object(ig_mod, "CLOUDFLARE_ACCOUNT_ID", "acc"), \
     mock.patch.object(ig_mod, "CLOUDFLARE_API_TOKEN", "tok"), \
     mock.patch.object(ig_mod.time, "sleep", lambda s: None), \
     mock.patch.object(ig_mod.requests, "post", return_value=cf_json_response()) as _post:
    _gen_dia = make_gen()
    _path = _gen_dia.generate_image("/diagram a circuit board", 0)
    check("diagram image generated", _path is not None, str(_path))
    _form = _post.call_args.kwargs.get("data", {})
    check("diagram negative sent (no drawing bans)",
          "photograph" in _form.get("negative_prompt", "")
          and "illustration" not in _form.get("negative_prompt", ""),
          str(_form.get("negative_prompt")))
    check("klein anchor skipped for non-photo modes",
          "files" not in _post.call_args.kwargs, str(list(_post.call_args.kwargs)))
    check("mode usage recorded", _gen_dia.mode_usage == {"diagram": 1}, str(_gen_dia.mode_usage))

# Anchor gating: a real reference file, toggled by the mode.
_anchor_file = os.path.join(TEMP_DIR, JOB, "anchor_probe.jpg")
with open(_anchor_file, "wb") as _af:
    _af.write(JPEG_MAGIC + b"x" * 5000)
_gen_anchor = make_gen()
_gen_anchor.anchor_image_path = _anchor_file
_klein = config.CLOUDFLARE_KLEIN_MODELS[0]
with mock.patch.object(ig_mod.requests, "post", return_value=cf_json_response()) as _post:
    _gen_anchor._use_anchor = True
    _gen_anchor._generate_cloudflare("x", 1, _klein, 30, negative_prompt="n")
    check("photo mode sends the klein anchor",
          "files" in _post.call_args.kwargs, str(list(_post.call_args.kwargs)))
with mock.patch.object(ig_mod.requests, "post", return_value=cf_json_response()) as _post:
    _gen_anchor._use_anchor = False
    _gen_anchor._generate_cloudflare("x", 2, _klein, 30, negative_prompt="n")
    check("non-photo mode withholds the klein anchor",
          "files" not in _post.call_args.kwargs, str(list(_post.call_args.kwargs)))

print("== 8f. mode usage surfaces in the summary ==")
_gen_sum = make_gen()
_gen_sum.provider_usage = {"cloudflare (m)": 2}
_gen_sum.mode_usage = {"photo": 1, "diagram": 1}
check("summary names non-default modes",
      "modes: diagram x1" in _gen_sum.provider_summary_text(2, 2),
      _gen_sum.provider_summary_text(2, 2))
_gen_sum.mode_usage = {"photo": 2}
check("summary hides the default mode",
      "modes:" not in _gen_sum.provider_summary_text(2, 2),
      _gen_sum.provider_summary_text(2, 2))

print("== 8g. the script LLM is told it may pick a mode ==")
with mock.patch.object(sg_mod, "ENABLE_LLM_IMAGE_MODES", True):
    _help = mode_directive_help()
    check("mode help offered when enabled", "/decompose" in _help and "/poster" in _help, _help[:80])
    check("mode help names every non-photo mode",
          all(("/" + m) in _help for m in config.IMAGE_MODES if m != "photo"), _help)
with mock.patch.object(sg_mod, "ENABLE_LLM_IMAGE_MODES", False):
    check("mode help disappears when disabled", mode_directive_help() == "")

_captured = {}


class _CaptureLLM:
    def __init__(self, reply):
        self.reply = reply

    def generate_text(self, system_prompt, user_prompt, **kwargs):
        _captured["sys"] = system_prompt
        return self.reply


_sg = SceneGenerator.__new__(SceneGenerator)
_sg.llm = _CaptureLLM('{"prompts": ["a fox, wide shot, soft light"]}')
with mock.patch.object(sg_mod, "ENABLE_LLM_IMAGE_MODES", True):
    _sg._polish_visuals({"motive": "m", "style_bible": "s"}, [{"description": "d"}])
check("polish prompt offers the render modes", "/diagram" in _captured["sys"], _captured["sys"][:120])
with mock.patch.object(sg_mod, "ENABLE_LLM_IMAGE_MODES", False):
    _sg._polish_visuals({"motive": "m", "style_bible": "s"}, [{"description": "d"}])
check("polish prompt drops the modes when disabled",
      "/diagram" not in _captured["sys"], _captured["sys"][:120])

_sg.llm = _CaptureLLM('{"scenes": [{"narration": "n", "description": "d"}], "caption": "c", "hashtags": []}')
_spine = {"motive": "m", "style_bible": "s", "beats": [], "hook": "", "cta": ""}
with mock.patch.object(sg_mod, "ENABLE_LLM_IMAGE_MODES", True):
    _sg._generate_scenes("topic", _spine, 1, 2)
check("scene prompt offers the render modes", "/decompose" in _captured["sys"], _captured["sys"][:120])
with mock.patch.object(sg_mod, "ENABLE_LLM_IMAGE_MODES", False):
    _sg._generate_scenes("topic", _spine, 1, 2)
check("scene prompt drops the modes when disabled",
      "/decompose" not in _captured["sys"], _captured["sys"][:120])

print("== 8h. every scene must be its own moment, not a re-render ==")
_sg.llm = _CaptureLLM('{"prompts": ["p"]}')
_sg._polish_visuals({"motive": "m", "style_bible": "s"}, [{"description": "d"}])
_polish_sys = _captured["sys"]
check("polish demands a DIFFERENT moment per scene",
      "DIFFERENT moment" in _polish_sys, _polish_sys[:200])
check("polish varies the shot list across scenes",
      "wide establishing" in _polish_sys and "close-ups" in _polish_sys, _polish_sys[:200])
check("polish forbids repeating the previous framing",
      "never repeat the previous prompt's framing" in _polish_sys, _polish_sys[:200])

_sg.llm = _CaptureLLM('{"scenes": [{"narration": "n", "description": "d"}], "caption": "c", "hashtags": []}')
_sg._generate_scenes("topic", _spine, 1, 2)
check("scene prompt asks for a NEW moment per scene",
      "NEW moment" in _captured["sys"], _captured["sys"][:200])
check("scene prompt still locks the look to the style bible",
      "keeps this look" in _captured["sys"], _captured["sys"][:200])

_sg.llm = _CaptureLLM('{"motive": "m", "style_bible": "s", "beats": [], "hook": "", "cta": ""}')
_sg._generate_spine("topic")
check("spine stops pinning location/framing in the style bible",
      "Never pin the location" in _captured["sys"], _captured["sys"][:200])
check("spine still asks for a recurring look",
      "recurring LOOK" in _captured["sys"], _captured["sys"][:200])

shutil.rmtree(os.path.join(TEMP_DIR, JOB), ignore_errors=True)
for _extra in ("verify_image_unit_art", "verify_image_unit_alias", "verify_image_unit_bad",
               "verify_image_unit_modes"):
    shutil.rmtree(os.path.join(TEMP_DIR, _extra), ignore_errors=True)

print(f"\nRESULT: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
print("ALL CHECKS PASSED")
