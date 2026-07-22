import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "rag_api"))

from app.generator import load_prompt_template


def test_week8_prompt_templates_are_file_backed():
    assert "retrieved evidence" in load_prompt_template("system_v1.md")
    assert "当前知识库未覆盖" in load_prompt_template("no_answer_v1.md")
