# Methodology change log

Dated changes to the rules and the scope, newest first. `scripts/build_methodology.py` renders this file into the
Methodology page. Format: a `## <day> <Mon> <year>` heading, then one `- ` line per change. `backticks` become code.

## 22 Nov 2026
- Coverage rule added: an official call needs 2 companies, each covering 95% or more of the last 24 h and reporting within the last 15 minutes. Otherwise the state is not enough data, never up.
- First public version of this page, generated from rules version `1-draft-rolling`.

## 12 Nov 2026
- Two definitions reported side by side: Hard down (90% or more of calls failing over 3 minutes) and Degraded (10% or more over 10 minutes).

## 11 Nov 2026
- Cloudflare Workers probe network started.

## 8 Nov 2026
- GitHub Actions probe network (Microsoft) started.
- AWS reference network added: shown, never counted.

## 1 Nov 2026
- Rolling 10-minute window drafted, with several checks a minute from each probe network.
