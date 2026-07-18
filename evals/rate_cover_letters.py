#!/usr/bin/env python3
"""Независимый LLM-оценщик качества cover letters. Рубрика 0-10, порог ≥7.
Использует Ollama Cloud (та же учётка, но отдельный вызов-оценщик — модель без
доступа к промпту генератора). Exit 0 = средний балл ≥7 и ≥80% писем ≥7.
Запуск: python3 -m evals.rate_cover_letters [--sample N]"""
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import config, http_client, store  # noqa: E402

RUBRIC = """Ты — строгий карьерный консультант. Оцени сопроводительное письмо по рубрике 0-10:
+2 начинается с "Здравствуйте!", 2 абзаца, без подписи
+2 первый абзац связывает опыт с ролью (без воды "откликаюсь потому что")
+3 конкретные кейсы с фактами (не выдуманные, релевантные вакансии)
+2 длина 60-120 слов, короткие предложения, без канцелярита
+1 нет markdown/HTML/плейсхолдеров/длинных тире
Ответь ТОЛЬКО JSON: {"score": N, "reason": "..."}"""


def rate(letter, title, company):
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": RUBRIC},
            {"role": "user", "content": f"Вакансия: {title} @ {company}\n\nПисьмо:\n{letter}"},
        ],
        "temperature": 0.0, "max_tokens": 200,
    }
    if "deepseek" in config.OLLAMA_MODEL.lower():
        payload["reasoning_effort"] = "none"
    resp = http_client.request(
        "POST", f"{config.OLLAMA_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {config.ollama_api_key()}",
                 "Content-Type": "application/json"},
        data=json.dumps(payload).encode(), timeout=60)
    if resp.status != 200:
        return None
    content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    m = re.search(r'\{.*\}', content, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def main():
    sample_n = 10
    if "--sample" in sys.argv:
        sample_n = int(sys.argv[sys.argv.index("--sample") + 1])
    if not config.ollama_api_key():
        print(json.dumps({"error": "OLLAMA_API_KEY not set"}))
        return 1
    vac = store.load()
    with_letters = [r for r in vac.values() if r.get("cover_letter") and not r.get("migrated")]
    if not with_letters:
        print(json.dumps({"error": "no cover letters to rate"}))
        return 1
    sample = random.sample(with_letters, min(sample_n, len(with_letters)))
    results = []
    for r in sample:
        verdict = rate(r["cover_letter"], r["title"], r.get("company", ""))
        if verdict:
            results.append({"vacancy_id": r["vacancy_id"], **verdict})
    if not results:
        print(json.dumps({"error": "rater unavailable"}))
        return 1
    scores = [x["score"] for x in results]
    avg = sum(scores) / len(scores)
    pass_rate = sum(1 for s in scores if s >= 7) / len(scores)
    out = {"rated": len(results), "avg": round(avg, 2), "pass_rate": round(pass_rate, 2),
           "threshold_met": avg >= 7 and pass_rate >= 0.8, "details": results}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["threshold_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
