# DEV3 convert ops

## Що зроблено
- smart-фільтр 400 від /sapi/v1/convert/getQuote (ігнор ALL/порожні from/to)
- мінімальний binance_client із підписом і сирим Response для діагностики
- phases через systemd override (див. ops/systemd/70-cli-args.conf)
- app shim у src/app.py (плацдарм під реальну логіку)

## Як запустити вручну
systemctl start dev3-convert@asia.service
systemctl start dev3-convert@us.service

## Таймери
systemctl list-timers 'dev3-convert@*.timer'

## Моніторинг
journalctl -fu dev3-convert@asia.service | grep -E --line-buffered 'getQuote failed:|ERROR|WARNING'

## Відкат convert_api
cp -f "$(ls -1t src/core/convert_api.py.bak.* | head -n1)" src/core/convert_api.py
systemctl start dev3-convert@asia.service
