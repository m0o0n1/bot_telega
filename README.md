# bot_telega

This bot is made for INT-11 PT_START2024.

The task was to create a bot which monitors the state of the channel/group and notifies admins if there are users without an access.

## How to use it?
Create a channel/group. Now add the bot to channel and make it administrator. After doing this start the private chat with the bot (/start, /me) and execute '/load' command to load a txt file that would contain the list of usernames (thos starting with @) allowed to be in a chat.
After that you can invite users and bot will track them.

Every admin in the channel shoud start (/start) the bot to be able to receive the messages.

## How to start it?
To start a bot you have to install docker software. Then just run 
```
sudo docker compose build --no-cache && sudo docker compose up
```
### Notes
I don't know why but it is a probability that `docker compose up` would fail to run first time. Just rerun it.

One of the main features of this bot is that it can track multiple chat simultaniously.

Also it saves the previous state so, when the bot is restarted the data is not lost.
