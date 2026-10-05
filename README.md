# Self Destructing Downloader
This is a robot for downloading videos and images that are sent through Telegram in a self-destructing way.

Robot capabilities:
- High speed in storage
- Sends a copy to your saved messages
- Optimal use of resources

# Requirements
- Python 3.8 or newer (including Python 3.14)
- Telethon 1.38.1 (installed from `requirements.txt`)

# Installation
```
git clone https://github.com/mahdiashtian/self-destructing-downloader.git
```
```
cd self-destructing-downloader
```
```
pip install -r requirements.txt
```
# Usage
```
touch .env
```
Open the ".env" file and copy the following information into it:
```
API_ID=123456
API_HASH="35886641ed1bfaa92e7ee30er9888"
```
You can get these values from the my.telegram.org site.

Then enter the following command in the terminal and complete the authentication process:
```
python main.py
```

The client is created and started inside `asyncio.run()`, so startup works on
Python 3.14 without relying on an implicitly created event loop. The existing
`mahdiashtian.session` login is reused.

# Tests
After installing the requirements, run:
```
python -m unittest discover -s tests -v
```
The regression tests construct a real Telethon client with an in-memory session,
replace network operations, and verify startup, shutdown and download behavior.
They do not require Telegram credentials or a live login.
