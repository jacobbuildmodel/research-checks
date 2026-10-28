"""Writes out/value.csv from lib.value()."""
import os

import lib

here = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(here, "out"), exist_ok=True)
with open(os.path.join(here, "out", "value.csv"), "w", encoding="utf-8", newline="\n") as f:
    f.write(f"key,value\nT1,{lib.value()}\n")
