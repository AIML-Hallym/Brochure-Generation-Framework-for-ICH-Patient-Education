# -*- coding: utf-8 -*-
"""
End-to-end demo without an API key: placeholder pictures -> 6 synthetic cases (fixed sentences, no LLM) -> 12 PDFs.

  python examples/run_demo.py            # outputs/demo/cache/*.json, outputs/demo/pdf/{EN,KO}/*.pdf
  python examples/run_demo.py --llm      # LLM wording (set ICH_API_KEY, and ICH_BASE_URL / ICH_MODEL if needed)
"""
import os
import sys
import subprocess

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES = os.path.join(HERE, "assets", "images")
OUT = os.path.join(HERE, "outputs", "demo")


def run(*args):
    print("$", " ".join(args), flush=True)
    subprocess.run([sys.executable, *args], cwd=HERE, check=True)


if __name__ == "__main__":
    if not os.path.isdir(os.path.join(IMAGES, "about_ich")):
        run("tools/make_placeholder_images.py", IMAGES)
    run("run_batch.py", "--inputs", "examples/demo_inputs.csv", "--out", OUT, *([] if "--llm" in sys.argv else ["--dry"]))
    run("render_brochures.py", "--cache", os.path.join(OUT, "cache"), "--out", os.path.join(OUT, "pdf"), "--images", IMAGES)
