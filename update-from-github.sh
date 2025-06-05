#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Fetch latest code and reset to origin/dev
git fetch origin
git reset --hard origin/dev

# Restart the systemd service
sudo systemctl restart crypto-bot.service
