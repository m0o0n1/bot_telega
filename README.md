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
## How it works?

There is 2 containers: for python bot and for PostgreSQL database. The bot needs this database to store the allowed usernames in the database $DB_NAME, which consists of tables representing every chat. The table name for the specific chat is a unique chat_id from telegram (for example, if the chat_id = -1337 then the table_name would be _1337).

Also there is a table for storing a previous state of the bot (to handle the restart of a bot, when the data is lost).

### Notes
I don't know why but it is a probability that `docker compose up` would fail to run first time. Just rerun it.

One of the main features of this bot is that it can track multiple chat simultaniously.

Also it saves the previous state so, when the bot is restarted the data is not lost.

The settings are stored in .env file
