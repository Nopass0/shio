# QuickChat module for Hikka

## Official Hikka documentation
- [Hikka user documentation](https://hikka.pw)
- [Hikka developer documentation](https://dev.hikka.pw)
- [Hikka source code repository](https://github.com/hikariatama/Hikka)

## Installing the module
1. Download the [`modules/quick_chat.py`](../modules/quick_chat.py) file from this repository.
2. Send the file to the account where Hikka is running (or host it somewhere reachable over HTTPS).
3. In Hikka, run `.dlmod` while replying to the uploaded file **or** provide the public URL to the file (for example `.dlmod https://example.com/quick_chat.py`).
4. Wait for the loader to confirm that `QuickChat` has been installed.

## Usage
- Create an empty supergroup: `.quickchat Project hub`
- Create a chat and immediately invite users (use `|` or a newline to separate the title from the invite list):
  - `.quickchat Project hub | @user1 @user2`
  - `.quickchat "Project hub" @user1 @user2`

The module also accepts comma-separated lists and ignores duplicates when resolving invitees.
