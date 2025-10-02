SHELL := /bin/bash
PY ?= /root/telegram-crypto-bot-github/.venv/bin/python

DEPLOY_SRV_DIR := /srv/dev3/bin
DEPLOY_ETC_DIR := /etc/systemd/system/dev3-convert@.service.d
SINCE ?= 2 minutes ago

.PHONY: deploy deploy-srv deploy-systemd reload restart restart-asia restart-us \
        logs logs-asia logs-us timers status help

## ===== Deploy =====
deploy: deploy-srv deploy-systemd reload  ## install entrypoint + systemd override, reload daemon
deploy-srv:
	install -d $(DEPLOY_SRV_DIR)
	install -m 0755 scripts/convert_cycle.py $(DEPLOY_SRV_DIR)/convert_cycle.py
deploy-systemd:
	install -d $(DEPLOY_ETC_DIR)
	install -m 0644 ops/systemd/dev3-convert@.service.d/70-cli-args.conf \
		$(DEPLOY_ETC_DIR)/70-cli-args.conf
reload:
	systemctl daemon-reload

## ===== Runtime =====
restart: restart-asia restart-us          ## restart both services
restart-asia:
	systemctl restart dev3-convert@asia.service
restart-us:
	systemctl restart dev3-convert@us.service

## ===== Observability =====
logs: logs-asia logs-us                   ## show recent logs for both
logs-asia:
	journalctl -u dev3-convert@asia.service --since "$(SINCE)" --no-pager | awk '/config in use|app.run/{print}'
logs-us:
	journalctl -u dev3-convert@us.service --since "$(SINCE)" --no-pager   | awk '/config in use|app.run/{print}'

timers:                                    ## list convert timers and their next fire times
	systemctl list-timers 'dev3-convert@*.timer' --no-pager

status:                                    ## concise status of services
	systemctl --no-pager --full status dev3-convert@asia.service dev3-convert@us.service || true

help:                                      ## this help
	@awk 'BEGIN{FS=":.*##"; printf "\nTargets:\n"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST); echo

## ===== Observability: audit =====
audit-today: ## run quiet audit for today
	./scripts/audit_quiet_today.sh
