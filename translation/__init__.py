"""Translation layer: Vertex AI Gemini client and pilot pipeline.

Depends on the Vertex AI SDK (``google-cloud-aiplatform``) and on the parser
package ``pretranslation_cst`` for CST/masking/chunking.
"""

from .client import (
    TranslatedUnit,
    build_prompt,
    restore_translated,
    translate_unit,
    verify_placeholders,
)

__all__ = [
    "TranslatedUnit",
    "build_prompt",
    "restore_translated",
    "translate_unit",
    "verify_placeholders",
]