from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from telegram import Update
from web3 import Web3
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Basic configuration for logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        # Console handler
        logging.StreamHandler(),
        # File handler with rotation
        RotatingFileHandler(
            filename="bot_log.log",  # Log file path
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=5,  # Keep up to 5 backup logs
        ),
    ],
)

logger = logging.getLogger(__name__)

##############################################################################################
## Web3
##############################################################################################

RPC_URL = os.getenv("RPC_URL")
PAIR_CONTRACT_ADDRESS = Web3.to_checksum_address(
    os.getenv("PAIR_CONTRACT_ADDRESS")
)  # fnd pair address
PRICE_FEED_ADDRESS = Web3.to_checksum_address(os.getenv("PRICE_FEED_ADDRESS"))
TOKEN_DECIMALS = os.getenv("TOKEN_DECIMALS")
with open("./pairAbi.json", "r") as abi_file:
    contract_abi = json.load(abi_file)

with open("./priceFeedAbi.json", "r") as abi_file:
    price_feed_abi = json.load(abi_file)


web3 = Web3(Web3.HTTPProvider(RPC_URL))
# Check if connected to the blockchain
if web3.is_connected():
    logger.info("Connected to Ethereum blockchain")
else:
    logger.error("Failed to connect to Ethereum blockchain")


# Create the contract instance
contract = web3.eth.contract(address=PAIR_CONTRACT_ADDRESS, abi=contract_abi)

price_feed_contract = web3.eth.contract(address=PRICE_FEED_ADDRESS, abi=price_feed_abi)

# event_filter will be handled when starting polling
event_filter = None


def get_latest_eth_price():
    latest_price = price_feed_contract.functions.latestRoundData().call()
    # The response can contain multiple items, price being the second item (index 1)
    eth_price = (
        latest_price[1] / 1e8
    )  # Adjust according to how price is represented in the contract
    return eth_price


##############################################################################################
## Telegram
##############################################################################################

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ROCKET_EMOJI_DIVIDER = 20
PORT = int(os.environ.get("PORT", "8443"))


def format_swap_message(event):
    tokens_got = event["args"]["amount0Out"] / 10**TOKEN_DECIMALS
    if tokens_got == 0:
        return False
    token_name = "RareFiND"
    token_symbol = "FND"
    spent_eth = event["args"]["amount1In"] / 1e18
    spent_eth_usd_value = spent_eth * get_latest_eth_price()
    token_price = spent_eth_usd_value / tokens_got
    transaction_hash = event["transactionHash"].hex()

    # Calculate the number of rockets: at least 1 rocket, plus 1 for every $20 spent
    num_rockets = max(1, int(spent_eth_usd_value // ROCKET_EMOJI_DIVIDER))
    rockets = "🚀" * num_rockets  # Repeat the rocket emoji

    # Format the message with HTML tags for bold text and line breaks
    text = (
        f"<b>{token_name} ({token_symbol}) BUY!</b>\n"
        f"{rockets}\n\n"
        f"<b>Spent:</b> {spent_eth:.3f} ETH = (${spent_eth_usd_value:.2f})\n"
        f"<b>Got:</b> {tokens_got:.2f} {token_symbol}\n"
        f"<b>Price:</b> {token_price:.6f}\n\n"
        f"<a href='https://etherscan.io/tx/{transaction_hash}'>TX</a> | <a href='https://www.dextools.io/app/en/ether/pair-explorer/{PAIR_CONTRACT_ADDRESS}'>Dex</a>"
    )
    return text


# Modify the monitor_buys function to use the format_swap_message function
async def monitor_buys(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Monitors swap events and sends Telegram messages."""
    try:
        new_entries = event_filter.get_new_entries()
        for event in new_entries:
            text = format_swap_message(event)  # Format the message
            if text:
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                logger.info(f"Function: monitor_buys: Got new price:\n{text}")
    except Exception as e:
        logger.error("Function: monitor_buys: Error fetching new entries: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Starts the monitoring when the /start command is issued."""
    chat_id = update.effective_chat.id
    global event_filter
    event_filter = contract.events.Swap.create_filter(fromBlock="latest")

    if chat_id == CHAT_ID:
        await context.bot.send_message(
            chat_id=chat_id, text="Monitoring for buys has started."
        )
        # Pass the chat_id directly as the context for the job
        context.job_queue.run_repeating(
            monitor_buys, interval=10, first=0, name="monitoring_active"
        )
        logger.info("Function: start: Monitoring for buys has started.")
    else:
        await context.bot.send_message(
            chat_id=chat_id, text="This bot works only on @rarefnd group."
        )
        logger.info("Function: start: This bot works only on @rarefnd group.")


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stops the bot from monitoring swap events."""
    chat_id = update.effective_chat.id
    if chat_id == CHAT_ID:
        current_jobs = context.job_queue.get_jobs_by_name("monitoring_active")

        # Retrieve all jobs and stop them
        for job in current_jobs:
            job.schedule_removal()

        await context.bot.send_message(
            chat_id=chat_id, text="Rare Buy Bot has stopped monitoring buys."
        )
        logger.info("Function: stop: Rare Buy Bot has stopped monitoring buys.")
    else:
        await context.bot.send_message(
            chat_id=chat_id, text="This bot works only on @rarefnd group."
        )
        logger.info("Function: stop: This bot works only on @rarefnd group.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a help message."""
    chat_id = update.effective_chat.id
    message = (
        "Rare Buy Bot monitors buy events and notifies @rarefnd group chat.\n"
        "To start the bot, type /start@rare_buy_bot.\n"
        "This bot works only on @rarefnd group."
    )
    await context.bot.send_message(chat_id=chat_id, text=message)


def main():
    # Create the Application as before
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stop", stop))

    # Run the bot
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url="https://rare-buy-bot.herokuapp.com/",
    )


# Your existing code for the monitor_buys function

if __name__ == "__main__":
    main()
