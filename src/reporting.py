from __future__ import annotations
from pathlib import Path
from typing import Mapping, Any, Iterable, List, Tuple
from datetime import datetime, timezone
import os
import csv
import sys
import fcntl
import tempfile

CSV_FIELDS = [
    "ts",
    "region",
    "phase",
    "from",
    "to",
    "wallet",
    "amount",
    "ratio",
    "toAmount",
    "available",
    "insufficient",
    "ok",
    "quoteId",
    "error",
]


def _default_outdir() -> Path:
    root = os.environ.get("CONVERT_LOG_ROOT", "/srv/dev3/logs/convert")
    return Path(root) / datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_cli_region_phase(argv: List[str] | None = None) -> Tuple[str, str]:
    argv = argv if argv is not None else (sys.argv or [])
    region, phase = "", ""
    for i, a in enumerate(argv):
        if a == "--region" and i + 1 < len(argv):
            region = argv[i + 1]
        if a == "--phase" and i + 1 < len(argv):
            phase = argv[i + 1]
        if a.startswith("--region="):
            region = a.split("=", 1)[1]
        if a.startswith("--phase="):
            phase = a.split("=", 1)[1]
    return (region or "n/a"), (phase or "n/a")


def _stamp_ts(item: Mapping[str, Any]) -> str:
    ts = item.get("ts")
    if ts:
        return str(ts)
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_row(item: Mapping[str, Any], cli_rp: Tuple[str, str]) -> dict:
    rgn, phs = cli_rp

    def _b(v: Any) -> str:
        s = str(v).strip().lower()
        return "True" if s in ("1", "true", "yes") else "False"

    return {
        "ts": _stamp_ts(item),
        "region": (item.get("region") or rgn or "n/a"),
        "phase": (item.get("phase") or phs or "n/a"),
        "from": item.get("from") or "",
        "to": item.get("to") or "",
        "wallet": item.get("wallet") or "",
        "amount": item.get("amount") or "",
        "ratio": item.get("ratio") or "",
        "toAmount": item.get("toAmount") or "",
        "available": item.get("available") or "",
        "insufficient": _b(item.get("insufficient", False)),
        "ok": _b(item.get("ok", True)),
        "quoteId": item.get("quoteId") or "",
        "error": item.get("error") or "",
    }


def _read_existing_rows(csv_path: Path) -> List[dict]:
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        return list(rd)


def _dedup_rows(existing: List[dict], new_rows: List[dict]) -> List[dict]:
    seen_qid = {
        (r.get("quoteId") or "").strip()
        for r in existing
        if (r.get("quoteId") or "").strip()
    }

    def key(r):
        return (r.get("from"), r.get("to"), r.get("wallet"), str(r.get("amount")))

    seen_key = {key(r) for r in existing}
    out = []
    for r in new_rows:
        qid = (r.get("quoteId") or "").strip()
        k = key(r)
        if qid and qid in seen_qid:  # по quoteId
            continue
        if k in seen_key:  # по (from,to,wallet,amount)
            continue
        if qid:
            seen_qid.add(qid)
        seen_key.add(k)
        out.append(r)
    return out


def write_reports(
    items: Iterable[Mapping[str, Any]], outdir: str | Path | None = None
) -> str:
    outdir_path = Path(outdir) if outdir else _default_outdir()
    outdir_path.mkdir(parents=True, exist_ok=True)

    cli_rp = _parse_cli_region_phase()
    rows = [_to_row(x, cli_rp) for x in (list(items) or [])]

    csv_path = outdir_path / "candidates.csv"
    lock_path = outdir_path / ".candidates.csv.lock"

    with lock_path.open("w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        existing = _read_existing_rows(csv_path)
        rows = _dedup_rows(existing, rows)

        if rows:
            with tempfile.NamedTemporaryFile(
                "w", delete=False, dir=outdir_path, encoding="utf-8", newline=""
            ) as tf:
                tmp = Path(tf.name)
                if csv_path.exists() and csv_path.stat().st_size > 0:
                    with csv_path.open("r", encoding="utf-8", newline="") as rf:
                        tf.write(rf.read())
                    writer = csv.DictWriter(
                        tf, fieldnames=CSV_FIELDS, lineterminator="\n"
                    )
                else:
                    writer = csv.DictWriter(
                        tf, fieldnames=CSV_FIELDS, lineterminator="\n"
                    )
                    writer.writeheader()
                for r in rows:
                    writer.writerow(r)
            os.replace(tmp, csv_path)

        # summary з усього дня + по фазах
        try:
            all_rows = _read_existing_rows(csv_path)
        except Exception:
            all_rows = existing + rows

        def _b(s):
            return str((s or "")).strip().lower() == "true"

        def _agg(rs):
            return {
                "total": len(rs),
                "ok": sum(1 for r in rs if _b(r.get("ok"))),
                "insufficient": sum(1 for r in rs if _b(r.get("insufficient"))),
                "errors": sum(1 for r in rs if (r.get("error") or "").strip()),
            }

        agg_all = _agg(all_rows)
        agg_an = _agg(
            [r for r in all_rows if (r.get("phase") or "").strip().lower() == "analyze"]
        )
        agg_tr = _agg(
            [r for r in all_rows if (r.get("phase") or "").strip().lower() == "trade"]
        )
        agg_or = _agg(
            [r for r in all_rows if (r.get("phase") or "").strip().lower() == "order"]
        )
        rgn, phs = _parse_cli_region_phase()

        lines = [
            f"Region/phase: {rgn}/{phs}",
            f"Total routes (all): {agg_all['total']}",
            f"  OK: {agg_all['ok']}  Errors: {agg_all['errors']}  Insufficient: {agg_all['insufficient']}",
            f"Analyze: total={agg_an['total']} ok={agg_an['ok']} errors={agg_an['errors']} insufficient={agg_an['insufficient']}",
            f"Trade:   total={agg_tr['total']} ok={agg_tr['ok']} errors={agg_tr['errors']} insufficient={agg_tr['insufficient']}",
            f"Order:   total={agg_or['total']} ok={agg_or['ok']} errors={agg_or['errors']} insufficient={agg_or['insufficient']}",
        ]
        (outdir_path / "summary.txt").write_text("\n".join(lines), encoding="utf-8")
        fcntl.flock(lk, fcntl.LOCK_UN)

    return str(outdir_path)
