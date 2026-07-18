"""TC-01: cron-конфиг существует и запускает pipeline."""
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_cron_config_exists_and_points_to_pipeline():
    path = os.path.join(BASE, "config", "cron.yaml")
    assert os.path.exists(path)
    content = open(path, encoding="utf-8").read()
    assert "src.pipeline" in content
    assert "0 9 */2 * *" in content
    assert "no_agent: true" in content


def test_pipeline_module_importable_and_has_run():
    from src import pipeline
    assert callable(pipeline.run)
