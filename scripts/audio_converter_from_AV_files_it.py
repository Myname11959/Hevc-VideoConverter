# Compatibilità: modulo rinominato in 'scripts/string_audio_generator.py'
import warnings

warnings.warn(
    "DEPRECATION: usa 'scripts.string_audio_generator' al posto di 'scripts.audio_converter_from_AV_files_it'",
    DeprecationWarning,
    stacklevel=2,
)
try:
    # percorso canonico (package 'scripts')
    from scripts.string_audio_generator import AudioConverter, StringAudioGenerator
except ModuleNotFoundError:
    # fallback se importato senza 'scripts.' ma PYTHONPATH include scripts/
    from string_audio_generator import AudioConverter, StringAudioGenerator  # type: ignore
__all__ = ["AudioConverter", "StringAudioGenerator"]
