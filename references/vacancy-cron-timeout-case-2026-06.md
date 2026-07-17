# Vacancy monitoring incident — AI/PM tracker stopped updating (2026-06-25)

## Symptoms

- User asked why AI/PM vacancy updates stopped arriving.
- Cron job `6c63e3b8d351` appeared active but `last_status: error`.
- No Telegram reports received since the last successful run.

## Diagnostic path

1. `cronjob list` showed the job was **enabled and scheduled**, not paused.
2. `session_search` revealed recent runs ended with errors.
3. `~/.hermes/cron/output/6c63e3b8d351/2026-06-25_09-18-38.md` contained the real error:
   ```
   TimeoutError: Cron job 'Ежедневный поиск вакансий AI/PM' idle for 600s (limit 600s)
   — last activity: executing tool: terminal
   ```
4. The previous run log (2026-06-22) had the same `TimeoutError` pattern.
5. `cronjob list` showed schedule `0 9 */3 * *` — every 3 days, not daily.
6. Sheets API metadata query revealed the target tab is named **«AI»**, while the prompt referenced **«Лист1»**.
7. Google OAuth refresh token was working, ruling out auth as the root cause.

## Root causes

1. **Overloaded LLM-driven prompt.** It asked the agent to run ~144 web_search calls (12 domains × 12 query variants) plus `terminal` and `execute_code`. This exceeded the 600-second cron session limit.
2. **Wrong sheet tab name.** The processor was writing to or checking a non-existent «Лист1»; the real tab is «AI».
3. **Misaligned schedule.** Every-3-days schedule did not match the user's expectation of daily updates.

## Fix applied

1. Created deterministic processor `~/.hermes/scripts/ai_pm_vacancies.py`.
2. Rewrote the cron prompt to:
   - run exactly 12 parallel web_search calls (one per domain);
   - pass the raw JSON results to the processor via stdin;
   - let the processor handle filtering, dedup, Sheets write, seen.json update, and Telegram report.
3. Verified the target sheet tab name and hardcoded `SHEET_NAME = "AI"`.
4. Deleted the old cron job and created a new one (`6d9bd734b2ab`) with schedule `0 9 * * *`.
5. Tested the processor:
   - empty input: produced a valid "no new vacancies" report;
   - sample input: wrote one new row to the AI tab and updated seen.json.

## Verification commands

```bash
# Verify tab names
python3 -c "... Sheets API metadata query ..."

# Test empty input
echo '[]' | python3 ~/.hermes/scripts/ai_pm_vacancies.py

# Test with sample results
cat /tmp/sample_vacancies.json | python3 ~/.hermes/scripts/ai_pm_vacancies.py
```

## Lessons for future vacancy trackers

- Keep LLM-driven search to one batched call per source/domain.
- Never let LLM infer or compute Google Sheets ranges.
- Always verify the actual sheet tab name before writing.
- Use deterministic scripts for all stateful operations (dedup, Sheets, seen.json).
- When a cron job fails silently with `TimeoutError`, first suspect too many tool calls, not network/auth issues.
