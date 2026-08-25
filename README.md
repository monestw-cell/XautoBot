# X to Telegram Sync Bot 🤖🔄

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Tweepy](https://img.shields.io/badge/API-Tweepy-1DA1F2?logo=x&logoColor=white)](https://tweepy.org)
[![Telegram](https://img.shields.io/badge/Broadcast-Telegram-2CA5E0?logo=telegram&logoColor=white)](https://telegram.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An automated social media relay bot that monitors X (formerly Twitter) accounts and hashtags, instantly broadcasting new posts, threads, media, and videos directly to Telegram channels and groups.

---

## ✨ Key Capabilities

- **⚡ Real-Time Polling & Webhooks:** Instantaneous retrieval and forwarding of new tweets.
- **🖼️ Rich Media Extraction:** Seamlessly forwards photos, multi-image galleries, and native MP4 videos.
- **🔍 Smart Content Filtering:** Filter out retweets, replies, quote tweets, or match specific keywords.
- **🛡️ Rate-Limit Safe:** Intelligent backoff algorithms adhering strictly to X API quotas.
- **🩺 Self-Healing & Health Check:** Integrated web server ensuring zero-downtime on cloud hosting providers.

---

## 🚀 Setup & Deployment

```bash
# Clone the repository
git clone https://github.com/monestw-cell/x-telegram-sync-bot.git
cd x-telegram-sync-bot

# Install requirements
pip install -r requirements.txt

# Run
python main.py
```

---

## 📄 License
Released under the [MIT License](LICENSE).
