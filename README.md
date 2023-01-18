# Self Destructing Downloader
This is a robot for downloading videos and images that are sent through Telegram in a self-destructing way.

Robot capabilities:
- High speed in storage
- Sends a copy to your saved messages
- Optimal use of resources

# Requirements
- Python (3.5, 3.6, 3.7, 3.8, 3.9, 3.10)
- Telethon (1.26.1)

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
