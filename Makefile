SHELL := /bin/bash
PY ?= /root/telegram-crypto-bot-github/.venv/bin/python

DEPLOY_SRV_DIR := /srv/dev3/bin
DEPLOY_ETC_DIR := /etc/systemd/system/dev3-convert@.service.d

.PHONY: deploy deploy-srv deploy-systemd reload restart-asia restart-us

deploy: deploy-srv deploy-systemd reload

deploy-srv:
	install -d $(DEPLOY_SRV_DIR)
	install -m 0755 scripts/convert_cycle.py $(DEPLOY_SRV_DIR)/convert_cycle.py

deploy-systemd:
	install -d $(DEPLOY_ETC_DIR)
	install -m 0644 ops/systemd/dev3-convert@.service.d/70-cli-args.conf \
		$(DEPLOY_ETC_DIR)/70-cli-args.conf

reload:
	systemctl daemon-reload

restart-asia:
	systemctl restart dev3-convert@asia.service

restart-us:
	systemctl restart dev3-convert@us.service
