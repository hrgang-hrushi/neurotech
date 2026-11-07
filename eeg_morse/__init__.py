"""EEG (ANT Neuro eego) -> Morse dots/dashes -> English.

    from eeg_morse import load, preset, decode
    res = decode(load("session.cnt"), preset("motor"))
    print(res.morse, res.text)
"""
from .config import PRESETS, PipelineConfig, preset
from .io import Recording, load
from .morse import decode as decode_morse
from .morse import encode as encode_morse
from .pipeline import calibrate, decode

__all__ = ["PRESETS", "PipelineConfig", "Recording", "calibrate", "decode",
           "decode_morse", "encode_morse", "load", "preset"]
__version__ = "0.1.0"
