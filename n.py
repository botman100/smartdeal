import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import time
import random
import json
import pandas as pd
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
import chromedriver_autoinstaller
import asyncio
import logging
import os
from dotenv import load_dotenv
from flask import Flask, request

# Load environment variables from .env file
load_dotenv()

# Retrieve environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_TOKEN = os.getenv("API_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# Validate environment variables
if not BOT_TOKEN or not API_TOKEN or not CHANNEL_ID:
    print("Error: Missing environment variables. Please check your .env file.")
    exit(1)

# Suppress TensorFlow Lite warnings
logging.getLogger('tensorflow').setLevel(logging.ERROR)

# URL of the deals page
URL = "https://www.smartprix.com/deals"

# List of User-Agent strings for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15"
]

# ModijiURL API Configuration
SHORTEN_API_URL = "https://modijiurl.com/api"

# Validate the Telegram bot token
try:
    bot = Bot(token=BOT_TOKEN)
    print("Telegram bot initialized successfully.")
except ImportError:
    print("Error importing telegram module. Please ensure it is installed correctly.")
    exit(1)
except TelegramError as e:
    print(f"Invalid Telegram bot token. Please check and update it: {e}")
    exit(1)
except Exception as e:
    print(f"Error initializing Telegram bot: {e}")
    exit(1)

# To store already shared deals
shared_deals = set()

# Function to generate a unique alias
def generate_unique_alias():
    return f"deal{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"

# Function to shorten the URL with retry mechanism and exponential backoff
def shorten_url(original_url, retries=3):
    for attempt in range(retries):
        try:
            # Encode the original URL
            encoded_url = requests.utils.quote(original_url)

            # Create a unique alias
            custom_alias = generate_unique_alias()

            # Prepare the API request
            api_request_url = f"{SHORTEN_API_URL}?api={API_TOKEN}&url={encoded_url}&alias={custom_alias}"

            # Send the request to shorten the URL
            response = requests.get(api_request_url, timeout=20).json()

            if response.get("status") == "success":
                shortened_url = response.get("shortenedUrl")
                return shortened_url
            elif response.get("message") == "Alias already exists.":
                # Alias already exists, try again
                continue
            else:
                print(f"Error shortening URL: {response.get('message')}")
                time.sleep(2 ** attempt)  # Exponential backoff
        except requests.exceptions.RequestException as e:
            print(f"Error in URL shortening (Attempt {attempt + 1}): {e}")
            time.sleep(2 ** attempt)  # Exponential backoff

    print("Exceeded maximum retries for URL shortening.")
    return original_url  # Return original URL if all retries fail

# Function to fetch and parse deals with retry mechanism and exponential backoff
def fetch_deals(retries=3):
    for attempt in range(retries):
        try:
            # Automatically install and set up ChromeDriver
            chromedriver_autoinstaller.install()

            # Set up Chrome options
            chrome_options = Options()
            chrome_options.add_argument("--headless")  # Run in headless mode
            chrome_options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")  # Rotate User-Agent
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")  # Avoid detection as a bot
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-gpu")  # Disable GPU acceleration
            chrome_options.add_argument("--enable-unsafe-swiftshader")  # Enable unsafe SwiftShader
            chrome_options.add_argument("--disable-webgpu")  # Disable WebGPU

            # Initialize the WebDriver
            driver_service = Service()
            driver = webdriver.Chrome(service=driver_service, options=chrome_options)

            # Open the deals page
            print("Opening URL in Selenium:", URL)
            driver.get(URL)
            time.sleep(random.uniform(5, 10))  # Wait for page to load

            # Scroll to load all deals
            last_height = driver.execute_script("return document.body.scrollHeight")
            while True:
                # Scroll down to bottom
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(2, 4))  # Wait for new deals to load

                # Calculate new scroll height and compare with last scroll height
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

                # Try to click "Load More" button if present
                try:
                    load_more = driver.find_element(By.CLASS_NAME, 'sm-load-more')
                    load_more.click()
                    time.sleep(random.uniform(3, 5))  # Wait for new deals to load
                except Exception as e:
                    print(f"Load More button not found or already clicked: {e}")
                    break

            # Parse the page source with BeautifulSoup
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            driver.quit()

            # Find all deal containers
            deals = soup.find_all("div", class_="sm-deal", attrs={"data-way": ""})

            # List to store extracted deals
            extracted_deals = []

            for deal in deals:
                try:
                    # Extract product name
                    product_name_tag = deal.find("a", class_="name clamp-3")
                    product_name = product_name_tag.get_text(strip=True) if product_name_tag else "N/A"

                    # Extract deal price
                    deal_price_tag = deal.find("span", class_="price")
                    deal_price = deal_price_tag.get_text(strip=True) if deal_price_tag else "N/A"

                    # Extract product image URL
                    image_tag = deal.find("img", class_="sm-img")
                    image_url = image_tag['src'] if image_tag and 'src' in image_tag.attrs else "N/A"

                    # Extract deal link (direct link from the "Visit" button)
                    visit_button_tag = deal.find("a", class_="sm-btn flat white-grad size-xs", href=True)
                    visit_link = visit_button_tag["href"] if visit_button_tag else "N/A"
                    if visit_link.startswith("https://l.smartprix.com/l?k="):
                        # Extract the actual URL from the "Visit" button
                        visit_response = requests.get(visit_link, allow_redirects=True, timeout=20)
                        full_link = visit_response.url
                    else:
                        full_link = visit_link

                    # Create a unique identifier for the deal
                    deal_id = full_link

                    # Validate all fields
                    if product_name == "N/A" or deal_price == "N/A" or image_url == "N/A" or full_link == "N/A":
                        continue

                    # Shorten every 4th deal's link
                    if len(extracted_deals) % 4 == 0:
                        full_link = shorten_url(full_link)

                    extracted_deals.append({
                        "name": product_name,
                        "price": deal_price,
                        "image": image_url,
                        "link": full_link,
                        "id": deal_id
                    })
                except Exception as e:
                    print(f"Error parsing a deal: {e}")

            return extracted_deals

        except requests.exceptions.RequestException as e:
            print(f"Error fetching deals (Attempt {attempt + 1}): {e}")
            time.sleep(2 ** attempt)  # Exponential backoff

    print("Exceeded maximum retries for fetching deals.")
    return []

# Function to validate image URL with retry mechanism and exponential backoff
def validate_image_url(image_url, retries=3):
    for attempt in range(retries):
        try:
            response = requests.head(image_url, allow_redirects=True, timeout=20)
            if response.status_code == 200:
                return True
            else:
                print(f"Invalid image URL: {image_url}. Status Code: {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"Error validating image URL: {image_url}. Attempt {attempt + 1}: {e}")
            time.sleep(2 ** attempt)  # Exponential backoff

    print(f"Exceeded maximum retries for validating image URL: {image_url}.")
    return False

# Function to escape Markdown characters
def escape_markdown(text):
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in escape_chars:
        text = text.replace(char, '\\' + char)
    return text

# Function to send deals to Telegram
async def send_deals_to_telegram(deals):
    if not deals:
        return

    for i, deal in enumerate(deals, start=1):
        try:
            # Validate all fields
            if deal['name'] == "N/A" or deal['price'] == "N/A" or deal['link'] == "N/A":
                continue

            # Validate image URL
            if deal['image'] == "N/A" or not validate_image_url(deal['image']):
                continue

            # Escape Markdown characters in product name and price
            escaped_product_name = escape_markdown(deal['name'])
            escaped_deal_price = escape_markdown(deal['price'])

            message = f"🔥 *New Deal Alert!* 🔥\n\n" \
                      f"🛍️ *Product:* {escaped_product_name}\n" \
                      f"💰 *Price:* {escaped_deal_price}\n" \
                      f"🔗 [View Deal]({deal['link']})"

            # Send the image and message
            await bot.send_photo(chat_id=CHANNEL_ID, photo=deal['image'], caption=message, parse_mode=ParseMode.MARKDOWN_V2)
            # Add delay of 12 seconds between sending each deal
            await asyncio.sleep(12)
        except TelegramError as e:
            if "Flood control exceeded" in str(e):
                print(f"TelegramError: {e}. Retrying in {int(e.retry_after)} seconds.")
                await asyncio.sleep(int(e.retry_after) + random.uniform(1, 5))
            elif "Can't parse entities" in str(e):
                print(f"TelegramError: {e}. Invalid Markdown formatting.")
            else:
                print(f"TelegramError sending deal to Telegram: {e}")
        except Exception as e:
            print(f"Error sending deal to Telegram: {e}")

# Function to save deals to CSV
def save_deals_to_csv(deals):
    if not deals:
        return

    # Convert deals to DataFrame
    df = pd.DataFrame(deals)
    df.to_csv('smartprix_deals.csv', index=False)

# Scheduled job to check for new deals every 15 minutes
async def scheduled_job():
    deals = fetch_deals()

    # Filter out deals that have already been shared
    new_deals = [deal for deal in deals if deal['id'] not in shared_deals]

    if new_deals:
        await send_deals_to_telegram(new_deals)
        # Mark the deals as shared
        for deal in new_deals:
            shared_deals.add(deal['id'])

# Create a Flask app
app = Flask(__name__)

# Route to keep the application alive
@app.route('/')
def home():
    return "Smartprix Deals Bot is running!"

# Function to run the scheduled job
def run_scheduled_job():
    asyncio.run(scheduled_job())

# Schedule the job to run every 15 minutes
import schedule
import threading

def run_continuously(interval=60):
    while True:
        schedule.run_pending()
        time.sleep(interval)

# Start the scheduler in a separate thread
scheduler_thread = threading.Thread(target=run_continuously)
scheduler_thread.start()

# Schedule the job to run every 15 minutes
schedule.every(15).minutes.do(run_scheduled_job)

# Main function
if __name__ == "__main__":
    # First run to fetch and send deals immediately
    asyncio.run(scheduled_job())

    # Run the Flask app
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))