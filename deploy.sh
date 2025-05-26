#!/bin/bash

cd /root/crypto-profit-bot/telegram-crypto-bot
git pull
systemctl restart crypto-bot.service
