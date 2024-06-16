import logging
import os
import io
import psycopg2
import atexit

from datetime import timedelta
from telegram import Chat, ChatMember, ChatMemberUpdated, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ChatMemberHandler,
    ConversationHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Get environment variables
BOT_TOKEN=os.getenv("BOT_TOKEN")
DELTA_CHECK=int(os.getenv("DELTA_CHECK"))
DB_HOST=os.getenv("DB_HOST")
DB_DATABASE=os.getenv("DB_DATABASE")
DB_USER=os.getenv("DB_USER")
DB_PASSWORD=os.getenv("DB_PASSWORD")

handled_channels = set()
chats_data = dict()

def chat_id_normalize(chat_id: int) -> str:
    if chat_id < 0:
        return '_' + str(chat_id)[1:]
    return str(chat_id)

def check_table(table_name: str) -> bool:
    if not table_name:
        return False

    conn = psycopg2.connect(dbname=DB_DATABASE, user=DB_USER, password=DB_PASSWORD, host=DB_HOST)
    cursor = conn.cursor()
    cursor.execute("select * from information_schema.tables where table_name=%s", (table_name,))
    cursor.close()
    conn.close()
    return bool(cursor.rowcount)

async def check_members(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Job routine wich checks users and notifies admins if some of them don't have access to channel anymore"""
    denied_users = set()
    table_name = chat_id_normalize(ctx.job.chat_id)
    logger.info(f"table_name: {table_name}")
    if not check_table(table_name):
        return
    
    global chats_data
    try:
        usernames = chats_data[ctx.job.chat_id] 
        conn = psycopg2.connect(dbname=DB_DATABASE, user=DB_USER, password=DB_PASSWORD, host=DB_HOST)
        
        for username in usernames:
            cursor = conn.cursor()
            cmd = f"SELECT * FROM {table_name} WHERE username=%s"
            cursor.execute(cmd, (username, ))
            logger.info(f"INFO-----: {username}, {table_name}, {cursor.rowcount}")
            if not cursor.rowcount:
                denied_users.add(username)
            cursor.close()
        conn.close()
    except KeyError:
        logger.warning("Chat data is uninitialized for chat id: %s", str(ctx.job.chat_id))
    if denied_users:
        text_to_send = "Please, check this users for access:"
        i = 0
        for username in denied_users:
            text_to_send += f"\n{i+1}. {username}"
            i += 1
            
        admins = await ctx.bot.get_chat_administrators(chat_id=ctx.job.chat_id)
        for admin in admins:
            if admin.user.is_bot:
                continue
            await ctx.bot.sendMessage(chat_id=admin.user.id, text=f"Hello, {admin.user.username}. {text_to_send}") 

def extract_status_change(chat_member_update: ChatMemberUpdated) -> tuple:
    status_change = chat_member_update.difference().get("status")
    if status_change is None:
        return None
    
    old_is_member, new_is_member = chat_member_update.difference().get("is_member", (None, None))
    old_status, new_status = status_change
    was_member = old_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (old_status == ChatMember.RESTRICTED and old_is_member is True)
    is_member = new_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (new_status == ChatMember.RESTRICTED and new_is_member is True)

    return was_member, is_member    

def remove_job_if_exists(name: str, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Remove job with given name. Returns whether job was removed."""
    current_jobs = ctx.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True

def create_table_query(table_name: str) -> None:
    """Tries to create a table. IF table already exists does nothing"""
    conn = psycopg2.connect(dbname=DB_DATABASE, user=DB_USER, password=DB_PASSWORD, host=DB_HOST)
    cursor = conn.cursor()
    cursor.execute(f"CREATE TABLE IF NOT EXISTS {table_name} (id SERIAL PRIMARY KEY, username VARCHAR(255));")
    conn.commit()
    cursor.close()
    conn.close()


def add_to_table_query(table_name: str, username: str) -> str:
    """Adds a username to table"""
    conn = psycopg2.connect(dbname=DB_DATABASE, user=DB_USER, password=DB_PASSWORD, host=DB_HOST)
    cursor = conn.cursor()
    cursor.execute(f"INSERT INTO {table_name} (username) select %s where not exists (select username from {table_name} where username=%s);", (username, username))
    conn.commit()
    cursor.close()
    conn.close()

def add_state_to_db(chat_id: int) -> None:
    real_id = str(chat_id)
    conn = psycopg2.connect(dbname=DB_DATABASE, user=DB_USER, password=DB_PASSWORD, host=DB_HOST)
    cursor = conn.cursor()
    cursor.execute(f"CREATE TABLE IF NOT EXISTS prev_state (id SERIAL PRIMARY KEY, chat_id VARCHAR(255));")
    cursor.execute(f"INSERT INTO prev_state (chat_id) select %s where not exists (select chat_id from prev_state where chat_id=%s);", (real_id, real_id))
    conn.commit()
    cursor.close()
    conn.close()

def remove_state_from_db(chat_id: int) -> None:
    real_id = str(chat_id)
    conn = psycopg2.connect(dbname=DB_DATABASE, user=DB_USER, password=DB_PASSWORD, host=DB_HOST)
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM prev_state WHERE chat_id=%s;", (real_id, ))
    conn.commit()
    cursor.close()
    conn.close()

async def track_chats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Tracks the chats the bot is in"""
    result = extract_status_change(update.my_chat_member)
    if result is None:
        return 
    was_member, is_member = result

    global handled_channels
    cause_name = update.effective_user.full_name
    chat = update.effective_chat
    table_name = chat_id_normalize(chat.id)
    if chat.type != Chat.PRIVATE:
        if chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
            if not was_member and is_member:
                logger.info("%s added the bot to the group %s", cause_name, chat.title)
                ctx.bot_data.setdefault("group_ids", set()).add(chat.id)
                ctx.job_queue.run_repeating(check_members, interval=timedelta(seconds=DELTA_CHECK), name=str(chat.id), chat_id=chat.id)
                handled_channels.add(chat.id)
                add_state_to_db(chat.id)
            elif was_member and not is_member:
                logger.info("%s removed the bot from group %s", cause_name, chat.title)
                ctx.bot_data.setdefault("groupd_ids", set()).discard(chat.id)
                removed = remove_job_if_exists(str(chat.id), ctx)
                if not removed:
                    logger.info("Failed to remove jobs for group %s", chat.title)
                handled_channels.remove(chat.id)
                remove_state_from_db(chat.id)
        elif not was_member and is_member:
            logger.info("%s added the bot to the channel %s", cause_name, chat.title)
            ctx.bot_data.setdefault("channel_ids", set()).add(chat.id)
            ctx.job_queue.run_repeating(check_members, interval=timedelta(seconds=DELTA_CHECK), name=str(chat.id), chat_id=chat.id)
            handled_channels.add(chat.id)
            add_state_to_db(chat.id)
        elif was_member and not is_member:
            logger.info("%s removed the bot from channel %s", cause_name, chat.title)
            ctx.bot_data.setdefault("channel_ids", set()).discard(chat.id)
            removed = remove_job_if_exists(str(chat.id), ctx)
            if not removed:
                logger.info("Failed to remove jobs for channel %s", chat.title)
            handled_channels.remove(chat.id)
            remove_state_from_db(chat.id)
    logger.info(f"{handled_channels}")

def inset_to_usernames(chat_id: int, username: str):
    real_id = str(chat_id)
    conn = psycopg2.connect(dbname=DB_DATABASE, user=DB_USER, password=DB_PASSWORD, host=DB_HOST)
    cursor = conn.cursor()
    cursor.execute(f"CREATE TABLE IF NOT EXISTS usernames (id SERIAL PRIMARY KEY, chat_id VARCHAR(255), username VARCHAR(255));")
    cursor.execute(f"INSERT INTO usernames (chat_id, username) VALUES (%s, %s);", (real_id, username))
    conn.commit()
    cursor.close()
    conn.close()

def remove_from_usernames(chat_id: int, username: str):
    real_id = str(chat_id)
    conn = psycopg2.connect(dbname=DB_DATABASE, user=DB_USER, password=DB_PASSWORD, host=DB_HOST)
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM usernames WHERE chat_id=%s AND username=%s;", (real_id, username))
    conn.commit()
    cursor.close()
    conn.close()


async def track_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Tracks the users joining the chat"""
    result = extract_status_change(update.chat_member)
    if result is None:
        return

    was_member, is_member = result
    cause_name = update.chat_member.from_user.username
    member_name = update.chat_member.new_chat_member.user.username
    chat = update.effective_chat
    table_name = chat_id_normalize(chat.id)
    
    global chats_data
    if not was_member and is_member:
        logger.info("%s added %s to chat %s", cause_name, member_name, chat.title)
        if chat.id not in chats_data.keys():
            chats_data[chat.id] = set()
        chats_data[chat.id].add(member_name)
        inset_to_usernames(chat.id, member_name)
    elif was_member and not is_member:
        logger.info("%s removed %s from chat %s", cause_name, member_name, chat.title)
        if chat.id not in chats_data.keys():
            chats_data[chat.id] = set()
        chats_data[chat.id].remove(member_name)
        remove_from_usernames(chat.id, member_name)

async def command_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await ctx.bot.send_message(chat_id=update.effective_chat.id, text="You are now using this bot!")

async def get_admin_chats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> dict:
    d = dict()
    for chat_id in handled_channels:
        admins = await ctx.bot.get_chat_administrators(chat_id=chat_id)
        for admin in admins:
            if admin.user.is_bot:
                continue
            if update.effective_user.username == admin.user.username:
                channel = await ctx.bot.get_chat(chat_id)
                if not channel.username:
                    d[channel.title] = chat_id
                else:
                    d[channel.username] = chat_id

    return d

async def command_me(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    global handled_channels
    text_channels = "You are admin in:"
    
    d = await get_admin_chats(update, ctx)
    if not d:
        await ctx.bot.send_message(chat_id=update.effective_chat.id, text="You are not an admin in any chat that is being handled!")
    else:
        i = 0
        text_channels = "You are an admin in this channels:"
        for key in d.keys():
            text_channels += f"\n{i + 1}. {key}"
            i += 1
        await ctx.bot.send_message(chat_id=update.effective_chat.id, text=text_channels)

# Definetly not a good idea to iterate usernames and add them using different queries. Better would be to make a function that adds an array with one query, but...
async def command_load_get_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message.document.file_id:
        update.message.reply_text(text="Bad file")
    
    file_id = update.message.document.file_id
    file_info = await ctx.bot.get_file(file_id=file_id)
    
    text_repr = []
    with io.BytesIO() as mem_file:
        await file_info.download_to_memory(mem_file)
  
        text_repr += [i.decode() for i in mem_file.getvalue().replace(b'\r',b'').split(b'\n')]
        
    d = await get_admin_chats(update, ctx)
    table_name = chat_id_normalize(d[ctx.user_data.pop(0)])
    create_table_query(table_name)
    for username in text_repr:
        add_to_table_query(table_name, username)
        
    return ConversationHandler.END

async def command_load_ask_txt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data[0] = update.message.text
    await update.message.reply_text(text="Now send me a file in txt format")
    return "command_load_get_file"
    
async def command_load_hello(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = await get_admin_chats(update, ctx)
    if not d:
        return ConversationHandler.END

    i = 0
    text = "You are an admin in this channels. Please enter the name of the channel to load the data."
    for key in d.keys():
        text += f"\n{i + 1}. {key}"
        i += 1
    await update.message.reply_text(text=text)
    return "command_load_ask_txt"

async def command_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(text="Bye!")
    return ConversationHandler.END

def get_handled_from_db(application):    
    conn = psycopg2.connect(dbname=DB_DATABASE, user=DB_USER, password=DB_PASSWORD, host=DB_HOST)
    
    global handled_channels
    global chats_data
    
    cursor = conn.cursor()
    cursor.execute(f"CREATE TABLE IF NOT EXISTS prev_state (id SERIAL PRIMARY KEY, chat_id VARCHAR(255));")
    cursor.execute(f"CREATE TABLE IF NOT EXISTS usernames (id SERIAL PRIMARY KEY, chat_id VARCHAR(255), username VARCHAR(255));")
    cmd = f"SELECT chat_id FROM prev_state;"
    cursor.execute(cmd)
    res = cursor.fetchall()
    conn.commit()
    cursor.close()
    
    
    logger.info(res)
    for el in res:
        handled_channels.add(int(el[0]))
        if int(el[0]) not in chats_data.keys():
            chats_data[int(el[0])] = set()
        cursor = conn.cursor()
        cursor.execute(f"SELECT username FROM usernames WHERE chat_id='{el[0]}';")
        d = cursor.fetchall()
        cursor.close()
        for name in d:
            chats_data[int(el[0])].add(name[0])
        
        application.bot_data.setdefault("group_ids", set()).add(int(el[0]))
        application.job_queue.run_repeating(check_members, interval=timedelta(seconds=DELTA_CHECK), name=el[0], chat_id=int(el[0]))
    conn.close()
    
def main() -> None:
    """Run the bot."""
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    convHandlerLoad = ConversationHandler(
        entry_points=[CommandHandler("load", command_load_hello)],
        states={
            "command_load_ask_txt": [MessageHandler(filters.TEXT & ~filters.COMMAND, command_load_ask_txt), 
                                     MessageHandler(filters.Document.TXT, command_load_get_file)
                                    ],
            "command_load_get_file": [MessageHandler(filters.Document.TXT, command_load_get_file)],
        },
        fallbacks=[CommandHandler("cancel", command_cancel)]
    )

    application.add_handler(convHandlerLoad)
    application.add_handler(CommandHandler('start', command_start))
    application.add_handler(CommandHandler('me', command_me))
    application.add_handler(ChatMemberHandler(track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(ChatMemberHandler(track_member, ChatMemberHandler.CHAT_MEMBER))
    
    get_handled_from_db(application)

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
